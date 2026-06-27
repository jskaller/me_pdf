# H12 Runtime-Validated Candidate Chain

## Terminal state

```text
AGENT_CANDIDATE_REPAIR_VALIDATED
```

## Runtime evidence

The representative H11/H12 blocker PDF produced a validator-pass candidate chain under the runtime job audit folder:

```text
/app/workspace/jobs/MM-17179-H11-BATCH2_ROI4987_English_1-26_rev_Fillable/audit/h12/h12_full_candidate_chain_verdict.json
```

The runtime chain validated repairs for:

```text
PDF/UA-1/7.21.7
PDF/UA-1/7.21.4.1
PDF/UA-1/7.18.4
PDF/UA-1/7.18.1
```

Final validator state:

```text
PDF/UA-1: PASS
WCAG-2-2-Machine: PASS
ISO-32000-1-Tagged: PASS
remaining_failed_rules: 0
qpdf: PASS
render_compare: PASS
render_diff_pct: 0.0
pages_flagged: 0
```

## Rule-count progression

```text
baseline:
  PDF/UA-1/7.21.7: 2
  PDF/UA-1/7.21.4.1: 1
  PDF/UA-1/7.18.4: 102
  PDF/UA-1/7.18.1: 102
  failed_rule_elements_total: 4

after font chain:
  PDF/UA-1/7.21.7: 0
  PDF/UA-1/7.21.4.1: 0
  PDF/UA-1/7.18.4: 102
  PDF/UA-1/7.18.1: 102
  failed_rule_elements_total: 2

after Form StructParent:
  PDF/UA-1/7.21.7: 0
  PDF/UA-1/7.21.4.1: 0
  PDF/UA-1/7.18.4: 0
  PDF/UA-1/7.18.1: 102
  failed_rule_elements_total: 1

after Form Alt:
  PDF/UA-1/7.21.7: 0
  PDF/UA-1/7.21.4.1: 0
  PDF/UA-1/7.18.4: 0
  PDF/UA-1/7.18.1: 0
  failed_rule_elements_total: 0
```

## Productionization patch

This patch adds guarded source policy and tests for the validated chain.

```text
app/tools/repair/mm17179_guarded_candidate_repair.py
app/tools/tests/test_mm17179_guarded_candidate_repair_policy.py
```

The module records guarded adoption policy for the validated chain and keeps final production claims conservative.

## Semantic caveat

The final `/Alt` labels used to clear `PDF/UA-1/7.18.1` are validator-safe placeholders derived from existing generic field names. They are not human-reviewed production-quality field labels.

Therefore:

```text
safe_to_claim_pdfua_validator_pass: true
safe_to_claim_human_reviewed_field_labels: false
safe_to_claim_production_ready_without_label_review: false
```

## Non-goals

This patch does not claim:

```text
broad unrestricted repair for arbitrary PDFs
human-reviewed field labels
production readiness without the final validation gates
```
