# Montefiore PDF/UA Hermes Remediation

Clean Hermes-based baseline for the Montefiore PDF/UA remediation environment.

## Runtime model

```text
/opt/data        = Hermes state/config/API keys/sessions/memory
/app             = remediation app/code/contracts/tools
/app/workspace   = remediation job filesystem
```

## Production WebUI intake contract

The intended user-facing production workflow is:

```text
Open WebUI message begins with:

PDF:

-> Hermes loads the pdf-remediation skill/runbook
-> the agent uses the single orchestrator
-> /app/tools/orchestrate/remediate.py runs against /app/workspace
-> final STATUS/package reflects the orchestrator result truthfully
```

The first user message must begin with `PDF:`. `app/AGENTS.md` treats that prefix as the explicit remediation-mode switch, and `app/hermes_skills/pdf-remediation/SKILL.md` declares the same trigger language for the bundled Hermes runbook.

Open WebUI connects to Hermes through the OpenAI-compatible gateway configured in `docker-compose.yml`:

```text
OPENAI_API_BASE_URL=http://hermes:8642/v1
```

Hermes loads the version-controlled runbooks from:

```text
HERMES_BUNDLED_SKILLS=/app/hermes_skills
```

For unattended Open WebUI operation, Hermes approval mode must be `auto`. The default manual approval mode can stall jobs at the first terminal command because the WebUI path does not answer Hermes command-approval prompts. `.env.example` documents the live setting command:

```bash
docker exec <container> hermes config set approvals.mode auto
```

This repository documents and statically verifies the intake contract. A static check does not prove a full PDF upload, WebUI chat submission, orchestrator stream, or final package result. Full runtime proof still requires submitting a real PDF through Open WebUI with a first message beginning `PDF:` and observing that the orchestrator completes truthfully.

## First-time setup

Create a local `.env` file if one does not already exist:

```bash
test -f .env || cp .env.example .env
```

Edit `.env` and set your local values, especially:

```dotenv
NVIDIA_API_KEY=your-nvidia-nim-key
API_SERVER_KEY=change-me-local-dev
OPENAI_API_KEY=change-me-local-dev
```

`OPENAI_API_KEY` is the local Hermes gateway token used by Open WebUI. It should match `API_SERVER_KEY`; it is not an OpenAI account key.

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

The sync script copies these values from `.env` into `hermes/data/.env` and patches the live Hermes config when the container is running:

```text
NVIDIA_API_KEY
NVIDIA_BASE_URL
PRIMARY_MODEL
VISION_MODEL
API_SERVER_KEY
OPENAI_API_KEY
API_SERVER_MODEL_NAME
```

Do not commit `.env` or `hermes/data/.env`.

## Start the stack

After setting `.env`, syncing Hermes runtime credentials, and setting Hermes approval mode to `auto` for unattended WebUI use:

```bash
./scripts/sync-hermes-env.sh
docker compose up -d
docker exec pdf-remediation-hermes hermes config set approvals.mode auto
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
docker exec pdf-remediation-hermes hermes config set approvals.mode auto
```

This prevents Hermes from continuing to use a stale provider key from `hermes/data/.env`. Reapply approval mode after restart if the runtime config does not persist it.

## Provider-side NIM verification

Before debugging Hermes or Open WebUI, verify the configured NVIDIA NIM models directly:

```bash
./scripts/verify-nim-config.sh
```

This validates:

```text
PRIMARY_MODEL=stepfun-ai/step-3.7-flash
VISION_MODEL=meta/llama-4-maverick-17b-128e-instruct
```

The script reads `.env` without sourcing it, so `.env` is not executed as shell code.

Expected result:

```text
HTTP/2 200 for stepfun-ai/step-3.7-flash
HTTP/2 200 for meta/llama-4-maverick-17b-128e-instruct
```

If this script fails, fix the NVIDIA key/model configuration before debugging Docker, Hermes, or Open WebUI.

## Quick verification

Run the static WebUI intake contract check:

```bash
bash scripts/verify-webui-pdf-contract.sh
```

This verifies the repository-level contract that:

```text
Open WebUI points at Hermes gateway
Hermes loads /app/hermes_skills
pdf-remediation declares the PDF: trigger
AGENTS.md declares PDF: as the remediation-mode switch
/app/tools/orchestrate/remediate.py exists
.env.example documents approval-mode auto for unattended WebUI operation
```

It does not upload a PDF or prove end-to-end remediation.

Check that the dashboard and Open WebUI are serving:

```bash
curl -fsS http://127.0.0.1:9119 >/dev/null && echo "Hermes dashboard ok"
curl -fsS http://127.0.0.1:8080/_app/version.json
```

Check that the Hermes API exposes the configured model.

This command reads `API_SERVER_KEY` from `.env` without sourcing the file:

```bash
API_SERVER_KEY="$(
  python3 - <<'PY'
from pathlib import Path

for raw in Path(".env").read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() == "API_SERVER_KEY":
        print(value.strip().strip('"').strip("'"))
        break
PY
)"

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

For full manual runtime verification, use Open WebUI at `http://127.0.0.1:8080`, attach or reference the source PDF according to the active operator workflow, and make the first message begin with:

```text
PDF:
```

Then confirm the agent loads the remediation runbook, invokes `/app/tools/orchestrate/remediate.py` against `/app/workspace`, and reports the final `STATUS.json`/package result without overriding the orchestrator outcome.

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

## Hermes model configuration

Hermes model selection is controlled from the repo-level `.env` file. This keeps handoff simple: each operator should copy `.env.example` to `.env`, set their gateway/API key and model values, then sync Hermes runtime config.

Relevant values:

```dotenv
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
PRIMARY_PROVIDER=nvidia
PRIMARY_MODEL=stepfun-ai/step-3.7-flash
VISION_PROVIDER=nvidia
VISION_MODEL=meta/llama-4-maverick-17b-128e-instruct
```

Apply the `.env` values to Hermes with:

```bash
./scripts/sync-hermes-env.sh
docker compose restart hermes
```

Do not commit `.env`, `hermes/data/.env`, or Hermes runtime `config.yaml` files. Those are local/runtime state.
