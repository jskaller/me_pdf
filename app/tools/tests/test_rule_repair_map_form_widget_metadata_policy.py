#!/usr/bin/env python3
"""H10B policy tests for PDF/UA-1/7.18.4 form-widget metadata adoption.

H10B intentionally defers metadata adoption because the H10A-V ISO-32000-1
informational profile regressed from PASS to FAIL. These tests preserve the
fail-closed state: no active runtime strategy, no guarded metadata adoption yet,
and a documented deferral decision.
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
DECISION_DOC = REPO_ROOT / "docs" / "H10B_FORM_WIDGET_METADATA_ADOPTION_DECISION.md"
TARGET_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"


class FormWidgetMetadataDeferralPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule_map = json.loads(RULE_MAP.read_text())
        self.entry = self.rule_map["rules"][TARGET_RULE]
        self.decision_doc = DECISION_DOC.read_text()

    def test_target_rule_remains_present_and_repairable_unbuilt(self) -> None:
        self.assertEqual(self.entry["clause"], "7.18.4")
        self.assertEqual(self.entry.get("resolvability"), "repairable_unbuilt")

    def test_h10b_defers_metadata_adoption_for_iso_regression_review(self) -> None:
        self.assertIn("ADOPTION_DEFERRED_FOR_ISO_REGRESSION_REVIEW", self.decision_doc)
        self.assertIn("PDF_UA/ISO-32000-1-Tagged.xml", self.decision_doc)
        self.assertIn("before: PASS", self.decision_doc)
        self.assertIn("after: FAIL", self.decision_doc)
        self.assertIn("classification: informational", self.decision_doc)

    def test_form_widget_repair_is_not_in_active_strategies(self) -> None:
        active_strategies = self.entry.get("strategies", [])
        self.assertEqual(active_strategies, [])
        self.assertNotIn(
            FORM_WIDGET_SCRIPT,
            [strategy.get("repair_script") for strategy in active_strategies],
        )

    def test_no_guarded_metadata_was_adopted_while_deferred(self) -> None:
        self.assertNotIn("guarded_strategy_candidates", self.entry)
        self.assertNotIn("reviewed_strategy_metadata", self.entry)
        self.assertNotIn("reviewed_learned_strategies", self.entry)

    def test_lookup_does_not_emit_form_widget_script_as_executable_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10b_lookup_") as td:
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
        self.assertIn("target-rule clearance from 204 failures to 0 failures", self.decision_doc)
        self.assertIn("required PDF/UA-1/WCAG profile accounting", self.decision_doc)
        self.assertIn("PDF20 prohibition", self.decision_doc)
        self.assertIn("experimental/custom profile non-authoritative", self.decision_doc)

    def test_production_readiness_is_not_claimed(self) -> None:
        self.assertIn("does not make the strategy production-active", self.decision_doc)
        self.assertIn("does not claim production readiness", self.decision_doc)
        self.assertIn("does not change `app/tools/orchestrate/remediate.py`", self.decision_doc)
        self.assertIn("does not change `app/tools/packaging/`", self.decision_doc)


if __name__ == "__main__":
    unittest.main()
