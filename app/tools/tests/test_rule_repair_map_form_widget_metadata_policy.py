#!/usr/bin/env python3
"""H10B/H10C policy tests for PDF/UA-1/7.18.4 form-widget metadata adoption.

H10B deferred metadata adoption because the H10A-V ISO-32000-1 informational
profile regressed from PASS to FAIL. H10C reviewed runtime ISO evidence and
classified the regression as a structural side effect, so the canonical rule map
remains unchanged until the repair is adjusted.
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
H10B_DECISION_DOC = REPO_ROOT / "docs" / "H10B_FORM_WIDGET_METADATA_ADOPTION_DECISION.md"
H10C_DECISION_DOC = REPO_ROOT / "docs" / "H10C_ISO_REGRESSION_REVIEW.md"
TARGET_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"


class FormWidgetMetadataDeferralPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_map = json.loads(RULE_MAP.read_text())
        self.entry = self.rule_map["rules"][TARGET_RULE]
        self.h10b_decision_doc = H10B_DECISION_DOC.read_text()
        self.h10c_decision_doc = H10C_DECISION_DOC.read_text()

    def test_target_rule_remains_present_and_repairable_unbuilt(self) -> None:
        self.assertEqual(self.entry["clause"], "7.18.4")
        self.assertEqual(self.entry.get("resolvability"), "repairable_unbuilt")

    def test_h10b_defers_metadata_adoption_for_iso_regression_review(self) -> None:
        self.assertIn("ADOPTION_DEFERRED_FOR_ISO_REGRESSION_REVIEW", self.h10b_decision_doc)
        self.assertIn("PDF_UA/ISO-32000-1-Tagged.xml", self.h10b_decision_doc)
        self.assertIn("before: PASS", self.h10b_decision_doc)
        self.assertIn("after: FAIL", self.h10b_decision_doc)
        self.assertIn("classification: informational", self.h10b_decision_doc)

    def test_h10c_blocks_metadata_for_structural_iso_side_effect(self) -> None:
        self.assertIn("ISO_REGRESSION_REQUIRES_REPAIR_CHANGE", self.h10c_decision_doc)
        self.assertIn("STRUCTURAL_SIDE_EFFECT", self.h10c_decision_doc)
        self.assertIn("ISO 19005-2:2011/Annex_L", self.h10c_decision_doc)
        self.assertIn("correlation_to_form_widget_objects: true", self.h10c_decision_doc)
        self.assertIn("correlation_to_struct_tree_root: true", self.h10c_decision_doc)
        self.assertIn("correlation_to_parent_tree: true", self.h10c_decision_doc)
        self.assertIn("No guarded metadata is adopted", self.h10c_decision_doc)
        self.assertIn("No active executable strategy is added", self.h10c_decision_doc)
        self.assertIn("must not emit tools/repair/repair_form_widget_structure.py", self.h10c_decision_doc)

    def test_form_widget_repair_is_not_in_active_strategies(self) -> None:
        active_strategies = self.entry.get("strategies", [])
        self.assertEqual(active_strategies, [])
        self.assertNotIn(
            FORM_WIDGET_SCRIPT,
            [strategy.get("repair_script") for strategy in active_strategies],
        )

    def test_no_guarded_metadata_was_adopted_while_iso_regression_requires_repair_change(self) -> None:
        self.assertNotIn("guarded_strategy_candidates", self.entry)
        self.assertNotIn("reviewed_strategy_metadata", self.entry)
        self.assertNotIn("reviewed_learned_strategies", self.entry)

    def test_lookup_does_not_emit_form_widget_script_as_executable_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_lookup_") as td:
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

    def test_h10av_target_rule_delta_and_profile_policy_are_documented(self) -> None:
        for doc in (self.h10b_decision_doc, self.h10c_decision_doc):
            self.assertIn("204", doc)
            self.assertIn("0", doc)
            self.assertIn("required PDF/UA-1", doc)
            self.assertIn("PDF20", doc)
            self.assertIn("experimental/custom", doc)

    def test_production_readiness_is_not_claimed(self) -> None:
        for doc in (self.h10b_decision_doc, self.h10c_decision_doc):
            self.assertIn("does not claim production readiness", doc)
            self.assertIn("does not change", doc)
        self.assertIn("app/tools/orchestrate/remediate.py", self.h10c_decision_doc)
        self.assertIn("app/tools/packaging/status_json_writer.py", self.h10c_decision_doc)


if __name__ == "__main__":
    unittest.main()
