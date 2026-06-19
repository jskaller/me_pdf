#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Checking Hermes WebUI PDF: intake contract..."
bash scripts/verify-webui-pdf-contract.sh

echo "Checking compose config..."
docker compose config >/dev/null

echo "Checking Hermes container status..."
docker compose ps

echo "Checking mounted app files..."
docker compose exec hermes sh -lc '
  test -f /app/AGENTS.md &&
  test -f /app/SOUL.md &&
  test -d /app/tools &&
  test -d /app/workspace &&
  echo "mounts ok"
'

echo "Checking dashboard port from host..."
curl -fsS "http://127.0.0.1:${HERMES_DASHBOARD_PORT:-9119}" >/dev/null || {
  echo "Dashboard did not return a basic HTTP response. Check docker compose logs."
  exit 1
}

echo "Checking gateway TCP port from host..."
python3 - <<'PY'
import os
import socket

host = "127.0.0.1"
port = int(os.environ.get("HERMES_API_PORT", "8642"))
with socket.create_connection((host, port), timeout=5):
    pass
print("gateway tcp ok")
PY

echo "Smoke test complete."
