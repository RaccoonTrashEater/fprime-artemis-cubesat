#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "${TASK_DIR}/.venv/bin/python" ]]; then
  echo "Run tools/yamcs/bootstrap.sh first." >&2
  exit 2
fi
exec "${TASK_DIR}/.venv/bin/python" "${TASK_DIR}/passthrough.py" "$@"
