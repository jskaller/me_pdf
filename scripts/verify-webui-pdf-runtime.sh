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

compose_env_value() {
  local key="$1"
  DOCKER_COMPOSE_CONFIG_TEXT="$DOCKER_COMPOSE_CONFIG_TEXT" python3 - "$key" <<'PY'
import os
import sys

key = sys.argv[1]
for raw in os.environ.get("DOCKER_COMPOSE_CONFIG_TEXT", "").splitlines():
    stripped = raw.strip()
    if stripped.startswith(f"{key}:"):
        print(stripped.split(":", 1)[1].strip().strip('"').strip("'"))
        break
PY
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

if ! DOCKER_COMPOSE_CONFIG_TEXT="$(docker compose config 2>/dev/null)"; then
  info "RUNTIME CONFIG SKIPPED: docker compose config failed for this checkout."
  info "GATEWAY SMOKE SKIPPED: compose config is unavailable."
  info "FULL PDF REMEDIATION NOT TESTED"
  exit 0
fi
export DOCKER_COMPOSE_CONFIG_TEXT

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

webui_base="$(compose_env_value OPENAI_API_BASE_URL)"
if [[ "$webui_base" != "http://hermes:8642/v1" ]]; then
  fail "Open WebUI OPENAI_API_BASE_URL expected http://hermes:8642/v1, got '${webui_base:-<missing>}'"
fi
info "Open WebUI -> Hermes gateway config verified: OPENAI_API_BASE_URL=$webui_base"

bundled_skills="$(compose_env_value HERMES_BUNDLED_SKILLS)"
if [[ "$bundled_skills" != "/app/hermes_skills" ]]; then
  fail "HERMES_BUNDLED_SKILLS expected /app/hermes_skills, got '${bundled_skills:-<missing>}'"
fi
info "Hermes bundled skills config verified: HERMES_BUNDLED_SKILLS=$bundled_skills"

compose_exec hermes python3 - <<'PY'
from pathlib import Path

checks = {
    "/app/hermes_skills/pdf-remediation/SKILL.md": Path("/app/hermes_skills/pdf-remediation/SKILL.md"),
    "/app/AGENTS.md": Path("/app/AGENTS.md"),
    "/app/SOUL.md": Path("/app/SOUL.md"),
    "/app/tools/orchestrate/remediate.py": Path("/app/tools/orchestrate/remediate.py"),
}
missing = [name for name, path in checks.items() if not path.is_file()]
if missing:
    raise SystemExit("missing container files: " + ", ".join(missing))

skill = checks["/app/hermes_skills/pdf-remediation/SKILL.md"].read_text()
agents = checks["/app/AGENTS.md"].read_text()
if "PDF:" not in skill or "begins" not in skill:
    raise SystemExit("pdf-remediation skill does not contain PDF: trigger language")
if "first message begins with `PDF:`" not in agents and 'first message begins with "PDF:"' not in agents:
    raise SystemExit("AGENTS.md does not declare PDF: as the first-message switch")
if "/app/tools/orchestrate/remediate.py" not in agents and "tools/orchestrate/remediate.py" not in agents:
    raise SystemExit("AGENTS.md does not identify the single orchestrator path")
print("container contract files ok")
PY
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
  models_tmp="$(mktemp)"
  trap 'rm -f "$models_tmp"' EXIT
  curl -fsS \
    -H "Authorization: Bearer ${api_key}" \
    "http://127.0.0.1:${host_api_port}/v1/models" >"$models_tmp"
  python3 - "$models_tmp" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
data = json.loads(path.read_text())
if not isinstance(data, dict):
    raise SystemExit('ERROR: /v1/models did not return a JSON object')
print('Hermes gateway /v1/models responded with JSON.')
PY
  rm -f "$models_tmp"
  trap - EXIT
  info "GATEWAY SMOKE PASS: Hermes /v1/models responded through the host gateway."
fi

info "RUNTIME CONFIG PASS"
info "FULL PDF REMEDIATION NOT TESTED"
info "This runtime verifier did not upload a PDF, did not run the orchestrator, and did not inspect STATUS.json or packaged deliverables."
