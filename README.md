# Montefiore PDF/UA Hermes Remediation

Clean Hermes-based baseline for the Montefiore PDF/UA remediation environment.

## Runtime model

```text
/opt/data        = Hermes state/config/API keys/sessions/memory
/app             = remediation app/code/contracts/tools
/app/workspace   = remediation job filesystem
```

## First-time setup

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set your local values, especially:

```dotenv
NVIDIA_API_KEY=your-nvidia-nim-key
API_SERVER_KEY=change-me-local-dev
```

The validated default models are:

```dotenv
PRIMARY_MODEL=stepfun-ai/step-3.7-flash
VISION_MODEL=meta/llama-4-maverick-17b-128e-instruct
```

## Hermes runtime environment sync

Hermes persists its own runtime environment under:

```text
hermes/data/.env
```

Inside the Docker container this is mounted as:

```text
/opt/data/.env
```

Hermes may read provider credentials from `/opt/data/.env`. Because `./hermes/data` is persisted across container restarts, stale credentials can survive even after the project root `.env` has been updated.

For team use, treat the project root `.env` as the source of truth, then sync it into Hermes runtime state before starting the stack or after rotating keys.

Run:

```bash
./scripts/sync-hermes-env.sh
```

The sync script copies these values from `.env` into `hermes/data/.env`:

```text
NVIDIA_API_KEY
NVIDIA_BASE_URL
PRIMARY_MODEL
VISION_MODEL
```

Do not commit `.env` or `hermes/data/.env`.

## Start the stack

After setting `.env` and syncing Hermes runtime credentials:

```bash
./scripts/sync-hermes-env.sh
docker compose up -d
```

Expected local services:

```text
Hermes dashboard:
http://127.0.0.1:9119

Hermes OpenAI-compatible API:
http://127.0.0.1:8642/v1

Open WebUI:
http://127.0.0.1:8080
```

## After rotating the NVIDIA key

Update `NVIDIA_API_KEY` in the project root `.env`, then run:

```bash
./scripts/sync-hermes-env.sh
docker compose restart hermes
```

This prevents Hermes from continuing to use a stale provider key from `hermes/data/.env`.

## Quick verification

Check that the dashboard and Open WebUI are serving:

```bash
curl -fsS http://127.0.0.1:9119 >/dev/null && echo "Hermes dashboard ok"
curl -fsS http://127.0.0.1:8080/_app/version.json
```

Check that the Hermes API exposes the configured model:

```bash
set -a
source .env
set +a

curl -sS \
  -H "Authorization: Bearer ${API_SERVER_KEY}" \
  http://127.0.0.1:8642/v1/models
```

Check chat through Hermes:

```bash
curl -sS \
  -H "Authorization: Bearer ${API_SERVER_KEY}" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8642/v1/chat/completions \
  -d '{
    "model": "Hermes Agent",
    "messages": [
      {"role": "user", "content": "Reply with only: ok"}
    ],
    "stream": false
  }'
```

If direct NVIDIA calls work but Hermes returns a provider `403`, check whether `hermes/data/.env` has a stale `NVIDIA_API_KEY`, then rerun:

```bash
./scripts/sync-hermes-env.sh
docker compose restart hermes
```

## Git hygiene

These files contain local secrets or runtime state and should remain uncommitted:

```text
.env
hermes/data/
hermes/open-webui/
```
