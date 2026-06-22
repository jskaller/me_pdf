#!/usr/bin/env python3
"""H10F policy tests for guarded non-runtime PDF/UA-1/7.18.4 metadata adoption.

H10F records validated guarded metadata only. It must not place
repair_form_widget_structure.py in active strategies[] and must not make
lookup_repair_plan.py emit the repair as an executable repair step.
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
H10F_DOC = REPO_ROOT / "docs" / "H10F_GUARDED_FORM_WIDGET_METADATA_ADOPTION.md"
PRODUCTION_STATUS_DOC = REPO_ROOT / "docs" / "PRODUCTION_REMEDIATION_STATUS.md"
TARGET_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"
STRATEGY_ID = "form_widget_structure_construction_v1"


class FormWidgetGuardedMetadataAdoptionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_map = json.loads(RULE_MAP.read_text())
        self.entry = self.rule_map["rules"][TARGET_RULE]
        self.candidates = self.entry.get("guarded_strategy_candidates", [])
        self.candidate = self.candidates[0] if self.candidates else {}
        self.h10f_doc = H10F_DOC.read_text()
        self.production_status_doc = PRODUCTION_STATUS_DOC.read_text()

    def test_rule_map_remains_valid_json_and_target_rule_present(self) -> None:
        json.loads(RULE_MAP.read_text())
        self.assertEqual(self.entry["clause"], "7.18.4")
        self.assertEqual(self.entry.get("resolvability"), "repairable_unbuilt")

    def test_guarded_metadata_is_adopted_under_non_runtime_path(self) -> None:
        self.assertIn("guarded_strategy_candidates", self.entry)
        self.assertEqual(len(self.candidates), 1)
        self.assertEqual(self.candidate["strategy_id"], STRATEGY_ID)
        self.assertEqual(self.candidate["strategy_name"], "Form-widget structure construction")
        self.assertEqual(self.candidate["repair_script"], FORM_WIDGET_SCRIPT)
        self.assertEqual(self.candidate["repair_version"], "1.4.0")

    def test_form_widget_repair_is_not_in_active_strategies_array(self) -> None:
        active_strategies = self.entry.get("strategies", [])
        self.assertEqual(active_strategies, [])
        self.assertNotIn(
            FORM_WIDGET_SCRIPT,
            [strategy.get("repair_script") for strategy in active_strategies],
        )

    def test_runtime_and_production_defaults_remain_disabled(self) -> None:
        self.assertIs(self.candidate["runtime_active"], False)
        self.assertIs(self.candidate["production_default"], False)
        self.assertEqual(self.candidate["activation_status"], "guarded_metadata_only")
        self.assertIs(self.candidate["requires_explicit_activation_patch"], True)
        self.assertIs(self.candidate["requires_runtime_gating_implementation"], True)

    def test_h10e_evidence_is_recorded(self) -> None:
        self.assertEqual(self.candidate["h10e_terminal_state"], "ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS")
        self.assertEqual(self.candidate["target_rule_before_count"], 204)
        self.assertEqual(self.candidate["target_rule_after_count"], 0)
        self.assertEqual(self.candidate["target_rule_status"], "CLEARED")
        self.assertEqual(self.candidate["iso_profile_before"], "PASS")
        self.assertEqual(self.candidate["iso_profile_after"], "PASS")
        self.assertEqual(self.candidate["iso_regression_review_classification"], "BENIGN_INFORMATIONAL")

    def test_qpdf_object_preservation_and_profile_accounting_evidence_is_recorded(self) -> None:
        self.assertEqual(self.candidate["qpdf"], "PASS")
        self.assertEqual(self.candidate["object_diagnostics"], "PASS")
        self.assertEqual(self.candidate["preservation"], "PASS")
        self.assertEqual(self.candidate["profile_accounting_terminal_state"], "VERAPDF_DELTA_VALIDATED")
        self.assertEqual(self.candidate["new_authoritative_rule_ids"], [])
        self.assertEqual(self.candidate["increased_authoritative_rule_ids"], [])

    def test_no_production_readiness_or_webui_validation_claim_is_made(self) -> None:
        self.assertIs(self.candidate["pdf_still_noncompliant_overall"], True)
        self.assertIs(self.candidate["production_readiness_claimed"], False)
        self.assertIs(self.candidate["webui_production_path_validated"], False)

    def test_required_safety_constraints_are_recorded(self) -> None:
        for key in (
            "source_overwrite_refused",
            "workspace_job_output_status_paths_refused_for_isolated_trial",
            "field_values_not_dumped",
            "requires_complete_widget_evidence",
            "requires_widgets_truncated_false",
            "requires_widget_evidence_complete_true",
            "requires_explicit_output_path",
            "requires_nonfixture_apply_guard",
        ):
            self.assertIs(self.candidate[key], True, key)

    def test_future_runtime_gates_are_recorded(self) -> None:
        required = {
            "precondition_check_form_widget_structure_inspection",
            "complete_widget_evidence_required",
            "widgets_truncated_must_be_false",
            "all_widgets_missing_or_validly_mapped_struct_parent_precondition",
            "safe_output_path_policy",
            "source_overwrite_refusal",
            "workspace_output_discipline",
            "post_repair_qpdf",
            "post_repair_pdfua1_profile",
            "post_repair_pinned_wcag_profile",
            "post_repair_iso_profile_no_regression",
            "post_repair_profile_accounting",
            "post_repair_form_widget_diagnostic",
            "preservation_check",
            "status_truthfulness",
            "package_truthfulness",
            "review_required_if_residual_failures_remain",
        }
        self.assertEqual(set(self.candidate["future_runtime_gates"]), required)

    def test_lookup_does_not_emit_form_widget_script_as_executable_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10f_lookup_") as td:
            parsed_failures = Path(td) / "parsed_failures.json"
            parsed_failures.write_text(
                json.dumps(
                    {
                        "result": "FAIL",
                        "total_failures": 1,
                        "unique_rules_failing": 1,
                        "failures_by_rule": [
                            {
                                "rule_id": TARGET_RULE,
                                "description": "Widget annotation is not nested within a Form structure element",
                                "failures": 1,
                            }
                        ],
                    }
                )
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(LOOKUP),
                    str(parsed_failures),
                    "--map",
                    str(RULE_MAP),
                ],
                check=True,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )
        output = json.loads(completed.stdout)
        self.assertEqual(output["result"], "ALL_MANUAL")
        self.assertEqual(output["repair_steps"], [])
        self.assertNotIn(FORM_WIDGET_SCRIPT, completed.stdout)
        self.assertEqual(output["hermes_required"][0]["reason"], "all_strategies_exhausted")

    def test_h10f_document_records_runtime_gating_contract(self) -> None:
        self.assertIn("GUARDED_METADATA_ADOPTED_RUNTIME_NOT_ACTIVE", self.h10f_doc)
        self.assertIn("H10F does not activate runtime execution", self.h10f_doc)
        self.assertIn("lookup_repair_plan.py", self.h10f_doc)
        self.assertIn("repair_form_widget_structure.py", self.h10f_doc)
        self.assertIn("repair_steps", self.h10f_doc)
        self.assertIn("H10G must implement explicit precondition-gated runtime behavior", self.h10f_doc)
        self.assertIn("must not simply move the metadata into active `strategies[]`", self.h10f_doc)

    def test_production_status_records_h10f_state(self) -> None:
        self.assertIn("H10F", self.production_status_doc)
        self.assertIn("GUARDED_METADATA_ADOPTED_RUNTIME_NOT_ACTIVE", self.production_status_doc)
        self.assertIn("guarded metadata adopted: true", self.production_status_doc)
        self.assertIn("runtime activation enabled: false", self.production_status_doc)
        self.assertIn("WebUI production-path evidence collected: false", self.production_status_doc)
        self.assertIn("Production readiness is not claimed", self.production_status_doc)


if __name__ == "__main__":
    unittest.main()
