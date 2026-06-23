#!/usr/bin/env python3
"""H11 tests for guarded post-form-widget inspection acceptance."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "app"))

from tools.orchestrate.guarded_acceptance import (  # noqa: E402
    TARGET_RULE,
    evaluate_guarded_acceptance,
)


class H11GuardedPostInspectionAcceptancePolicyTests(unittest.TestCase):
    def base_evidence(self) -> dict:
        return {
            "repair_strategy_id": "form_widget_structure_construction_v1",
            "target_rule": TARGET_RULE,
            "input_pdf": "/tmp/job/repair/pass0_source.pdf",
            "candidate_pdf": "/tmp/job/guarded_candidates/form_widget_structure/output.pdf",
            "final_pdf": "/tmp/job/repair/final.pdf",
            "status_path": "/tmp/job/STATUS.json",
            "package_path": "/tmp/job/package",
            "orchestrator_outcome_path": "/tmp/job/audit/orchestrator_outcome.json",
            "qpdf_result": "PASS",
            "verapdf_pdfua1_result": "FAIL",
            "verapdf_wcag_result": "FAIL",
            "verapdf_iso_result": "PASS",
            "profile_accounting_result": "PASS",
            "iso_regression_result": "PASS",
            "post_form_widget_inspection_result": "INSPECTED",
            "post_form_widget_inspection": self.good_post_inspection_report(),
            "preservation_result": "PASS",
            "residual_failures": [{"rule_id": "PDF/UA-1/7.21.7", "failures": 1}],
            "new_authoritative_failures": [],
            "increased_authoritative_failures": [],
            "target_rule_before_count": 204,
            "target_rule_after_count": 0,
            "target_rule_status": "CLEARED",
        }

    def good_post_inspection_report(self, widget_count: int = 2) -> dict:
        widgets = [
            {
                "annotation_objgen": f"{index} 0",
                "struct_parent": index,
                "parent_tree_mapping_present": True,
                "already_nested_in_form": True,
                "referenced_from_non_form_element": False,
            }
            for index in range(widget_count)
        ]
        return {
            "schema": "montefiore.form_widget_structure_inspection",
            "result": "INSPECTED",
            "pdf_object_evidence": {
                "available": True,
                "widget_annotation_count": widget_count,
                "widgets_with_struct_parent_count": widget_count,
                "widgets_with_parent_tree_mapping_count": widget_count,
                "widgets_already_nested_in_form_count": widget_count,
                "widgets_referenced_from_non_form_count": 0,
                "widgets_bounded_count": widget_count,
                "widgets_truncated": False,
                "widget_evidence_complete": True,
                "form_struct_element_count": 1,
                "widgets": widgets,
            },
            "decision": {
                "chosen_option": "A",
                "repair_implementation_safe_now": False,
                "design_ready_for_future_patch": True,
                "reason": "post-repair structure diagnostic is complete",
                "blockers": [],
                "required_next_evidence": [],
            },
        }

    def decide(self, **overrides):
        evidence = self.base_evidence()
        evidence.update(overrides)
        return evaluate_guarded_acceptance(evidence)

    def test_inspected_with_complete_form_widget_evidence_reaches_review_required_not_structure_rejection(self):
        decision = self.decide()

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED")
        self.assertEqual(decision["status_result"], "REVIEW_REQUIRED")
        self.assertEqual(decision["package_policy"], "REVIEW_REQUIRED_WITH_CANDIDATE")
        self.assertFalse(decision["pass_allowed"])
        self.assertFalse(decision["promote_candidate_to_final"])

    def test_inspected_without_detailed_evidence_remains_rejected_fail_closed(self):
        decision = self.decide(post_form_widget_inspection=None)

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC")
        self.assertIn("post_form_widget_inspection_evidence_missing", decision["blockers"])
        self.assertFalse(decision["pass_allowed"])

    def test_inspected_with_truncated_widget_evidence_remains_rejected(self):
        report = self.good_post_inspection_report()
        report["pdf_object_evidence"]["widgets_truncated"] = True
        report["pdf_object_evidence"]["widget_evidence_complete"] = False

        decision = self.decide(post_form_widget_inspection=report)

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC")
        self.assertIn("post_form_widget_inspection_evidence_incomplete", decision["blockers"])
        self.assertIn("post_form_widget_inspection_widgets_truncated", decision["blockers"])

    def test_inspected_with_non_form_references_remains_rejected(self):
        report = self.good_post_inspection_report()
        report["pdf_object_evidence"]["widgets_referenced_from_non_form_count"] = 1
        report["pdf_object_evidence"]["widgets"][0]["referenced_from_non_form_element"] = True

        decision = self.decide(post_form_widget_inspection=report)

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC")
        self.assertIn("post_form_widget_inspection_non_form_references", decision["blockers"])
        self.assertIn("post_form_widget_inspection_widget_records_not_form_nested", decision["blockers"])

    def test_inspected_result_is_not_global_pass_for_qpdf_gate(self):
        decision = self.decide(qpdf_result="INSPECTED")

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_QPDF")
        self.assertIn("qpdf_result_not_pass", decision["blockers"])

    def test_post_inspection_artifact_path_can_supply_detailed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "guarded_form_widget_structure_after.json"
            report_path.write_text(json.dumps(self.good_post_inspection_report()))

            decision = self.decide(
                post_form_widget_inspection=None,
                artifacts={"post_inspection": str(report_path)},
            )

        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED")
        self.assertEqual(decision["status_result"], "REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
