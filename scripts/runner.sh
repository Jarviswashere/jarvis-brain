#!/usr/bin/env bash
# Start the skill runner. Keys: a=arm d=disarm s=stop p=preflight-ok e=estop-ack q=quit
set -euo pipefail
JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$JARVIS_DIR"
[ -f .env ] && { set -a; . ./.env; set +a; }
exec .venv/bin/python -m runner.app --port "${RUNNER_PORT:-8765}" "$@"
