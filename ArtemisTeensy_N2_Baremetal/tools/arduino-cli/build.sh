#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" == "Darwin" && "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" == "1" ]]; then
  if [[ -x /opt/homebrew/bin/arduino-cli ]]; then
    ARDUINO_CLI=(/usr/bin/arch -arm64 /opt/homebrew/bin/arduino-cli)
  else
    ARDUINO_CLI_BIN="$(command -v arduino-cli)"
    ARDUINO_CLI=(/usr/bin/arch -arm64 "$ARDUINO_CLI_BIN")
  fi
else
  ARDUINO_CLI_BIN="$(command -v arduino-cli)"
  ARDUINO_CLI=("$ARDUINO_CLI_BIN")
fi
SKETCH_DIR="$ROOT_DIR/firmware/satellite_teensy"
FQBN="teensy:avr:teensy41"
BUILD_DIR="$ROOT_DIR/build/arduino-cli"
LIBRARIES_DIR="$ROOT_DIR/firmware/libs"

export ARDUINO_CONFIG_FILE="$ROOT_DIR/tools/arduino-cli/arduino-cli.yaml"

"${ARDUINO_CLI[@]}" core update-index
"${ARDUINO_CLI[@]}" core install teensy:avr
"${ARDUINO_CLI[@]}" compile --clean \
  --fqbn "$FQBN" \
  --libraries "$LIBRARIES_DIR" \
  --build-path "$BUILD_DIR" \
  "$SKETCH_DIR"
