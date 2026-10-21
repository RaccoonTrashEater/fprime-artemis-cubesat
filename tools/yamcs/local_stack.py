#!/usr/bin/env python3
"""Run the current N2 native deployment and Yamcs on software-only PTYs."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "ArtemisRpiTeensy_N2"
SCIENCE_VIEWER_PORT = 8063
sys.path.insert(0, str(PROJECT / "tools"))
from local_link import LocalLink


def main():
    run_id = secrets.token_hex(6)
    science_format = os.environ.get("N2_LOCAL_SCIENCE_FORMAT", "counts-csv")
    if science_format not in ("counts-csv", "pulses-v1"):
        raise SystemExit("N2_LOCAL_SCIENCE_FORMAT accepts counts-csv or pulses-v1")
    raw_faults = os.environ.get("N2_LOCAL_SCIENCE_FAULTS", "")
    science_faults = frozenset(item.strip() for item in raw_faults.split(",") if item.strip())
    allowed_faults = {"drop-first-0", "corrupt-first-1", "withhold-receipt"}
    if science_faults - allowed_faults:
        raise SystemExit("N2_LOCAL_SCIENCE_FAULTS accepts drop-first-0,corrupt-first-1,withhold-receipt")
    verification_timeout = int(os.environ.get("N2_VERIFICATION_TIMEOUT_SECONDS", "120"))
    if not 5 <= verification_timeout <= 600:
        raise SystemExit("N2_VERIFICATION_TIMEOUT_SECONDS must be between 5 and 600")

    platform = "Darwin" if sys.platform == "darwin" else "Linux"
    artifacts = PROJECT / "build-artifacts" / platform / "ArtemisRpiTeensyDeployment"
    binary = artifacts / "bin" / "ArtemisRpiTeensyDeployment"
    dictionary = artifacts / "dict" / "ArtemisRpiTeensyDeploymentTopologyDictionary.json"
    if not binary.is_file() or not dictionary.is_file():
        raise SystemExit("Native artifacts missing. Run tools/yamcs/build_native.sh first.")
    data = json.loads(dictionary.read_text())
    if not any(c["name"] == "ArtemisRpiTeensyDeployment.missionApp.PING" for c in data["commands"]):
        raise SystemExit("Stale/non-N2 dictionary: regenerate/build neutron2-develop first.")
    constants = {c["qualifiedName"]: c["value"] for c in data.get("constants", [])}
    if constants.get("N2CdrTcp.ENABLED") is True:
        raise SystemExit("CDR TCP artifacts selected: use run_cdr_tcp.sh or rebuild with build_native.sh for the local UART demo.")
    required_profile = {"ComCfg.TmFrameFixedSize": 1024,
                        "FW_CMD_STRING_MAX_SIZE": 504,
                        "FW_FIXED_LENGTH_STRING_SIZE": 504}
    if any(constants.get(name) != value for name, value in required_profile.items()):
        raise SystemExit("Wrong native build profile: run tools/yamcs/build_native.sh before local testing.")
    for port, kind in [(8090, socket.SOCK_STREAM), (SCIENCE_VIEWER_PORT, socket.SOCK_STREAM),
                       (50000, socket.SOCK_DGRAM),
                       (50001, socket.SOCK_DGRAM), (50002, socket.SOCK_DGRAM)]:
        with socket.socket(socket.AF_INET, kind) as check:
            if kind == socket.SOCK_STREAM:
                check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            check.bind(("127.0.0.1", port))
    run = ROOT / "yamcs" / "run" / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    storage_root = Path(os.environ.get("N2_STORAGE_ROOT", str(ROOT / "yamcs/data/onboard-storage"))).expanduser().resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    os.environ["N2_STORAGE_ROOT"] = str(storage_root)
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    os.environ["N2_LOCAL_SCIENCE_FORMAT"] = science_format
    simulator_root = (ROOT / "tools/yamcs/pulse_sim" if science_format == "pulses-v1"
                      else ROOT / "external/payload-neutron-simulation")
    os.environ["NEUTRON_PAYLOAD_SIM_ROOT"] = str(simulator_root)
    os.environ["FPRIME_DOWNLINK_DIR"] = str(run / "received-files")
    os.environ["TMPDIR"] = str(run)
    config = ROOT / "yamcs" / "config"
    # Persist a generated local signing key in ignored runtime state, not Git.
    local_key = ROOT / "yamcs" / "data" / "local-signing-key"
    local_key.parent.mkdir(parents=True, exist_ok=True)
    if not local_key.exists():
        local_key.write_text(secrets.token_hex(32))
        local_key.chmod(0o600)
    # Override only the global config; leave dependency templates untouched.
    import shutil
    working_config = run / "config"
    shutil.copytree(config, working_config)
    global_file = working_config / "etc" / "yamcs.yaml"
    global_config = yaml.safe_load(global_file.read_text())
    global_config["secretKey"] = local_key.read_text().strip()
    global_file.write_text(yaml.safe_dump(global_config))
    instance_file = working_config / "etc" / "yamcs.fprime-project.yaml"
    instance_config = yaml.safe_load(instance_file.read_text())
    for service in instance_config["services"]:
        if service["class"].endswith("FprimeFilePacketService"):
            service["args"]["downlinkMirrorDir"] = str(run / "received-files")
    instance_config["services"].append({
        "class": "org.yamcs.ProcessRunner",
        "args": {"command": [sys.executable, str(ROOT / "tools/yamcs/command_verifier.py"),
                             "--manifest", str(run / "manifest.json")],
                 "restart": "always", "logLevel": "INFO"},
    })
    instance_file.write_text(yaml.safe_dump(instance_config))
    metadata = {
        "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
        "url": "http://127.0.0.1:8090", "instance": "fprime-project",
        "local_run_id": run_id,
        "storage_root": str(storage_root),
        "verification_timeout_seconds": verification_timeout,
        "science_viewer_url": f"http://127.0.0.1:{SCIENCE_VIEWER_PORT}",
        "local_science_fault_profile": sorted(science_faults),
        "local_science_format": science_format,
        "local_science_packets_per_tick": 32 if science_format == "pulses-v1" else 1,
        "local_pulse_seed": os.environ.get("N2_LOCAL_PULSE_SEED", "12345") if science_format == "pulses-v1" else None,
        "local_source_sha256": {
            name: hashlib.sha256((ROOT / "tools/yamcs" / name).read_bytes()).hexdigest()
            for name in ("local_stack.py", "local_link.py", "science_ingest.py", "science_viewer.py",
                         "pulse_analysis.py", "pulse_cycle.py", "pulse_sim/neutron_payload_sim.py")
            if (ROOT / "tools/yamcs" / name).is_file()
        },
        "run_dir": str(run), "binary": str(binary), "dictionary": str(dictionary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "dictionary_sha256": hashlib.sha256(dictionary.read_bytes()).hexdigest(),
        "local_profile_constants": required_profile,
        "source_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "source_status": subprocess.check_output(["git", "-C", str(ROOT), "status", "--short"], text=True).splitlines(),
        "transport": "software-only UART-mux/CCSDS PTYs; no board UART or RF emulation",
    }
    metadata["command_verifier_sha256"] = hashlib.sha256((ROOT / "tools/yamcs/command_verifier.py").read_bytes()).hexdigest()
    (run / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (ROOT / "yamcs" / "run" / "current.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: v for k, v in metadata.items() if k not in ("binary", "dictionary")}, indent=2), flush=True)
    os.chdir(ROOT)
    command = [str(Path(sys.executable).parent / "fprime-yamcs"), "--no-app",
               "--dictionary", str(dictionary), "--communication-selection", "uart",
               "--uart-device", "{gds_uart}", "--uart-baud", "115200", "--uart-skip-port-check",
               "--yamcs-config-dir", str(working_config), "--yamcs-data-dir", str(ROOT / "yamcs" / "data"),
               "--logs", str(run / "logs"), "--log-directly", "--log-to-stdout", "--skip-browser-open"]
    loop = LocalLink([str(binary), "-d", "{app_uart}"], command, run_id=run_id,
                     science_faults=science_faults, viewer_port=SCIENCE_VIEWER_PORT)
    # The legacy helper's setup precedes its own finally; cover partial startup
    # here as well so a missing ground executable cannot leave F′ running.
    try:
        return loop.run()
    finally:
        loop.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
