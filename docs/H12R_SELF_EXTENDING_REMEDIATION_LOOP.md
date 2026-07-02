# H12R - Self-Extending Remediation Loop with Two Synthetic Fixtures

## Baseline

```text
baseline commit inspected: 0ba889757e613722f70d01c763b27036412e3292
branch: master
```

## Terminal state

```text
SELF_EXTENDING_LOOP_VALIDATED_AND_REUSED_ON_SECOND_FIXTURE
```

This H12R patch adds a controlled synthetic proof of the self-extending repair lifecycle. It does not claim production readiness and does not claim full veraPDF/qpdf authority for the synthetic fixtures. The validation gates in this patch are controlled equivalents that exercise the same result schema and fail-closed status behavior.

## Files changed

```text
app/tools/agent/create_candidate_repair.py
app/tools/tests/generate_h12r_fixtures.py
app/tools/tests/test_self_extending_candidate_workbench_policy.py
docs/H12R_SELF_EXTENDING_REMEDIATION_LOOP.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## Target-selection preflight result

```json
{
  "selected_target_rule": "PDF/UA-1/7.21.7",
  "why_selected": "rule map marks missing ToUnicode as HERMES_REQUIRED/repairable_unbuilt with no active strategy; controlled synthetic fixtures can prove generation and reuse",
  "existing_active_strategy": false,
  "existing_guarded_strategy_sufficient": false,
  "remediable_in_principle": true,
  "fixture_generation_feasible": true,
  "validation_feasible": true
}
```

Selection basis from current repo behavior:

```text
app/tools/audit/rule_repair_map.json has PDF/UA-1/7.21.7 with confidence HERMES_REQUIRED, repair_script null, args_pattern null, resolvability repairable_unbuilt, and no active strategies array.
```

The selected target is objectively remediable in the synthetic harness because the fixtures carry an isolated missing-ToUnicode failure marker that can be cleared without structural side effects. This is a harness substitute for the Hermes generator boundary, not a production ToUnicode repair for real PDFs.

## Fixture A

```text
Generated path at smoke/runtime:
<workspace>/fixtures/h12r_fixture_a_missing_tounicode.pdf
```

Fixture A contains:

```text
fixture=A
object-seed=1201
H12R_TARGET_FAIL: PDF/UA-1/7.21.7
```

Fixture A proves:

```text
unsupported failure
-> strategy request
-> workbench candidate generation
-> sandbox apply against copied PDF only
-> controlled validation
-> candidate_result.json
-> guarded adoption proposal metadata
```

## Fixture B

```text
Generated path at smoke/runtime:
<workspace>/fixtures/h12r_fixture_b_missing_tounicode_distinct.pdf
```

Fixture B contains:

```text
fixture=B
object-seed=2209
H12R_TARGET_FAIL: PDF/UA-1/7.21.7
```

Fixture B differs from Fixture A by fixture marker, object seed, and visible text. The distinction is asserted by `is_distinct_fixture()` and by the H12R policy test. Fixture B is not an identical copy and is used to prove reuse/generalization rather than hardcoding to Fixture A.

## Strategy request artifact

Fixture A emits a strategy request equivalent to:

```json
{
  "schema": "montefiore.hermes_strategy_request.synthetic_h12r",
  "ticket": "H12R-SYNTHETIC-A",
  "target_rule": "PDF/UA-1/7.21.7",
  "generator_boundary": "deterministic_local_generator_substitute_for_hermes"
}
```

Runtime path in smoke:

```text
<workspace>/requests/h12r_a_strategy_request.json
```

## Candidate workbench command

```bash
PYTHONPATH=app python3 app/tools/agent/create_candidate_repair.py \
  --mode candidate \
  --strategy-request <workspace>/requests/h12r_a_strategy_request.json \
  --input-pdf <workspace>/fixtures/h12r_fixture_a_missing_tounicode.pdf \
  --workspace <workspace> \
  --ticket H12R-SYNTHETIC-A \
  --target-rule PDF/UA-1/7.21.7
```

## Fixture A candidate attempt directory

```text
<workspace>/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001/
```

Attempt contents:

```text
strategy_request.json
input.pdf
candidate_synthetic_tounicode_marker_repair_v1.py
candidate_output.pdf
candidate_stdout.json
candidate_result.json
adoption_proposal.json
```

The candidate implementation is generated at runtime into the attempt directory. No target-rule repair source is committed under `app/tools/repair`.

## Fixture A validation summary

```json
{
  "decision": "CANDIDATE_VALIDATED",
  "target_rule_before_count": 1,
  "target_rule_after_count": 0,
  "validation": {
    "qpdf": "CONTROLLED_PASS",
    "verapdf_pdfua1": "CONTROLLED_PASS",
    "verapdf_wcag": "CONTROLLED_PASS",
    "verapdf_iso": "CONTROLLED_PASS",
    "profile_accounting": "CONTROLLED_PASS",
    "preservation": "CONTROLLED_PASS"
  },
  "new_authoritative_failures": [],
  "increased_authoritative_failures": [],
  "promotion_allowed": false
}
```

## Fixture A adoption proposal

```text
<workspace>/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001/adoption_proposal.json
```

The adoption proposal marks the generated synthetic strategy as available only for the H12R reuse smoke. It keeps `production_default` false and records that real veraPDF validation is required before production use.

## Fixture B remediation/reuse command

```bash
PYTHONPATH=app python3 app/tools/agent/create_candidate_repair.py \
  --mode reuse \
  --input-pdf <workspace>/fixtures/h12r_fixture_b_missing_tounicode_distinct.pdf \
  --workspace <workspace> \
  --ticket H12R-SYNTHETIC-B \
  --target-rule PDF/UA-1/7.21.7 \
  --adoption-proposal <workspace>/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001/adoption_proposal.json
```

Proof Fixture B did not generate another candidate:

```text
The reuse path counts candidate_repairs/**/attempt-* before and after Fixture B execution and records new_candidate_generation_attempted=false.
```

Fixture B status/outcome summary:

```json
{
  "decision": "REUSE_VALIDATED",
  "reused_strategy_from_fixture_a": true,
  "new_candidate_generation_attempted": false,
  "normal_pipeline_used": true,
  "status_json_result": "PASS",
  "orchestrator_outcome_result": "PASS",
  "target_rule_before_count": 1,
  "target_rule_after_count": 0
}
```

Runtime paths in smoke:

```text
<workspace>/jobs/H12R-SYNTHETIC-B/STATUS.json
<workspace>/jobs/H12R-SYNTHETIC-B/orchestrator_outcome.json
```

## Manual repair-source check

```text
manual target repair committed: false
app/tools/repair changed: false
candidate implementation generated at runtime under workspace/candidate_repairs: true
```

## Validation commands

Focused validation run by the patch authoring environment:

```bash
cd /mnt/data/h12r
PYTHONPATH=app python3 -m unittest app/tools/tests/test_self_extending_candidate_workbench_policy.py
python3 -m py_compile app/tools/agent/create_candidate_repair.py app/tools/tests/generate_h12r_fixtures.py
```

Expected local validation after pulling:

```bash
python3 -m py_compile \
  app/tools/orchestrate/remediate.py \
  app/tools/packaging/status_json_writer.py \
  app/tools/packaging/package_deliverables.py

python3 -m py_compile \
  app/tools/agent/create_candidate_repair.py \
  app/tools/tests/generate_h12r_fixtures.py

PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_orchestrator_guarded_form_widget_policy.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py \
  app/tools/tests/test_lookup_repair_plan_guarded_candidates_policy.py \
  app/tools/tests/test_rule_repair_map_form_widget_metadata_policy.py \
  app/tools/tests/test_production_readiness_matrix_policy.py

PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_self_extending_candidate_workbench_policy.py

PYTHONPATH=app python3 app/tools/tests/test_m1_gate_verdict.py
```

## Smoke command

```bash
tmpdir=$(mktemp -d)
PYTHONPATH=app python3 app/tools/tests/generate_h12r_fixtures.py "$tmpdir/fixtures"
PYTHONPATH=app python3 - <<'PY'
import json
from pathlib import Path
from tools.agent.create_candidate_repair import build_strategy_request
root = Path('$tmpdir')
fixture = root / 'fixtures' / 'h12r_fixture_a_missing_tounicode.pdf'
request = build_strategy_request('H12R-SYNTHETIC-A', fixture)
(root / 'requests').mkdir(parents=True, exist_ok=True)
(root / 'requests' / 'h12r_a_strategy_request.json').write_text(json.dumps(request, indent=2, sort_keys=True) + '\n')
PY
PYTHONPATH=app python3 app/tools/agent/create_candidate_repair.py \
  --mode candidate \
  --strategy-request "$tmpdir/requests/h12r_a_strategy_request.json" \
  --input-pdf "$tmpdir/fixtures/h12r_fixture_a_missing_tounicode.pdf" \
  --workspace "$tmpdir" \
  --ticket H12R-SYNTHETIC-A \
  --target-rule PDF/UA-1/7.21.7
PYTHONPATH=app python3 app/tools/agent/create_candidate_repair.py \
  --mode reuse \
  --input-pdf "$tmpdir/fixtures/h12r_fixture_b_missing_tounicode_distinct.pdf" \
  --workspace "$tmpdir" \
  --ticket H12R-SYNTHETIC-B \
  --target-rule PDF/UA-1/7.21.7 \
  --adoption-proposal "$tmpdir/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001/adoption_proposal.json"
```

## Production-readiness statement

Production readiness is not claimed. H12R validates the self-extension lifecycle and second-fixture reuse on controlled synthetic fixtures. The next production step must apply this workbench pattern to real active blocker artifacts with authoritative qpdf, veraPDF PDF/UA-1, pinned WCAG, ISO, profile accounting, preservation, text/render, STATUS, and package evidence.

## Next patch

Apply the workbench to a real active blocker from MM-17179, preferably `PDF/UA-1/7.21.7` or `PDF/UA-1/7.21.4.1`, and prove that the generated candidate improves the WebUI production-path outcome without unsafe promotion or unsupported PASS claims.
