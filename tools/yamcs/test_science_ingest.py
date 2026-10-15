import threading
import unittest

from science_ingest import MAX_RAW_BYTES, PayloadReceiverAdapter, YamcsGroundPublisher
from payload_receiver import DATA_BYTES, MAGIC, TYPE_DATA, TYPE_END, TYPE_HEADER, crc16_ccitt


def header(product_id, transfer_id, raw, *, size=None, count=None, file_crc=None):
    size = len(raw) if size is None else size
    count = (size + DATA_BYTES - 1) // DATA_BYTES if count is None else count
    file_crc = crc16_ccitt(raw) if file_crc is None else file_crc
    return (MAGIC + bytes([TYPE_HEADER, transfer_id]) + product_id.to_bytes(4, "little")
            + size.to_bytes(4, "little") + count.to_bytes(2, "little")
            + bytes([DATA_BYTES]) + file_crc.to_bytes(2, "little"))


def data_packet(transfer_id, index, payload):
    packet = MAGIC + bytes([TYPE_DATA, transfer_id]) + index.to_bytes(2, "little")
    packet += bytes([len(payload)]) + payload
    return packet + crc16_ccitt(packet).to_bytes(2, "little")


def end_packet(transfer_id, count, file_crc):
    return MAGIC + bytes([TYPE_END, transfer_id]) + count.to_bytes(2, "little") + file_crc.to_bytes(2, "little")


class ScienceIngestTests(unittest.TestCase):
    def setUp(self):
        self.raw = b"t_s,counts,flag\n" + b"".join(
            f"{idx},{idx % 7},BG\n".encode() for idx in range(45)
        )
        self.received = []
        self.retries = []
        self.receiver = PayloadReceiverAdapter(
            "run-test",
            lambda blob, manifest: self.received.append((blob, manifest)) or True,
            type("RetrySink", (), {"write": lambda _, packet: self.retries.append(packet) or len(packet)})(),
        )

    def packets(self, transfer=7, product=0x1234):
        count = (len(self.raw) + DATA_BYTES - 1) // DATA_BYTES
        return [header(product, transfer, self.raw)] + [
            data_packet(transfer, idx, self.raw[idx * DATA_BYTES:(idx + 1) * DATA_BYTES])
            for idx in range(count)
        ] + [end_packet(transfer, count, crc16_ccitt(self.raw))]

    def test_requires_matching_end_and_deduplicates_header(self):
        packets = self.packets()
        self.receiver.receive(packets[0])
        self.receiver.receive(packets[1])
        received_before_duplicate = len(self.receiver.packets)
        self.receiver.receive(packets[0])
        self.assertEqual(len(self.receiver.packets), received_before_duplicate)
        for packet in packets[2:-1]:
            self.receiver.receive(packet)
        self.assertEqual(self.received, [])
        self.receiver.receive(packets[-1])
        self.receiver.tick()
        self.assertEqual(len(self.received), 1)
        blob, manifest = self.received[0]
        self.assertEqual(blob, self.raw)
        self.assertEqual(manifest["productId"], 0x1234)
        self.assertEqual(manifest["transferId"], 7)
        self.assertEqual(manifest["bytes"], len(self.raw))
        self.assertEqual(manifest["verifiedGroundReceipt"], False)

        # A completed duplicate header cannot schedule a second publication.
        self.receiver.receive(packets[0])
        self.receiver.tick()
        self.assertEqual(len(self.received), 1)

    def test_end_requests_missing_packets_and_one_shot_faults_repair(self):
        class RetrySink:
            def write(inner_self, packet):
                self.retries.append(packet)
                faulted.retry_written(packet)
                return len(packet)

        faulted = PayloadReceiverAdapter(
            "run-test",
            lambda blob, manifest: self.received.append((blob, manifest)) or True,
            RetrySink(),
            frozenset({"drop-first-0", "corrupt-first-1"}),
        )
        packets = self.packets()
        faulted.receive(packets[0])
        for packet in packets[1:-1]:
            packet = faulted.apply_local_fault_fixture(packet)
            if packet is not None:
                faulted.receive(packet)
        faulted.receive(packets[-1])
        self.assertTrue(self.retries)
        self.assertEqual(self.retries[0][2], 4)  # TYPE_RETRY_REQUEST
        retries_after_first_end = len(self.retries)
        faulted.receive(packets[-1])
        self.assertEqual(len(self.retries), retries_after_first_end)
        self.assertEqual(faulted.counters["duplicateEndPackets"], 1)
        self.assertEqual(faulted.counters["faultPacketsDropped"], 1)
        self.assertEqual(faulted.counters["faultPacketsCorrupted"], 1)
        for packet in packets[1:-1]:
            packet = faulted.apply_local_fault_fixture(packet)
            if packet is not None:
                faulted.receive(packet)
        faulted.tick()
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0][0], self.raw)
        self.assertEqual(self.received[0][1]["faults"]["packetsDropped"], 1)
        self.assertEqual(self.received[0][1]["faults"]["packetsCorrupted"], 1)
        self.assertGreaterEqual(self.received[0][1]["faults"]["retryRequestsSent"], 1)
        self.assertEqual(self.received[0][1]["groundIngestCounters"]["recoveredPackets"], 2)

    def test_rejects_oversize_header_and_bad_packet_crc(self):
        oversize = header(1, 1, self.raw, size=MAX_RAW_BYTES + 1,
                          count=(MAX_RAW_BYTES + DATA_BYTES) // DATA_BYTES)
        self.receiver.receive(oversize)
        self.assertIsNone(self.receiver.active_header)
        self.assertEqual(self.receiver.counters["rejectedHeaders"], 1)

        packets = self.packets(transfer=8)
        self.receiver.receive(packets[0])
        corrupt = bytearray(packets[1])
        corrupt[7] ^= 1
        self.receiver.receive(bytes(corrupt))
        self.assertEqual(self.receiver.counters["badDataPacketCrc"], 1)
        self.assertNotIn(0, self.receiver.packets)

    def test_requires_whole_file_crc_after_matching_end(self):
        crc = (crc16_ccitt(self.raw) + 1) & 0xFFFF
        count = (len(self.raw) + DATA_BYTES - 1) // DATA_BYTES
        packets = [header(3, 9, self.raw, file_crc=crc)] + [
            data_packet(9, idx, self.raw[idx * DATA_BYTES:(idx + 1) * DATA_BYTES])
            for idx in range(count)
        ] + [end_packet(9, count, crc)]
        for packet in packets:
            self.receiver.receive(packet)
        self.assertEqual(self.received, [])
        self.assertEqual(self.receiver.counters["wholeFileCrcFailures"], 1)

    def test_transient_publish_failure_retains_capture_until_verified_retry(self):
        failed = threading.Event()
        published = threading.Event()
        failures = []
        receipts = []
        publish_attempts = []

        receiver = None

        def on_result(receipt):
            receiver.publication_succeeded(receipt)
            receipts.append(receipt)
            published.set()

        def on_failure(manifest, error_text):
            receiver.publication_failed(manifest, error_text)
            failures.append(error_text)
            failed.set()

        publisher = YamcsGroundPublisher(
            "run-test", on_result=on_result, on_failure=on_failure
        )

        def submit(blob, manifest):
            return publisher.submit(blob, manifest)

        receiver = PayloadReceiverAdapter(
            "run-test", submit,
            type("RetrySink", (), {"write": lambda _, packet: len(packet)})(),
        )

        def publish_once_then_succeed(blob, manifest):
            publish_attempts.append((blob, dict(manifest)))
            if len(publish_attempts) == 1:
                raise OSError("temporary Yamcs readback failure")
            result = dict(manifest)
            result.update({
                "objectName": "verified-raw.bin",
                "receiptObject": "verified-raw.bin.receipt.json",
                "verifiedGroundReceipt": True,
            })
            return result

        publisher._publish = publish_once_then_succeed
        publisher.start()
        try:
            packets = self.packets(transfer=10, product=0x4321)
            for packet in packets:
                receiver.receive(packet)
            receiver.tick()

            self.assertTrue(failed.wait(2), "publisher did not report transient failure")
            self.assertIsNotNone(receiver.pending_capture)
            self.assertEqual(len(receipts), 0, "receipt appeared before a successful readback")
            self.assertFalse(receiver.pending_capture[1]["verifiedGroundReceipt"])
            self.assertEqual(len(failures), 1)

            # Bypass the production backoff so the unit test remains bounded.
            receiver.next_submit_try = 0.0
            receiver.tick()
            self.assertTrue(published.wait(2), "retained capture was not retried")
            self.assertIsNone(receiver.pending_capture)
            self.assertEqual(len(publish_attempts), 2)
            self.assertEqual(len(receipts), 1)
            self.assertTrue(receipts[0]["verifiedGroundReceipt"])

            # A duplicate completed transfer must not publish or emit a second receipt.
            receiver.receive(packets[0])
            receiver.tick()
            self.assertEqual(len(publish_attempts), 2)
            self.assertEqual(len(receipts), 1)
        finally:
            publisher.close()


if __name__ == "__main__":
    unittest.main()
