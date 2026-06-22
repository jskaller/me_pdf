#!/usr/bin/env python3
"""H10G policy tests for fail-closed guarded candidate lookup gating.

Guarded candidates must remain separate from active strategies. Default lookup
must keep PDF/UA-1/7.18.4 manual/Hermes-routed. Guarded lookup may emit the
form-widget repair only when explicit guarded enablement and complete
precondition evidence are present.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_MAP = REPO_ROOT / "app" / "tools" / "audit" / "rule_repair_map.json"
LOOKUP = REPO_ROOT / "app" / "tools" / "audit" / "lookup_repair_plan.py"
TARGET_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"
STRATEGY_ID = "form_widget_structure_construction_v1"


class LookupRepairPlanGuardedCandidatesPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_map = json.loads(RULE_MAP.read_text())
        self.entry = self.rule_map["rules"][TARGET_RULE]
        self.tmp = tempfile.TemporaryDirectory(prefix="h10g_lookup_")
        self.tmp_path = Path(self.tmp.name)
        self.failure_json = self.tmp_path / "parsed_failures.json"
        self.failure_json.write_text(json.dumps({
            "result": "FAIL",
            "total_failures": 1,
            "unique_rules_failing": 1,
            "failures_by_rule": [{
                "rule_id": TARGET_RULE,
                "description": "Widget annotation not nested within a Form tag in the structure tree",
                "failures": 1,
            }],
        }))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _lookup(self, *extra: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(LOOKUP), str(self.failure_json), "--map", str(RULE_MAP), *extra],
            check=True,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)

    def _valid_precondition_report(self, **overrides: object) -> Path:
        report = {
            "schema": "montefiore.form_widget_structure_inspection",
            "version": "1.1.0",
            "result": "INSPECTED",
            "target_rule": TARGET_RULE,
            "pdf_path": "/workspace/jobs/JOB/input.pdf",
            "job_dir": "/workspace/jobs/JOB",
            "repair_performed": False,
            "rule_map_mutation_performed": False,
            "pdf_object_evidence": {
                "available": True,
                "acroform_present": True,
                "widget_annotation_count": 2,
                "widgets_bounded_count": 2,
                "bounded_widget_records_count": 2,
                "widgets_missing_struct_parent_count": 2,
                "widget_evidence_complete": True,
                "widgets_truncated": False,
                "struct_tree_root_present": True,
                "parent_tree_present": True,
                "sensitive_field_values_redacted": True,
            },
            "guarded_runtime_preconditions": {
                "planned_struct_parent_assignments": 2,
                "planned_form_struct_elements": 2,
                "source_overwrite_allowed": False,
                "output_path_policy": "explicit_safe_intermediate_required",
            },
        }
        for key, value in overrides.items():
            if key in report["pdf_object_evidence"]:
                report["pdf_object_evidence"][key] = value
            elif key in report["guarded_runtime_preconditions"]:
                report["guarded_runtime_preconditions"][key] = value
            else:
                report[key] = value
        path = self.tmp_path / "preconditions.json"
        path.write_text(json.dumps(report))
        return path

    def test_active_strategies_remain_empty_for_target_rule(self) -> None:
        self.assertEqual(self.entry.get("strategies"), [])
        self.assertNotIn(FORM_WIDGET_SCRIPT, json.dumps(self.entry.get("strategies", [])))

    def test_default_lookup_ignores_guarded_candidates(self) -> None:
        output = self._lookup()
        self.assertEqual(output["result"], "ALL_MANUAL")
        self.assertEqual(output["repair_steps"], [])
        self.assertEqual(output.get("guarded_candidates"), [])
        self.assertNotIn(FORM_WIDGET_SCRIPT, json.dumps(output["repair_steps"]))
        self.assertEqual(output["hermes_required"][0]["reason"], "all_strategies_exhausted")

    def test_guarded_lookup_without_precondition_report_blocks(self) -> None:
        output = self._lookup("--enable-guarded-candidates")
        self.assertEqual(output["result"], "ALL_MANUAL")
        self.assertEqual(output["repair_steps"], [])
        self.assertEqual(output["guarded_candidates"][0]["emitted"], False)
        self.assertIn("missing_precondition_report", output["guarded_candidates"][0]["blocked_reasons"])

    def test_missing_precondition_report_path_blocks(self) -> None:
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(self.tmp_path / "missing.json"))
        self.assertEqual(output["repair_steps"], [])
        self.assertIn("precondition_report_not_found", output["guarded_candidates"][0]["blocked_reasons"])

    def test_malformed_precondition_report_blocks(self) -> None:
        bad = self.tmp_path / "bad.json"
        bad.write_text("{")
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(bad))
        self.assertEqual(output["repair_steps"], [])
        self.assertTrue(output["guarded_candidates"][0]["blocked_reason"].startswith("malformed_precondition_report"))

    def test_widgets_truncated_blocks(self) -> None:
        report = self._valid_precondition_report(widgets_truncated=True)
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(report))
        self.assertEqual(output["repair_steps"], [])
        self.assertIn("widgets_truncated", output["guarded_candidates"][0]["blocked_reasons"])

    def test_incomplete_widget_evidence_blocks(self) -> None:
        report = self._valid_precondition_report(widget_evidence_complete=False)
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(report))
        self.assertEqual(output["repair_steps"], [])
        self.assertIn("widget_evidence_incomplete", output["guarded_candidates"][0]["blocked_reasons"])

    def test_zero_widgets_blocks(self) -> None:
        report = self._valid_precondition_report(widget_annotation_count=0, widgets_bounded_count=0)
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(report))
        self.assertEqual(output["repair_steps"], [])
        self.assertIn("no_widget_annotations", output["guarded_candidates"][0]["blocked_reasons"])

    def test_no_planned_assignments_blocks(self) -> None:
        report = self._valid_precondition_report(planned_struct_parent_assignments=0)
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(report))
        self.assertEqual(output["repair_steps"], [])
        self.assertIn("no_planned_struct_parent_assignments", output["guarded_candidates"][0]["blocked_reasons"])

    def test_valid_preconditions_emit_guarded_repair_step(self) -> None:
        report = self._valid_precondition_report()
        output = self._lookup("--enable-guarded-candidates", "--precondition-report", str(report))
        self.assertEqual(output["result"], "PLAN_READY")
        self.assertEqual(len(output["repair_steps"]), 1)
        step = output["repair_steps"][0]
        self.assertEqual(step["repair_script"], FORM_WIDGET_SCRIPT)
        self.assertEqual(step["strategy_id"], STRATEGY_ID)
        self.assertIs(step["guarded"], True)
        self.assertIs(step["runtime_active"], False)
        self.assertIs(step["production_default"], False)
        self.assertIs(step["requires_post_validation"], True)
        self.assertIn("qpdf", step["required_post_validations"])
        self.assertIn("verapdf_iso_no_regression", step["required_post_validations"])
        self.assertEqual(step["required_terminal_behavior"], "REVIEW_REQUIRED_IF_RESIDUAL_FAILURES_REMAIN")
        self.assertEqual(output["guarded_candidates"][0]["emitted"], True)


if __name__ == "__main__":
    unittest.main()
