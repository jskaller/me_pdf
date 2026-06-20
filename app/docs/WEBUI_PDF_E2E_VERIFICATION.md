# WebUI PDF End-to-End Verification

This procedure verifies the user-facing PDF remediation path:

```text
Open WebUI
-> first message begins with PDF:
-> real PDF is submitted
-> Hermes loads the pdf-remediation runbook
-> Hermes invokes /app/tools/orchestrate/remediate.py
-> workspace/jobs/<job> is created
-> STATUS.json and package artifacts truthfully reflect the orchestrator outcome
```

This is a manual WebUI E2E procedure. It is not a CLI-only orchestrator test, and it is not satisfied by `/v1/models` gateway smoke success.

## Component classification

- Production path code: read-only for this patch.
- Runtime/operator config: checked by the existing runtime verifier.
- Skill/runbook guidance: read-only; must be observed through WebUI behavior.
- Documentation-only behavior: this procedure.
- Test/smoke verification: `scripts/verify-webui-pdf-e2e-preflight.sh`.
- Workspace artifact: generated locally only; never commit E2E workspace or PDF output.
- Missing behavior: full WebUI PDF proof until this procedure is run.
- Risky/unknown behavior: WebUI file attachment semantics and whether the agent can see the attached PDF path without additional operator placement under `workspace/input/`.

## Preflight

From the repo root:

```bash
cd ~/projects/pdf_remediation
git status --short
git pull
bash -n scripts/verify-webui-pdf-contract.sh
bash -n scripts/verify-webui-pdf-runtime.sh
bash -n scripts/verify-webui-pdf-e2e-preflight.sh
bash -n scripts/smoke-test.sh
bash scripts/verify-webui-pdf-contract.sh
bash scripts/verify-webui-pdf-runtime.sh
RUN_DOCKER_RUNTIME_CHECK=1 bash scripts/smoke-test.sh
```

The runtime verifier must pass before attempting the WebUI E2E.

## Fixture PDF

Use a small non-private PDF.

If the PDF is already in the repo workspace flow, place it under:

```text
workspace/input/WEBUI-E2E-001/e2e-smoke.pdf
```

Do not commit this PDF or any generated outputs.

If using Open WebUI attachment upload, keep a local copy of the same PDF and record its filename in the final report. The test is only valid if Hermes can either access the uploaded PDF or is instructed to use the copy under `/app/workspace/input/WEBUI-E2E-001/e2e-smoke.pdf`.

Recommended local setup for a filesystem-backed fixture:

```bash
mkdir -p workspace/input/WEBUI-E2E-001
cp /path/to/non-private-small.pdf workspace/input/WEBUI-E2E-001/e2e-smoke.pdf
```

## Manual WebUI E2E run

1. Open:

```text
http://127.0.0.1:8080
```

2. Start a new chat using the Hermes model.

3. Attach the same small PDF if testing WebUI attachment handling. Also ensure the source PDF exists at:

```text
/app/workspace/input/WEBUI-E2E-001/e2e-smoke.pdf
```

4. The first user message must begin exactly:

```text
PDF:
```

5. Use this copy-ready prompt:

```text
PDF:
Ticket: WEBUI-E2E-001
Source PDF basename: e2e-smoke
Source PDF path: /app/workspace/input/WEBUI-E2E-001/e2e-smoke.pdf

Run the standard Montefiore PDF/UA remediation workflow through the single orchestrator only. Derive title, subject, and keywords from the PDF text. Invoke /app/tools/orchestrate/remediate.py against /app/workspace. When the orchestrator completes, read /app/workspace/jobs/WEBUI-E2E-001_e2e-smoke/STATUS.json and /app/workspace/jobs/WEBUI-E2E-001_e2e-smoke/audit/orchestrator_outcome.json if present. Report only what those artifacts support. Do not claim PASS unless STATUS.json or orchestrator_outcome.json says PASS. Do not claim that external validators were run.
```

6. Watch whether the chat shows the runbook behavior and invokes the orchestrator. Valid evidence includes visible command execution, JSON phase stream, or logs showing `/app/tools/orchestrate/remediate.py`.

## Evidence collection after the WebUI run

Run:

```bash
docker compose logs hermes --tail=500 > /tmp/hermes-webui-pdf-e2e.log
find workspace/jobs -maxdepth 5 -type f | sort > /tmp/hermes-webui-pdf-e2e-jobs.txt
find workspace/output -maxdepth 5 -type f | sort > /tmp/hermes-webui-pdf-e2e-output.txt
E2E_TICKET=WEBUI-E2E-001 E2E_BASENAME=e2e-smoke bash scripts/verify-webui-pdf-e2e-preflight.sh > /tmp/hermes-webui-pdf-e2e-summary.txt
```

Inspect:

```bash
cat /tmp/hermes-webui-pdf-e2e-summary.txt
cat /tmp/hermes-webui-pdf-e2e-jobs.txt
cat /tmp/hermes-webui-pdf-e2e-output.txt
grep -E 'PDF:|pdf-remediation|remediate.py|phase|HERMES_REQUIRED|COMPLETE|STATUS.json|orchestrator' /tmp/hermes-webui-pdf-e2e.log | tail -100
```

Do not commit `/tmp` evidence, workspace job artifacts, source PDFs, remediated PDFs, or output packages.

## Required proof artifacts

A successful or truthfully terminal E2E run must identify:

```text
workspace/jobs/WEBUI-E2E-001_e2e-smoke/
workspace/jobs/WEBUI-E2E-001_e2e-smoke/audit/orchestrator_outcome.json
workspace/jobs/WEBUI-E2E-001_e2e-smoke/STATUS.json
workspace/output/WEBUI-E2E-001_remediated/
```

Depending on outcome, output may include a remediated PDF, a review folder, or a failed/escalation package. FAIL and ESCALATION must not copy a production-ready remediated PDF as a successful deliverable.

## Result matrix

| Classification | Required evidence |
|---|---|
| PASS | WebUI path invoked the orchestrator, `orchestrator_outcome.json` or `STATUS.json` says `PASS`, output package exists, and final WebUI response matches `PASS` without claiming external validator completion. |
| REVIEW_REQUIRED | WebUI path invoked the orchestrator, status/outcome says `REVIEW_REQUIRED`, review or package artifacts exist, and final WebUI response matches the review-required state. |
| FAIL/ESCALATION | WebUI path invoked the orchestrator, status/outcome says `FAIL` or `ESCALATION`, failed/escalation package or report exists, and final WebUI response does not overclaim success. |
| BLOCKED | Open WebUI did not route to Hermes, Hermes model was unavailable, upload/path access failed, Hermes did not load the runbook, Hermes did not invoke the orchestrator, or the orchestrator failed before creating a job workspace. |
| INVALID | The test used CLI-only orchestrator execution, skipped WebUI, did not submit a real PDF, or relied only on `/v1/models`/gateway smoke success. |

## Boundaries

Do not count any of the following as WebUI E2E proof:

```text
CLI-only orchestrator execution
static contract check only
Docker runtime check only
/v1/models gateway response only
runbook confirmation without real PDF submission
workspace artifacts from an unrelated prior job
```

Do not modify repair scripts, rule maps, learned-strategy adoption files, packaging behavior, final PDF behavior, or committed workspace artifacts during this procedure unless a specific blocker is found and separately approved.
