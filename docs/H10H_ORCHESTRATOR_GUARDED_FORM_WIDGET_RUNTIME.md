# H10H - Orchestrator Guarded Form-Widget Runtime

## Baseline commit

```text
562780b69fdb76f35f0f2adc461e2f8b27619a4d
Record H10G guarded lookup status
```

## Final commit

```text
Final H10H status commit: see `git log -1` after the final docs/PRODUCTION_REMEDIATION_STATUS.md update.
```

## Terminal state

```text
ORCHESTRATOR_RUNTIME_BLOCKED_BY_STATUS_PACKAGE_CONTRACT
```

## Decision

H10H does not enable guarded form-widget runtime in `app/tools/orchestrate/remediate.py`.

This is intentional. The current orchestrator path can run the normal remediation loop and write truthful `orchestrator_outcome.json`, `STATUS.json`, and outcome-aware packages for the existing supported repairs, but it does not yet expose the full guarded acceptance contract required for `PDF/UA-1/7.18.4` form-widget structure construction.

Runtime integration would be unsafe without adding and proving all of the following post-repair acceptance gates in the orchestrator path:

```text
qpdf after guarded repair
veraPDF PDF/UA-1 after guarded repair
pinned WCAG profile after guarded repair
ISO tagged profile no-regression review
veraPDF profile accounting
form-widget structure inspection after repair
preservation / equivalent QA after repair
truthful residual-failure routing to REVIEW_REQUIRED rather than PASS
truthful STATUS/package routing for intermediate guarded outputs
```

## Orchestrator runtime integration status

```text
orchestrator runtime integrated: false
exact opt-in flag: none implemented
runtime default-on: false
default orchestrator behavior changed: false
default lookup behavior changed: false
guarded lookup behavior changed: false
```

No `--enable-guarded-form-widget-repair` flag was added in this blocked patch. The orchestrator must not pass `--enable-guarded-candidates` or `--precondition-report` to `lookup_repair_plan.py` until the missing acceptance/status/package contract is implemented.

## Lookup status

H10G lookup gating remains the active guarded boundary:

```text
required lookup flag: --enable-guarded-candidates
required lookup precondition input: --precondition-report <path>
default lookup emits repair_form_widget_structure.py: false
guarded lookup without valid precondition report: blocked
guarded lookup with valid precondition report: may emit guarded repair step
```

## Rule map and repair script status

```text
rule_repair_map.json changed by H10H: false
active strategies[] changed by H10H: false
lookup_repair_plan.py changed by H10H: false
repair_form_widget_structure.py changed by H10H: false
```

The guarded candidate remains metadata-only. `rules["PDF/UA-1/7.18.4"].strategies[]` remains empty, and `tools/repair/repair_form_widget_structure.py` is not promoted into the default orchestrator plan.

## Precondition evidence status

H10G requires a guarded precondition report that proves object evidence and runtime path safety before lookup may emit the guarded repair step.

Current code can inspect object evidence through:

```text
app/tools/audit/form_widget_structure_inspection.py
```

However, H10H does not wire the orchestrator to generate the full guarded runtime precondition wrapper because runtime acceptance remains blocked by the post-validation/status-package contract. A future unblocked patch should combine inspection output and parsed target-rule evidence into a report containing:

```text
target_rule: PDF/UA-1/7.18.4
AcroForm present
widget_annotation_count > 0
widgets_bounded_count == widget_annotation_count
widget_evidence_complete true
widgets_truncated false
planned_struct_parent_assignments > 0
planned_form_struct_elements > 0
field values not dumped / redacted
source overwrite disallowed
explicit safe intermediate output path
```

## Repair output path safety

No guarded repair output path is created by H10H.

A future unblocked runtime must write only to a guarded intermediate path under the job repair area, never to:

```text
source PDF
final deliverable path
STATUS.json
orchestrator_outcome.json
package output path
```

## Post-validation status

The existing orchestrator already performs substantial final validation and packaging, but the required guarded form-widget bundle is not complete. The missing explicit guarded acceptance pieces are:

```text
qpdf after guarded repair
verapdf_iso_regression_review.py
verapdf_profile_accounting.py
after-repair form_widget_structure_inspection.py
explicit guarded repair acceptance artifact tying those checks together
```

Because these are absent from `remediate.py`, H10H blocks runtime integration rather than risking false PASS or wrong artifact routing.

## Residual failure behavior

No new residual failure behavior is enabled in H10H.

The required future behavior remains:

```text
If PDF/UA-1/7.18.4 clears but other PDF/UA or WCAG failures remain, terminal state must be REVIEW_REQUIRED or ESCALATION, not PASS.
If qpdf fails, terminal state must be FAIL or an equivalent non-PASS result.
If ISO regresses, the guarded output must not be accepted as production-final.
```

## STATUS/package behavior

```text
STATUS/package behavior changed by H10H: false
STATUS/package behavior validated end-to-end for guarded runtime: false
false-success package produced: false
```

H10H makes no packaging code changes and produces no generated PDFs or workspace artifacts.

## Runtime smoke

```text
runtime smoke run: false
reason: guarded orchestrator runtime not enabled
```

No MM-17179 guarded orchestrator smoke was run because this patch ends blocked before runtime integration.

## Tests

H10H adds:

```text
app/tools/tests/test_orchestrator_guarded_form_widget_policy.py
```

The test locks the safe blocked state:

```text
no orchestrator guarded runtime flag
no default guarded lookup flags in remediate.py
no direct form-widget repair invocation in remediate.py
active strategies[] unchanged
production readiness not claimed
missing guarded acceptance gates remain explicit blockers
```

## Production-readiness statement

Production readiness is not claimed.

H10H confirms that H10G lookup gating remains safe, but guarded orchestrator runtime must wait for a narrow acceptance-contract patch. The intended production path from Open WebUI `PDF:` prompt through Hermes, orchestrator runtime, validation, truthful status, and deliverables packaging has not yet been proven for the guarded form-widget repair.

## Next recommended patch

```text
H10I - Guarded form-widget acceptance/status-package contract
```

H10I should not redesign the pipeline. It should add the missing guarded acceptance bundle to the orchestrator path, prove that residual failures cannot produce PASS, prove that qpdf/ISO/profile-accounting/form-widget diagnostics are authoritative for the guarded intermediate output, and only then add `--enable-guarded-form-widget-repair`.
