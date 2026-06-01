#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
. ./.env
set +a

BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

curl -fsS "${BASE_URL}/models" \
  -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
  -H "Accept: application/json"

echo
