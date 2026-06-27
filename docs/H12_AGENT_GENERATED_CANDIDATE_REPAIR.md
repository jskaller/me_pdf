# H12 — Agent-Generated Candidate Repair for Remaining Active Blockers

## Updated terminal state

```text
AGENT_CANDIDATE_REPAIR_VALIDATED
```

The earlier source-only H12 patch truthfully stopped at `AGENT_CANDIDATE_REPAIR_BLOCKED_BY_MISSING_EVIDENCE` because the connector-backed environment did not contain live H11/H12 runtime artifacts. A later Docker/runtime H12 run used those artifacts and validated the candidate chain on the representative MM-17179 / ROI4987 fillable PDF blocker class.

## Runtime evidence artifact

```text
/app/workspace/jobs/MM-17179-H11-BATCH2_ROI4987_English_1-26_rev_Fillable/audit/h12/h12_full_candidate_chain_verdict.json
```

## Validated scope

```text
PDF/UA-1/7.21.7
PDF/UA-1/7.21.4.1
PDF/UA-1/7.18.4
PDF/UA-1/7.18.1
```

## Final runtime validator state

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

## Candidate chain

1. GlyphLessFont ToUnicode CMap repair.
   - Cleared the `PDF/UA-1/7.21.7` GlyphLessFont failure.
   - Replaced the defective ToUnicode CMap with explicit observed-code mappings, including U+2019.

2. ZapfDingbats checkbox appearance vectorization.
   - Cleared the remaining `PDF/UA-1/7.21.7` ZapfDingbats glyph failure.
   - Cleared `PDF/UA-1/7.21.4.1` for the unembedded ZapfDingbats appearance font.
   - Replaced matching `/ZaDb` text checkbox marks with vector path drawing.

3. Widget `/StructParent` + `/Form` StructElem + ParentTree repair.
   - Cleared `PDF/UA-1/7.18.4`.
   - Assigned 102 widgets unique `/StructParent` values.
   - Created 102 `/StructElem` objects with `/S /Form` and `/K` OBJR entries.
   - Extended the ParentTree and set `ParentTreeNextKey` to 104.

4. Form StructElem `/Alt` fallback.
   - Cleared `PDF/UA-1/7.18.1`.
   - Added conservative `/Alt` descriptions to the 102 Form StructElem objects.

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

## Productionization source patch

Added:

```text
app/tools/repair/mm17179_guarded_candidate_repair.py
app/tools/tests/test_mm17179_guarded_candidate_repair_policy.py
docs/H12_RUNTIME_VALIDATED_CANDIDATE_CHAIN.md
```

The source module records guarded adoption policy for the validated chain and enforces final claim boundaries.

## Semantic caveat

The generated `/Alt` labels are validator-safe placeholders derived from generic field names. They are not human-reviewed production-quality field labels.

Therefore the truthful claim boundary is:

```text
safe_to_claim_pdfua_validator_pass: true
safe_to_claim_human_reviewed_field_labels: false
safe_to_claim_production_ready_without_label_review: false
```

## Non-goals

This H12 result does not claim broad unrestricted repair for arbitrary PDFs, does not claim human-reviewed field labels, and does not claim production readiness without the required final validation gates.
