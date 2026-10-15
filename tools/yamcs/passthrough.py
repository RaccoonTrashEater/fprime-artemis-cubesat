#!/usr/bin/env python3
"""Exercise the synthetic literal payload pass-through using Yamcs only."""
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import secrets
import time
from urllib import error, parse

from smoke import ROOT, INSTANCE, api, issue, wait_for_event

DEPLOYMENT = "ArtemisRpiTeensyDeployment"
COMPONENT = "payloadManager"
MAX_LITERAL_BYTES = 128


def parameter(name):
    listing = api(f"/api/mdb/{INSTANCE}/parameters?" + parse.urlencode({"q": name.split(".")[-1], "limit": 500}))
    matches = [p["qualifiedName"] for p in listing.get("parameters", [])
               if p["qualifiedName"].endswith("/" + name.replace(".", "/"))]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Yamcs parameter for {name}, found {matches}")
    return api(f"/api/processors/{INSTANCE}/realtime/parameters/" + parse.quote(matches[0], safe="/"))


def wait_for_running(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            instances = api("/api/instances")
            if any(i["name"] == INSTANCE and i["state"] == "RUNNING"
                   for i in instances.get("instances", [])):
                return
        except (error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Yamcs instance {INSTANCE} did not reach RUNNING within {timeout}s")


def returned_event(command, event_name, predicate, timeout=30):
    released = datetime.fromisoformat(command["generationTime"].replace("Z", "+00:00"))
    expected_type = f"{DEPLOYMENT}.{COMPONENT}.{event_name}"
    return wait_for_event(event_name, timeout=timeout, after=released,
                          predicate=lambda event: event.get("type") == expected_type and predicate(event))


def mode_value(acquired_after=None, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = parameter(f"{DEPLOYMENT}.missionApp.CurrentMode")
        acquired = value.get("acquisitionTime")
        if value.get("acquisitionStatus") == "ACQUIRED" and acquired:
            acquired_at = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
            if acquired_after is None or acquired_at >= acquired_after:
                mode = value.get("engValue", {}).get("stringValue")
                if mode is not None:
                    return mode
        time.sleep(0.5)
    raise RuntimeError("Yamcs has no fresh acquired missionApp.CurrentMode value")


def probe():
    current = json.loads((ROOT / "yamcs" / "run" / "current.json").read_text())
    run = Path(current["run_dir"])
    evidence_path = run / f"passthrough-{secrets.token_hex(6)}.json"
    base = 'literal command: keep spaces, =, [brackets], \'quotes\', /? !'
    seed = 'MAX128: "A B" = C;[]{}!@#$%^&*()/+-_'
    maximum = (seed * ((MAX_LITERAL_BYTES // len(seed)) + 1))[:MAX_LITERAL_BYTES]
    if len(base.encode("ascii")) <= 40 or len(maximum.encode("ascii")) != MAX_LITERAL_BYTES:
        raise RuntimeError("Probe vectors do not cover >40 characters and the declared maximum")
    vectors = [
        {"requestId": secrets.randbelow(0xFFFFFFFC) + 1, "literalCommand": base},
        {"requestId": secrets.randbelow(0xFFFFFFFC) + 1, "literalCommand": maximum},
    ]
    result = {
        "result": "IN_PROGRESS",
        "route": "Yamcs -> PayloadManager -> typed synthetic pass-through port -> PayloadDriver_NeutronSim -> typed response port -> Yamcs event",
        "hardware_or_rf_used": False,
        "text_contract": "printable ASCII only; embedded NUL and non-ASCII are not validated",
        "max_literal_bytes": MAX_LITERAL_BYTES,
        "vectors": vectors,
    }
    try:
        wait_for_running()
        stack_started = datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))
        result["mode_before"] = mode_value(acquired_after=stack_started)
        first_release = None
        for vector in vectors:
            command = issue(
                f"{DEPLOYMENT}.{COMPONENT}.SYNTHETIC_PASSTHROUGH",
                vector,
            )
            if first_release is None:
                first_release = datetime.fromisoformat(command["generationTime"].replace("Z", "+00:00"))
            vector_result = {"command": command}
            vector_result["forwarded_event"] = returned_event(
                command,
                "SyntheticPassthroughForwarded",
                lambda event, v=vector: (
                    str(event.get("extra", {}).get("requestId")) == str(v["requestId"])
                    and event.get("extra", {}).get("literalCommand") == v["literalCommand"]
                ),
            )
            vector_result["response_event"] = returned_event(
                command,
                "SyntheticPassthroughResponse",
                lambda event, v=vector: (
                    str(event.get("extra", {}).get("requestId")) == str(v["requestId"])
                    and event.get("extra", {}).get("literalEcho") == v["literalCommand"]
                    and str(event.get("extra", {}).get("status")) in ("SIMULATED_ECHOED", "0")
                ),
            )
            result.setdefault("observed", []).append(vector_result)

        # Let any unexpected, mode-related event from the command path reach Yamcs.
        time.sleep(1)
        result["mode_after"] = mode_value()
        if result["mode_after"] != result["mode_before"]:
            raise RuntimeError(f"Pass-through changed mission mode: {result['mode_before']} -> {result['mode_after']}")

        if first_release is None:
            raise RuntimeError("No command was issued")
        mode_events = api("/api/archive/fprime-project/events?" +
                          parse.urlencode({"q": "ModeChanged", "limit": 100}))
        returned = mode_events.get("events", mode_events.get("event", []))
        new_mode_events = [event for event in returned
                           if event.get("type") == f"{DEPLOYMENT}.missionApp.ModeChanged"
                           and datetime.fromisoformat(event["receptionTime"].replace("Z", "+00:00")) >= first_release]
        result["mode_change_events_after_commands"] = new_mode_events
        if new_mode_events:
            raise RuntimeError("Pass-through emitted a mission mode change event")

        result["result"] = "PASS"
    except Exception as exc:
        result["result"] = "FAIL"
        result["error"] = str(exc)
        raise
    finally:
        evidence_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        print(f"Evidence: {evidence_path}")


if __name__ == "__main__":
    # Prevent concurrent local Yamcs probes from sharing command/event histories.
    with (ROOT / "yamcs/run/demo.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        probe()
