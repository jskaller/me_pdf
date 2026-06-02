#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing .env at $ENV_FILE" >&2
  exit 1
fi

read_env() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
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
print(value)
PY
}

NVIDIA_API_KEY="$(read_env NVIDIA_API_KEY)"
NVIDIA_BASE_URL="$(read_env NVIDIA_BASE_URL)"
PRIMARY_MODEL="$(read_env PRIMARY_MODEL)"
VISION_MODEL="$(read_env VISION_MODEL)"

NVIDIA_BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"
PRIMARY_MODEL="${PRIMARY_MODEL:-stepfun-ai/step-3.7-flash}"
VISION_MODEL="${VISION_MODEL:-meta/llama-4-maverick-17b-128e-instruct}"

if [[ -z "$NVIDIA_API_KEY" || "$NVIDIA_API_KEY" == "replace-me" ]]; then
  echo "ERROR: NVIDIA_API_KEY is missing or placeholder in .env" >&2
  exit 1
fi

echo "Testing primary text model:"
echo "  PRIMARY_MODEL=$PRIMARY_MODEL"
echo "  NVIDIA_BASE_URL=$NVIDIA_BASE_URL"
echo "  NVIDIA_API_KEY length=${#NVIDIA_API_KEY}"
echo

curl -sS -i \
  -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
  -H "Content-Type: application/json" \
  "${NVIDIA_BASE_URL}/chat/completions" \
  -d "{
    \"model\": \"${PRIMARY_MODEL}\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"Reply with only: ok\"}
    ],
    \"max_tokens\": 16384,
    \"temperature\": 1.0,
    \"top_p\": 0.95,
    \"stream\": false
  }"

echo
echo
echo "Testing vision model:"
echo "  VISION_MODEL=$VISION_MODEL"
echo

python3 - <<'PY'
import base64
from pathlib import Path

png_b64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
Path("/tmp/hermes_nim_test.png").write_bytes(base64.b64decode(png_b64))
PY

IMAGE_B64="$(base64 < /tmp/hermes_nim_test.png | tr -d '\n')"

curl -sS -i \
  -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
  -H "Content-Type: application/json" \
  "${NVIDIA_BASE_URL}/chat/completions" \
  -d "{
    \"model\": \"${VISION_MODEL}\",
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": [
          {\"type\": \"text\", \"text\": \"Briefly describe this test image.\"},
          {
            \"type\": \"image_url\",
            \"image_url\": {
              \"url\": \"data:image/png;base64,${IMAGE_B64}\"
            }
          }
        ]
      }
    ],
    \"max_tokens\": 256,
    \"temperature\": 0.2,
    \"top_p\": 0.9,
    \"stream\": false
  }"

echo
