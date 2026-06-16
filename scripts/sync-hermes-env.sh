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
NVIDIA_FALLBACK_API_KEY="${NVIDIA_FALLBACK_API_KEY:-}"
NVIDIA_CREDENTIAL_POOL_STRATEGY="${NVIDIA_CREDENTIAL_POOL_STRATEGY:-fill_first}"

NVIDIA_RATE_LIMIT_ENABLED="${NVIDIA_RATE_LIMIT_ENABLED:-1}"
NVIDIA_RATE_LIMIT_RPM="${NVIDIA_RATE_LIMIT_RPM:-32}"
NVIDIA_RATE_LIMIT_BURST="${NVIDIA_RATE_LIMIT_BURST:-4}"
NVIDIA_RATE_LIMIT_STATE_PATH="${NVIDIA_RATE_LIMIT_STATE_PATH:-/app/workspace/runtime/nvidia_rate_limit.json}"

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

case "$NVIDIA_CREDENTIAL_POOL_STRATEGY" in
  fill_first|round_robin|least_used|random) ;;
  *)
    echo "ERROR: NVIDIA_CREDENTIAL_POOL_STRATEGY must be one of: fill_first, round_robin, least_used, random" >&2
    exit 1
    ;;
esac

case "$NVIDIA_RATE_LIMIT_ENABLED" in
  0|1|true|false|TRUE|FALSE|yes|no|YES|NO) ;;
  *)
    echo "ERROR: NVIDIA_RATE_LIMIT_ENABLED must be a boolean-like value." >&2
    exit 1
    ;;
esac

if ! [[ "$NVIDIA_RATE_LIMIT_RPM" =~ ^[0-9]+$ ]] || [[ "$NVIDIA_RATE_LIMIT_RPM" -lt 1 ]]; then
  echo "ERROR: NVIDIA_RATE_LIMIT_RPM must be a positive integer." >&2
  exit 1
fi

if ! [[ "$NVIDIA_RATE_LIMIT_BURST" =~ ^[0-9]+$ ]] || [[ "$NVIDIA_RATE_LIMIT_BURST" -lt 1 ]]; then
  echo "ERROR: NVIDIA_RATE_LIMIT_BURST must be a positive integer." >&2
  exit 1
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

HERMES_SELF_EXTENSION_THROTTLE_ENABLED="$NVIDIA_RATE_LIMIT_ENABLED"
HERMES_SELF_EXTENSION_MAX_CALLS_PER_MINUTE="$NVIDIA_RATE_LIMIT_RPM"
HERMES_SELF_EXTENSION_THROTTLE_STATE="$NVIDIA_RATE_LIMIT_STATE_PATH"

echo "Loaded defaults from root .env"
echo "  PRIMARY_PROVIDER=$PRIMARY_PROVIDER"
echo "  PRIMARY_MODEL=$PRIMARY_MODEL"
echo "  VISION_PROVIDER=$VISION_PROVIDER"
echo "  VISION_MODEL=$VISION_MODEL"
echo "  API_SERVER_MODEL_NAME=$API_SERVER_MODEL_NAME"
echo "  NVIDIA_CREDENTIAL_POOL_STRATEGY=$NVIDIA_CREDENTIAL_POOL_STRATEGY"
echo "  NVIDIA_RATE_LIMIT_ENABLED=$NVIDIA_RATE_LIMIT_ENABLED"
echo "  NVIDIA_RATE_LIMIT_RPM=$NVIDIA_RATE_LIMIT_RPM"
echo "  NVIDIA_RATE_LIMIT_BURST=$NVIDIA_RATE_LIMIT_BURST"

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "WARNING: NVIDIA_API_KEY is empty in .env" >&2
fi

if docker compose ps --status running hermes | grep -q hermes; then
  echo "Syncing running Hermes /opt/data/.env gateway auth keys from root .env..."

  docker compose exec -T hermes python3 - \
    "$API_SERVER_KEY" \
    "${OPENAI_API_KEY:-}" \
    "$API_SERVER_MODEL_NAME" \
    "${NVIDIA_API_KEY:-}" \
    "$NVIDIA_FALLBACK_API_KEY" \
    "$NVIDIA_CREDENTIAL_POOL_STRATEGY" \
    "$NVIDIA_RATE_LIMIT_ENABLED" \
    "$NVIDIA_RATE_LIMIT_RPM" \
    "$NVIDIA_RATE_LIMIT_BURST" \
    "$NVIDIA_RATE_LIMIT_STATE_PATH" \
    "$HERMES_SELF_EXTENSION_THROTTLE_ENABLED" \
    "$HERMES_SELF_EXTENSION_MAX_CALLS_PER_MINUTE" \
    "$HERMES_SELF_EXTENSION_THROTTLE_STATE" <<'PY'
from pathlib import Path
import sys

(
    api_server_key,
    openai_api_key,
    api_server_model_name,
    nvidia_api_key,
    nvidia_fallback_api_key,
    nvidia_credential_pool_strategy,
    nvidia_rate_limit_enabled,
    nvidia_rate_limit_rpm,
    nvidia_rate_limit_burst,
    nvidia_rate_limit_state_path,
    hermes_self_extension_throttle_enabled,
    hermes_self_extension_max_calls_per_minute,
    hermes_self_extension_throttle_state,
) = sys.argv[1:14]

p = Path("/opt/data/.env")
text = p.read_text() if p.exists() else ""
updates = {
    "API_SERVER_KEY": api_server_key,
    "OPENAI_API_KEY": openai_api_key,
    "API_SERVER_MODEL_NAME": api_server_model_name,
    "NVIDIA_API_KEY": nvidia_api_key,
    "NVIDIA_FALLBACK_API_KEY": nvidia_fallback_api_key,
    "NVIDIA_CREDENTIAL_POOL_STRATEGY": nvidia_credential_pool_strategy,
    "NVIDIA_RATE_LIMIT_ENABLED": nvidia_rate_limit_enabled,
    "NVIDIA_RATE_LIMIT_RPM": nvidia_rate_limit_rpm,
    "NVIDIA_RATE_LIMIT_BURST": nvidia_rate_limit_burst,
    "NVIDIA_RATE_LIMIT_STATE_PATH": nvidia_rate_limit_state_path,
    "HERMES_SELF_EXTENSION_THROTTLE_ENABLED": hermes_self_extension_throttle_enabled,
    "HERMES_SELF_EXTENSION_MAX_CALLS_PER_MINUTE": hermes_self_extension_max_calls_per_minute,
    "HERMES_SELF_EXTENSION_THROTTLE_STATE": hermes_self_extension_throttle_state,
}

def quote_env(value: str) -> str:
    if value == "":
        return ""
    needs_quote = any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "'", "#", "$", "\\"])
    if not needs_quote:
        return value
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

out = []
seen = set()
for line in text.splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            out.append(f"{k}={quote_env(updates[k])}")
            seen.add(k)
            continue
    out.append(line)

for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={quote_env(v)}")

p.write_text("\n".join(out) + "\n")
print("Synced /opt/data/.env gateway auth keys and rate-limit settings")
PY

  echo "Patching running Hermes /opt/data/config.yaml from root .env..."

  docker compose exec -T hermes python3 - \
    "$PRIMARY_PROVIDER" \
    "$PRIMARY_MODEL" \
    "$PRIMARY_PROVIDER_BASE_URL" \
    "$PRIMARY_PROVIDER_API_KEY" \
    "$VISION_PROVIDER" \
    "$VISION_MODEL" \
    "$VISION_PROVIDER_BASE_URL" \
    "$VISION_PROVIDER_API_KEY" \
    "$NVIDIA_FALLBACK_API_KEY" \
    "$NVIDIA_CREDENTIAL_POOL_STRATEGY" \
    "$NVIDIA_RATE_LIMIT_ENABLED" \
    "$NVIDIA_RATE_LIMIT_RPM" \
    "$NVIDIA_RATE_LIMIT_BURST" \
    "$NVIDIA_RATE_LIMIT_STATE_PATH" <<'PY'
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
    nvidia_fallback_api_key,
    nvidia_credential_pool_strategy,
    nvidia_rate_limit_enabled,
    nvidia_rate_limit_rpm,
    nvidia_rate_limit_burst,
    nvidia_rate_limit_state_path,
) = sys.argv[1:15]

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

strategies = data.setdefault("credential_pool_strategies", {})
if primary_provider == "nvidia" and nvidia_fallback_api_key:
    strategies["nvidia"] = nvidia_credential_pool_strategy
elif not nvidia_fallback_api_key and strategies.get("nvidia") == nvidia_credential_pool_strategy:
    strategies.pop("nvidia", None)

rate_limits = data.setdefault("rate_limits", {})
rate_limits["nvidia"] = {
    "enabled": nvidia_rate_limit_enabled,
    "rpm": int(nvidia_rate_limit_rpm),
    "burst": int(nvidia_rate_limit_burst),
    "state_path": nvidia_rate_limit_state_path,
    "mapped_to": {
        "HERMES_SELF_EXTENSION_THROTTLE_ENABLED": nvidia_rate_limit_enabled,
        "HERMES_SELF_EXTENSION_MAX_CALLS_PER_MINUTE": nvidia_rate_limit_rpm,
        "HERMES_SELF_EXTENSION_THROTTLE_STATE": nvidia_rate_limit_state_path,
    },
}

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
print(f"  credential_pool_strategies.nvidia={strategies.get('nvidia', '<unset>')}")
print(f"  rate_limits.nvidia.rpm={rate_limits['nvidia']['rpm']}")
print(f"  rate_limits.nvidia.burst={rate_limits['nvidia']['burst']}")
PY
else
  echo "Hermes is not running; no live config was patched."
  echo "Start Hermes, then rerun this script to patch /opt/data/config.yaml."
fi
