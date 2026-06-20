#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARNING: $*" >&2
}

info() {
  echo "$*"
}

read_env() {
  local key="$1"
  local env_file="${2:-.env}"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi
  python3 - "$env_file" "$key" <<'PY'
from pathlib import Path
import sys

env_file = Path(sys.argv[1])
key = sys.argv[2]
value = ""
for raw in env_file.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() == key:
        value = v.strip().strip('"').strip("'")
        break
print(value)
PY
}

compose_service_running() {
  local service="$1"
  local cid
  cid="$(docker compose ps -q "$service" 2>/dev/null || true)"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || true)" == "true" ]]
}

compose_exec() {
  local service="$1"
  shift
  docker compose exec -T "$service" "$@"
}

info "STATIC CONTRACT CHECK"
bash scripts/verify-webui-pdf-contract.sh
info "STATIC CONTRACT PASS"

if ! command -v docker >/dev/null 2>&1; then
  info "RUNTIME CONFIG SKIPPED: docker command is not available."
  info "GATEWAY SMOKE SKIPPED: docker command is not available."
  info "FULL PDF REMEDIATION NOT TESTED"
  exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
  info "RUNTIME CONFIG SKIPPED: docker compose is not available."
  info "GATEWAY SMOKE SKIPPED: docker compose is not available."
  info "FULL PDF REMEDIATION NOT TESTED"
  exit 0
fi

if ! docker compose config >/dev/null 2>&1; then
  info "RUNTIME CONFIG SKIPPED: docker compose config failed for this checkout."
  info "GATEWAY SMOKE SKIPPED: compose config is unavailable."
  info "FULL PDF REMEDIATION NOT TESTED"
  exit 0
fi

if ! compose_service_running hermes; then
  fail "Hermes service is defined but not running. Start the stack with: docker compose up -d"
fi
info "Hermes service running."

if docker compose config --services | grep -qx 'open-webui'; then
  if ! compose_service_running open-webui; then
    fail "Open WebUI service is defined but not running. Start it with: docker compose up -d open-webui"
  fi
  info "Open WebUI service running."
else
  warn "Open WebUI service is not defined in docker compose config; skipping Open WebUI service runtime check."
fi

webui_base="$(docker compose config | python3 - <<'PY'
import sys
text = sys.stdin.read().splitlines()
for line in text:
    stripped = line.strip()
    if stripped.startswith("OPENAI_API_BASE_URL:"):
        print(stripped.split(":", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
if [[ "$webui_base" != "http://hermes:8642/v1" ]]; then
  fail "Open WebUI OPENAI_API_BASE_URL expected http://hermes:8642/v1, got '${webui_base:-<missing>}'"
fi
info "Open WebUI -> Hermes gateway config verified: OPENAI_API_BASE_URL=$webui_base"

bundled_skills="$(docker compose config | python3 - <<'PY'
import sys
text = sys.stdin.read().splitlines()
for line in text:
    stripped = line.strip()
    if stripped.startswith("HERMES_BUNDLED_SKILLS:"):
        print(stripped.split(":", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
if [[ "$bundled_skills" != "/app/hermes_skills" ]]; then
  fail "HERMES_BUNDLED_SKILLS expected /app/hermes_skills, got '${bundled_skills:-<missing>}'"
fi
info "Hermes bundled skills config verified: HERMES_BUNDLED_SKILLS=$bundled_skills"

compose_exec hermes sh -lc '
  set -eu
  test -f /app/hermes_skills/pdf-remediation/SKILL.md
  test -f /app/AGENTS.md
  test -f /app/SOUL.md
  test -f /app/tools/orchestrate/remediate.py
  grep -Eq "begins with \"PDF:\"|begins with `PDF:`|message begins with \"PDF:\"|message begins with `PDF:`" /app/hermes_skills/pdf-remediation/SKILL.md
  grep -Eq "first message begins with `PDF:`|first message begins with \"PDF:\"" /app/AGENTS.md
  grep -Eq "/app/tools/orchestrate/remediate.py|tools/orchestrate/remediate.py" /app/AGENTS.md
  echo "container contract files ok"
'
info "Hermes skill visibility verified inside container."
info "Hermes orchestrator path verified inside container."

approval_mode=""
if approval_mode="$(compose_exec hermes sh -lc 'hermes config get approvals.mode 2>/dev/null || true' | tail -n 1 | tr -d '\r' | awk '{print $NF}')" && [[ -n "$approval_mode" ]]; then
  :
else
  approval_mode=""
fi

if [[ -z "$approval_mode" || "$approval_mode" == "null" || "$approval_mode" == "None" ]]; then
  approval_mode="$(compose_exec hermes python3 - <<'PY' 2>/dev/null || true
from pathlib import Path
try:
    import yaml
except Exception:
    raise SystemExit(0)
path = Path('/opt/data/config.yaml')
if not path.exists():
    raise SystemExit(0)
data = yaml.safe_load(path.read_text()) or {}
value = (((data.get('approvals') or {}).get('mode')) or '')
if value:
    print(value)
PY
)"
fi

if [[ "$approval_mode" == "auto" ]]; then
  info "Hermes approval mode verified: auto"
elif [[ -n "$approval_mode" ]]; then
  fail "Hermes approval mode is '$approval_mode', expected 'auto' for unattended WebUI operation. Run: docker exec pdf-remediation-hermes hermes config set approvals.mode auto"
else
  warn "Could not verify Hermes approval mode. Check manually with: docker exec pdf-remediation-hermes hermes config get approvals.mode"
fi

host_api_port="$(read_env HERMES_API_PORT || true)"
host_api_port="${host_api_port:-8642}"
api_key="$(read_env API_SERVER_KEY || true)"
if [[ -z "$api_key" ]]; then
  warn "API_SERVER_KEY is unavailable from .env; skipping Hermes /v1/models gateway smoke."
  info "GATEWAY SMOKE SKIPPED: API_SERVER_KEY unavailable."
else
  curl -fsS \
    -H "Authorization: Bearer ${api_key}" \
    "http://127.0.0.1:${host_api_port}/v1/models" >/tmp/hermes_webui_pdf_models.json
  python3 - <<'PY'
import json
from pathlib import Path
path = Path('/tmp/hermes_webui_pdf_models.json')
data = json.loads(path.read_text())
if not isinstance(data, dict):
    raise SystemExit('ERROR: /v1/models did not return a JSON object')
print('Hermes gateway /v1/models responded with JSON.')
PY
  rm -f /tmp/hermes_webui_pdf_models.json
  info "GATEWAY SMOKE PASS: Hermes /v1/models responded through the host gateway."
fi

info "RUNTIME CONFIG PASS"
info "FULL PDF REMEDIATION NOT TESTED"
info "This runtime verifier did not upload a PDF, did not run the orchestrator, and did not inspect STATUS.json or packaged deliverables."
