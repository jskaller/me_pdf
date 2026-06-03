#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_ENV="$ROOT_DIR/.env"
HERMES_ENV_DIR="$ROOT_DIR/hermes/data"
HERMES_ENV="$HERMES_ENV_DIR/.env"

if [[ ! -f "$PROJECT_ENV" ]]; then
  echo "ERROR: .env not found at repo root." >&2
  echo "Copy .env.example to .env and set your provider/model values first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$PROJECT_ENV"
set +a

PRIMARY_PROVIDER="${PRIMARY_PROVIDER:-nvidia}"
VISION_PROVIDER="${VISION_PROVIDER:-$PRIMARY_PROVIDER}"
NVIDIA_BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

if [[ -z "${PRIMARY_MODEL:-}" ]]; then
  echo "ERROR: PRIMARY_MODEL is not set in .env." >&2
  exit 1
fi

if [[ -z "${VISION_MODEL:-}" ]]; then
  echo "ERROR: VISION_MODEL is not set in .env." >&2
  exit 1
fi

mkdir -p "$HERMES_ENV_DIR"
touch "$HERMES_ENV"

upsert_env() {
  local key="$1"
  local value="$2"

  if grep -q "^${key}=" "$HERMES_ENV"; then
    python3 - "$HERMES_ENV" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]

lines = path.read_text().splitlines()
out = []
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={value}")
    else:
        out.append(line)

path.write_text("\n".join(out) + "\n")
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$HERMES_ENV"
  fi
}

if [[ -n "${NVIDIA_API_KEY:-}" ]]; then
  upsert_env "NVIDIA_API_KEY" "$NVIDIA_API_KEY"
fi

upsert_env "NVIDIA_BASE_URL" "$NVIDIA_BASE_URL"
upsert_env "PRIMARY_PROVIDER" "$PRIMARY_PROVIDER"
upsert_env "PRIMARY_MODEL" "$PRIMARY_MODEL"
upsert_env "VISION_PROVIDER" "$VISION_PROVIDER"
upsert_env "VISION_MODEL" "$VISION_MODEL"

echo "Synced Hermes env file: $HERMES_ENV"
echo "  PRIMARY_PROVIDER=$PRIMARY_PROVIDER"
echo "  PRIMARY_MODEL=$PRIMARY_MODEL"
echo "  VISION_PROVIDER=$VISION_PROVIDER"
echo "  VISION_MODEL=$VISION_MODEL"

if docker compose ps --status running hermes | grep -q hermes; then
  echo "Patching running Hermes /opt/data/config.yaml from .env..."

  docker compose exec -T hermes python3 - \
    "$PRIMARY_PROVIDER" \
    "$PRIMARY_MODEL" \
    "$NVIDIA_BASE_URL" \
    "$VISION_PROVIDER" \
    "$VISION_MODEL" <<'PY'
from pathlib import Path
import sys
import yaml

primary_provider, primary_model, nvidia_base_url, vision_provider, vision_model = sys.argv[1:6]

path = Path("/opt/data/config.yaml")
if not path.exists():
    raise SystemExit("ERROR: /opt/data/config.yaml not found in Hermes container")

data = yaml.safe_load(path.read_text()) or {}

model = data.setdefault("model", {})
model["provider"] = primary_provider
model["default"] = primary_model

if primary_provider == "nvidia":
    model["base_url"] = nvidia_base_url

auxiliary = data.setdefault("auxiliary", {})
vision = auxiliary.setdefault("vision", {})
vision["provider"] = vision_provider
vision["model"] = vision_model
vision.setdefault("base_url", "")
vision.setdefault("api_key", "")
vision.setdefault("timeout", 120)
vision.setdefault("extra_body", {})
vision.setdefault("download_timeout", 30)

path.write_text(yaml.safe_dump(data, sort_keys=False))
print("Updated /opt/data/config.yaml")
PY

  docker compose exec -T hermes sh -lc '
    echo "# model"
    grep -nA4 "^model:" /opt/data/config.yaml
    echo
    echo "# auxiliary vision"
    grep -nA8 "^  vision:" /opt/data/config.yaml || grep -nA12 "^auxiliary:" /opt/data/config.yaml
  '
else
  echo "Hermes is not running; only hermes/data/.env was synced."
  echo "Start Hermes, then rerun this script to patch /opt/data/config.yaml."
fi
