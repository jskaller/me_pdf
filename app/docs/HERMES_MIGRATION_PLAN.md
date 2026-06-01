# Hermes Migration Plan

## Goal

Replace the OpenClaw runtime dependency with Hermes while preserving the PDF/UA remediation workflow, contracts, tools, and orchestrator-first operating model.

## Non-goals

- Do not rewrite the repair tools.
- Do not manually run individual scripts as the main workflow.
- Do not reintroduce multi-reasoning-model switching.
- Do not change the workspace/job contract unless required by the residual contract.

## Carry forward unchanged

- `tools/`
- `workspace/`
- `tools/audit/rule_repair_map.json`
- `AGENTS.md`
- `SOUL.md`
- existing skill/rule/checklist docs as migration source material

## Remove

- OpenClaw Docker installation
- `openclaw.json` runtime dependency
- `.openclaw/` local state
- OpenClaw-specific entrypoint behavior
- `OPENCLAW_REQUIRED` as the external agent-facing signal name

## Replace with

- Hermes Docker service
- Hermes web dashboard
- NVIDIA NIM provider
- `PRIMARY_MODEL=stepfun-ai/Step-3.7-Flash`
- `VISION_MODEL=meta/llama-4-maverick-17b-128e-instruct`
- `HERMES_REQUIRED` or `AI_REQUIRED` as the new operator-facing signal

## Approved filesystem model

- `/opt/data` = Hermes state/config/API keys/sessions/memory/skills
- `/app` = remediation app/code/contracts/tools
- `/app/workspace` = remediation job filesystem

## Phase 0: Baseline Hermes Docker

Bring up Hermes with dashboard/API, persistent data, mounted app/workspace, and NVIDIA credentials.

## Phase 1: New clean repo

Create the new clean project under `~/projects/pdf_remediation`, copy forward only intentional source assets, and exclude runtime state.

## Phase 2: Contract preservation

Preserve AGENTS/SOUL orchestrator-first workflow and JSON-line phase behavior.

## Phase 3: Residual contract implementation

Implement `residual_analysis.json` and ensure post-repair residuals, not baseline failures, trigger Hermes/AI review.

## Phase 4: OpenClaw prompt conversion

Convert `OPENCLAW_PROMPT_TEMPLATES.md` into Hermes skills/tasks.

## Phase 5: Gate and verdict repair

Implement milestone fixes from `ORCHESTRATOR_REVIEW.md` and `OPENCLAW_PROMPT_TEMPLATES.md` in order.

## Phase 6: Model validation

Test text and vision NIM models directly and through Hermes before trusting them in remediation.

## Phase 7: End-to-end job validation

Run a representative PDF job through orchestrator, residual analysis, repair, QA, packaging, and final `STATUS.json`.
