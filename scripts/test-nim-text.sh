#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env missing"
  exit 1
fi

set -a
. ./.env
set +a

if [ -z "${NVIDIA_API_KEY:-}" ] || [ "$NVIDIA_API_KEY" = "nvapi-your-key-here" ]; then
  echo "ERROR: set NVIDIA_API_KEY in .env first"
  exit 1
fi

MODEL="${PRIMARY_MODEL:-stepfun-ai/step-3.7-flash}"
BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

echo "Testing NVIDIA NIM text model: $MODEL"

RESPONSE="$(
  curl -fsS "${BASE_URL}/chat/completions" \
    -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"${MODEL}\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"You are a concise test assistant. Answer with final content only.\"},
        {\"role\": \"user\", \"content\": \"Reply with exactly this final text: NIM text OK\"}
      ],
      \"temperature\": 0,
      \"max_tokens\": 256
    }"
)"

RESPONSE_JSON="$RESPONSE" python3 - <<'PY'
import json
import os

raw = os.environ.get("RESPONSE_JSON", "")
if not raw.strip():
    raise SystemExit("ERROR: empty response from NIM")

data = json.loads(raw)
choice = data["choices"][0]
message = choice.get("message", {})

print("model:", data.get("model"))
print("finish_reason:", choice.get("finish_reason"))
print("content:", message.get("content"))
if message.get("reasoning") or message.get("reasoning_content"):
    print("reasoning_present: yes")
print("usage:", data.get("usage"))

if choice.get("finish_reason") == "length":
    raise SystemExit("ERROR: model hit max_tokens before final content")

if not message.get("content"):
    raise SystemExit("ERROR: model returned no final content")

print("NIM text test complete.")
PY
