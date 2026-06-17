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

## Patch 18B veraPDF delta evidence

Patch 18B replaces the governed `verapdf_delta_unavailable` placeholder when veraPDF is available. The readiness layer now runs a bounded helper against both PDFs from the isolated replacement-trial directory:

```text
JOB/audit/learned_strategy_replacement_trial/.../normal_final.pdf
JOB/audit/learned_strategy_replacement_trial/.../learned_trial.pdf
```

The helper writes sidecars in that same trial directory:

```text
verapdf_normal_final.xml
verapdf_normal_final.stdout.txt
verapdf_normal_final.stderr.txt
verapdf_learned_trial.xml
verapdf_learned_trial.stdout.txt
verapdf_learned_trial.stderr.txt
verapdf_delta.json
```

veraPDF validation failures are evidence, not operational command failure. A nonzero veraPDF exit caused by compliance failures is parsed and compared. Operational failures remain conservative readiness blockers:

```text
verapdf missing       -> SKIPPED, verapdf_delta_unavailable
verapdf timeout       -> ERROR,   verapdf_delta_timeout
XML parse failure     -> ERROR,   verapdf_delta_parse_failed
introduced/worsened   -> FAIL,    verapdf_delta_regression_detected
no introduced/worsened failures -> PASS
```

The delta is rule-level and records introduced, resolved, worsened, improved, and unchanged rule buckets. `production_testing_evidence_complete` means evidence is complete for review only. It still does not approve adoption, does not replace the normal final PDF, does not soften status, and does not mutate the rule map or `app/tools/repair/*`.
