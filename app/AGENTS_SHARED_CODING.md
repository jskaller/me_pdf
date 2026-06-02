# Shared Coding Rules

Use this file for repository coding, testing, and tool-use mechanics in all modes.

These rules are intentionally general. They do not replace, weaken, or reinterpret PDF/UA remediation rules, skill instructions, orchestrator behavior, gate policy, JSON status requirements, or validator requirements.

## Path discipline

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

## Inspect before editing

Before editing a file:

1. Verify the path exists.
2. Read the relevant lines.
3. Identify the exact target block.
4. Apply one focused patch.
5. Re-read the changed lines.

If the target block is not found, stop and inspect the current file. Do not retry the same patch.

## Tool failure recovery

Never repeat an identical failing command or patch.

After one failure:

1. Read the error.
2. Inspect the relevant file, path, or runtime state.
3. Change strategy.

After two related failures, stop and report the blocker or run the smallest diagnostic command that changes what you know.

## Preserve existing contracts

Before changing code, identify the public contract being touched: CLI arguments, exit codes, JSON keys, return shapes, filenames, sidecar names, or documented behavior.

Do not change public contracts unless the operator explicitly asks.
When a contract must change, update the smallest related tests or docs.

## Change size

Prefer the smallest complete change.
Do not rewrite whole files when a focused patch is enough.
Do not introduce new dependencies unless explicitly requested.
Do not add abstractions before there are at least two real call sites.

## Python style

Prefer simple, explicit Python over clever code.
Use descriptive names.
Keep functions small enough to test directly.
Avoid broad `except Exception` unless the error is logged or converted into a documented result.
Avoid hidden global state.
Preserve deterministic behavior for tests.

## Input and output boundaries

Validate inputs at command-line, file, JSON, and external-tool boundaries.
Fail with actionable messages.
For CLI tools, preserve meaningful nonzero exit codes on failure.
For JSON outputs, keep keys stable and include enough context to debug failures.

## Tests for generated code

When adding behavior, add or update the smallest deterministic test that proves it.
Prefer real local code paths over mocks.
Use mocks only for external services, slow tools, nondeterminism, or filesystem isolation.
Name regression tests after the failure mode they prevent.

## Fallback behavior

Do not silently downgrade, skip, or fabricate results.
If a tool, file, model, or dependency is missing, report the blocker clearly.
Fallbacks must be explicit and visible in output or status.

## Testing ladder

Use the smallest useful verification before broader tests:

1. `python3 -m py_compile FILE`
2. targeted unit test
3. focused smoke script
4. broader suite only when required by the change

Do not run expensive full workflows unless explicitly requested or required by the change.

## After editing

After editing:

1. Re-read the changed lines.
2. Run `python3 -m py_compile` for changed Python files when applicable.
3. Run the smallest relevant test.
4. Report failures honestly; do not claim success from partial output.
