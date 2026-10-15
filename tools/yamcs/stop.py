#!/usr/bin/env python3
"""Signal only this checkout's recorded local stack runner."""
import json
import os
from pathlib import Path
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[2]
manifest = ROOT / "yamcs" / "run" / "current.json"
if not manifest.exists():
    raise SystemExit("No local stack manifest exists.")
pid = int(json.loads(manifest.read_text())["pid"])
command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False).stdout
if str(ROOT / "tools" / "yamcs" / "local_stack.py") not in command:
    raise SystemExit("Recorded runner is absent or PID was reused; no process was signaled.")
os.kill(pid, signal.SIGINT)
print(f"Requested graceful shutdown of local N2/Yamcs runner PID {pid}.")
