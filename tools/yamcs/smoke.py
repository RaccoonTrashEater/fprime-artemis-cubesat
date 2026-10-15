#!/usr/bin/env python3
"""Issue/observe an N2 ping exclusively through the Yamcs HTTP API."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import secrets
import time
from urllib import request, parse, error

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8090"
INSTANCE = "fprime-project"
PROCESSOR = "realtime"


def api(path, body=None):
    req = request.Request(URL + path, None if body is None else json.dumps(body).encode(),
                          {"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with request.urlopen(req, timeout=10) as response:
        return json.load(response)


def issue(name, args):
    # Resolve the converter's qualified space-system path instead of assuming
    # the reference deployment's namespace or using the original FPP name.
    listing = api(f"/api/mdb/{INSTANCE}/commands?" + parse.urlencode({"q": name.split(".")[-1], "limit": 500}))
    matches = [c["qualifiedName"] for c in listing.get("commands", [])
               if c["qualifiedName"].endswith("/" + name.replace(".", "/"))]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Yamcs command for {name}, found {matches}")
    return api(f"/api/processors/{INSTANCE}/{PROCESSOR}/commands/" + parse.quote(matches[0], safe="/"),
               {"args": args, "origin": "n2-local-yamcs-smoke", "sequenceNumber": int(time.time()) % 2147483647})


def events(query):
    response = api(f"/api/archive/{INSTANCE}/events?" + parse.urlencode({"q": query, "limit": 100}))
    return response.get("events", response.get("event", []))


def wait_for_event(query, timeout=30, after=None, predicate=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = events(query)
        if after is not None:
            found = [e for e in found if datetime.fromisoformat(e["receptionTime"].replace("Z", "+00:00")) >= after]
        if predicate is not None:
            found = [e for e in found if predicate(e)]
        if found:
            return found[0]
        time.sleep(0.5)
    raise RuntimeError(f"No Yamcs event matching {query!r} within {timeout}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", type=int, default=None)
    args = parser.parse_args()
    token = args.token if args.token is not None else secrets.randbelow(4294967295)
    deadline = time.monotonic() + 90
    while True:
        try:
            instances = api("/api/instances")
            if any(i["name"] == INSTANCE and i["state"] == "RUNNING" for i in instances.get("instances", [])):
                break
        except (error.URLError, TimeoutError, OSError):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Yamcs instance did not reach RUNNING within 90s")
        time.sleep(1)
    command = issue("ArtemisRpiTeensyDeployment.missionApp.PING", {"token": token})
    released = datetime.fromisoformat(command["generationTime"].replace("Z", "+00:00"))
    pong = wait_for_event(f"token={token}", after=released,
                          predicate=lambda e: e.get("type") == "ArtemisRpiTeensyDeployment.missionApp.Pong"
                          and e.get("extra", {}).get("token") == str(token))
    result = {"result": "PASS", "token": token, "command": command, "pong_from_yamcs": pong}
    current = json.loads((ROOT / "yamcs" / "run" / "current.json").read_text())
    dest = Path(current["run_dir"]) / f"ping-{token}.json"
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"Evidence: {dest}")


if __name__ == "__main__":
    main()
