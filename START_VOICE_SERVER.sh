#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f "$PWD/voice.config.toml" ]]; then
  export VOICE_CONFIG_PATH="$PWD/voice.config.toml"
fi

if [[ -x "$PWD/.venv/bin/python" ]]; then
  PYTHON_CMD="$PWD/.venv/bin/python"
else
  PYTHON_CMD="${PYTHON_CMD:-python3}"
fi

cat <<'BANNER'
========================================================
  Voice-Command Listening Server
  faster-whisper + noise filtering + emotion detection
========================================================
Starting server on http://localhost:5123
Leave this terminal open while using voice mode.
Press Ctrl+C to stop.

BANNER

exec "$PYTHON_CMD" "$PWD/voice_server.py"
