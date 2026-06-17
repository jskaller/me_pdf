# Learned Strategy Production-Test Review Policy

Patch 19B adds a reviewed-evidence layer for Patch 19A production-test reports.
It is diagnostic-only and non-adoptive.

## Purpose

The review artifact records who reviewed a controlled learned production-test
report, which candidate and rule were reviewed, which report hash was reviewed,
and what risks or manual notes remain.

The review is not approval. The review is not adoption. The review must not make
a learned strategy production-ready.

## Artifact

The review tool writes:

```text
JOB/audit/learned_strategy_production_test_review.json
```

It reads:

```text
JOB/audit/learned_strategy_production_test_report.json
```

## Required review inputs

A review requires:

- reviewer identity
- candidate id
- rule id
- production-test report path
- production-test report SHA-256, recorded by the tool
- optional supplied production-test report SHA-256, which must match if supplied
- manual review notes or known risks
- explicit non-adoptive review decision

Allowed decisions are:

```text
review_recorded
review_requires_followup
review_rejected
```

Forbidden decisions include, but are not limited to:

```text
approved
adoptable
production_ready
ready_for_adoption
```

## Mandatory safety flags

Every review artifact must preserve these values:

```json
{
  "review_is_adoption": false,
  "candidate_is_adoptable": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false,
  "normal_final_pdf_remains_authoritative": true
}
```

The policy also records:

```json
{
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "review_makes_candidate_production_ready": false
}
```

## Mutation boundaries

The review tool may only write the review sidecar artifact under `JOB/audit`.
It must not mutate:

- authoritative `STATUS.json`
- package deliverables
- `app/tools/repair/*`
- `app/tools/audit/rule_repair_map.json`
- final PDF output
- learned activation metadata

If protected mutation is detected, the review result must become `BLOCKED`.

## CLI usage

```bash
PYTHONPATH=/app python3 tools/audit/learned_strategy_production_test_review.py \
  --job-dir "$JOB" \
  --reviewer "Reviewer Name" \
  --candidate-id "smoke-changed-valid-candidate" \
  --rule-id "PDF/UA-1/7.21.7" \
  --review-decision review_requires_followup \
  --review-notes "Evidence reviewed; candidate remains diagnostic-only." \
  --known-risks "Manual review remains required before any future adoption design."
```

This command records review evidence only. It does not change the normal
orchestrator outcome, package status, final PDF, rule map, or repair scripts.
