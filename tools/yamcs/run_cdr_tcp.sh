#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
  echo "Run tools/yamcs/bootstrap.sh first." >&2
  exit 2
fi
exec "${SCRIPT_DIR}/.venv/bin/python" -u "${SCRIPT_DIR}/cdr_tcp.py" "$@"
