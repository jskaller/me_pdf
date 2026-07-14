#!/usr/bin/env python3
"""H13U fixture-target preflight tests."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "app"))

from tools.audit.self_extension_fixture_preflight import (  # noqa: E402
    build_preflight,
    build_preflight_from_job,
    preflight_blocks_retry,
    surface_preflight,
)


class SelfExtensionFixturePreflightTests(unittest.TestCase):
    def test_match_allows_retry_loop_smoke(self):
        preflight = build_preflight(
            expected_target_rule_id="PDF/UA-1/7.21.7",
            residual_rules=["PDF/UA-1/7.21.7"],
            rule_map={"rules": {"PDF/UA-1/7.21.7": {"manual": True, "strategies": []}}},
            fixture="fixture-a.pdf",
        )
        self.assertEqual(preflight["result"], "MATCH")
        self.assertEqual(preflight["actual_target_rule_id"], "PDF/UA-1/7.21.7")
        self.assertTrue(preflight["self_extension_would_run"])
        self.assertFalse(preflight_blocks_retry(preflight))
        self.assertEqual(preflight["candidate_classification"], "MATCHES_EXPECTED_TARGET")
        self.assertFalse(preflight["residual_rules"][0]["known_repair_available"])

    def test_mismatch_blocks_retry_loop_smoke(self):
        preflight = build_preflight(
            expected_target_rule_id="PDF/UA-1/7.21.7",
            residual_rules=["PDF/UA-1/7.21.4.1"],
        )
        self.assertEqual(preflight["result"], "MISMATCH")
        self.assertEqual(preflight["actual_target_rule_id"], "PDF/UA-1/7.21.4.1")
        self.assertFalse(preflight["self_extension_would_run"])
        self.assertTrue(preflight_blocks_retry(preflight))
        self.assertEqual(preflight["candidate_classification"], "MISMATCHES_EXPECTED_TARGET")

    def test_no_target_blocks_retry_loop_smoke(self):
        preflight = build_preflight(
            expected_target_rule_id="PDF/UA-1/7.21.7",
            residual_rules=[],
        )
        self.assertEqual(preflight["result"], "NO_TARGET")
        self.assertIsNone(preflight["actual_target_rule_id"])
        self.assertFalse(preflight["self_extension_would_run"])
        self.assertTrue(preflight_blocks_retry(preflight))
        self.assertEqual(preflight["candidate_classification"], "NO_SELF_EXTENSION_TARGET")

    def test_preflight_from_job_prefers_strategy_gap_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            (audit / "strategy_gap.json").write_text(json.dumps({
                "result": "HERMES_REQUIRED",
                "rules": ["PDF/UA-1/7.21.7"],
            }))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({
                "overall_result": "ESCALATION",
                "residual_analysis": {"targetable_residual_rules": ["PDF/UA-1/7.21.4.1"]},
            }))
            preflight = build_preflight_from_job(
                job,
                expected_target_rule_id="PDF/UA-1/7.21.7",
                fixture="JOB1/input.pdf",
            )
            self.assertEqual(preflight["result"], "MATCH")
            self.assertEqual(preflight["actual_target_rule_id"], "PDF/UA-1/7.21.7")
            self.assertEqual(preflight["fixture"], "JOB1/input.pdf")
            self.assertIn("strategy_gap.json", preflight["evidence_sources"][0])

    def test_preflight_surfaces_to_status_and_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            (job / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "result": "PASS"}))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({"overall_result": "PASS", "result": "PASS"}))
            preflight = build_preflight(
                expected_target_rule_id="PDF/UA-1/7.21.7",
                residual_rules=["PDF/UA-1/7.21.4.1"],
            )
            surfaced = surface_preflight(job, preflight)
            self.assertEqual(surfaced["result"], "MISMATCH")
            self.assertTrue((audit / "self_extension_fixture_preflight.json").exists())
            for path in (job / "STATUS.json", audit / "orchestrator_outcome.json"):
                payload = json.loads(path.read_text())
                self.assertEqual(payload["overall_result"], "ESCALATION")
                self.assertEqual(payload["fixture_preflight"]["result"], "MISMATCH")
                self.assertEqual(payload["fixture_preflight"]["actual_target_rule_id"], "PDF/UA-1/7.21.4.1")
                self.assertFalse(payload["fixture_preflight"]["self_extension_would_run"])

    def test_known_repair_available_is_reported_without_mutating_rule_map(self):
        rule_map = {
            "rules": {
                "PDF/UA-1/7.21.4.1": {
                    "manual": False,
                    "resolvability": "effective",
                    "strategies": [{"script": "tools/repair/existing.py"}],
                }
            }
        }
        preflight = build_preflight(
            expected_target_rule_id="PDF/UA-1/7.21.4.1",
            residual_rules=["PDF/UA-1/7.21.4.1"],
            rule_map=rule_map,
        )
        self.assertTrue(preflight["residual_rules"][0]["known_repair_available"])
        self.assertTrue(preflight["policy"]["evidence_only"])
        self.assertFalse(preflight["policy"]["source_repair_creation_allowed"])
        self.assertFalse(preflight["policy"]["rule_map_mutation_allowed"])
        self.assertFalse(preflight["policy"]["adoption_allowed"])
        self.assertFalse(preflight["policy"]["final_pdf_update_from_failed_candidate_allowed"])


if __name__ == "__main__":
    unittest.main()
