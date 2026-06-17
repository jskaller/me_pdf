# Learned Strategy Production-Testing Readiness Policy

Patch 18A adds a diagnostic-only production-testing readiness layer after learned execution dry-run, candidate quality, deeper validation, and isolated replacement trial evidence.

This policy answers one narrow question: which validation helpers are wired, which remain unavailable, and what blocks production testing review for a changed learned candidate?

## Boundary

Production-testing readiness is not production adoption. A readiness report must not:

- replace the normal final PDF
- soften PASS, FAIL, REVIEW_REQUIRED, or ESCALATION
- mutate `app/tools/audit/rule_repair_map.json`
- mutate `app/tools/repair/*`
- promote learned scripts
- activate learned strategies outside temporary smoke setup and cleanup
- introduce `adoptable`, `approved`, or `production_ready` terminal states

Every readiness report must keep:

```json
{
  "candidate_is_adoptable": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false
}
```

## Explicit flags

The readiness layer is opt-in only:

```text
--learned-execution-dry-run
--learned-replacement-trial
--learned-production-readiness
```

`--learned-production-readiness` without replacement-trial evidence fails closed by writing a skipped/blocked diagnostic and leaving normal orchestration authority unchanged.

## Artifact

The readiness layer writes:

```text
JOB/audit/learned_strategy_production_testing_readiness_report.json
```

The orchestrator learned-execution diagnostics reference this artifact when the explicit readiness flag is used.

## Required checks

For each isolated replacement-trial result, Patch 18A evaluates or governs these checks:

1. `metadata`
2. `form_field_preservation`
3. `render_compare`
4. `verapdf_delta`

A helper may be performed only when the existing helper is stable, bounded, and can compare `normal_final.pdf` to `learned_trial.pdf` without misleading evidence. If the helper is unavailable or unsafe, the readiness report records a governed blocker such as:

```text
metadata_validation_unavailable
form_field_preservation_unavailable
render_compare_unavailable
verapdf_delta_unavailable
```

## Decision values

Readiness decisions are conservative:

```text
Any failed hard check
→ production_testing_blocked

Any required helper unavailable/skipped
→ production_testing_needs_manual_review

All required checks performed and PASS, no hard blockers
→ production_testing_evidence_complete
```

`production_testing_evidence_complete` still means evidence is complete for review; it does not approve adoption.

## Remaining work before production testing

Production testing remains blocked or manual-review-only until each required helper either runs against the isolated learned trial or has a documented replacement with equivalent evidence. In particular, veraPDF delta evidence must compare the normal final PDF and learned-trial PDF directly; normal orchestrator veraPDF artifacts alone are not enough for learned-trial delta evidence.

### Patch 18A decision-mapping repair

Helper invocation errors are treated as governed helper-unavailable blockers, not as hard production-testing failures. This keeps unavailable, unsafe, or non-JSON helper execution in `production_testing_needs_manual_review`. A readiness result becomes `production_testing_blocked` only when a check actually performs and returns `result: FAIL`, such as a metadata difference, form-field preservation difference, render regression, or veraPDF delta failure.
