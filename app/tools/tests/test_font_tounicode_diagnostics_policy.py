import unittest

from tools.audit.font_tounicode_diagnostics import (
    GATE_READY_FOR_CANDIDATE_CREATION,
    TARGET_RULE,
    TERMINAL_BLOCKED_BY_MISSING_EVIDENCE,
    build_tounicode_repair_readiness_report,
    collect_font_records,
    deterministic_mapping_evidence,
)


class FontToUnicodeDiagnosticsPolicyTests(unittest.TestCase):
    def test_missing_deterministic_evidence_blocks_tounicode_candidate_creation(self):
        report = build_tounicode_repair_readiness_report(
            font_records=[
                {
                    "object_id": "12 0 R",
                    "base_font": "ABCDEE+MySubsetFont",
                    "subtype": "TrueType",
                    "encoding": None,
                    "to_unicode_present": False,
                    "character_code_usage_evidence": None,
                }
            ],
            active_failure_count=4,
            text_extraction_before=None,
            render_comparison_available=False,
            h11_artifacts_available=False,
        )

        self.assertEqual(report["target_rule"], TARGET_RULE)
        self.assertFalse(report["repair_allowed"])
        self.assertFalse(report["candidate_creation_allowed"])
        self.assertEqual(report["candidate_gate_state"], TERMINAL_BLOCKED_BY_MISSING_EVIDENCE)
        self.assertEqual(
            report["terminal_state_if_stopped_here"],
            TERMINAL_BLOCKED_BY_MISSING_EVIDENCE,
        )
        self.assertIn("h11_runtime_artifacts_unavailable_locally", report["missing_report_evidence"])
        self.assertIn("actual_text_extraction_before_repair", report["missing_report_evidence"])
        self.assertIn("rendered_text_comparison_before_after", report["missing_report_evidence"])
        self.assertFalse(report["safe_to_claim_pass"])
        self.assertFalse(report["safe_to_claim_production_ready"])

    def test_tounicode_mapping_cannot_be_authorized_from_guesswork_or_ocr(self):
        guess = deterministic_mapping_evidence(
            {
                "object_id": "15 0 R",
                "base_font": "SubsetFont",
                "subtype": "TrueType",
                "encoding": "WinAnsiEncoding",
                "to_unicode_present": False,
                "character_code_usage_evidence": {"codes": [65, 66]},
                "mapping_source": "guess",
            }
        )
        ocr = deterministic_mapping_evidence(
            {
                "object_id": "16 0 R",
                "base_font": "SubsetFont",
                "subtype": "TrueType",
                "encoding": "WinAnsiEncoding",
                "to_unicode_present": False,
                "character_code_usage_evidence": {"codes": [65, 66]},
                "mapping_source": "ocr",
            }
        )

        self.assertFalse(guess["deterministic_mapping_available"])
        self.assertFalse(ocr["deterministic_mapping_available"])
        self.assertIn("authoritative_mapping_source", guess["missing_evidence"])
        self.assertIn("authoritative_mapping_source", ocr["missing_evidence"])

    def test_qpdf_font_inventory_extracts_missing_tounicode_font_records(self):
        qpdf_json = {
            "objects": {
                "12 0 R": {
                    "value": {
                        "/Type": "/Font",
                        "/Subtype": "/TrueType",
                        "/BaseFont": "/ABCDEE+Subset",
                        "/Encoding": {
                            "/Differences": [65, "/A", "/B"],
                        },
                        "/Widths": [600, 600],
                    }
                },
                "13 0 R": {
                    "value": {
                        "/Type": "/Font",
                        "/Subtype": "/Type1",
                        "/BaseFont": "/Helvetica",
                        "/ToUnicode": "14 0 R",
                    }
                },
            }
        }

        records = collect_font_records(qpdf_json)
        self.assertEqual(len(records), 2)
        missing = [record for record in records if not record["to_unicode_present"]]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["object_id"], "12 0 R")
        self.assertEqual(missing[0]["subtype"], "TrueType")
        self.assertTrue(missing[0]["widths_present"])

    def test_complete_authoritative_evidence_opens_gate_but_does_not_claim_pass(self):
        report = build_tounicode_repair_readiness_report(
            font_records=[
                {
                    "object_id": "12 0 R",
                    "base_font": "ABCDEE+Subset",
                    "subtype": "TrueType",
                    "encoding": {"/Differences": [65, "/A", "/B"]},
                    "differences": [65, "/A", "/B"],
                    "to_unicode_present": False,
                    "character_code_usage_evidence": {"codes": [65, 66]},
                    "mapping_source": "encoding_differences",
                }
            ],
            active_failure_count=4,
            text_extraction_before={"result": "PASS", "text": "AB"},
            render_comparison_available=True,
            h11_artifacts_available=True,
        )

        self.assertTrue(report["repair_allowed"])
        self.assertTrue(report["candidate_creation_allowed"])
        self.assertEqual(report["candidate_gate_state"], GATE_READY_FOR_CANDIDATE_CREATION)
        self.assertIsNone(report["terminal_state_if_stopped_here"])
        self.assertFalse(report["safe_to_claim_pass"])
        self.assertFalse(report["safe_to_claim_production_ready"])


if __name__ == "__main__":
    unittest.main()
