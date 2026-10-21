#!/usr/bin/env bash
# Generate and build the stock CCSDS-over-TCP CDR profile for N2.
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
  echo "The project F' virtual environment is missing; run the existing build setup first." >&2
  exit 2
fi

source "${PROJECT}/fprime-venv/bin/activate"
cd "${PROJECT}"
TASK_CMAKE_ARGS=("-DNEUTRON2_CDR_TCP=ON" "-DNEUTRON2_LOCAL_YAMCS=OFF")
if [[ "$(uname -s)" == Darwin ]]; then
  TASK_CMAKE_ARGS+=("-DCMAKE_OSX_ARCHITECTURES=$(uname -m)")
fi

fprime-util generate -f "${TASK_CMAKE_ARGS[@]}"
fprime-util build
