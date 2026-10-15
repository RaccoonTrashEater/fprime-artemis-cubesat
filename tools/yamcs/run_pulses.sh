#!/usr/bin/env bash
# Software-only synthetic pulse demo; FOM/calibration and hardware are deferred.
set -euo pipefail
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export N2_LOCAL_SCIENCE_FORMAT=pulses-v1
exec "${TASK_DIR}/run.sh" "$@"
