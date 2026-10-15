#!/usr/bin/env python3
"""Correlate the supported N2 Yamcs commands with FSW and ground outcomes.

Only VERIFIED_COLLECT_AND_DOWNLINK and VERIFIED_REQUEST_SCIENCE_DOWNLINK are
covered. Yamcs command release/dispatch acknowledgments remain distinct from
these asynchronous completion acknowledgments.
"""

from __future__ import annotations

import argparse
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib import error, parse, request


SUPPORTED_COMMANDS = {
    ("scienceApp", "VERIFIED_COLLECT_AND_DOWNLINK"): "capture",
    ("commsApp", "VERIFIED_REQUEST_SCIENCE_DOWNLINK"): "redownlink",
}
CAPTURE_EVENT = ".scienceApp.VerifiedCaptureStatus"
COMMS_EVENT = ".commsApp.VerifiedDownlinkStatus"
STORED_EVENT = ".storageManager.ScienceProductCommitted"
SENDER_STARTED_EVENT = ".payloadDownlinkApp.PayloadDownlinkStarted"
SENDER_COMPLETE_EVENT = ".payloadDownlinkApp.PayloadDownlinkComplete"
GROUND_RECEIPT_EVENT = "GroundScienceReceiptVerified"
MAX_ARCHIVE_PAGES = 2000
PAGE_SIZE = 500
MAX_REMEMBERED_EVENTS = 8192
POLL_SECONDS = 0.5
HTTP_TIMEOUT_SECONDS = 5
# Yamcs 5.12.8 CommandQueueManager.addToCommandHistory accepts STRING values only:
# https://github.com/yamcs/yamcs/blob/yamcs-5.12.8/yamcs-core/src/main/java/org/yamcs/commanding/CommandQueueManager.java#L354-L362


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_command_name(value: str) -> tuple[str, str] | None:
    parts = [part for part in value.replace("/", ".").split(".") if part]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def scalar_value(value: dict | None):
    if not isinstance(value, dict):
        return value
    for name in ("stringValue", "uint32Value", "sint32Value", "uint64Value", "sint64Value",
                 "booleanValue", "timestampValue"):
        if name in value:
            return value[name]
    return None


def uint32(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not 0 <= parsed <= 0xFFFFFFFF:
        return None
    return parsed


def event_field(event: dict, name: str) -> str | None:
    value = event.get("extra", {}).get(name)
    return None if value is None else str(value)


def event_uint(event: dict, name: str) -> int | None:
    return uint32(event_field(event, name))


def event_identity(event: dict) -> str:
    return "|".join(str(event.get(name, "")) for name in
                     ("source", "seqNumber", "generationTime", "type"))


def command_token(command: dict) -> int | None:
    for assignment in command.get("assignments", []):
        if assignment.get("name") == "verificationToken":
            value = scalar_value(assignment.get("value"))
            return uint32(value)
    return None


def latest_attributes(command: dict) -> dict[str, object]:
    result = {}
    for attribute in command.get("attr", command.get("attributes", [])):
        name = attribute.get("name")
        if name:
            result[name] = scalar_value(attribute.get("value"))
    return result


class YamcsHttp:
    def __init__(self, base_url: str, timeout: float = HTTP_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def json(self, method: str, path: str, body: dict | None = None) -> dict:
        raw = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if raw is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request(self.base_url + path, data=raw, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = response.read()
        if not payload:
            return {}
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError(f"Yamcs returned a non-object response for {path}")
        return decoded

    def bytes(self, path: str) -> bytes:
        req = request.Request(self.base_url + path, headers={"Accept": "application/octet-stream"})
        with request.urlopen(req, timeout=self.timeout) as response:
            return response.read()


class CommandVerifier:
    """Bounded poller whose authoritative input is the current Yamcs archive."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.run_dir = Path(self.manifest["run_dir"]).resolve()
        self.run_id = str(self.manifest["local_run_id"])
        self.started_at_text = str(self.manifest["started_at"])
        self.started_at = parse_time(self.started_at_text)
        if self.started_at is None:
            raise ValueError("manifest started_at must be an RFC 3339 timestamp")
        self.timeout_seconds = int(self.manifest.get("verification_timeout_seconds", 120))
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("verification_timeout_seconds must be between 1 and 600")
        self.instance = str(self.manifest.get("instance", "fprime-project"))
        self.processor = str(self.manifest.get("processor", "realtime"))
        self.api = YamcsHttp(str(self.manifest.get("url", "http://127.0.0.1:8090")))
        self.state_path = self.run_dir / "command-verifier-state.json"
        self.state = self._load_state()
        self._stop = False

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"version": 1, "runId": self.run_id, "startedAt": self.started_at_text,
                    "commands": {}, "tokenOwners": {}, "postedAttributes": {},
                    "seenEventIdentities": []}
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("runId") != self.run_id or state.get("startedAt") != self.started_at_text:
            raise RuntimeError("verifier state belongs to a different Yamcs run")
        if state.get("version") != 1:
            raise RuntimeError("unsupported command verifier state version")
        state.setdefault("commands", {})
        state.setdefault("tokenOwners", {})
        state.setdefault("postedAttributes", {})
        state.setdefault("seenEventIdentities", [])
        return state

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _pages(self, path: str, params: dict[str, str]) -> list[dict]:
        results = []
        next_token = None
        visited_tokens = set()
        for _ in range(MAX_ARCHIVE_PAGES):
            query = dict(params)
            if next_token:
                query["next"] = next_token
            response = self.api.json("GET", path + "?" + parse.urlencode(query))
            rows = response.get("commands", response.get("entry", []))
            if not rows:
                rows = response.get("events", response.get("event", []))
            results.extend(row for row in rows if isinstance(row, dict))
            next_token = response.get("continuationToken") or None
            if next_token is None:
                return results
            if next_token in visited_tokens:
                raise RuntimeError("Yamcs archive pagination returned a repeated continuation token")
            visited_tokens.add(next_token)
        raise RuntimeError("Yamcs archive pagination exceeded the bounded page limit")

    def _fetch_commands(self) -> list[dict]:
        rows = self._pages(f"/api/archive/{parse.quote(self.instance, safe='')}/commands",
                           {"start": self.started_at_text, "order": "asc", "limit": str(PAGE_SIZE)})
        return [row for row in rows if self._supported_kind(row) is not None]

    def _fetch_events(self) -> list[dict]:
        base = f"/api/archive/{parse.quote(self.instance, safe='')}/events"
        params = {"start": self.started_at_text, "order": "asc", "limit": str(PAGE_SIZE)}
        # FSW events carry the token and transfer identity; ground receipts are
        # sent by the separate local ingest source.
        fsw = self._pages(base, dict(params, source="FPrimeEventProcessor"))
        ground = self._pages(base, dict(params, source="n2-local-science-ingest"))
        by_identity = {event_identity(event): event for event in fsw + ground}
        events = list(by_identity.values())
        events.sort(key=lambda event: (parse_time(event.get("receptionTime")) or
                                       parse_time(event.get("generationTime")) or self.started_at,
                                       int(event.get("seqNumber", 0))))
        remembered = self.state["seenEventIdentities"]
        remembered_set = set(remembered)
        for event in events:
            identity = event_identity(event)
            if identity not in remembered_set:
                remembered.append(identity)
                remembered_set.add(identity)
        if len(remembered) > MAX_REMEMBERED_EVENTS:
            del remembered[:-MAX_REMEMBERED_EVENTS]
        return events

    @staticmethod
    def _supported_kind(command: dict) -> str | None:
        name = normalize_command_name(str(command.get("commandName", "")))
        return SUPPORTED_COMMANDS.get(name) if name else None

    @staticmethod
    def _typed_value(kind: str, value):
        if kind == "STRING":
            return {"type": "STRING", "stringValue": str(value)}
        raise ValueError(f"Yamcs 5.12 command-history updates support STRING values only, got {kind}")

    def _post_updates(self, commands: list[dict], updates: dict[str, dict[str, tuple[str, object, object]]]) -> None:
        by_id = {str(command.get("id", "")): command for command in commands}
        posted = self.state["postedAttributes"]
        for command_id, fields in updates.items():
            command = by_id.get(command_id)
            if command is None or not fields:
                continue
            attributes = []
            for name, (kind, value, semantic) in fields.items():
                attributes.append({"name": name, "value": self._typed_value(kind, value)})
            qualified_name = str(command.get("commandName", ""))
            path_name = parse.quote(qualified_name, safe="")
            path = (f"/api/processors/{parse.quote(self.instance, safe='')}/"
                    f"{parse.quote(self.processor, safe='')}/commandhistory/{path_name}")
            try:
                self.api.json("POST", path, {"id": command_id, "attributes": attributes})
            except (error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                print(f"[command-verifier] command-history update failed id={command_id}: {exc}",
                      file=sys.stderr, flush=True)
                continue
            remembered = posted.setdefault(command_id, {})
            for name, (_kind, _value, semantic) in fields.items():
                remembered[name] = semantic

    def _queue_attr(self, updates, command, name: str, kind: str, value, semantic=None) -> None:
        command_id = str(command.get("id", ""))
        if not command_id:
            return
        semantic = value if semantic is None else semantic
        current = latest_attributes(command).get(name)
        saved = self.state["postedAttributes"].get(command_id, {}).get(name)
        if str(current) == str(semantic) or str(saved) == str(semantic):
            return
        row = updates.setdefault(command_id, {})
        if name not in row or str(row[name][2]) != str(semantic):
            row[name] = (kind, value, semantic)

    def _correlation(self, updates, command, *, token=None, request_id=None, generation=None,
                     product_id=None, transfer_id=None, product_bytes=None, crc=None, sha256=None,
                     receipt_object=None) -> None:
        values = (("Verification_RunId", "STRING", self.run_id),
                  ("Verification_Token", "STRING", token),
                  ("Verification_RequestId", "STRING", request_id),
                  ("Verification_Generation", "STRING", generation),
                  ("Verification_ProductId", "STRING", product_id),
                  ("Verification_TransferId", "STRING", transfer_id),
                  ("Verification_Bytes", "STRING", product_bytes),
                  ("Verification_CRC16_CCITT", "STRING", crc),
                  ("Verification_SHA256", "STRING", sha256),
                  ("Verification_ReceiptObject", "STRING", receipt_object))
        for name, kind, value in values:
            if value is not None:
                self._queue_attr(updates, command, name, kind, value)

    def _ack(self, updates, command, stage: str, status: str, message: str) -> None:
        if status not in ("OK", "NOK", "TIMEOUT"):
            raise ValueError(f"invalid verification acknowledgment status: {status}")
        # Yamcs renders the native command Completion column from this final
        # status and only recognizes OK/NOK. Keep TIMEOUT on stage attributes,
        # while representing a timed-out overall command as a final failure.
        posted_status = "NOK" if stage == "CommandComplete" and status == "TIMEOUT" else status
        command_id = str(command.get("id", ""))
        status_name = f"{stage}_Status"
        time_name = f"{stage}_Time"
        queued = updates.get(command_id, {})
        current = latest_attributes(command)
        saved = self.state["postedAttributes"].get(command_id, {})

        def known_value(name: str):
            if name in queued:
                return queued[name][2]
            value = current.get(name)
            return saved.get(name) if value is None else value

        previous_status = known_value(status_name)
        same_status = (previous_status is not None) and (str(previous_status) == posted_status)
        self._queue_attr(updates, command, status_name, "STRING", posted_status)
        if not same_status or known_value(time_name) is None:
            # Preserve the first acknowledgment time while the stage remains
            # in the same state, including across verifier restarts.
            now_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            self._queue_attr(updates, command, time_name, "STRING", now_utc)
        self._queue_attr(updates, command, f"{stage}_Message", "STRING", message)

    def _event_after(self, event: dict, command: dict) -> bool:
        event_time = parse_time(event.get("receptionTime")) or parse_time(event.get("generationTime"))
        command_time = parse_time(command.get("generationTime"))
        return event_time is not None and command_time is not None and event_time >= command_time

    def _events_of_type(self, events: list[dict], suffix: str, command: dict) -> list[dict]:
        return [event for event in events
                if str(event.get("type", "")).endswith(suffix) and self._event_after(event, command)]

    def _final_status(self, command: dict) -> str | None:
        value = latest_attributes(command).get("CommandComplete_Status")
        return str(value) if value in ("OK", "NOK", "TIMEOUT") else None

    @staticmethod
    def _owner_sort_key(command: dict) -> tuple[float, str]:
        command_time = parse_time(command.get("generationTime"))
        return (command_time.timestamp() if command_time is not None else float("inf"),
                str(command.get("id", "")))

    def _ensure_token_owners(self, commands: list[dict]) -> None:
        candidates: dict[str, list[dict]] = {}
        for command_id, saved in self.state["commands"].items():
            token = uint32(saved.get("token"))
            if token not in (None, 0):
                candidates.setdefault(str(token), []).append(
                    {"id": command_id, "generationTime": saved.get("generationTime")})
        for command in commands:
            token = command_token(command)
            if token not in (None, 0):
                candidates.setdefault(str(token), []).append(command)
        owners = self.state["tokenOwners"]
        for token, rows in candidates.items():
            if token not in owners:
                owners[token] = min(rows, key=self._owner_sort_key).get("id", "")

    def _fail_command(self, updates, command, token, kind, status: str, message: str) -> None:
        self._correlation(updates, command, token=token)
        self._ack(updates, command, "PayloadAccepted", status, message)
        if kind == "capture":
            self._ack(updates, command, "PayloadTerminal", status, message)
        else:
            self._ack(updates, command, "SenderComplete", status, message)
        self._ack(updates, command, "GroundReceipt", status, message)
        self._ack(updates, command, "CommandComplete", status, message)

    @staticmethod
    def _match_int(event: dict, key: str, expected: int) -> bool:
        return event_uint(event, key) == expected

    def _verify_receipt(self, event: dict, product_id: int, transfer_id: int,
                        product_bytes: int, crc: int) -> tuple[bool, str, dict | None, bytes | None]:
        extra = event.get("extra", {})
        if str(extra.get("runId", "")) != self.run_id:
            return False, "receipt run ID does not match this Yamcs run", None, None
        receipt_name = str(extra.get("receiptObject", ""))
        raw_name = str(extra.get("objectName", ""))
        if not receipt_name or not raw_name:
            return False, "ground receipt event omitted the object names", None, None
        try:
            query = parse.urlencode({"instance": self.instance})
            receipt_path = "/api/storage/buckets/fprimeFilesIn/objects/" + parse.quote(receipt_name, safe="")
            raw_path = "/api/storage/buckets/fprimeFilesIn/objects/" + parse.quote(raw_name, safe="")
            receipt_bytes = self.api.bytes(receipt_path + "?" + query)
            raw = self.api.bytes(raw_path + "?" + query)
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, ValueError, UnicodeDecodeError) as exc:
            return False, f"Yamcs raw/receipt object readback failed: {exc}", None, None

        digest = hashlib.sha256(raw).hexdigest()
        calculated_crc = binascii.crc_hqx(raw, 0xFFFF)
        expected_sha = str(extra.get("sha256", ""))
        checks = {
            "receipt run ID": receipt.get("runId") == self.run_id,
            "receipt product ID": uint32(receipt.get("productId")) == product_id,
            "receipt transfer ID": uint32(receipt.get("transferId")) == transfer_id,
            "receipt bytes": uint32(receipt.get("bytes")) == product_bytes,
            "receipt CRC": uint32(receipt.get("crc16Ccitt")) == crc,
            "receipt raw object": receipt.get("objectName") == raw_name,
            "receipt object identity": receipt.get("receiptObject") == receipt_name,
            "ground receipt flag": receipt.get("verifiedGroundReceipt") is True,
            "event product ID": uint32(extra.get("productId")) == product_id,
            "event transfer ID": uint32(extra.get("transferId")) == transfer_id,
            "event bytes": uint32(extra.get("bytes")) == product_bytes,
            "event CRC": uint32(extra.get("crc16Ccitt")) == crc,
            "event SHA": len(expected_sha) == 64 and expected_sha == digest,
            "raw byte length": len(raw) == product_bytes,
            "raw CRC": calculated_crc == crc,
            "receipt SHA": receipt.get("sha256") == digest,
            "event and receipt SHA": receipt.get("sha256") == expected_sha,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            return False, "ground receipt identity/readback mismatch: " + ", ".join(failed), receipt, raw

        stem = f"verified-{product_id:08x}-{transfer_id:02x}"
        (self.run_dir / f"{stem}.receipt.json").write_bytes(receipt_bytes)
        (self.run_dir / f"{stem}.bin").write_bytes(raw)
        return True, "ground receipt and independently downloaded raw bytes match", receipt, raw

    def _ground_receipts(self, events: list[dict], command: dict, product_id: int,
                         transfer_id: int) -> list[dict]:
        receipts = self._events_of_type(events, GROUND_RECEIPT_EVENT, command)
        return [event for event in receipts
                if event_field(event, "runId") == self.run_id
                and self._match_int(event, "productId", product_id)
                and self._match_int(event, "transferId", transfer_id)]

    def _capture_command(self, updates, command, token: int, events: list[dict], now: float) -> None:
        statuses = [event for event in self._events_of_type(events, CAPTURE_EVENT, command)
                    if self._match_int(event, "verificationToken", token)
                    and not (event_uint(event, "reasonCode") == 2
                             and event_uint(event, "requestId") == 0
                             and event_uint(event, "generation") == 0)]
        admissions = [event for event in statuses if event_field(event, "state") == "ACCEPTED"]
        if not admissions:
            rejected = [event for event in statuses if event_field(event, "state") != "ACCEPTED"]
            if rejected:
                failure = rejected[0]
                state = event_field(failure, "state") or "INVALID"
                reason = event_uint(failure, "reasonCode") or 0
                status = "TIMEOUT" if state == "TIMED_OUT" else "NOK"
                self._fail_command(updates, command, token, "capture", status,
                                   f"FSW rejected capture: state={state} reason={reason}")
                return
            if now >= self._deadline(command):
                self._fail_command(updates, command, token, "capture", "TIMEOUT",
                                   "no token-correlated payload admission event before deadline")
            return

        contexts = {(event_uint(event, "requestId"), event_uint(event, "generation")) for event in admissions}
        if len(contexts) != 1 or None in next(iter(contexts)):
            self._fail_command(updates, command, token, "capture", "NOK",
                               "ambiguous token-to-request/generation mapping")
            return
        request_id, generation = next(iter(contexts))
        if request_id == 0 or generation == 0:
            self._fail_command(updates, command, token, "capture", "NOK",
                               "payload admission omitted request ID or internal generation")
            return
        self._correlation(updates, command, token=token, request_id=request_id, generation=generation)
        self._ack(updates, command, "PayloadAccepted", "OK",
                  f"FSW admitted request {request_id}, internal generation {generation}")

        terminals = [event for event in statuses
                     if event_field(event, "state") != "ACCEPTED"
                     and event_uint(event, "requestId") == request_id
                     and event_uint(event, "generation") == generation]
        distinct_terminals = {(event_field(event, "state"), event_uint(event, "productId"),
                               event_uint(event, "productBytes"), event_uint(event, "sourceCrc"),
                               event_uint(event, "reasonCode")) for event in terminals}
        if len(distinct_terminals) > 1:
            self._ack(updates, command, "PayloadTerminal", "NOK",
                      "multiple conflicting terminal events matched the same generation")
            self._ack(updates, command, "SenderComplete", "NOK", "payload terminal identity was ambiguous")
            self._ack(updates, command, "GroundReceipt", "NOK", "payload terminal identity was ambiguous")
            self._ack(updates, command, "CommandComplete", "NOK", "ambiguous payload terminal event")
            return
        if not terminals:
            if now >= self._deadline(command):
                self._ack(updates, command, "PayloadTerminal", "TIMEOUT",
                          "no terminal payload event before deadline")
                self._ack(updates, command, "SenderComplete", "TIMEOUT", "capture did not reach a downlink")
                self._ack(updates, command, "GroundReceipt", "TIMEOUT", "no ground receipt before deadline")
                self._ack(updates, command, "CommandComplete", "TIMEOUT", "capture operation timed out")
            return

        terminal = terminals[0]
        state = event_field(terminal, "state") or "UNKNOWN"
        reason = event_uint(terminal, "reasonCode") or 0
        product_id = event_uint(terminal, "productId") or 0
        product_bytes = event_uint(terminal, "productBytes") or 0
        crc = event_uint(terminal, "sourceCrc") or 0
        if state != "COMPLETED" or reason != 0 or product_id == 0 or product_bytes == 0:
            status = "TIMEOUT" if state == "TIMED_OUT" else "NOK"
            self._ack(updates, command, "PayloadTerminal", status,
                      f"payload terminal state={state} reason={reason}")
            self._ack(updates, command, "SenderComplete", status,
                      f"payload terminal state={state}; no product was downlinked")
            self._ack(updates, command, "GroundReceipt", status,
                      f"payload terminal state={state}; no ground receipt is possible")
            self._ack(updates, command, "CommandComplete", status,
                      f"capture did not produce a validated payload product: state={state} reason={reason}")
            return

        self._correlation(updates, command, token=token, request_id=request_id, generation=generation,
                          product_id=product_id, product_bytes=product_bytes, crc=crc)
        self._ack(updates, command, "PayloadTerminal", "OK",
                  f"request {request_id}, generation {generation} completed with product {product_id}")

        rejections = [event for event in self._events_of_type(
            events, ".storageManager.ScienceProductRejected", command)
                      if self._match_int(event, "productId", product_id)]
        if rejections:
            if len({event_identity(event) for event in rejections}) != 1:
                self._ack(updates, command, "StorageCommitted", "NOK",
                          "multiple storage rejections matched the token-bound product")
                rejection_message = "multiple storage rejections matched the product"
            else:
                reason = event_uint(rejections[0], "reason") or 0
                rejection_message = f"StorageManager rejected product {product_id}, reason={reason}"
                self._ack(updates, command, "StorageCommitted", "NOK", rejection_message)
            self._ack(updates, command, "SenderComplete", "NOK", "storage rejected the product")
            self._ack(updates, command, "GroundReceipt", "NOK", "storage rejected the product")
            self._ack(updates, command, "CommandComplete", "NOK", rejection_message)
            return

        commits = [event for event in self._events_of_type(events, STORED_EVENT, command)
                   if self._match_int(event, "productId", product_id)
                   and self._match_int(event, "productBytes", product_bytes)
                   and self._match_int(event, "sourceCrc", crc)]
        if not commits:
            if now >= self._deadline(command):
                self._ack(updates, command, "StorageCommitted", "TIMEOUT",
                          "no matching durable storage commit was observed before deadline")
                self._ack(updates, command, "SenderComplete", "TIMEOUT", "committed product did not enter downlink")
                self._ack(updates, command, "GroundReceipt", "TIMEOUT", "no verified ground receipt before deadline")
                self._ack(updates, command, "CommandComplete", "TIMEOUT",
                          "payload completed but no matching durable storage commit was observed")
            return
        if len({event_identity(event) for event in commits}) != 1:
            self._ack(updates, command, "StorageCommitted", "NOK",
                      "multiple storage commits matched the token-bound product")
            self._ack(updates, command, "CommandComplete", "NOK",
                      "multiple storage commits matched the token-bound product")
            return
        self._ack(updates, command, "StorageCommitted", "OK",
                  f"product {product_id} is durably committed")

        starts = [event for event in self._events_of_type(events, SENDER_STARTED_EVENT, command)
                  if self._match_int(event, "productId", product_id)
                  and self._match_int(event, "byteCount", product_bytes)]
        transfers = {event_uint(event, "transferId") for event in starts}
        transfers.discard(None)
        if len(transfers) > 1:
            self._ack(updates, command, "SenderComplete", "NOK",
                      "multiple sender transfers matched the token-bound product")
            self._ack(updates, command, "GroundReceipt", "NOK",
                      "sender transfer identity was ambiguous")
            self._ack(updates, command, "CommandComplete", "NOK",
                      "multiple sender transfers matched the token-bound product")
            return
        early_failures = [event for event in self._events_of_type(events, COMMS_EVENT, command)
                          if self._match_int(event, "verificationToken", 0)
                          and self._match_int(event, "productId", product_id)
                          and self._match_int(event, "productBytes", product_bytes)
                          and self._match_int(event, "sourceCrc", crc)
                          and event_uint(event, "stateValue") in (3, 4)]
        if not transfers and early_failures:
            failed_transfers = {event_uint(event, "transferId") for event in early_failures}
            failed_transfers.discard(None)
            failed_transfers.discard(0)
            if len(failed_transfers) == 1:
                transfer_id = next(iter(failed_transfers))
                self._correlation(updates, command, token=token, request_id=request_id,
                                  generation=generation, product_id=product_id,
                                  transfer_id=transfer_id, product_bytes=product_bytes, crc=crc)
                message = "Comms reported a matching sender rejection before transfer start"
            else:
                message = "Comms sender rejection did not identify one transfer"
            self._ack(updates, command, "SenderComplete", "NOK", message)
            self._ack(updates, command, "GroundReceipt", "NOK", message)
            self._ack(updates, command, "CommandComplete", "NOK", message)
            return
        if not transfers:
            if now >= self._deadline(command):
                self._ack(updates, command, "SenderComplete", "TIMEOUT", "no matching sender transfer started")
                self._ack(updates, command, "GroundReceipt", "TIMEOUT", "no verified ground receipt before deadline")
                self._ack(updates, command, "CommandComplete", "TIMEOUT", "product downlink did not start")
            return
        transfer_id = next(iter(transfers))
        if transfer_id == 0:
            self._ack(updates, command, "SenderComplete", "NOK", "sender transfer ID was zero")
            self._ack(updates, command, "GroundReceipt", "NOK", "sender transfer ID was zero")
            self._ack(updates, command, "CommandComplete", "NOK", "sender transfer ID was zero")
            return

        failed_status = [event for event in self._events_of_type(events, COMMS_EVENT, command)
                         if self._match_int(event, "verificationToken", 0)
                         and self._match_int(event, "productId", product_id)
                         and self._match_int(event, "transferId", transfer_id)
                         and event_uint(event, "stateValue") in (3, 4)]
        if failed_status:
            self._ack(updates, command, "SenderComplete", "NOK", "Comms reported a failed matching transfer")
            self._ack(updates, command, "GroundReceipt", "NOK", "Comms reported a failed matching transfer")
            self._ack(updates, command, "CommandComplete", "NOK", "token-bound product downlink failed")
            return

        done = [event for event in self._events_of_type(events, SENDER_COMPLETE_EVENT, command)
                if self._match_int(event, "transferId", transfer_id)]
        if not done:
            if now >= self._deadline(command):
                self._ack(updates, command, "SenderComplete", "TIMEOUT", "matching sender completion was not observed")
                self._ack(updates, command, "GroundReceipt", "TIMEOUT", "no verified ground receipt before deadline")
                self._ack(updates, command, "CommandComplete", "TIMEOUT", "sender did not complete before deadline")
            return
        self._correlation(updates, command, token=token, request_id=request_id, generation=generation,
                          product_id=product_id, transfer_id=transfer_id,
                          product_bytes=product_bytes, crc=crc)
        self._ack(updates, command, "SenderComplete", "OK",
                  f"sender completed product {product_id}, transfer {transfer_id}")
        self._verify_ground_and_finish(updates, command, token, request_id, generation,
                                       product_id, transfer_id, product_bytes, crc, events, now)

    def _redownlink_command(self, updates, command, token: int, events: list[dict], now: float) -> None:
        statuses = [event for event in self._events_of_type(events, COMMS_EVENT, command)
                    if self._match_int(event, "verificationToken", token)
                    and not (event_uint(event, "reasonCode") == 2
                             and event_uint(event, "productId") == 0
                             and event_uint(event, "transferId") == 0)]
        starts = [event for event in statuses if event_uint(event, "stateValue") == 1]
        failures = [event for event in statuses if event_uint(event, "stateValue") in (3, 4)]
        if not starts:
            if failures:
                failure = failures[0]
                reason = event_uint(failure, "reasonCode") or event_uint(failure, "lastError") or 0
                self._fail_command(updates, command, token, "redownlink", "NOK",
                                   f"Comms rejected or failed verified downlink, reason={reason}")
            elif now >= self._deadline(command):
                self._fail_command(updates, command, token, "redownlink", "TIMEOUT",
                                   "no token-correlated sender admission before deadline")
            return

        contexts = {(event_uint(event, "productId"), event_uint(event, "productBytes"),
                     event_uint(event, "sourceCrc"), event_uint(event, "transferId")) for event in starts}
        if len(contexts) != 1:
            self._fail_command(updates, command, token, "redownlink", "NOK",
                               "ambiguous token-to-product/transfer binding")
            return
        product_id, product_bytes, crc, transfer_id = next(iter(contexts))
        if not product_id or not product_bytes or crc is None or not transfer_id:
            self._fail_command(updates, command, token, "redownlink", "NOK",
                               "Comms admission omitted product, size, CRC, or transfer ID")
            return
        storage_rejections = [event for event in self._events_of_type(
            events, ".storageManager.ScienceProductRejected", command)
                              if self._match_int(event, "productId", product_id)]
        if storage_rejections:
            reasons = sorted({event_uint(event, "reason") or 0 for event in storage_rejections})
            message = f"StorageManager rejected product {product_id}, reasons={reasons}"
            self._ack(updates, command, "SenderComplete", "NOK", message)
            self._ack(updates, command, "GroundReceipt", "NOK", message)
            self._ack(updates, command, "CommandComplete", "NOK", message)
            return
        self._correlation(updates, command, token=token, product_id=product_id,
                          transfer_id=transfer_id, product_bytes=product_bytes, crc=crc)
        self._ack(updates, command, "PayloadAccepted", "OK",
                  f"Comms bound token to selected product {product_id}, transfer {transfer_id}")

        bad = [event for event in failures
               if event_uint(event, "productId") in (0, product_id)
               and event_uint(event, "transferId") in (0, transfer_id)]
        if bad:
            reason = event_uint(bad[0], "reasonCode") or event_uint(bad[0], "lastError") or 0
            self._ack(updates, command, "SenderComplete", "NOK", f"Comms sender failed, reason={reason}")
            self._ack(updates, command, "CommandComplete", "NOK", "verified redownlink failed")
            return

        sender_starts = [event for event in self._events_of_type(events, SENDER_STARTED_EVENT, command)
                         if self._match_int(event, "productId", product_id)
                         and self._match_int(event, "byteCount", product_bytes)
                         and self._match_int(event, "transferId", transfer_id)]
        done_status = [event for event in starts + statuses
                       if self._match_int(event, "verificationToken", token)
                       and self._match_int(event, "productId", product_id)
                       and self._match_int(event, "productBytes", product_bytes)
                       and self._match_int(event, "sourceCrc", crc)
                       and self._match_int(event, "transferId", transfer_id)
                       and self._match_int(event, "stateValue", 2)]
        sender_done = [event for event in self._events_of_type(events, SENDER_COMPLETE_EVENT, command)
                       if self._match_int(event, "transferId", transfer_id)]
        if sender_starts and done_status and sender_done:
            self._correlation(updates, command, token=token, product_id=product_id,
                              transfer_id=transfer_id, product_bytes=product_bytes, crc=crc)
            self._ack(updates, command, "SenderComplete", "OK",
                      f"sender completed product {product_id}, transfer {transfer_id}")
            self._verify_ground_and_finish(updates, command, token, None, None,
                                           product_id, transfer_id, product_bytes, crc, events, now)
            return
        if now >= self._deadline(command):
            self._ack(updates, command, "SenderComplete", "TIMEOUT",
                      "matching FSW sender start and completion were not both observed")
            self._ack(updates, command, "GroundReceipt", "TIMEOUT", "no verified ground receipt before deadline")
            self._ack(updates, command, "CommandComplete", "TIMEOUT", "verified redownlink timed out")

    def _verify_ground_and_finish(self, updates, command, token, request_id, generation,
                                  product_id, transfer_id, product_bytes, crc, events, now) -> None:
        receipts = self._ground_receipts(events, command, product_id, transfer_id)
        if not receipts:
            if now >= self._deadline(command):
                self._ack(updates, command, "GroundReceipt", "TIMEOUT",
                          "sender completed but no matching current-run ground receipt arrived")
                self._ack(updates, command, "CommandComplete", "TIMEOUT",
                          "sender completion did not receive an independently verified ground receipt")
            return
        if len({event_identity(event) for event in receipts}) != 1:
            self._ack(updates, command, "GroundReceipt", "NOK", "multiple receipt events matched this transfer")
            self._ack(updates, command, "CommandComplete", "NOK", "ground receipt event identity was ambiguous")
            return
        receipt_ok, message, receipt, _raw = self._verify_receipt(
            receipts[0], product_id, transfer_id, product_bytes, crc)
        if not receipt_ok:
            self._ack(updates, command, "GroundReceipt", "NOK", message)
            self._ack(updates, command, "CommandComplete", "NOK", message)
            return
        self._correlation(updates, command, token=token, request_id=request_id, generation=generation,
                          product_id=product_id, transfer_id=transfer_id, product_bytes=product_bytes,
                          crc=crc, sha256=receipt["sha256"], receipt_object=receipt["receiptObject"])
        self._ack(updates, command, "GroundReceipt", "OK", message)
        self._ack(updates, command, "CommandComplete", "OK",
                  "token-correlated payload, storage, sender, Yamcs receipt, raw bytes, CRC, and SHA-256 verified")

    def _deadline(self, command: dict) -> float:
        command_time = parse_time(command.get("generationTime"))
        if command_time is None:
            return time.time()
        return command_time.timestamp() + self.timeout_seconds

    def poll_once(self) -> None:
        commands = self._fetch_commands()
        events = self._fetch_events()
        now = time.time()
        updates: dict[str, dict[str, tuple[str, object, object]]] = {}
        self._ensure_token_owners(commands)

        command_state = self.state["commands"]
        for command in commands:
            command_id = str(command.get("id", ""))
            if not command_id:
                continue
            kind = self._supported_kind(command)
            if kind is None:
                continue
            token = command_token(command)
            entry = command_state.setdefault(command_id, {})
            entry.update({"commandName": command.get("commandName"), "kind": kind,
                          "token": token, "generationTime": command.get("generationTime")})
            if self._final_status(command) is not None:
                continue
            owner_id = self.state["tokenOwners"].get(str(token)) if token not in (None, 0) else None
            if token not in (None, 0) and owner_id != command_id:
                self._fail_command(updates, command, token, kind, "NOK",
                                   f"verification token is already owned by command {owner_id}")
                continue
            if token is None:
                self._fail_command(updates, command, None, kind, "NOK",
                                   "verificationToken argument is missing or outside UINT32 range")
            elif token == 0:
                self._fail_command(updates, command, token, kind, "NOK", "verificationToken must be nonzero")
            elif kind == "capture":
                self._capture_command(updates, command, token, events, now)
            else:
                self._redownlink_command(updates, command, token, events, now)

        self._post_updates(commands, updates)
        self._save_state()

    def run(self) -> int:
        print(f"[command-verifier] run={self.run_id} instance={self.instance} processor={self.processor}",
              flush=True)
        while not self._stop:
            try:
                self.poll_once()
            except (error.URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError) as exc:
                print(f"[command-verifier] poll failed; pending rows remain unverified: {exc}",
                      file=sys.stderr, flush=True)
            time.sleep(POLL_SECONDS)
        self._save_state()
        return 0

    def stop(self, _signum=None, _frame=None) -> None:
        self._stop = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path,
                        help="local_stack run manifest containing current run identity and timeout")
    args = parser.parse_args(argv)
    verifier = CommandVerifier(args.manifest)
    signal.signal(signal.SIGTERM, verifier.stop)
    signal.signal(signal.SIGINT, verifier.stop)
    return verifier.run()


if __name__ == "__main__":
    raise SystemExit(main())
