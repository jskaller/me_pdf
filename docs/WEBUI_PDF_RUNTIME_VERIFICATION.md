# Hermes WebUI PDF Runtime Verification

## Static check

Run:

```bash
bash scripts/verify-webui-pdf-contract.sh
```

This checks repository files only. It reports the static `PDF:` intake contract, the bundled skills path, the WebUI-to-Hermes service URL, the `AGENTS.md` mode switch, the orchestrator path, and approval-mode guidance.

It does not contact Docker, submit a PDF, run remediation, inspect `STATUS.json`, or prove a final package.

## Optional Docker runtime check

Run:

```bash
bash scripts/verify-webui-pdf-runtime.sh
```

The runtime check is read-only. It verifies live Docker assumptions where possible:

- Hermes service is running.
- Open WebUI service is running when defined.
- Open WebUI is configured to use the Hermes gateway.
- Hermes has the `pdf-remediation` runbook mounted.
- Hermes has `/app/tools/orchestrate/remediate.py` mounted.
- The `PDF:` trigger language is visible inside the Hermes container.
- Approval mode is `auto`, or the script reports that it could not verify approval mode.
- The Hermes gateway responds to a harmless models endpoint request when local gateway auth is available.

The script clearly distinguishes static contract verification, runtime config verification, gateway smoke verification, and the fact that full PDF remediation was not tested.

If Docker is unavailable, the script reports the runtime check as skipped. If Docker is available but a required live service or config is wrong, the script fails with an actionable message.

## Optional smoke integration

Normal smoke:

```bash
bash scripts/smoke-test.sh
```

Normal smoke plus the deeper Docker runtime verifier:

```bash
RUN_DOCKER_RUNTIME_CHECK=1 bash scripts/smoke-test.sh
```

## Remaining full end-to-end verification

Full production-path verification still requires a real PDF job:

1. Start the Docker stack.
2. Open Open WebUI.
3. Submit a real PDF job with the first message beginning `PDF:`.
4. Observe Hermes loading the `pdf-remediation` runbook.
5. Observe Hermes invoking `/app/tools/orchestrate/remediate.py` against `/app/workspace`.
6. Inspect `STATUS.json`.
7. Inspect packaged deliverables.
8. Confirm the final response truthfully reflects the orchestrator outcome.

Do not treat runtime config pass or gateway smoke pass as proof that a PDF was remediated.
