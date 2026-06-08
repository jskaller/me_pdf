#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_ENV="$ROOT_DIR/.env"

if [[ ! -f "$PROJECT_ENV" ]]; then
  echo "ERROR: .env not found at repo root." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$PROJECT_ENV"
set +a

PRIMARY_PROVIDER="${PRIMARY_PROVIDER:-nvidia}"
VISION_PROVIDER="${VISION_PROVIDER:-$PRIMARY_PROVIDER}"
NVIDIA_BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

API_SERVER_MODEL_NAME="${API_SERVER_MODEL_NAME:-Hermes Agent}"

if [[ -z "${PRIMARY_MODEL:-}" ]]; then
  echo "ERROR: PRIMARY_MODEL is not set in .env." >&2
  exit 1
fi

if [[ -z "${VISION_MODEL:-}" ]]; then
  echo "ERROR: VISION_MODEL is not set in .env." >&2
  exit 1
fi

if [[ -z "${API_SERVER_KEY:-}" ]]; then
  echo "ERROR: API_SERVER_KEY is not set in root .env." >&2
  echo "Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARNING: OPENAI_API_KEY is empty in .env; Open WebUI may fail auth." >&2
elif [[ "$OPENAI_API_KEY" != "$API_SERVER_KEY" ]]; then
  echo "WARNING: OPENAI_API_KEY differs from API_SERVER_KEY; Open WebUI may fail auth." >&2
fi

if [[ "$PRIMARY_PROVIDER" == "nvidia" ]]; then
  PRIMARY_PROVIDER_BASE_URL="${PRIMARY_PROVIDER_BASE_URL:-$NVIDIA_BASE_URL}"
  PRIMARY_PROVIDER_API_KEY="${PRIMARY_PROVIDER_API_KEY:-${NVIDIA_API_KEY:-}}"
else
  PRIMARY_PROVIDER_BASE_URL="${PRIMARY_PROVIDER_BASE_URL:-}"
  PRIMARY_PROVIDER_API_KEY="${PRIMARY_PROVIDER_API_KEY:-}"
fi

if [[ "$VISION_PROVIDER" == "nvidia" ]]; then
  VISION_PROVIDER_BASE_URL="${VISION_PROVIDER_BASE_URL:-$NVIDIA_BASE_URL}"
  VISION_PROVIDER_API_KEY="${VISION_PROVIDER_API_KEY:-${NVIDIA_API_KEY:-}}"
else
  VISION_PROVIDER_BASE_URL="${VISION_PROVIDER_BASE_URL:-}"
  VISION_PROVIDER_API_KEY="${VISION_PROVIDER_API_KEY:-}"
fi

echo "Loaded defaults from root .env"
echo "  PRIMARY_PROVIDER=$PRIMARY_PROVIDER"
echo "  PRIMARY_MODEL=$PRIMARY_MODEL"
echo "  VISION_PROVIDER=$VISION_PROVIDER"
echo "  VISION_MODEL=$VISION_MODEL"
echo "  API_SERVER_MODEL_NAME=$API_SERVER_MODEL_NAME"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "WARNING: NVIDIA_API_KEY is empty in .env" >&2
fi

if docker compose ps --status running hermes | grep -q hermes; then
  echo "Syncing running Hermes /opt/data/.env gateway auth keys from root .env..."

  docker compose exec -T hermes sh -lc '
python3 -c "import os; from pathlib import Path; p=Path(\"/opt/data/.env\"); text=p.read_text() if p.exists() else \"\"; updates={\"API_SERVER_KEY\":os.environ.get(\"API_SERVER_KEY\",\"\"),\"OPENAI_API_KEY\":os.environ.get(\"OPENAI_API_KEY\",\"\"),\"API_SERVER_MODEL_NAME\":os.environ.get(\"API_SERVER_MODEL_NAME\",\"Hermes Agent\")}; out=[]; seen=set();
for line in text.splitlines():
    if \"=\" in line and not line.strip().startswith(\"#\"):
        k=line.split(\"=\",1)[0].strip()
        if k in updates:
            v=updates[k]
            if k==\"API_SERVER_MODEL_NAME\" and \" \" in v: v=chr(34)+v+chr(34)
            out.append(k+\"=\"+v); seen.add(k); continue
    out.append(line)
for k,v in updates.items():
    if k not in seen:
        if k==\"API_SERVER_MODEL_NAME\" and \" \" in v: v=chr(34)+v+chr(34)
        out.append(k+\"=\"+v)
p.write_text(\"\\n\".join(out)+\"\\n\")
print(\"Synced /opt/data/.env gateway auth keys\")"
'

  echo "Patching running Hermes /opt/data/config.yaml from root .env..."

  docker compose exec -T hermes python3 - \
    "$PRIMARY_PROVIDER" \
    "$PRIMARY_MODEL" \
    "$PRIMARY_PROVIDER_BASE_URL" \
    "$PRIMARY_PROVIDER_API_KEY" \
    "$VISION_PROVIDER" \
    "$VISION_MODEL" \
    "$VISION_PROVIDER_BASE_URL" \
    "$VISION_PROVIDER_API_KEY" <<'PY'
from pathlib import Path
import sys
import yaml

(
    primary_provider,
    primary_model,
    primary_base_url,
    primary_api_key,
    vision_provider,
    vision_model,
    vision_base_url,
    vision_api_key,
) = sys.argv[1:9]

path = Path("/opt/data/config.yaml")
if not path.exists():
    raise SystemExit("ERROR: /opt/data/config.yaml not found in Hermes container")

data = yaml.safe_load(path.read_text()) or {}

model = data.setdefault("model", {})
model["provider"] = primary_provider
model["default"] = primary_model
model["base_url"] = primary_base_url
model["api_key"] = primary_api_key

auxiliary = data.setdefault("auxiliary", {})
vision = auxiliary.setdefault("vision", {})
vision["provider"] = vision_provider
vision["model"] = vision_model
vision["base_url"] = vision_base_url
vision["api_key"] = vision_api_key
vision.setdefault("timeout", 120)
vision.setdefault("download_timeout", 30)
vision.setdefault("extra_body", {})

path.write_text(yaml.safe_dump(data, sort_keys=False))

def redacted(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "<set>"
    return f"{value[:4]}...{value[-4:]}"

print("Updated /opt/data/config.yaml")
print(f"  model.provider={model.get('provider')}")
print(f"  model.default={model.get('default')}")
print(f"  model.base_url={model.get('base_url')}")
print(f"  model.api_key={redacted(model.get('api_key', ''))}")
print(f"  auxiliary.vision.provider={vision.get('provider')}")
print(f"  auxiliary.vision.model={vision.get('model')}")
print(f"  auxiliary.vision.base_url={vision.get('base_url')}")
print(f"  auxiliary.vision.api_key={redacted(vision.get('api_key', ''))}")
PY
else
  echo "Hermes is not running; no live config was patched."
  echo "Start Hermes, then rerun this script to patch /opt/data/config.yaml."
fi
