# Active Production Blocker Selection Report

Patch: H6 - Active Production Blocker Selection Report

Starting baseline requested by operator: `9aa44cd Prioritize active blocker evidence in matrix`

Report status: `MATRIX_EVIDENCE_RECORDED`

## Scope guardrail

H6 is diagnostic-only. This report does not implement repairs, does not mutate `app/tools/audit/rule_repair_map.json`, does not adopt a final PDF, does not change packaging/status/orchestrator behavior, does not weaken validators, and does not commit workspace/private PDF artifacts.

## Files reviewed for H6 scope

The H6 review read the current `master` versions of the H5 matrix and surrounding production-path context:

- `app/tools/audit/production_readiness_matrix.py`
- `app/tools/tests/test_production_readiness_matrix_policy.py`
- `docs/PRODUCTION_CORPUS_SELECTION.md`
- `docs/PRODUCTION_READINESS_MATRIX.md`
- `docs/examples/corpus_manifest.example.json`
- `docs/MM_17179_BLOCKER_ANALYSIS.md`
- `app/tools/audit/residual_analysis.py`
- `app/tools/audit/lookup_repair_plan.py`
- `app/tools/audit/rule_repair_map.json`
- `app/tools/orchestrate/remediate.py`
- `app/tools/packaging/status_json_writer.py`
- `app/tools/packaging/package_deliverables.py`

## Matrix commands run

Production profile:

```bash
bash scripts/run-production-readiness-matrix.sh \
  --inspect-existing \
  --profile production \
  --manifest docs/examples/corpus_manifest.example.json \
  --out /tmp/h6-production-matrix.json
```

Actionable profile:

```bash
bash scripts/run-production-readiness-matrix.sh \
  --inspect-existing \
  --profile actionable \
  --manifest docs/examples/corpus_manifest.example.json \
  --out /tmp/h6-actionable-matrix.json
```

## Manifest load status

Both H6 matrix runs loaded the reviewed manifest successfully:

```json
"manifest": {
  "error": "",
  "loaded": true,
  "path": "docs/examples/corpus_manifest.example.json"
}
```

The manifest identified two representative production-corpus rows and excluded fixture/historical rows from production readiness counting.

## Production corpus rows selected

The production profile selected 2 rows, both `production_corpus` with `source_kind=private_local_or_representative_pdf`.

| Job | Classification | Included profiles | Notes |
|---|---|---|---|
| `MM-17161_FinancialAidMMVPolicyRevised_06032026_TinaM` | `PASS` | `all`, `production` | PASS with matched top-level remediated PDF, audit report, and checksum evidence. |
| `MM-17179_ROI4987_English_1-26_rev_Fillable` | `ESCALATION` | `all`, `production`, `actionable` | Current active production blocker row with residual targetable rules and active HERMES_REQUIRED signals. |

Production corpus summary:

| Field | Value |
|---|---:|
| selected_profile | `production` |
| selected_rows_count | 2 |
| production_rows_count | 2 |
| representative_real_pdf_coverage_count | 2 |
| production_pass_count | 1 |
| production_escalation_count | 1 |
| production_fail_count | 0 |
| production_review_required_count | 0 |
| production_incomplete_count | 0 |
| production_mismatch_count | 0 |
| fixture_rows_count | 0 |
| historical_probe_rows_count | 0 |
| stale_or_incomplete_rows_count | 0 |

## Actionable rows selected

The actionable profile selected 1 row:

| Job | Classification | Included profiles | Notes |
|---|---|---|---|
| `MM-17179_ROI4987_English_1-26_rev_Fillable` | `ESCALATION` | `all`, `production`, `actionable` | Single representative production escalation row. |

Actionable corpus summary:

| Field | Value |
|---|---:|
| selected_profile | `actionable` |
| selected_rows_count | 1 |
| production_rows_count | 1 |
| representative_real_pdf_coverage_count | 1 |
| production_escalation_count | 1 |
| production_pass_count | 0 |

## H5 blocker priority summary: production profile

| rule_id | priority_bucket | recommended_next_action | affected_production_rows | current_production_blocker_rows | active_blocker_sources | historical_or_context_sources | priority_evidence_tiers | active_hermes_required_count | post_repair_validator_failure_count | residual_targetable_current_count | residual_non_targetable_current_count | pre_repair_only_count | repair_plan_only_count | executed_and_cleared_count |
|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `PDF/UA-1/7.18.1` | `P1_single_production_blocker` | `build_or_repair_strategy` | 1 | 1 | `residual_targetable_rules` | `repair_plan.rules`, `repair_scripts_executed` | `T3_residual_targetable_current` | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| `PDF/UA-1/7.18.4` | `P1_single_production_blocker` | `build_or_repair_strategy` | 1 | 1 | `active_hermes_required_signals`, `residual_targetable_rules` | `repair_plan.hermes_required` | `T1_active_hermes_required` | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| `PDF/UA-1/7.21.4.1` | `P1_single_production_blocker` | `build_or_repair_strategy` | 1 | 1 | `active_hermes_required_signals`, `residual_targetable_rules` | `repair_plan.hermes_required` | `T1_active_hermes_required` | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| `PDF/UA-1/7.21.7` | `P1_single_production_blocker` | `build_or_repair_strategy` | 1 | 1 | `active_hermes_required_signals`, `residual_targetable_rules` | `repair_plan.hermes_required` | `T1_active_hermes_required` | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| `PDF/UA-1/5` | `P4_mapped_but_unproven` | `audit_rule_map_and_tests` | 2 | 0 | none | `repair_plan.rules`, `repair_scripts_executed` | `T5_contextual_pre_repair_or_plan` | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `PDF/UA-1/7.1` | `P4_mapped_but_unproven` | `audit_rule_map_and_tests` | 2 | 0 | none | `repair_plan.rules`, `repair_scripts_executed` | `T5_contextual_pre_repair_or_plan` | 0 | 0 | 0 | 0 | 0 | 2 | 1 |
| `PDF/UA-1/7.10` | `P4_mapped_but_unproven` | `audit_rule_map_and_tests` | 1 | 0 | none | `repair_plan.rules`, `repair_scripts_executed` | `T5_contextual_pre_repair_or_plan` | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `PDF/UA-1/7.21.4.2` | `P4_mapped_but_unproven` | `audit_rule_map_and_tests` | 1 | 0 | none | `repair_plan.rules`, `repair_scripts_executed` | `T5_contextual_pre_repair_or_plan` | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| `PDF/UA-1/7.3` | `P4_mapped_but_unproven` | `audit_rule_map_and_tests` | 2 | 0 | none | `repair_plan.rules`, `repair_scripts_executed` | `T5_contextual_pre_repair_or_plan` | 0 | 0 | 0 | 0 | 0 | 2 | 1 |

## Current active production blockers

H6 found no `P0_systemic_production_blocker` because no rule recurred as a current active blocker across more than one production row.

H6 found four `P1_single_production_blocker` rules, all on `MM-17179_ROI4987_English_1-26_rev_Fillable`:

- `PDF/UA-1/7.18.1`: current blocker via `residual_targetable_rules`; mapped strategy count is 1 and `fix_link_annotation_descriptions.py` appears in executed-script context, so this needs audit before becoming a design target.
- `PDF/UA-1/7.18.4`: current blocker via `active_hermes_required_signals` and `residual_targetable_rules`; `rule_map_resolvability=repairable_unbuilt`; active signal reports 204 failures for widget annotations not nested within a `/Form` structure element.
- `PDF/UA-1/7.21.4.1`: current blocker via `active_hermes_required_signals` and `residual_targetable_rules`; `rule_map_resolvability=missing_map_entry`; active signal reports 2 failures and `reason=unknown_rule`.
- `PDF/UA-1/7.21.7`: current blocker via `active_hermes_required_signals` and `residual_targetable_rules`; `rule_map_resolvability=repairable_unbuilt`; active signal reports 4 failures for missing `/ToUnicode` map.

MM-17179 is therefore a single representative production blocker candidate, not a systemic corpus-wide blocker.

## Rules excluded from P0/P1

The following rules were visible but excluded from P0/P1 because H5 evidence showed contextual/mapped-but-unproven evidence only, with `current_production_blocker_rows=0`:

| rule_id | Exclusion reason | Evidence |
|---|---|---|
| `PDF/UA-1/5` | mapped-but-unproven / repair-plan-only / executed-and-cleared context | `P4_mapped_but_unproven`, `repair_plan_only_count=2`, `executed_and_cleared_count=1` |
| `PDF/UA-1/7.1` | mapped-but-unproven / repair-plan-only / executed-and-cleared context | `P4_mapped_but_unproven`, `repair_plan_only_count=2`, `executed_and_cleared_count=1` |
| `PDF/UA-1/7.10` | mapped-but-unproven / repair-plan-only / executed-and-cleared context | `P4_mapped_but_unproven`, `repair_plan_only_count=1`, `executed_and_cleared_count=1` |
| `PDF/UA-1/7.21.4.2` | mapped-but-unproven / repair-plan-only / executed-and-cleared context | `P4_mapped_but_unproven`, `repair_plan_only_count=1`, `executed_and_cleared_count=1` |
| `PDF/UA-1/7.3` | mapped-but-unproven / repair-plan-only / executed-and-cleared context | `P4_mapped_but_unproven`, `repair_plan_only_count=2`, `executed_and_cleared_count=1` |

No fixture-only or historical/stale-only production blockers were selected in the production/actionable H6 profiles.

## H7 recommendation

H6 recommends `PDF/UA-1/7.18.4` as the next implementation-design target.

Reasoning:

- It is a current active production blocker with `P1_single_production_blocker` priority.
- It has the strongest H5 evidence tier: `T1_active_hermes_required`.
- It is supported by both `active_hermes_required_signals` and `residual_targetable_rules`.
- The active signal reports 204 failures on the single representative production escalation row.
- It is known from the MM-17179 analysis as the form-widget nesting blocker family.

H7 must be design-first and must not implement a repair until object-level evidence proves a safe deterministic transformation.

H7 for `PDF/UA-1/7.18.4` must inspect at minimum:

- `/StructTreeRoot` and `/ParentTree` availability and consistency;
- page-level `/StructParents` and widget annotation `/StructParent` values;
- existing `/Form` structure elements or safe insertion points;
- AcroForm field tree, field names, field values, widget annotation identities, and tab order;
- page boxes and visual/layout preservation requirements;
- whether object identity and field behavior survive any proposed structure edit;
- before/after validator delta requirements and package-routing behavior if the job remains `ESCALATION`.

Secondary design candidates remain blocked behind evidence-first inspection:

- `PDF/UA-1/7.21.7`: design-first only; prove deterministic character-code-to-Unicode mapping before any CMap generation.
- `PDF/UA-1/7.21.4.1`: design-first only; distinguish Base-14 substitution, embedded subsets, font descriptors, visual preservation, and text extraction before any rule-map entry or implementation.

## Test status

Local operator reported:

```text
PYTHONPATH=app python3 -m unittest app/tools/tests/test_production_readiness_matrix_policy.py
.....................
----------------------------------------------------------------------
Ran 21 tests in 0.083s

OK
```

After this report update is pulled locally, rerun the same test command and rerun the two H6 matrix commands above to verify the committed report remains aligned with current matrix behavior.

## Final H6 conclusion

H6 identifies no systemic `P0` production blocker.

H6 identifies four `P1_single_production_blocker` rules, all on the single representative production escalation row `MM-17179_ROI4987_English_1-26_rev_Fillable`.

The recommended H7 target is a design-first investigation of `PDF/UA-1/7.18.4` form-widget nesting. This is not a production-readiness claim and not authorization to implement a repair in H6.
