#!/usr/bin/env python3
"""Ground-side channel-1 reconstruction and verified Yamcs receipt.

This adapter consumes one N2 payload packet per already-validated UART
channel-1 frame. It never opens payload source files: only reconstructed bytes
that pass packet, transfer, and whole-file checks are offered to Yamcs.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import queue
import threading
import time
from typing import Callable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
N2_TOOLS = PROJECT_ROOT / "ArtemisRpiTeensy_N2" / "tools"
import sys

if str(N2_TOOLS) not in sys.path:
    sys.path.insert(0, str(N2_TOOLS))

from payload_receiver import (  # noqa: E402
    DATA_BYTES,
    MAGIC,
    MAX_PACKET,
    TYPE_DATA,
    TYPE_END,
    TYPE_HEADER,
    TYPE_RETRY_REQUEST,
    PayloadReceiver,
    crc16_ccitt,
)


MAX_RAW_BYTES = 1024 * 1024
MAX_EXPECTED_PACKETS = (MAX_RAW_BYTES + DATA_BYTES - 1) // DATA_BYTES
TRANSFER_IDLE_TIMEOUT_S = 120.0
RECENT_IDENTITIES = 64
YAMCS_TIMEOUT_S = 5.0
BUCKET = "fprimeFilesIn"
INSTANCE = "fprime-project"
YAMCS_URL = "http://127.0.0.1:8090"
RECEIPT_EVENT = "GroundScienceReceiptVerified"


def _identity_key(run_id: str, product_id: int, transfer_id: int,
                  size: int, crc: int, digest: str) -> tuple:
    return run_id, product_id, transfer_id, size, crc, digest


def _capture_key(manifest: Mapping) -> tuple:
    return (manifest.get("runId"), int(manifest.get("productId", -1)),
            int(manifest.get("transferId", -1)), int(manifest.get("bytes", -1)),
            int(manifest.get("crc16Ccitt", -1)), manifest.get("sha256"))


class PayloadReceiverAdapter(PayloadReceiver):
    """Strict bounded adapter around the existing serial PayloadReceiver.

    ``PayloadReceiver`` remains the implementation for retry bitmaps and
    reconstruction. This adapter supplies framed retries and enforces the
    ground's stronger packet/header/END contract before storing packet bytes.
    """

    def __init__(self, run_id: str, submit_capture: Callable[[bytes, dict], bool],
                 retry_writer, fault_profile: frozenset[str] = frozenset()) -> None:
        # ``run`` is intentionally never called: this receiver is fed one
        # complete payload packet at a time from LocalLink's UART parser.
        super().__init__(port="", baud=0, output=Path("."), timeout_s=0.0)
        self.run_id = run_id
        self._submit_capture = submit_capture
        self._retry_writer = retry_writer
        self.fault_profile = fault_profile
        self.active_header: tuple[int, int, int, int, int, int] | None = None
        self.end_identity: tuple[int, int, int] | None = None
        self.last_activity = 0.0
        self.active_counter_baseline: dict[str, int] | None = None
        self.pending_capture: tuple[bytes, dict] | None = None
        self.submit_retry_count = 0
        self.next_submit_try = 0.0
        self.recent_completed: OrderedDict[tuple[int, int], tuple[int, int, int, int]] = OrderedDict()
        self.seen_publications: OrderedDict[tuple, None] = OrderedDict()
        self.faults_applied: set[str] = set()
        self.requested_missing: set[int] = set()
        self.counters = {
            "channel1Packets": 0,
            "invalidPackets": 0,
            "badDataPacketCrc": 0,
            "duplicateHeaders": 0,
            "duplicateDataPackets": 0,
            "duplicateEndPackets": 0,
            "conflictingDataPackets": 0,
            "rejectedHeaders": 0,
            "rejectedEndPackets": 0,
            "completedTransfers": 0,
            "wholeFileCrcFailures": 0,
            "faultPacketsDropped": 0,
            "faultPacketsCorrupted": 0,
            "retryRequestsSent": 0,
            "recoveredPackets": 0,
        }

    def retry_written(self, packet: bytes) -> None:
        if (len(packet) >= 7 and packet[:3] == MAGIC + bytes([TYPE_RETRY_REQUEST])
                and len(packet) == 7 + packet[6]):
            start = int.from_bytes(packet[4:6], "little")
            bitmap = packet[7:]
            for byte_index, value in enumerate(bitmap):
                for bit in range(8):
                    if value & (1 << bit):
                        index = start + byte_index * 8 + bit
                        if index < MAX_EXPECTED_PACKETS:
                            self.requested_missing.add(index)
            self.counters["retryRequestsSent"] += 1

    def _reset_active(self) -> None:
        self.transfer_id = None
        self.product_id = 0
        self.total_bytes = 0
        self.total_packets = 0
        self.file_crc = 0
        self.packet_data_bytes = DATA_BYTES
        self.packets.clear()
        self.requested_missing.clear()
        self.end_seen = False
        self.end_identity = None
        self.active_header = None
        self.active_counter_baseline = None
        self.last_packet_s = 0.0
        self.last_activity = 0.0
        self.next_retry_request_s = 0.0

    def _remember_completed(self, product_id: int, transfer_id: int,
                            fingerprint: tuple[int, int, int, int]) -> None:
        key = (product_id, transfer_id)
        self.recent_completed[key] = fingerprint
        self.recent_completed.move_to_end(key)
        while len(self.recent_completed) > RECENT_IDENTITIES:
            self.recent_completed.popitem(last=False)

    def _remember_publication(self, key: tuple) -> None:
        self.seen_publications[key] = None
        self.seen_publications.move_to_end(key)
        while len(self.seen_publications) > RECENT_IDENTITIES * 2:
            self.seen_publications.popitem(last=False)

    def _expire_idle_transfer(self, now: float) -> None:
        if self.active_header is not None and now - self.last_activity > TRANSFER_IDLE_TIMEOUT_S:
            self._reset_active()

    def receive(self, packet: bytes) -> None:
        """Accept one N2 payload packet; channel framing is checked upstream."""
        self.counters["channel1Packets"] += 1
        if not isinstance(packet, bytes) or not (4 <= len(packet) <= MAX_PACKET):
            self.counters["invalidPackets"] += 1
            return
        if packet[:2] != MAGIC:
            self.counters["invalidPackets"] += 1
            return

        packet_type = packet[2]
        if packet_type == TYPE_HEADER:
            self._handle_header(packet)
            return

        if self.active_header is None or self.pending_capture is not None:
            return
        now = time.monotonic()
        self._expire_idle_transfer(now)
        if self.active_header is None or packet[3] != self.transfer_id:
            return

        if packet_type == TYPE_DATA:
            self._handle_data_strict(packet, now)
        elif packet_type == TYPE_END:
            self._handle_end(packet, now)

    def _handle_header(self, packet: bytes) -> None:
        now = time.monotonic()
        self._expire_idle_transfer(now)
        if len(packet) != 17:
            self.counters["invalidPackets"] += 1
            return

        transfer_id = packet[3]
        product_id = int.from_bytes(packet[4:8], "little")
        total_bytes = int.from_bytes(packet[8:12], "little")
        total_packets = int.from_bytes(packet[12:14], "little")
        packet_data_bytes = packet[14]
        file_crc = int.from_bytes(packet[15:17], "little")
        expected_packets = (total_bytes + DATA_BYTES - 1) // DATA_BYTES if total_bytes else 0
        if (total_bytes < 1 or total_bytes > MAX_RAW_BYTES
                or expected_packets < 1 or expected_packets > MAX_EXPECTED_PACKETS
                or total_packets != expected_packets or packet_data_bytes != DATA_BYTES):
            self.counters["rejectedHeaders"] += 1
            return

        fingerprint = (total_bytes, total_packets, packet_data_bytes, file_crc)
        pair = (product_id, transfer_id)
        completed = self.recent_completed.get(pair)
        if completed is not None:
            if completed == fingerprint:
                self.counters["duplicateHeaders"] += 1
            else:
                self.counters["rejectedHeaders"] += 1
            return

        if self.pending_capture is not None:
            self.counters["rejectedHeaders"] += 1
            return

        if self.active_header is not None:
            current = (self.product_id, self.transfer_id, self.total_bytes,
                       self.total_packets, self.packet_data_bytes, self.file_crc)
            incoming = (product_id, transfer_id, total_bytes, total_packets,
                        packet_data_bytes, file_crc)
            if current == incoming:
                # A retransmitted header must never clear already received data.
                self.counters["duplicateHeaders"] += 1
                self.last_packet_s = now
                self.last_activity = now
            else:
                # One active transfer bounds state and prevents an interleaved
                # or stale header from replacing the current product.
                self.counters["rejectedHeaders"] += 1
            return

        self.transfer_id = transfer_id
        self.product_id = product_id
        self.total_bytes = total_bytes
        self.total_packets = total_packets
        self.packet_data_bytes = packet_data_bytes
        self.file_crc = file_crc
        self.packets.clear()
        self.end_seen = False
        self.end_identity = None
        self.active_header = (product_id, transfer_id, total_bytes, total_packets,
                              packet_data_bytes, file_crc)
        self.active_counter_baseline = dict(self.counters)
        self.last_packet_s = now
        self.last_activity = now

    def _handle_data_strict(self, packet: bytes, now: float) -> None:
        if len(packet) < 9:
            self.counters["invalidPackets"] += 1
            return
        index = int.from_bytes(packet[4:6], "little")
        valid_len = packet[6]
        if index >= self.total_packets:
            self.counters["invalidPackets"] += 1
            return
        expected_len = min(DATA_BYTES, self.total_bytes - index * DATA_BYTES)
        if expected_len <= 0 or valid_len != expected_len or len(packet) != 9 + valid_len:
            self.counters["invalidPackets"] += 1
            return
        crc_offset = 7 + valid_len
        expected_crc = int.from_bytes(packet[crc_offset:crc_offset + 2], "little")
        if crc16_ccitt(packet[:crc_offset]) != expected_crc:
            self.counters["badDataPacketCrc"] += 1
            return

        chunk = packet[7:crc_offset]
        existing = self.packets.get(index)
        if existing is not None:
            if existing == chunk:
                self.counters["duplicateDataPackets"] += 1
                self.last_activity = now
            else:
                self.counters["conflictingDataPackets"] += 1
            return
        if index in self.requested_missing:
            self.requested_missing.discard(index)
            self.counters["recoveredPackets"] += 1
        self.packets[index] = chunk
        self.last_packet_s = now
        self.last_activity = now
        if self.end_seen:
            self._finalize_if_ready()

    def _handle_end(self, packet: bytes, now: float) -> None:
        if len(packet) != 8:
            self.counters["invalidPackets"] += 1
            return
        packet_count = int.from_bytes(packet[4:6], "little")
        file_crc = int.from_bytes(packet[6:8], "little")
        if packet_count != self.total_packets or file_crc != self.file_crc:
            self.counters["rejectedEndPackets"] += 1
            return
        incoming_identity = (self.transfer_id, packet_count, file_crc)
        if self.end_seen and self.end_identity == incoming_identity:
            self.counters["duplicateEndPackets"] += 1
            return
        self.end_seen = True
        self.end_identity = incoming_identity
        self.last_packet_s = now
        self.last_activity = now
        self._finalize_if_ready()
        if self.active_header is not None and not self.complete:
            self.request_retries_if_due(self._retry_writer, force=True)

    def _finalize_if_ready(self) -> None:
        if (self.active_header is None or not self.end_seen or self.end_identity is None
                or len(self.packets) != self.total_packets):
            return
        blob = self.reconstruct()
        actual_crc = crc16_ccitt(blob)
        if len(blob) != self.total_bytes or actual_crc != self.file_crc:
            self.counters["wholeFileCrcFailures"] += 1
            # A complete packet set with a bad whole-file CRC cannot be
            # repaired safely from the current packet map; discard it and wait
            # for a fresh header/transfer.
            self._reset_active()
            return

        product_id = self.product_id
        transfer_id = int(self.transfer_id)
        total_bytes = self.total_bytes
        total_packets = self.total_packets
        header_crc = self.file_crc
        digest = hashlib.sha256(blob).hexdigest()
        key = _identity_key(self.run_id, product_id, transfer_id,
                            total_bytes, header_crc, digest)
        self._remember_completed(product_id, transfer_id,
                                 (total_bytes, total_packets, DATA_BYTES, header_crc))
        if key in self.seen_publications:
            self.counters["duplicateHeaders"] += 1
            self._reset_active()
            return
        self._remember_publication(key)
        self.counters["completedTransfers"] += 1
        baseline = self.active_counter_baseline or {}
        transfer_counters = {
            name: value - baseline.get(name, 0)
            for name, value in self.counters.items()
        }
        manifest = {
            "runId": self.run_id,
            "productId": product_id,
            "transferId": transfer_id,
            "bytes": total_bytes,
            "packetCount": total_packets,
            "crc16Ccitt": header_crc,
            "crc16CcittHex": f"0x{header_crc:04X}",
            "sha256": digest,
            "verifiedGroundReceipt": False,
            "verificationMethod": "pending Yamcs GET byte and SHA-256 equality",
            "groundIngestCounters": transfer_counters,
            "faults": {
                "profile": sorted(self.fault_profile),
                "packetsDropped": transfer_counters["faultPacketsDropped"],
                "packetsCorrupted": transfer_counters["faultPacketsCorrupted"],
                "retryRequestsSent": transfer_counters["retryRequestsSent"],
                "recoveredPackets": transfer_counters["recoveredPackets"],
            },
        }
        self.pending_capture = (blob, manifest)
        self._reset_active()

    def apply_local_fault_fixture(self, packet: bytes) -> bytes | None:
        """Apply opt-in one-shot local-ground faults after UART CRC checking."""
        if len(packet) >= 6 and packet[:3] == MAGIC + bytes([TYPE_DATA]):
            index = int.from_bytes(packet[4:6], "little")
            if index == 0 and "drop-first-0" in self.fault_profile and "drop-first-0" not in self.faults_applied:
                self.faults_applied.add("drop-first-0")
                self.counters["faultPacketsDropped"] += 1
                return None
            if index == 1 and "corrupt-first-1" in self.fault_profile and "corrupt-first-1" not in self.faults_applied:
                self.faults_applied.add("corrupt-first-1")
                self.counters["faultPacketsCorrupted"] += 1
                damaged = bytearray(packet)
                if len(damaged) > 9:
                    damaged[7] ^= 0x01
                return bytes(damaged)
        return packet

    def tick(self) -> None:
        now = time.monotonic()
        self._expire_idle_transfer(now)
        if self.active_header is not None:
            self.request_retries_if_due(self._retry_writer)
        if self.pending_capture is not None and now >= self.next_submit_try:
            blob, manifest = self.pending_capture
            if self._submit_capture(blob, manifest):
                # Keep one bounded pending copy until the worker confirms
                # Yamcs GET readback, so a failed upload can be retried.
                self.next_submit_try = now + 1.0
            else:
                self.submit_retry_count += 1
                self.next_submit_try = now + min(5.0, 0.25 * (2 ** min(self.submit_retry_count, 4)))

    def publication_succeeded(self, receipt: dict) -> None:
        if self.pending_capture is None:
            return
        _blob, manifest = self.pending_capture
        if _capture_key(manifest) == _capture_key(receipt):
            self.pending_capture = None
            self.submit_retry_count = 0
            self.next_submit_try = 0.0

    def publication_failed(self, manifest: dict, error_text: str) -> None:
        if self.pending_capture is None or _capture_key(self.pending_capture[1]) != _capture_key(manifest):
            return
        self.submit_retry_count += 1
        delay = min(60.0, 5.0 * (2 ** min(self.submit_retry_count - 1, 4)))
        self.next_submit_try = time.monotonic() + delay
        print(f"[science-ingest] retaining bounded raw capture for retry in {delay:g}s: {error_text}", flush=True)


class _RetryWriter:
    """Turn receiver retry writes into nonblocking channel-1 PTY queue writes."""

    def __init__(self, enqueue_frame: Callable[[bytes], None], on_retry: Callable[[bytes], None]) -> None:
        self._enqueue_frame = enqueue_frame
        self._on_retry = on_retry

    def write(self, packet: bytes) -> int:
        if not packet or len(packet) > MAX_PACKET or packet[:2] != MAGIC:
            return 0
        frame = b"\xd4\xc3\x01" + len(packet).to_bytes(2, "little") + packet
        frame += crc16_ccitt(packet).to_bytes(2, "little")
        self._enqueue_frame(frame)
        self._on_retry(packet)
        return len(packet)


class YamcsGroundPublisher:
    """Bounded asynchronous publisher for reconstructed in-memory products."""

    def __init__(self, run_id: str, url: str = YAMCS_URL, instance: str = INSTANCE,
                 bucket: str = BUCKET, on_result: Callable[[dict], None] | None = None,
                 on_failure: Callable[[dict, str], None] | None = None) -> None:
        self.run_id = run_id
        self.url = url.rstrip("/")
        self.instance = instance
        self.bucket = bucket
        self.on_result = on_result
        self.on_failure = on_failure
        self._jobs: queue.Queue[tuple[bytes, dict] | None] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._pending_keys: set[tuple] = set()
        self._verified_keys: OrderedDict[tuple, None] = OrderedDict()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="n2-science-yamcs-upload", daemon=True)
        self._started = False
        self.last_error: str | None = None

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._thread.start()

    def submit(self, blob: bytes, manifest: dict) -> bool:
        key = _identity_key(self.run_id, int(manifest["productId"]), int(manifest["transferId"]),
                            int(manifest["bytes"]), int(manifest["crc16Ccitt"]), str(manifest["sha256"]))
        with self._lock:
            if key in self._verified_keys or key in self._pending_keys:
                return True
            if self._stop.is_set():
                return False
            try:
                self._jobs.put_nowait((bytes(blob), dict(manifest)))
            except queue.Full:
                return False
            self._pending_keys.add(key)
            return True

    def close(self) -> None:
        self._stop.set()
        if self._started and self._thread.is_alive():
            self._thread.join(timeout=0.25)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            if job is None:
                return
            blob, manifest = job
            key = _identity_key(self.run_id, int(manifest["productId"]), int(manifest["transferId"]),
                                int(manifest["bytes"]), int(manifest["crc16Ccitt"]), str(manifest["sha256"]))
            try:
                result = self._publish(blob, manifest)
                with self._lock:
                    self._pending_keys.discard(key)
                    self._verified_keys[key] = None
                    self._verified_keys.move_to_end(key)
                    while len(self._verified_keys) > RECENT_IDENTITIES * 2:
                        self._verified_keys.popitem(last=False)
                    self.last_error = None
                if self.on_result:
                    self.on_result(result)
            except Exception as exc:  # worker failure must not interrupt PTY traffic
                with self._lock:
                    self._pending_keys.discard(key)
                    self.last_error = str(exc)
                print(f"[science-ingest] Yamcs publish failed: {exc}", flush=True)
                if self.on_failure:
                    self.on_failure(manifest, str(exc))
            finally:
                self._jobs.task_done()

    def _publish(self, blob: bytes, incoming: dict) -> dict:
        if len(blob) != int(incoming["bytes"]) or len(blob) > MAX_RAW_BYTES:
            raise ValueError("reconstructed raw byte length is outside the accepted range")
        digest = hashlib.sha256(blob).hexdigest()
        crc = crc16_ccitt(blob)
        if digest != incoming["sha256"] or crc != int(incoming["crc16Ccitt"]):
            raise ValueError("reconstructed raw bytes changed before Yamcs publication")

        run_id = str(incoming["runId"])
        product_id = int(incoming["productId"])
        transfer_id = int(incoming["transferId"])
        object_name = f"n2-science-{run_id}-{product_id:08x}-{transfer_id:02x}-{digest[:12]}.bin"
        receipt_name = object_name + ".receipt.json"
        metadata = {
            "runId": run_id,
            "productId": str(product_id),
            "transferId": str(transfer_id),
            "bytes": str(len(blob)),
            "crc16Ccitt": str(crc),
            "sha256": digest,
        }

        # The Yamcs SDK uses multipart POST for upload. Add an explicit timeout
        # to every SDK request so a stalled ground service cannot hold a worker
        # forever; this thread is separate from the PTY/UART selector loop.
        from yamcs.client import YamcsClient

        client = YamcsClient(self.url)
        original_request = client.ctx.session.request

        def bounded_request(method, url, **kwargs):
            kwargs.setdefault("timeout", YAMCS_TIMEOUT_S)
            return original_request(method, url, **kwargs)

        client.ctx.session.request = bounded_request
        try:
            storage = client.get_storage_client()
            receipt_metadata = {
                "runId": run_id,
                "productId": str(product_id),
                "transferId": str(transfer_id),
                "objectName": object_name,
                "sha256": digest,
                "verifiedGroundReceipt": "true",
            }
            receipt = None
            for attempt in range(3):
                try:
                    # Object names are deterministic, so a bounded retry safely
                    # replaces the same bytes after transient service failures.
                    storage.upload_object(self.bucket, object_name, io.BytesIO(blob),
                                          content_type="application/octet-stream", metadata=metadata)
                    received = storage.download_object(self.bucket, object_name)
                    if (len(received) != len(blob) or received != blob
                            or hashlib.sha256(received).hexdigest() != digest):
                        raise ValueError("Yamcs GET did not return the exact uploaded raw product")
                    receipt = dict(incoming)
                    receipt.update({
                        "bucket": self.bucket,
                        "objectName": object_name,
                        "receiptObject": receipt_name,
                        "verifiedGroundReceipt": True,
                        "verificationMethod": "Yamcs GET exact bytes and SHA-256 match",
                        "verifiedAt": datetime.now(timezone.utc).isoformat(),
                    })
                    receipt_bytes = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                    storage.upload_object(self.bucket, receipt_name, io.BytesIO(receipt_bytes),
                                          content_type="application/json", metadata=receipt_metadata)
                    receipt_readback = storage.download_object(self.bucket, receipt_name)
                    if receipt_readback != receipt_bytes:
                        raise ValueError("Yamcs GET did not return the exact ground receipt manifest")
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise
                    time.sleep(0.25 * (attempt + 1))

            if receipt is None:
                raise RuntimeError("Yamcs did not verify the raw product")

            extras = {
                "runId": run_id,
                "productId": str(product_id),
                "transferId": str(transfer_id),
                "bytes": str(len(blob)),
                "crc16Ccitt": str(crc),
                "sha256": digest,
                "objectName": object_name,
                "receiptObject": receipt_name,
                "verifiedGroundReceipt": "true",
            }
            # This event marks ground receipt only. It is independent of any
            # sender-side COMPLETE/ACK state from F′ or the payload simulator.
            try:
                client.send_event(
                    self.instance,
                    message=f"{RECEIPT_EVENT}: Yamcs returned and verified {len(blob)} raw science bytes",
                    event_type=RECEIPT_EVENT,
                    severity="info",
                    source="n2-local-science-ingest",
                    extra=extras,
                )
            except Exception as exc:
                # The stored receipt remains a valid readback record, but a
                # missing archive event must remain visible to the acceptance
                # probe rather than being fabricated locally.
                print(f"[science-ingest] verified bucket receipt; Yamcs event failed: {exc}", flush=True)
            print(f"[science-ingest] verified raw object {object_name} sha256={digest}", flush=True)
            return receipt
        finally:
            client.close()


class GroundScienceIngest:
    """Glue packet receiver, retry envelope, local-only viewer, and publisher."""

    def __init__(self, run_id: str, enqueue_frame: Callable[[bytes], None],
                 fault_profile: frozenset[str] = frozenset(), on_result=None) -> None:
        self._retry_writer = _RetryWriter(enqueue_frame, self._on_retry)
        self._external_on_result = on_result
        # The publisher runs on a worker thread, while receive/tick and all
        # receiver state belong to LocalLink's PTY loop. At most one capture
        # can await publication, so a one-entry queue bounds callback memory.
        self._publication_callbacks: queue.Queue[tuple[str, dict, str | None]] = queue.Queue(maxsize=1)
        self.receiver = None
        self.publisher = YamcsGroundPublisher(run_id, on_result=self._on_publish_success,
                                               on_failure=self._on_publish_failure)
        self.receiver = PayloadReceiverAdapter(run_id, self.publisher.submit,
                                               self._retry_writer, fault_profile)
        self.publisher.start()

    def _on_retry(self, packet: bytes) -> None:
        self.receiver.retry_written(packet)

    def _on_publish_success(self, receipt: dict) -> None:
        self._queue_publication_callback("success", receipt)

    def _on_publish_failure(self, manifest: dict, error_text: str) -> None:
        self._queue_publication_callback("failure", manifest, error_text)

    def _queue_publication_callback(self, kind: str, payload: dict,
                                    error_text: str | None = None) -> None:
        callback = (kind, dict(payload), error_text)
        try:
            self._publication_callbacks.put_nowait(callback)
        except queue.Full:
            # This is prevented by the receiver's single pending-capture
            # admission rule. A bounded wait lets the PTY loop drain an
            # already queued terminal result without blocking UART handling.
            try:
                self._publication_callbacks.put(callback, timeout=YAMCS_TIMEOUT_S)
            except queue.Full:
                print("[science-ingest] publication callback queue remained full; "
                      "receiver state was left untouched", flush=True)

    def _drain_publication_callbacks(self) -> None:
        while True:
            try:
                kind, payload, error_text = self._publication_callbacks.get_nowait()
            except queue.Empty:
                return
            if kind == "success":
                self.receiver.publication_succeeded(payload)
                if self._external_on_result:
                    try:
                        self._external_on_result(payload)
                    except Exception as exc:
                        print(f"[science-ingest] receipt callback failed: {exc}", flush=True)
            elif kind == "failure":
                self.receiver.publication_failed(payload, error_text or "unknown Yamcs publish failure")
            else:
                print(f"[science-ingest] ignored unknown publication callback: {kind}", flush=True)

    def receive(self, packet: bytes) -> None:
        injected = self.receiver.apply_local_fault_fixture(packet)
        if injected is not None:
            self.receiver.receive(injected)

    def tick(self) -> None:
        self._drain_publication_callbacks()
        self.receiver.tick()

    def close(self) -> None:
        self.publisher.close()

    @property
    def counters(self) -> Mapping[str, int]:
        return dict(self.receiver.counters)
