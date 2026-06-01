#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_PATH="${1:-}"

if [ -z "$IMAGE_PATH" ]; then
  echo "Usage: ./scripts/test-nim-vision.sh /path/to/test-image.png"
  exit 1
fi

if [ ! -f "$IMAGE_PATH" ]; then
  echo "ERROR: image not found: $IMAGE_PATH"
  exit 1
fi

set -a
. ./.env
set +a

if [ -z "${NVIDIA_API_KEY:-}" ] || [ "$NVIDIA_API_KEY" = "nvapi-your-key-here" ]; then
  echo "ERROR: set NVIDIA_API_KEY in .env first"
  exit 1
fi

MODEL="${VISION_MODEL:-meta/llama-4-maverick-17b-128e-instruct}"
BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

MIME="image/png"
case "$IMAGE_PATH" in
  *.jpg|*.jpeg) MIME="image/jpeg" ;;
  *.webp) MIME="image/webp" ;;
esac

B64="$(base64 < "$IMAGE_PATH" | tr -d '\n')"

echo "Testing NVIDIA NIM vision model: $MODEL"

curl -fsS "${BASE_URL}/chat/completions" \
  -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL}\",
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": [
          {\"type\": \"text\", \"text\": \"Describe this image in one short sentence.\"},
          {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:${MIME};base64,${B64}\"}}
        ]
      }
    ],
    \"temperature\": 0,
    \"max_tokens\": 80
  }"

echo
echo "NIM vision test complete."
