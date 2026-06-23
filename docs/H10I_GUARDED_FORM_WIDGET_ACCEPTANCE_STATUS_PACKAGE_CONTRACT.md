# H10I - Guarded Form-Widget Acceptance / Status-Package Contract

## Baseline commit

```text
18ac1173af4df7f9e5d28472a949b4063dda778d
Restore H10F status history
```

## Final commit

```text
Final H10I status/documentation commit: see `git log -1` after this patch lands.
```

## Terminal state

```text
GUARDED_ACCEPTANCE_STATUS_PACKAGE_CONTRACT_READY
```

## Files changed

```text
app/tools/orchestrate/guarded_acceptance.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
app/tools/tests/test_guarded_acceptance_status_package_policy.py
docs/H10I_GUARDED_FORM_WIDGET_ACCEPTANCE_STATUS_PACKAGE_CONTRACT.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## Contract implemented

H10I adds a pure, side-effect-free guarded acceptance helper:

```text
app/tools/orchestrate/guarded_acceptance.py
```

The helper evaluates a guarded intermediate repair candidate for `PDF/UA-1/7.18.4` and produces an authoritative decision object containing:

```text
guarded_acceptance_result
terminal_state
status_result
package_policy
promote_candidate_to_final
review_required
pass_allowed
failure_reason
required_reports
```

H10I does not execute the guarded form-widget repair. It defines the contract that H10J can call after an explicit runtime opt-in produces a guarded intermediate candidate PDF.

## Authoritative guarded gates

The guarded candidate can allow PASS only when all of the following are safe:

```text
qpdf after guarded repair
veraPDF PDF/UA-1 after guarded repair
pinned WCAG profile after guarded repair
ISO no-regression review after guarded repair
profile accounting after guarded repair
after-repair form-widget structure inspection
preservation / equivalent QA
residual failure analysis
artifact path discipline
```

A guarded candidate is treated as an intermediate output unless `promote_candidate_to_final` is true.

## STATUS.json mapping

`status_json_writer.py` now includes the guarded acceptance fragment when either `audit/orchestrator_outcome.json` or `audit/guarded_acceptance.json` contains a guarded acceptance decision.

The writer remains orchestrator-outcome-authoritative, but H10I adds a fail-closed overlay:

```text
PASS + guarded pass_allowed=false -> corrected to REVIEW_REQUIRED/FAIL/ESCALATION according to guarded status_result
FAIL/ESCALATION guarded decision -> authoritative FAIL/ESCALATION
REVIEW_REQUIRED guarded decision -> not PASS
```

This prevents STATUS.json from claiming PASS when residual authoritative failures remain or a guarded validation/artifact gate rejects promotion.

## orchestrator_outcome.json mapping

`guarded_acceptance.py` exposes `build_orchestrator_outcome(decision, base=None)`, which builds truthful orchestrator outcome data:

```text
overall_result = guarded status_result
guarded_acceptance = full guarded decision
guarded_acceptance_terminal_state = terminal state
guarded_candidate_intermediate = true unless promoted
guarded_candidate_promoted_to_final = true only when acceptance allows promotion
```

If a caller supplies a base outcome that says PASS while the guarded decision does not allow PASS, the helper corrects the outcome to REVIEW_REQUIRED.

## Package routing mapping

`package_deliverables.py` now reads guarded acceptance from `orchestrator_outcome.json`, `STATUS.json`, or `audit/guarded_acceptance.json` and applies guarded package routing:

```text
PASS_FINAL_ALLOWED -> PDF may be copied as successful final deliverable
REVIEW_REQUIRED_WITH_CANDIDATE -> PDF may be copied for review, but report labels it review-required
REPORT_ONLY -> PDF is not copied to final deliverables
```

If a guarded candidate is not promoted, package routing cannot label it as a successful final PDF. FAIL and ESCALATION remain report-only.

## Why residual failures produce REVIEW_REQUIRED rather than PASS

The form-widget repair can clear the target rule while unrelated authoritative PDF/UA or WCAG failures remain. In that case, the target repair may be valuable evidence and may warrant human review, but the job is not a successful PDF/UA/WCAG remediation. H10I therefore maps target-rule clearance plus residual authoritative failures to:

```text
GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED
status_result: REVIEW_REQUIRED
pass_allowed: false
promote_candidate_to_final: false
package_policy: REVIEW_REQUIRED_WITH_CANDIDATE
```

## Why guarded intermediate outputs are not automatically final

A guarded repair output is created to test a narrow repair family. It is not automatically the job final PDF. It must remain distinct from:

```text
source PDF
final deliverable PDF
STATUS.json
orchestrator_outcome.json
package output path
workspace output path
```

Promotion is allowed only when all authoritative gates pass and no residual/new/increased authoritative failures remain.

## Runtime execution status

```text
guarded runtime execution activated: false
guarded runtime default-on: false
explicit orchestrator guarded runtime flag added: false
default lookup behavior changed: false
rule_map active strategies[] changed: false
```

H10I intentionally does not add `--enable-guarded-form-widget-repair`, does not call lookup with `--enable-guarded-candidates`, and does not invoke `repair_form_widget_structure.py` from `remediate.py`.

## WebUI production-path evidence

```text
WebUI PDF: production-path evidence claimed: false
Open WebUI PDF: prompt path proven: false
Hermes skill/runbook production path proven: false
guarded orchestrator runtime smoke: false
```

Production readiness is not claimed.

## Next patch

```text
H10J - Guarded Orchestrator Runtime Integration for PDF/UA-1/7.18.4
```

H10J should wire an explicit guarded runtime opt-in flag, generate or load guarded preconditions, call lookup with guarded candidates enabled only when safe, run the repair to a safe intermediate path, run the guarded acceptance bundle, and produce truthful `STATUS.json`, `orchestrator_outcome.json`, and package behavior.
