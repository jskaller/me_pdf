import unittest
from pathlib import Path

from tools.repair.mm17179_guarded_candidate_repair import (
    TERMINAL_VALIDATED,
    TERMINAL_VALIDATION_REGRESSION,
    build_final_report,
    conservative_alt_label,
    evaluate_adoption_gates,
    precondition_report_from_qpdf,
    semantic_quality_notes,
    validate_zapfdingbats_checkbox_stream,
    vector_checkmark_stream,
)


class MM17179GuardedCandidateRepairPolicyTests(unittest.TestCase):
    def test_missing_structure_preconditions_block_candidate_readiness(self):
        report = precondition_report_from_qpdf({
            "qpdf": [
                {},
                {
                    "obj:1 0 R": {"value": {"/Type": "/Catalog"}},
                    "obj:10 0 R": {"value": {"/Subtype": "/Widget", "/Rect": [0, 0, 10, 10]}},
                },
            ]
        })
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("StructTreeRoot missing", report["failed_preconditions"])
        self.assertIn("ParentTree missing", report["failed_preconditions"])

    def test_widget_evidence_bound_is_enforced(self):
        objects = {
            "obj:1 0 R": {"value": {"/StructTreeRoot": "13 0 R"}},
            "obj:13 0 R": {"value": {"/ParentTree": "48 0 R"}},
            "obj:48 0 R": {"value": {"/Nums": []}},
        }
        for idx in range(3):
            objects[f"obj:{100 + idx} 0 R"] = {"value": {"/Subtype": "/Widget", "/Rect": [0, 0, 10, 10]}}
        report = precondition_report_from_qpdf({"qpdf": [{}, objects]}, max_widgets=2)
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(report["widgets_truncated"])

    def test_zapfdingbats_checkbox_vector_candidate_is_pattern_bound(self):
        self.assertTrue(validate_zapfdingbats_checkbox_stream("BT /ZaDb 4 Tf (4) Tj ET", {"/Font": {"/ZaDb": "17 0 R"}}))
        self.assertFalse(validate_zapfdingbats_checkbox_stream("BT /ZaDb 4 Tf (8) Tj ET", {"/Font": {"/ZaDb": "17 0 R"}}))
        stream = vector_checkmark_stream([0, 0, 8, 8])
        self.assertIn(" m\n", stream)
        self.assertNotIn("/ZaDb", stream)
        self.assertNotIn("Tj", stream)

    def test_generated_alt_labels_remain_review_required(self):
        self.assertEqual(conservative_alt_label("/Btn", "Check Box13", "0"), "Checkbox field Check Box13, option 0")
        notes = semantic_quality_notes(generated_placeholder_alt=True)
        self.assertTrue(notes["human_review_required_for_label_quality"])
        self.assertTrue(notes["safe_to_claim_validator_pass"])
        self.assertFalse(notes["safe_to_claim_human_reviewed_field_labels"])
        self.assertFalse(notes["safe_to_claim_production_ready_without_label_review"])

    def test_all_validation_gates_are_required_for_validated_terminal(self):
        counts = {
            "PDF/UA-1/7.21.7": 0,
            "PDF/UA-1/7.21.4.1": 0,
            "PDF/UA-1/7.18.4": 0,
            "PDF/UA-1/7.18.1": 0,
            "failed_rule_elements_total": 0,
        }
        gate = evaluate_adoption_gates(
            qpdf_result={"result": "PASS"},
            render_compare={"result": "PASS", "pages_flagged": 0},
            profile_results={"PDF/UA-1": "PASS", "WCAG-2-2-Machine": "PASS", "ISO-32000-1-Tagged": "PASS"},
            final_rule_counts=counts,
        )
        self.assertEqual(gate["terminal_state"], TERMINAL_VALIDATED)
        self.assertTrue(gate["adoption_allowed"])

    def test_validation_failure_blocks_adoption(self):
        counts = {
            "PDF/UA-1/7.21.7": 0,
            "PDF/UA-1/7.21.4.1": 0,
            "PDF/UA-1/7.18.4": 0,
            "PDF/UA-1/7.18.1": 1,
            "failed_rule_elements_total": 1,
        }
        gate = evaluate_adoption_gates(
            qpdf_result={"result": "PASS"},
            render_compare={"result": "PASS", "pages_flagged": 0},
            profile_results={"PDF/UA-1": "FAIL", "WCAG-2-2-Machine": "PASS", "ISO-32000-1-Tagged": "PASS"},
            final_rule_counts=counts,
        )
        self.assertEqual(gate["terminal_state"], TERMINAL_VALIDATION_REGRESSION)
        self.assertFalse(gate["adoption_allowed"])

    def test_final_report_preserves_validator_pass_and_label_caveat(self):
        report = build_final_report(
            input_pdf=Path("input.pdf"),
            output_pdf=Path("output.pdf"),
            candidate_pdf=Path("candidate.pdf"),
            rule_count_progression={
                "baseline": {},
                "after_form_alt": {
                    "PDF/UA-1/7.21.7": 0,
                    "PDF/UA-1/7.21.4.1": 0,
                    "PDF/UA-1/7.18.4": 0,
                    "PDF/UA-1/7.18.1": 0,
                    "failed_rule_elements_total": 0,
                },
            },
            qpdf_result={"result": "PASS"},
            render_compare={"result": "PASS", "pages_flagged": 0, "page_results": [{"diff_pct": 0.0}]},
            profile_results={"PDF/UA-1": "PASS", "WCAG-2-2-Machine": "PASS", "ISO-32000-1-Tagged": "PASS"},
            evidence_artifacts={},
            generated_placeholder_alt=True,
            adoption_performed=True,
        )
        self.assertEqual(report["terminal_state"], TERMINAL_VALIDATED)
        self.assertTrue(report["safe_to_claim_pdfua_validator_pass"])
        self.assertFalse(report["safe_to_claim_human_reviewed_field_labels"])
        self.assertFalse(report["safe_to_claim_production_ready_without_label_review"])


if __name__ == "__main__":
    unittest.main()
