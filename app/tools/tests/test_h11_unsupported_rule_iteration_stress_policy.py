#!/usr/bin/env python3
"""H11 tests for unsupported-rule iteration stress evidence."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "app"))

from tools.audit.unsupported_rule_iteration_stress import build_report  # noqa: E402


class H11UnsupportedRuleIterationStressPolicyTests(unittest.TestCase):
    def make_job(self, root: Path) -> Path:
        job = root / "workspace" / "jobs" / "JOB1"
        audit = job / "audit"
        audit.mkdir(parents=True)
        return job

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def write_remediate_stub(self, app_dir: Path) -> None:
        path = app_dir / "tools" / "orchestrate" / "remediate.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PER_RULE_CAP = 3\nJOB_WARN_AT = 4\nJOB_HARD_CAP = 5\n")

    def test_actionable_unknown_rule_strategy_request_records_caps_and_stop_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            self.write_remediate_stub(app_dir)
            job = self.make_job(root)
            audit = job / "audit"

            self.write_json(audit / "repair_plan.json", {
                "hermes_required": [
                    {
                        "rule_id": "PDF/UA-1/7.21.4.1",
                        "description": "empty / not yet mapped",
                        "failures": 2,
                        "reason": "unknown_rule",
                        "strategies_attempted": [],
                    }
                ],
                "unknown_rules": [
                    {
                        "rule_id": "PDF/UA-1/7.21.4.1",
                        "description": "empty / not yet mapped",
                        "failures": 2,
                        "reason": "unknown_rule",
                    }
                ],
            })
            self.write_json(audit / "hermes_strategy_request.json", {
                "request_type": "pdfua_residual_strategy_design",
                "residual_failures": [
                    {
                        "rule_id": "PDF/UA-1/7.21.4.1",
                        "description": "empty / not yet mapped",
                        "failures": 2,
                    }
                ],
            })
            self.write_json(audit / "strategy_gap.json", {"result": "HERMES_REQUIRED"})
            self.write_json(audit / "orchestrator_outcome.json", {"overall_result": "ESCALATION"})
            self.write_json(job / "STATUS.json", {"overall_result": "ESCALATION"})

            report = build_report(job, app_dir=app_dir)

        self.assertEqual(report["result"], "UNSUPPORTED_RULE_PIPELINE_ACTIONABLE")
        self.assertEqual(report["configured_caps"]["per_rule_cap"], 3)
        rule = report["rules"][0]
        self.assertEqual(rule["rule_id"], "PDF/UA-1/7.21.4.1")
        self.assertEqual(rule["configured_max_attempts"], 3)
        self.assertEqual(rule["attempts_used"], 0)
        self.assertEqual(rule["final_stop_reason"], "no_working_script_available")
        self.assertTrue(rule["strategy_request_created"])
        self.assertEqual(rule["terminal_state"], "UNSUPPORTED_REVIEW_REQUIRED")
        self.assertFalse(report["safe_to_claim_pass"])

    def test_exhausted_attempts_and_repeated_attempts_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            self.write_remediate_stub(app_dir)
            job = self.make_job(root)
            audit = job / "audit"

            rule_id = "PDF/UA-1/7.21.7"
            self.write_json(audit / "repair_plan_post.json", {
                "hermes_required_effective": [
                    {
                        "rule_id": rule_id,
                        "description": "Font dictionary missing ToUnicode map",
                        "failures": 1,
                        "reason": "all_strategies_exhausted",
                    }
                ]
            })
            repeated_attempt = {
                "strategy": "missing_tounicode_trial",
                "repair_script": "tools/repair/fix_missing_tounicode.py",
                "input_pdf": "/tmp/in.pdf",
                "output_pdf": "/tmp/out.pdf",
                "result": "FAILED",
                "validation_artifacts": {"failures": "/tmp/failures.json"},
            }
            self.write_json(audit / "strategy_attempts.json", {
                "attempts": {
                    rule_id: [
                        {**repeated_attempt, "attempt": 1},
                        {**repeated_attempt, "attempt": 2},
                        {**repeated_attempt, "attempt": 3},
                    ]
                },
                "total_iterations": 3,
            })
            self.write_json(audit / "hermes_strategy_request.json", {
                "request_type": "pdfua_residual_strategy_design",
                "residual_failures": [{"rule_id": rule_id, "failures": 1}],
            })
            self.write_json(audit / "strategy_gap.json", {"result": "HERMES_REQUIRED"})

            report = build_report(job, app_dir=app_dir)

        self.assertEqual(report["result"], "UNSUPPORTED_RULE_PIPELINE_ACTIONABLE")
        rule = report["rules"][0]
        self.assertEqual(rule["attempts_used"], 3)
        self.assertEqual(rule["final_stop_reason"], "per_rule_attempt_cap_exhausted")
        self.assertTrue(rule["repeated_identical_attempts_detected"])
        self.assertTrue(rule["attempts"][1]["repeat_of_prior_attempt"])
        self.assertEqual(rule["terminal_state"], "ATTEMPTS_EXHAUSTED_REVIEW_REQUIRED")

    def test_missing_strategy_request_is_not_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            self.write_remediate_stub(app_dir)
            job = self.make_job(root)
            audit = job / "audit"

            self.write_json(audit / "repair_plan.json", {
                "hermes_required": [
                    {
                        "rule_id": "PDF/UA-1/7.21.7",
                        "description": "Font dictionary missing ToUnicode map",
                        "failures": 1,
                        "reason": "all_strategies_exhausted",
                    }
                ]
            })

            report = build_report(job, app_dir=app_dir)

        self.assertEqual(report["result"], "UNSUPPORTED_RULE_PIPELINE_NOT_ACTIONABLE")
        self.assertEqual(report["rules"][0]["terminal_state"], "UNSUPPORTED_RULE_NOT_ACTIONABLE")
        self.assertFalse(report["rules"][0]["strategy_request_created"])


if __name__ == "__main__":
    unittest.main()
