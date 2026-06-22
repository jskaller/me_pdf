#!/usr/bin/env python3
"""Policy tests for the MM-17179 blocker inspection diagnostic."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.mm17179_blocker_inspection import (
    TARGET_RULES,
    build_report,
    normalize_rule_map_state,
)


class MM17179BlockerInspectionPolicyTests(unittest.TestCase):
    def test_rule_map_states_preserve_unbuilt_and_unknown_distinctions(self) -> None:
        rule_map = {
            "rules": {
                "PDF/UA-1/7.18.4": {
                    "description": "Widget annotation not nested within a Form tag in the structure tree",
                    "repair_script": None,
                    "confidence": "HERMES_REQUIRED",
                    "resolvability": "repairable_unbuilt",
                    "emits_review_artifact": False,
                },
                "PDF/UA-1/7.21.7": {
                    "description": "Font dictionary missing ToUnicode map",
                    "repair_script": None,
                    "confidence": "HERMES_REQUIRED",
                    "resolvability": "repairable_unbuilt",
                    "emits_review_artifact": False,
                },
            }
        }

        states = {rule: normalize_rule_map_state(rule_map, rule) for rule in TARGET_RULES}

        self.assertTrue(states["PDF/UA-1/7.18.4"]["present_in_rule_map"])
        self.assertEqual(states["PDF/UA-1/7.18.4"]["resolvability"], "repairable_unbuilt")
        self.assertFalse(states["PDF/UA-1/7.18.4"]["safe_to_execute"])
        self.assertTrue(states["PDF/UA-1/7.21.7"]["present_in_rule_map"])
        self.assertEqual(states["PDF/UA-1/7.21.7"]["resolvability"], "repairable_unbuilt")
        self.assertFalse(states["PDF/UA-1/7.21.4.1"]["present_in_rule_map"])
        self.assertEqual(states["PDF/UA-1/7.21.4.1"]["reason"], "unknown_rule")
        self.assertFalse(states["PDF/UA-1/7.21.4.1"]["safe_to_execute"])

    def test_missing_private_pdf_keeps_decision_at_option_c(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mm17179_inspection_") as td:
            root = Path(td)
            job = root / "workspace" / "jobs" / "MM-17179_ROI4987_English_1-26_rev_Fillable"
            audit = job / "audit"
            audit.mkdir(parents=True)
            (job / "STATUS.json").write_text(json.dumps({"overall_result": "ESCALATION"}))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({"overall_result": "ESCALATION"}))
            rule_map = root / "rule_repair_map.json"
            rule_map.write_text(json.dumps({"rules": {}}))

            report = build_report(job, root / "missing.pdf", rule_map)

            self.assertEqual(report["decision"]["chosen_option"], "C")
            self.assertFalse(report["decision"]["repair_implementation_safe_now"])
            self.assertFalse(report["policy"]["repair_performed"])
            self.assertFalse(report["policy"]["safe_to_claim_production_ready"])
            self.assertEqual(report["job_artifacts"]["status"]["data"]["overall_result"], "ESCALATION")


if __name__ == "__main__":
    unittest.main()
