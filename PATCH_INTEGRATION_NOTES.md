# Patch 1 integration notes

This drop-in patch adds a new import-safe module:

```text
app/tools/orchestrate/self_extension_run_state.py
```

and tests:

```text
app/tools/tests/test_self_extension_run_state.py
```

Recommended executor integration:

1. At self-extension entry, call `SelfExtensionRunState.start(...)` and retain the returned object for the run.
2. Replace direct calls to `generate_candidate_source(...)` in the residual self-extension loop with `generation_call_with_run_state(...)`.
3. After `execute_residual_candidate(...)` returns, call `run_state.record_candidate_attempt(candidate_result)` only when a candidate script was actually produced/executed/validated.
4. Do not call `record_candidate_attempt` for 429/timeouts, semantic refusals, or boundary violations.
5. Leave final PDF path and `rule_repair_map.json` unchanged.

Suggested import in `self_extension_executor.py`:

```python
from tools.orchestrate.self_extension_run_state import (
    SelfExtensionRunState,
    generation_call_with_run_state,
    TRANSPORT_BLOCKED,
)
```

Suggested wrapper call:

```python
generation_response = generation_call_with_run_state(
    run_state=run_state,
    generation_request=generation_request,
    generate_fn=generate_candidate_source,
    sleep_fn=lambda seconds: time.sleep(seconds),
    config=config,
    job_dir=job_dir,
)
```

If `generation_response["result"] == "TRANSPORT_BLOCKED"`, surface that distinct outcome and do not report `candidate_failed` or `not_automatable`.
