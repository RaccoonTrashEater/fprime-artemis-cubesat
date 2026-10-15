#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV="${SCRIPT_DIR}/.venv"
PYTHON_BIN="${YAMCS_PYTHON:-}"

if [[ -z "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3.11 || true)"
fi
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Python 3.11 is required. Set YAMCS_PYTHON to a Python 3.11 executable." >&2
  exit 2
fi

if [[ ! -x "${VENV}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV}"
fi

"${VENV}/bin/python" -m pip install --no-cache-dir --disable-pip-version-check -r "${SCRIPT_DIR}/requirements.lock"
"${VENV}/bin/python" -m pip check
printf '\nYamcs runtime ready in %s\n' "${VENV}"
printf 'N2 checkout: %s\n' "${REPO_ROOT}"
