#!/usr/bin/env bash
# Native build setup only: functional acceptance runs through Yamcs.
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_ROOT="$(cd "${TASK_DIR}/../.." && pwd)"
PROJECT="${TASK_ROOT}/ArtemisRpiTeensy_N2"
EXPECTED_FPRIME=a750219414881d3461054e73c25a0868a5e648f9
if [[ ! -f "${PROJECT}/lib/fprime/requirements.txt" ]]; then
  echo "Initialize the pinned F' and PDU submodules first (see the Yamcs runbook)." >&2
  exit 2
fi
ACTUAL_FPRIME="$(git -C "${PROJECT}/lib/fprime" rev-parse HEAD)"
if [[ "${ACTUAL_FPRIME}" != "${EXPECTED_FPRIME}" ]]; then
  echo "F' SHA differs from the tested v4.2.1 baseline; review compatibility before building." >&2
  exit 2
fi
if [[ ! -x "${PROJECT}/fprime-venv/bin/python" ]]; then
  PYTHON_BIN="${FPRIME_PYTHON:-$(command -v python3.11 || true)}"
  if [[ -z "${PYTHON_BIN}" ]]; then
    echo "Python 3.11 is required; set FPRIME_PYTHON to its executable." >&2
    exit 2
  fi
  "${PYTHON_BIN}" -m venv "${PROJECT}/fprime-venv"
  "${PROJECT}/fprime-venv/bin/python" -m pip install --no-cache-dir -r "${PROJECT}/lib/fprime/requirements.txt"
fi
source "${PROJECT}/fprime-venv/bin/activate"
cd "${PROJECT}"
TASK_CMAKE_ARGS=("-DNEUTRON2_LOCAL_YAMCS=ON")
if [[ "$(uname -s)" == Darwin ]]; then
  TASK_CMAKE_ARGS+=("-DCMAKE_OSX_ARCHITECTURES=$(uname -m)")
fi
# This branch uses one unified topology, not separate local-demo/HIL FPP files.
fprime-util generate -f "${TASK_CMAKE_ARGS[@]}"
fprime-util build
