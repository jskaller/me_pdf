# General Engineering Agent

Use this file for non-remediation work in the `me_pdf` repository.

This mode applies when the operator's first message does **not** begin with `PDF:`.
Use the PDF/UA remediation workflow only when the operator explicitly starts the first message with `PDF:`.

Examples of general-engineering work include repository development, debugging, tests, Hermes configuration diagnosis, documentation, refactors, and small maintenance tasks.

## Working directory

The repository root inside the Hermes container is `/app`.

Before repository shell commands, run:

```bash
cd /app
```

After `cd /app`, use repository-relative paths such as:

```text
tools/lib/gates.py
tools/tests/test_m1_gate_verdict.py
workspace/...
```

Do not use `app/tools/...` from inside `/app`.
Do not construct `/app/app/...`.

Before patching a path, verify it exists with `test -f PATH`, `test -d PATH`, `ls PATH`, or a focused file read.

## Tool use

Prefer direct file inspection and targeted patches.
Do not run the PDF remediation orchestrator unless the task explicitly asks for a PDF remediation job.
Do not run individual PDF audit, repair, QA, or packaging scripts unless the task is engineering work on those scripts.
Do not emit remediation step JSON unless the operator explicitly requests remediation workflow output.

Never repeat an identical failing command or patch. After one failure, inspect the error and change strategy.
After two related failures, stop and report the blocker or run the smallest diagnostic command that changes what you know.

## Change policy

Keep changes minimal and reversible.
Do not modify milestone-protected files unless explicitly requested.
Do not edit `.env`, `hermes/data/.env`, local credentials, Docker state, or runtime state unless the operator explicitly asks for runtime configuration changes.

For code changes:

1. Inspect the current file before editing.
2. Patch only the requested area.
3. Re-read the changed lines.
4. Run the smallest relevant check first.

## Testing ladder

Use the smallest useful verification before broader tests:

1. `python3 -m py_compile FILE`
2. targeted unit test
3. focused smoke script
4. broader suite only when required by the change

Do not run expensive full workflows unless explicitly requested or required by the change.

## Response discipline

Do not narrate private reasoning.
For coding and configuration work, final responses should include only:

- files changed
- commands run
- test results
- remaining risks or blockers
