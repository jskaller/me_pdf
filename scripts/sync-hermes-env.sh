#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ENV="$ROOT/.env"
HERMES_ENV_DIR="$ROOT/hermes/data"
HERMES_ENV="$HERMES_ENV_DIR/.env"

if [[ ! -f "$PROJECT_ENV" ]]; then
  echo "ERROR: Missing project .env at: $PROJECT_ENV" >&2
  echo "Copy .env.example to .env and set NVIDIA_API_KEY first." >&2
  exit 1
fi

mkdir -p "$HERMES_ENV_DIR"

get_env_value() {
  local key="$1"
  grep -E "^${key}=" "$PROJECT_ENV" | tail -n 1 | cut -d= -f2-
}

NVIDIA_API_KEY_VALUE="$(get_env_value NVIDIA_API_KEY || true)"

if [[ -z "$NVIDIA_API_KEY_VALUE" || "$NVIDIA_API_KEY_VALUE" == "replace-me" ]]; then
  echo "ERROR: NVIDIA_API_KEY is missing or still set to replace-me in .env" >&2
  exit 1
fi

touch "$HERMES_ENV"

TMP_FILE="$(mktemp)"

# Preserve existing Hermes runtime env, but replace keys managed by project .env.
grep -v -E '^(NVIDIA_API_KEY|NVIDIA_BASE_URL|PRIMARY_MODEL|VISION_MODEL)=' "$HERMES_ENV" > "$TMP_FILE" || true

{
  echo "NVIDIA_API_KEY=${NVIDIA_API_KEY_VALUE}"

  for key in NVIDIA_BASE_URL PRIMARY_MODEL VISION_MODEL; do
    value="$(get_env_value "$key" || true)"
    if [[ -n "$value" ]]; then
      echo "${key}=${value}"
    fi
  done
} >> "$TMP_FILE"

mv "$TMP_FILE" "$HERMES_ENV"

chmod 600 "$HERMES_ENV"

echo "Synced project .env into Hermes runtime env:"
echo "  $HERMES_ENV"
echo "  NVIDIA_API_KEY length: ${#NVIDIA_API_KEY_VALUE}"
