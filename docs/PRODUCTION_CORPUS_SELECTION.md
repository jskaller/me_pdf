# Production Corpus Selection and Blocker Prioritization

Patch H4 adds corpus profiles to the production-readiness matrix so roadmap decisions are driven by representative evidence instead of whichever single PDF was most recently inspected.

The matrix remains diagnostic-only. It does not repair PDFs, change final PDF routing, change packaging authority, change `rule_repair_map.json`, or claim production readiness.

## Why profiles exist

A production-readiness report must separate these evidence types:

- `production_corpus`: real private/local or representative PDFs intended to count toward production-readiness evidence.
- `controlled_fixture`: controlled smoke rows such as `WEBUI-E2E-*`.
- `synthetic_generated_fixture`: generated fixtures used to verify a narrow contract.
- `historical_probe`: development runs, probes, experiments, `TEST-*`, `SMOKE_*`, `PROBE_*`, pre-patch rows, timestamped reruns, and similar historical artifacts.
- `stale_or_incomplete`: rows missing `STATUS.json`, `audit/orchestrator_outcome.json`, an output package, or rows with stale/shared package risk.
- `excluded`: rows explicitly excluded by manifest policy.

One controlled fixture can prove a narrow path. One real PDF can expose a real blocker. Neither is enough to prove a production-ready remediation system. Profiles prevent either one from distorting corpus-wide conclusions.

## Profile CLI

Run all rows:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile all
```

Run representative production rows only:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile production
```

Run controlled/synthetic fixture rows only:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile fixtures
```

Run historical, probe, stale, and incomplete rows:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile historical
```

Run production rows that are currently actionable:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile actionable
```

`actionable` is intentionally production-focused. Fixture-only failures should generally trigger more corpus collection or fixture cleanup before becoming the remediation roadmap.

## Manifest overrides

A manifest can override heuristics when local operators know which jobs are representative.

```bash
bash scripts/run-production-readiness-matrix.sh \
  --inspect-existing \
  --profile production \
  --manifest docs/examples/corpus_manifest.example.json
```

Manifest entries may set `source_kind`, assign a row to `production_corpus`, `controlled_fixture`, `historical_probe`, `stale_or_incomplete`, or `excluded`, and include/exclude job names from named profiles.

The example manifest must not include private PDF content. It may reference existing local job directory names because those names are already visible in workspace artifacts.

## Row metadata

Each matrix row now includes `corpus_profile`:

```json
{
  "primary_profile": "production_corpus",
  "included_in_profiles": ["all", "production", "actionable"],
  "excluded_from_production_reason": "",
  "manifest_source": "heuristic",
  "profile_reason": "representative/private source PDF evidence"
}
```

Use `excluded_from_production_reason` when explaining why a row is not counted toward representative readiness.

## Corpus summary

The matrix includes `corpus_summary` with counts for production rows, fixtures, historical/probe rows, stale/incomplete rows, excluded rows, representative real PDF coverage, synthetic fixture coverage, and production outcome counts.

This is the section to use for executive reporting. It distinguishes production `PASS`, `REVIEW_REQUIRED`, `FAIL`, `ESCALATION`, `MISMATCH`, and incomplete counts from fixture or historical evidence.

## Blocker priority summary

The matrix includes `blocker_priority_summary.rules`, grouped by rule ID. Patch H5 makes these rule observations source-aware so production priority is driven by current active blocker evidence, not by pre-repair-only or repair-plan-only context.

Current active blocker evidence includes:

- active `HERMES_REQUIRED` signals that were not reconciled as resolved, suppressed, or non-targetable;
- post-repair validator rule failures when rule-level failure summaries are available;
- residual targetable rules;
- residual non-targetable rules.

Contextual evidence remains visible but does not independently create P0/P1 production priority:

- pre-repair validator failures only;
- repair-plan rules only;
- `repair_plan.hermes_required` without active signal, post-validator, or residual evidence;
- repair scripts that executed when no current post-failure or residual evidence remains.

Each priority row now reports `rule_observation_sources`, `active_blocker_sources`, `historical_or_context_sources`, `current_blocker`, `priority_evidence_tiers`, and counts for pre-repair-only, repair-plan-only, residual, post-validator, active-Hermes, and executed-and-cleared evidence.

Rule-map presence is reported, but it is not proof of repair or proof that a rule is currently active. The matrix preserves:

```json
{"rule_map_entries_count_as_proven_repairs": false}
```

A repair becomes production evidence only when execution and validator/residual deltas support it.

## Priority buckets

- `P0_systemic_production_blocker`: current active blocker evidence recurs across more than one production row.
- `P1_single_production_blocker`: current active blocker evidence appears in exactly one production row.
- `P2_fixture_only_blocker`: current active blocker evidence is fixture-only.
- `P3_historical_or_stale_only`: current active blocker evidence appears only in historical/stale rows, or the observation is historical/stale only.
- `P4_mapped_but_unproven`: mapped rule exists but selected-corpus observations are contextual rather than current-active.
- `P5_external_validation_gap`: prioritization depends on evidence not yet ingested, often including external validators.

Recommended actions include `build_or_repair_strategy`, `audit_rule_map_and_tests`, `collect_more_corpus_evidence`, `exclude_stale_artifact`, and `external_validator_ingestion`. PASS rows with current active evidence are reported as risks via `pass_row_current_blocker_risks`; they do not normally create P0/P1 priority by themselves.

## MM-17179 / H3 interpretation

MM-17179 remains important evidence because it surfaced active blockers such as form-widget and font-related PDF/UA failures. H4 does not convert that evidence into a roadmap by itself.

MM-17179 should land as an actionable production row only when it is classified as representative production corpus. Its blocker families become systemic only if the selected production corpus shows recurrence across multiple representative rows. Until then, form-widget reconstruction remains single-row evidence, not a system-wide mandate.

## External validators

axesCheck and PAC 2024 remain `NOT_RUN` unless real artifacts are supplied by a future explicit workflow. The matrix must not treat veraPDF-only success as final external validator signoff.

## Executive production-readiness report hygiene

Before preparing an executive report:

1. run `--profile production` with a reviewed manifest;
2. inspect `corpus_summary` for production coverage and outcome counts;
3. inspect `blocker_priority_summary.rules` for P0/P1 production blockers;
4. explicitly list fixtures and historical rows as excluded from readiness counts;
5. state that external validators remain `NOT_RUN` unless separately supplied;
6. do not claim 10/10 production readiness unless production corpus evidence, packaging evidence, validator evidence, and external signoff all support it.
