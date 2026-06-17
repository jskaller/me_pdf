# Learned Strategy Orchestrator Discovery Policy

Patch 13A adds opt-in, discovery-only visibility from the normal orchestrator repair-plan path to already-active learned strategy metadata.

## Boundary

Normal remediation jobs may record active learned strategies as diagnostic candidates only. They must not execute learned strategies, import staged learned scripts, shell out to staged learned scripts, adopt learned output PDFs, mutate `app/tools/repair/*`, or mutate `app/tools/audit/rule_repair_map.json`.

## CLI behavior

Discovery is disabled by default. Operators can enable the diagnostic artifact with:

```bash
--learned-discovery
```

When the flag is omitted, the default remediation path should not create `audit/learned_strategy_discovery.json` and should not add learned strategy candidates to `repair_plan.json`.

When the flag is present, the orchestrator writes:

```text
JOB/audit/learned_strategy_discovery.json
```

and augments `JOB/audit/repair_plan.json` with separate diagnostic fields:

```json
{
  "active_learned_strategy_candidates": [],
  "learned_strategy_discovery": {
    "mode": "discovery_only",
    "execution_performed": false,
    "candidate_handling": "diagnostic_only_not_repair_steps"
  }
}
```

The built-in `repair_steps` list remains the only executable repair-plan list.

## Required artifact flags

The discovery artifact must state:

```json
{
  "mode": "discovery_only",
  "execution_performed": false,
  "final_pdf_adoption_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "orchestrator_execution_integration_performed": false
}
```

These fields are policy assertions and regression hooks. They document that Patch 13A is planning/visibility only.

## Expected MM-17179 behavior

Patch 13A must not change normal smoke semantics. The `MM-17179_ROI4987_English_1-26_rev_Fillable` smoke is still expected to end in `ESCALATION` with the same active/actionable residuals and the same suppressed zero-count rule. Discovery-only diagnostics must not soften or harden PASS/FAIL/ESCALATION decisions.

## Docker note for execution harness smoke

When testing the isolated learned execution harness inside Docker, use:

```bash
--repo-root /
```

Inside the Hermes container `/app` is the app package root, while learned-strategy metadata stores repository-relative paths beginning with `app/tools/...`.

## Next step

Patch 13B may introduce explicitly opted-in execution experiments only after Patch 13A is stable. Patch 13A intentionally does not add runtime learned strategy execution.
