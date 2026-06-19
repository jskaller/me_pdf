#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "missing required file: $path"
}

require_grep() {
  local pattern="$1"
  local path="$2"
  local message="$3"
  if ! grep -Eq "$pattern" "$path"; then
    fail "$message ($path)"
  fi
}

require_file docker-compose.yml
require_file .env.example
require_file app/AGENTS.md
require_file app/hermes_skills/pdf-remediation/SKILL.md
require_file app/tools/orchestrate/remediate.py

require_grep 'OPENAI_API_BASE_URL:[[:space:]]*"http://hermes:8642/v1"' \
  docker-compose.yml \
  'Open WebUI must point at the Hermes OpenAI-compatible gateway'

require_grep 'HERMES_BUNDLED_SKILLS:[[:space:]]*"/app/hermes_skills"' \
  docker-compose.yml \
  'Hermes must load bundled skills from /app/hermes_skills'

require_grep 'begins with "PDF:"|begins with `PDF:`|message begins with "PDF:"|message begins with `PDF:`' \
  app/hermes_skills/pdf-remediation/SKILL.md \
  'pdf-remediation skill must declare the PDF: trigger language'

require_grep 'first message begins with `PDF:`|first message begins with "PDF:"' \
  app/AGENTS.md \
  'AGENTS.md must declare PDF: as the remediation-mode switch'

require_grep 'approvals\.mode[[:space:]]+auto|approval mode: MUST be .auto.|approval-mode `auto`|approval mode must be `auto`' \
  .env.example \
  '.env.example must document approval-mode auto for unattended WebUI operation'

require_grep 'WebUI|WebUI operation|API-server/WebUI operation' \
  .env.example \
  '.env.example approval guidance must explicitly mention WebUI operation'

echo 'Hermes WebUI PDF: intake contract check passed.'
echo 'Verified: Open WebUI -> Hermes gateway, bundled skills path, PDF: trigger docs, AGENTS.md mode switch, orchestrator path, and approval-mode guidance.'
echo 'Note: this is a static contract check, not a full PDF upload/remediation run.'
