#!/usr/bin/env python3
"""Walk the CDR payload power and collection runbook through the Yamcs HTTP API.

Follows docs/operations/CDR_PAYLOAD_POWER_RUNBOOK.md, steps S0 to S6, and saves PASS, FAIL or SKIPPED for every step in one JSON evidence file under yamcs/run/.

Bench, against a stack someone already started (docs/operations/CDR_TCP.md):
    tools/yamcs/.venv/bin/python tools/yamcs/cdr_runbook_check.py --dictionary <matching dictionary>
  Sends no EPS command unless --allow-power is given. With it, the operator types GO before power on, and
  READY once the EPS owner has measured the payload powered and the payload owner says it is ready.

Laptop rehearsal, software only:
    tools/yamcs/build_cdr_tcp.sh
    tools/yamcs/.venv/bin/python tools/yamcs/cdr_runbook_check.py --rehearse-on-laptop
  Starts the CDR TCP spacecraft process against StatefulPdu from test_pdu_readability.py (a pseudo-terminal
  that keeps rail states and answers every SET, no hardware), starts the CDR ground, runs every step, then
  stops everything. Power on and off must be confirmed exactly as on the bench, and the fake PDU must end
  with every rail off.

Runbook v0.3 (2026-11-02) uses the named PDU commands of team commit 99e1682: GET_PDU_INFO, SET_PDU_RAIL with
rail RAIL_12V and an explicit CONFIRM, the PduRailSetResult event and the Rail12V channel (ON, OFF, STALE or
UNKNOWN). Power proof = command completes OK + PduRailSetResult readback equal to the request + a fresh Rail12V.

Safety: only the payload rail (RAIL_12V, output 7) is commanded. RAIL_5V_1 (the Pi Zero's own 5 V) and
RAIL_5V_2 (heater) are refused before anything is sent. Once power on has been sent, every exit path sends
power off.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib import error, parse, request

ROOT = Path(os.environ.get("N2_REPO", str(Path(__file__).resolve().parents[2])))
URL = "http://127.0.0.1:8090"
INSTANCE = "fprime-project"
PROCESSOR = "realtime"
D = "ArtemisRpiTeensyDeployment"
PAYLOAD_RAIL = 7                       # PDU 12 V output: the ICD names no PDU rail for the payload
RAIL_NAMES = {1: "RAIL_3V3_1", 2: "RAIL_3V3_2", 3: "RAIL_5V_1", 4: "RAIL_5V_2", 5: "RAIL_5V_3", 7: "RAIL_12V", 8: "RAIL_VBATT"}
RAIL_CHANNELS = {1: "Rail3V3_1", 2: "Rail3V3_2", 3: "Rail5V_1", 4: "Rail5V_2", 5: "Rail5V_3", 7: "Rail12V", 8: "RailVBatt"}
FORBIDDEN_RAILS = {3: "5V_1 powers the Pi Zero itself", 4: "5V_2 is the Kapton heater", 6: "reserved id"}
BITMAP_ORDER = [1, 2, 3, 4, 5, 7, 8, 9, 10]   # PDU firmware 2.2.2 output order (pdu_packet.c s_outputOrder)
EXPECT_FIRMWARE = (2, 2, 2)            # pinned by neutron2-develop d4fe283
ANSWER_LIMIT_S = 8                     # runbook proof limit: 2 driver ticks of 2 s plus one 2 s status poll
BUSY_WAIT_S = 4                        # BUSY means nothing was sent: wait, then send once more
FRESH_MARGIN = timedelta(seconds=1)    # a status poll sent just before the command can still be in flight


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def api(path, body=None):
    req = request.Request(URL + path, None if body is None else json.dumps(body).encode(),
                          {"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with request.urlopen(req, timeout=10) as response:
        return json.load(response)


def qualified(kind, name):
    """The Yamcs qualified name of one dictionary entry (kind = commands or parameters)."""
    listing = api(f"/api/mdb/{INSTANCE}/{kind}?" + parse.urlencode({"q": name.split(".")[-1], "limit": 500}))
    matches = [c["qualifiedName"] for c in listing.get(kind, [])
               if c["qualifiedName"].endswith("/" + name.replace(".", "/"))]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Yamcs {kind[:-1]} for {name}, found {matches}")
    return matches[0]


def events_since(after, etype, predicate=None):
    """Archive events of one F' type received at or after `after`, oldest first."""
    params = {"limit": 500, "order": "desc", "start": after.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}
    reply = api(f"/api/archive/{INSTANCE}/events?" + parse.urlencode(params))
    found = [e for e in reply.get("events", reply.get("event", []))
             if e.get("type") == etype and utc(e["receptionTime"]) >= after and (predicate is None or predicate(e))]
    return list(reversed(found))


def wait_events(after, etype, predicate=None, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        found = events_since(after, etype, predicate)
        if found or time.monotonic() > deadline:
            return found
        time.sleep(0.5)


def tlm(name, after=None, timeout=0.0):
    """Engineering value of one channel. With `after`, wait for a sample Yamcs acquired after that time."""
    path = f"/api/processors/{INSTANCE}/{PROCESSOR}/parameters/" + parse.quote(qualified("parameters", f"{D}.{name}"), safe="/")
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = api(path)
        except error.HTTPError as exc:
            if exc.code != 404:
                raise
            value = {}
        acquired = value.get("acquisitionTime")
        if after is None or (acquired and utc(acquired) >= after + FRESH_MARGIN):
            eng = value.get("engValue", {})
            if "stringValue" in eng:  # named states such as Rail12V = ON
                return eng["stringValue"]
            return next((v for k, v in eng.items() if k.endswith("Value")), None)
        if time.monotonic() > deadline:
            return None
        time.sleep(0.5)


def command(name, args):
    """Send one command through Yamcs, then wait for the dispatcher's verdict: OK, an error name, or no reply."""
    sent = api(f"/api/processors/{INSTANCE}/{PROCESSOR}/commands/" + parse.quote(qualified("commands", f"{D}.{name}"), safe="/"),
               {"args": args, "origin": "n2-cdr-runbook-check", "sequenceNumber": int(time.time() * 1000) % 2147483647})
    released = utc(sent["generationTime"])
    opcode = next(a["value"]["uint32Value"] for a in sent["assignments"] if a["name"] == "OpCode")

    def mine(event):
        return str(event.get("extra", {}).get("Opcode")) in (str(opcode), f"0x{opcode:x}")

    deadline = time.monotonic() + ANSWER_LIMIT_S + 4
    while time.monotonic() < deadline:
        if events_since(released, "CdhCore.cmdDisp.OpCodeCompleted", mine):
            return released, "OK"
        failed = events_since(released, "CdhCore.cmdDisp.OpCodeError", mine)
        if failed:
            return released, str(failed[0].get("extra", {}).get("error", "ERROR"))
        time.sleep(0.5)
    return released, "no reply"


def ask(prompt, word):
    """Operator gate on the bench. Anything but the expected word stops the run."""
    answer = input(f"\n>>> {prompt} Type {word} to continue, anything else to stop: ").strip()
    return answer.upper() == word


class Run:
    def __init__(self, rehearsal):
        self.rehearsal = rehearsal
        self.steps = []

    def step(self, sid, title, result, **detail):
        record = {"step": sid, "title": title, "result": result, **detail}
        self.steps.append(record)
        print(f"{result:13} {sid:4} {title}", flush=True)
        for key, value in detail.items():
            print(f"{'':19}{key}: {value}", flush=True)
        return result


def power(run, sid, rail, state):
    """One SET_PDU_RAIL with the runbook v0.3 proof: command OK + PduRailSetResult readback + a fresh rail channel."""
    word = "ON" if state else "OFF"
    args = {"rail": RAIL_NAMES[rail], "desiredState": word, "confirmation": "CONFIRM"}
    released, reply = command("epsManager.SET_PDU_RAIL", args)
    if reply == "BUSY":
        time.sleep(BUSY_WAIT_S)
        released, reply = command("epsManager.SET_PDU_RAIL", args)
    results = wait_events(released, f"{D}.epsDriverArtemis.PduRailSetResult",
                          lambda e: e.get("extra", {}).get("rail") == RAIL_NAMES[rail], ANSWER_LIMIT_S if reply == "OK" else 1)
    channel = tlm(f"epsManager.{RAIL_CHANNELS[rail]}", released, ANSWER_LIMIT_S)
    detail = {"command_reply": reply,
              "set_result": [e["message"] for e in results],
              "rail_channel_after": channel,
              "mismatch_events": [e["message"] for e in events_since(released, f"{D}.epsDriverArtemis.PduRailSetMismatch")],
              "operation_errors": [e["message"] for e in events_since(released, f"{D}.epsDriverArtemis.PduOperationError")]}
    confirmed = (reply == "OK" and any(e.get("extra", {}).get("readback") == word for e in results) and channel == word)
    run.step(sid, f"power {word.lower()} on {RAIL_NAMES[rail]}: command OK, PduRailSetResult readback {word}, "
             f"{RAIL_CHANNELS[rail]} = {word}", "PASS" if confirmed else "FAIL", **detail)
    return confirmed


def run_steps(run, args, onboard_dir=None):
    rail = args.rail
    may_power = args.allow_power or run.rehearsal
    has_report_mode = args.has_report_mode
    powered = False

    def power_off(sid):
        if not may_power:
            return
        if power(run, sid, rail, 0):
            return
        print("F6: power off not proven, sending off once more", flush=True)
        if not power(run, f"{sid}r", rail, 0):
            print("\n!!! F6: power off still not proven. The EPS owner removes payload power by hand now.", flush=True)

    # S0: events reach Yamcs
    start = datetime.now(timezone.utc)
    status = wait_events(start, f"{D}.epsManager.EpsStatusUpdated", timeout=12)
    if run.step("S0", "EpsStatusUpdated reaches Yamcs (events flow)", "PASS" if status else "FAIL",
                events_in_12s=len(status)) != "PASS":
        print("F1: stop, no power commands", flush=True)
        return

    # S0b: the PDU firmware the runbook was written for
    released, reply = command("epsManager.GET_PDU_INFO", {})
    info = wait_events(released, f"{D}.epsManager.PduInfoResult", timeout=ANSWER_LIMIT_S)
    extra = info[-1].get("extra", {}) if info else {}
    firmware = tuple(int(extra.get(p, -1)) for p in ("major", "minor", "patch"))
    flags = extra.get("flags")
    good = reply == "OK" and firmware == EXPECT_FIRMWARE and flags is not None and not int(flags) & 2
    result = "PASS" if good else "FAIL"
    run.step("S0b", f"PDU firmware {'.'.join(map(str, EXPECT_FIRMWARE))}, clean build", result,
             command_reply=reply, info=[e["message"] for e in info], firmware=firmware, build_flags=flags,
             git_hash=extra.get("hash"))
    if result == "FAIL":
        print("Stop: other firmware or a dirty build. Ask Dennis. Binary and dictionary must come from one build.", flush=True)
        return

    # S1: link check, payload rail off
    if has_report_mode:
        released, reply = command("missionApp.REPORT_MODE", {})
        pong = wait_events(released, f"{D}.missionApp.ModeReport", timeout=10)
        how = "REPORT_MODE answered"
    else:
        token = secrets.randbelow(4294967295)
        released, reply = command("missionApp.PING", {"token": token})
        pong = wait_events(released, f"{D}.missionApp.Pong", lambda e: e.get("extra", {}).get("token") == str(token), 10)
        how = "PING answered"
    link = tlm("epsManager.DriverLinkState")
    health = tlm("epsManager.EpsHealthState")
    channel = tlm(f"epsManager.{RAIL_CHANNELS[rail]}")
    bitmap = tlm("epsManager.RailStateBitmap")
    rail_on = channel == "ON"
    linked = reply == "OK" and bool(pong) and str(link) == "2"
    run.step("S1", f"{how}, EPS link 2", "PASS" if linked else "FAIL",
             command_reply=reply, answer=[e["message"] for e in pong], driver_link_state=link, eps_health=health,
             rail_channel=channel, bitmap=bitmap)
    if not linked:
        print("F1: stop, no power commands", flush=True)
        return
    if rail_on:
        run.step("S1b", f"{RAIL_NAMES[rail]} already shows ON before S2", "FAIL", rail_channel=channel)
        print("Stop: ask the EPS owner why the payload rail is already on.", flush=True)
        return
    run.step("S1b", f"{RAIL_NAMES[rail]} not on before S2", "PASS", rail_channel=channel)

    try:
        # S2 and S2b: power on, then the people at the bench confirm it
        if not may_power:
            run.step("S2", "power on", "SKIPPED", note="no --allow-power: no EPS command sent")
        else:
            if not run.rehearsal and not ask(f"About to switch rail {rail} ON. EPS owner says go?", "GO"):
                run.step("S2", "power on", "SKIPPED", note="operator did not type GO")
                return
            powered = True
            ok = power(run, "S2", rail, 1)
            if not ok:
                print("F2: power on not proven, powering off", flush=True)
                return
            if not run.rehearsal:
                if not ask("EPS owner: measured payload power on? Payload owner: ready after the warm-up?", "READY"):
                    run.step("S2b", "measured on and payload ready", "FAIL", note="F3: operator stopped")
                    return
                run.step("S2b", "measured on and payload ready (operator confirmed)", "PASS")
            else:
                run.step("S2b", "measurement and ready", "SKIPPED", note="laptop rehearsal: nothing to measure")

        # S3: collect
        released, reply = command("scienceApp.SCIENCE_CAPTURE", {"durationSeconds": args.capture_seconds})
        committed = wait_events(released, f"{D}.storageManager.ScienceProductCommitted", timeout=args.capture_seconds + 30)
        product = None
        if committed:
            m = re.search(r"product=(\d+)", committed[0].get("message", ""))
            product = m.group(1) if m else committed[0].get("extra", {}).get("productId")
        if run.step("S3", "SCIENCE_CAPTURE ends in ScienceProductCommitted", "PASS" if product else "FAIL",
                    command_reply=reply, committed=[e["message"] for e in committed], product=product) != "PASS":
            print("F4: no stored product", flush=True)
            return

        # S3b: back to BASE (no CommsApp in the CDR build moves MissionApp on)
        released, reply = command("missionApp.ENTER_BASE_MODE", {})
        changed = wait_events(released, f"{D}.missionApp.ModeChanged", timeout=5)
        run.step("S3b", "ENTER_BASE_MODE", "PASS" if reply == "OK" else "FAIL",
                 command_reply=reply, mode_changed=[e["message"] for e in changed])

        # S4: download with the team's stock helper
        cmd = [str(ROOT / "tools/yamcs/downlink_stock.sh"), "--product-id", str(product), "--timeout", "60"]
        stored = onboard_dir / f"product_{product}.bin" if onboard_dir else None
        if stored and stored.exists():
            cmd += ["--expected-file", str(stored)]
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=240)
        evidence = re.search(r"Evidence: (\S+)", done.stdout)
        if run.step("S4", "stock download of the product", "PASS" if done.returncode == 0 else "FAIL",
                    exit_code=done.returncode, byte_check=bool(stored and stored.exists()),
                    evidence=evidence.group(1) if evidence else None,
                    tail=(done.stdout + done.stderr).strip().splitlines()[-3:]) != "PASS":
            print("F5: download not PASS. Power off first, then retry with a new destination.", flush=True)
    finally:
        # S5: every exit path after a power-on attempt powers off
        if powered:
            power_off("S5")


class LaptopStack:
    """Fake PDU + CDR TCP spacecraft process + CDR ground on 127.0.0.1, stopped in reverse order."""

    def __init__(self, run_dir, binary, dictionary):
        self.run_dir, self.binary, self.dictionary = run_dir, binary, dictionary
        self.pdu = self.fsw = self.ground = None

    def __enter__(self):
        for port, kind in ((8090, socket.SOCK_STREAM), (50000, socket.SOCK_DGRAM), (50001, socket.SOCK_DGRAM), (50002, socket.SOCK_DGRAM)):
            with socket.socket(socket.AF_INET, kind) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    raise SystemExit(f"Port {port} is busy: stop the other stack first.")
        sys.path.insert(0, str(ROOT / "tools" / "yamcs"))
        import test_pdu_readability as readability  # StatefulPdu: a pseudo-terminal that keeps rail states, no hardware
        stack_dir = self.run_dir / "stack"
        stack_dir.mkdir(parents=True, exist_ok=True)
        self.pdu = readability.StatefulPdu()
        env = os.environ.copy()
        env["N2_STORAGE_ROOT"] = "onboard-storage"
        env["NEUTRON_PAYLOAD_SIM_ROOT"] = str(ROOT / "external/payload-neutron-simulation")
        self.fsw = subprocess.Popen([str(self.binary), "-a", "127.0.0.1", "-p", "50000", "-d", self.pdu.device],
                                    cwd=stack_dir, env=env, stdout=open(stack_dir / "fsw.log", "w"),
                                    stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(3)
        ground_log = self.run_dir / "ground.log"
        self.ground = subprocess.Popen([str(ROOT / "tools/yamcs/run_cdr_tcp.sh"), "--dictionary", str(self.dictionary),
                                        "--address", "127.0.0.1", "--port", "50000", "--run-dir", str(self.run_dir / "ground")],
                                       cwd=ROOT, stdout=open(ground_log, "w"), stderr=subprocess.STDOUT,
                                       start_new_session=True)
        deadline = time.monotonic() + 300
        while "Event processor running" not in ground_log.read_text(errors="replace"):
            if self.ground.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("the CDR ground did not reach 'Event processor running', see ground.log")
            time.sleep(1)
        time.sleep(5)
        return self

    def __exit__(self, *exc):
        if self.ground and self.ground.poll() is None:
            os.killpg(self.ground.pid, signal.SIGINT)
            try:
                self.ground.wait(60)
            except subprocess.TimeoutExpired:
                os.killpg(self.ground.pid, signal.SIGKILL)
        if self.fsw and self.fsw.poll() is None:
            os.killpg(self.fsw.pid, signal.SIGTERM)
            try:
                self.fsw.wait(5)
            except subprocess.TimeoutExpired:  # seen on 2026-10-20: the CDR process can ignore SIGTERM
                os.killpg(self.fsw.pid, signal.SIGKILL)
                self.fsw.wait(5)
        if self.pdu:
            self.pdu.close()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dictionary", help="matching JSON dictionary (bench run against a running CDR stack)")
    parser.add_argument("--rehearse-on-laptop", action="store_true", help="start a fake-PDU CDR stack and rehearse every step")
    parser.add_argument("--binary", help="CDR TCP spacecraft binary for the rehearsal (default: build-artifacts)")
    parser.add_argument("--allow-power", action="store_true", help="bench: allow the power on and off commands")
    parser.add_argument("--rail", type=int, default=PAYLOAD_RAIL, help="payload rail id (default 7, the 12 V output)")
    parser.add_argument("--capture-seconds", type=int, default=5, help="SCIENCE_CAPTURE length, 1 to 120 (default 5)")
    parser.add_argument("--run-dir", help="evidence folder (default yamcs/run/cdr-runbook-<UTC time>)")
    args = parser.parse_args()
    if args.rail in FORBIDDEN_RAILS or args.rail not in BITMAP_ORDER:
        raise SystemExit(f"Refused: rail {args.rail} ({FORBIDDEN_RAILS.get(args.rail, 'not a PDU output')}).")
    if not 1 <= args.capture_seconds <= 120:
        raise SystemExit("--capture-seconds must be 1 to 120")
    if args.rehearse_on_laptop == bool(args.dictionary):
        raise SystemExit("Give either --dictionary (bench) or --rehearse-on-laptop.")
    if args.allow_power and not args.rehearse_on_laptop and not sys.stdin.isatty():
        raise SystemExit("--allow-power needs an operator at the keyboard (GO and READY prompts).")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_dir).resolve() if args.run_dir else ROOT / "yamcs" / "run" / f"cdr-runbook-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run = Run(args.rehearse_on_laptop)
    started = datetime.now(timezone.utc).isoformat()
    if args.rehearse_on_laptop:
        artifacts = ROOT / "ArtemisRpiTeensy_N2" / "build-artifacts" / ("Darwin" if sys.platform == "darwin" else "Linux") / D
        binary = Path(args.binary) if args.binary else artifacts / "bin" / D
        dictionary = artifacts / "dict" / f"{D}TopologyDictionary.json"
        constants = {c["qualifiedName"]: c["value"] for c in json.loads(dictionary.read_text()).get("constants", [])}
        if constants.get("N2CdrTcp.ENABLED") is not True:
            raise SystemExit("These artifacts are not the CDR TCP build: run tools/yamcs/build_cdr_tcp.sh first.")
        args.has_report_mode = any(c["name"].endswith(".missionApp.REPORT_MODE") for c in json.loads(dictionary.read_text())["commands"])
        with LaptopStack(run_dir, binary, dictionary) as stack:
            run_steps(run, args, onboard_dir=run_dir / "stack" / "onboard-storage")
            fake = {"requests": len(stack.pdu.requests), "errors": stack.pdu.errors[:12], "bitmap_at_end": stack.pdu.bitmap}
            run.step("S6", "fake PDU ends with every rail off", "PASS" if stack.pdu.bitmap == 0 else "FAIL",
                     bitmap_at_end=stack.pdu.bitmap)
    else:
        args.has_report_mode = any(c["name"].endswith(".missionApp.REPORT_MODE")
                                   for c in json.loads(Path(args.dictionary).read_text())["commands"])
        fake = None
        run_steps(run, args)

    failed = [s["step"] for s in run.steps if s["result"] == "FAIL"]
    verdict = ("REHEARSAL PASS" if run.rehearsal else "PASS") if not failed else "FAIL"
    result = {"result": verdict, "mode": "laptop rehearsal (stateful fake PDU, simulated payload)" if run.rehearsal else "bench",
              "rail": args.rail, "allow_power": args.allow_power, "started": started,
              "finished": datetime.now(timezone.utc).isoformat(), "failed_steps": failed, "steps": run.steps,
              "fake_pdu": fake, "runbook": "docs/operations/CDR_PAYLOAD_POWER_RUNBOOK.md v0.3 (matched to 99e1682)"}
    dest = run_dir / "cdr-runbook.json"
    dest.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(f"\n{verdict}" + (f": failed {failed}" if failed else ""))
    print(f"Evidence: {dest}")
    raise SystemExit(0 if not failed else 1)


if __name__ == "__main__":
    main()
