#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TICKET="${1:-${E2E_TICKET:-}}"
BASENAME="${2:-${E2E_BASENAME:-}}"

safe_basename() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
name = Path(sys.argv[1]).stem
print(name.replace(' ', '_').replace('/', '_'))
PY
}

json_field() {
  local path="$1"
  local field="$2"
  python3 - "$path" "$field" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
field = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
try:
    data = json.loads(path.read_text())
except Exception as exc:
    print(f"JSON_PARSE_ERROR:{type(exc).__name__}")
    raise SystemExit(0)
value = data
for part in field.split('.'):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if value is None:
    raise SystemExit(0)
if isinstance(value, (dict, list)):
    print(json.dumps(value, sort_keys=True))
else:
    print(value)
PY
}

printf '%s\n' 'WEBUI PDF E2E PREFLIGHT'
printf '%s\n' 'This helper is read-only. It does not upload PDFs, run remediation, delete artifacts, or modify workspace state.'
printf '\n%s\n' '1. Static/runtime readiness'
bash scripts/verify-webui-pdf-contract.sh
bash scripts/verify-webui-pdf-runtime.sh

printf '\n%s\n' '2. Docker service snapshot'
docker compose ps

printf '\n%s\n' '3. Recent Hermes log hints'
docker compose logs hermes --tail=80 | grep -E 'PDF:|pdf-remediation|remediate.py|phase|HERMES_REQUIRED|COMPLETE|STATUS.json|orchestrator' || true

if [[ -z "$TICKET" || -z "$BASENAME" ]]; then
  printf '\n%s\n' '4. Workspace artifact scan'
  printf '%s\n' 'No TICKET/BASENAME supplied. Showing known status/outcome/package artifacts.'
  find workspace/jobs -maxdepth 5 -type f \( \
    -name 'STATUS.json' -o \
    -name 'orchestrator_outcome.json' -o \
    -name 'hermes_signals.json' -o \
    -name 'PACKAGE_CONTENTS.md' -o \
    -name 'SHA256SUMS.txt' \
  \) -print 2>/dev/null | sort || true
  find workspace/output -maxdepth 5 -type f -print 2>/dev/null | sort || true
  printf '\n%s\n' 'To inspect a specific E2E job, rerun with:'
  printf '%s\n' '  E2E_TICKET=<ticket> E2E_BASENAME=<basename-without-.pdf> bash scripts/verify-webui-pdf-e2e-preflight.sh'
  exit 0
fi

SAFE_BASE="$(safe_basename "$BASENAME")"
INPUT_PDF="workspace/input/${TICKET}/${BASENAME}.pdf"
JOB_DIR="workspace/jobs/${TICKET}_${SAFE_BASE}"
OUT_DIR="workspace/output/${TICKET}_remediated"
OUTCOME_JSON="${JOB_DIR}/audit/orchestrator_outcome.json"
STATUS_JSON="${JOB_DIR}/STATUS.json"
HERMES_SIGNALS="${JOB_DIR}/audit/hermes_signals.json"

printf '\n%s\n' '4. Expected paths for requested E2E job'
printf 'input_pdf=%s\n' "$INPUT_PDF"
printf 'job_dir=%s\n' "$JOB_DIR"
printf 'orchestrator_outcome=%s\n' "$OUTCOME_JSON"
printf 'status_json=%s\n' "$STATUS_JSON"
printf 'hermes_signals=%s\n' "$HERMES_SIGNALS"
printf 'output_dir=%s\n' "$OUT_DIR"

if [[ -f "$INPUT_PDF" ]]; then
  printf 'input_pdf_exists=yes\n'
else
  printf 'input_pdf_exists=no\n'
fi

printf '\n%s\n' '5. Observed artifacts for requested E2E job'
if [[ -d "$JOB_DIR" ]]; then
  find "$JOB_DIR" -maxdepth 5 -type f \( \
    -name 'STATUS.json' -o \
    -name 'orchestrator_outcome.json' -o \
    -name 'hermes_signals.json' -o \
    -name 'PACKAGE_CONTENTS.md' -o \
    -name 'SHA256SUMS.txt' -o \
    -name 'verdict_input.json' \
  \) -print | sort
else
  printf 'job_dir_exists=no\n'
fi

if [[ -d "$OUT_DIR" ]]; then
  find "$OUT_DIR" -maxdepth 5 -type f -print | sort
else
  printf 'output_dir_exists=no\n'
fi

printf '\n%s\n' '6. Parsed outcome fields'
printf 'orchestrator_outcome.overall_result=%s\n' "$(json_field "$OUTCOME_JSON" overall_result)"
printf 'STATUS.overall_result=%s\n' "$(json_field "$STATUS_JSON" overall_result)"
printf 'STATUS.result=%s\n' "$(json_field "$STATUS_JSON" result)"
printf 'STATUS.verdict_result_source=%s\n' "$(json_field "$STATUS_JSON" verdict_result_source)"

printf '\n%s\n' '7. Classification guidance'
printf '%s\n' 'PASS: orchestrator ran, STATUS/package exist, and final WebUI response matches PASS.'
printf '%s\n' 'REVIEW_REQUIRED: orchestrator ran, review package/status exist, and final WebUI response matches REVIEW_REQUIRED.'
printf '%s\n' 'FAIL/ESCALATION: orchestrator ran, truthful failed/escalation package exists, and final WebUI response does not overclaim.'
printf '%s\n' 'BLOCKED: WebUI did not route to Hermes, Hermes did not load runbook, or orchestrator was not invoked.'
printf '%s\n' 'INVALID: test used CLI-only execution or did not submit through Open WebUI.'
