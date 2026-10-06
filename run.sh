#!/usr/bin/env bash
# One-command local launch. Dependencies stay inside the project.
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null; then PYTHON_BIN=python3; fi
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required; Python 3.11 recommended"'
if [ ! -x .venv/bin/python ]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install -q -r backend/requirements.txt
(cd frontend && npm ci --no-audit --no-fund)
backend_pid=''
frontend_pid=''
cleanup() {
  trap - EXIT INT TERM
  if [ -n "$backend_pid" ]; then kill "$backend_pid" 2>/dev/null || true; fi
  if [ -n "$frontend_pid" ]; then kill "$frontend_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
(cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
backend_pid=$!
(cd frontend && exec ./node_modules/.bin/vite --host 127.0.0.1 --port 5173 --strictPort) &
frontend_pid=$!
echo 'Dashboard: http://localhost:5173   API: http://localhost:8000/docs'
# Exit if either server dies instead of leaving the other running indefinitely.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do sleep 1; done
exit 1
