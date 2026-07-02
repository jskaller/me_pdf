import json
import tempfile
import unittest
from pathlib import Path

from tools.agent.create_candidate_repair import (
    TARGET_RULE,
    build_strategy_request,
    is_distinct_fixture,
    run_candidate_workbench,
    run_reuse_pipeline,
    synthetic_failure_count,
    target_selection_preflight,
)
from tools.tests.generate_h12r_fixtures import generate_fixture_pair


class H12RSelfExtendingCandidateWorkbenchPolicyTests(unittest.TestCase):
    def test_h12r_candidate_generation_then_reuse_without_second_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rule_map = root / "rule_repair_map.json"
            rule_map.write_text(json.dumps({
                "rules": {
                    TARGET_RULE: {
                        "confidence": "HERMES_REQUIRED",
                        "resolvability": "repairable_unbuilt",
                        "strategies": [],
                    }
                }
            }))
            preflight = target_selection_preflight(rule_map)
            self.assertEqual(preflight["selected_target_rule"], TARGET_RULE)
            self.assertFalse(preflight["existing_active_strategy"])
            self.assertFalse(preflight["existing_guarded_strategy_sufficient"])
            self.assertTrue(preflight["remediable_in_principle"])

            fixtures = generate_fixture_pair(root / "fixtures")
            fixture_a = Path(fixtures["fixture_a"])
            fixture_b = Path(fixtures["fixture_b"])
            self.assertEqual(synthetic_failure_count(fixture_a), 1)
            self.assertEqual(synthetic_failure_count(fixture_b), 1)
            self.assertTrue(is_distinct_fixture(fixture_a, fixture_b))

            workspace = root / "workspace"
            request = build_strategy_request("H12R-SYNTHETIC-A", fixture_a)
            strategy_request_path = workspace / "requests" / "h12r_a_strategy_request.json"
            strategy_request_path.parent.mkdir(parents=True)
            strategy_request_path.write_text(json.dumps(request, indent=2, sort_keys=True))

            candidate_result = run_candidate_workbench(
                strategy_request_path=strategy_request_path,
                input_pdf=fixture_a,
                workspace=workspace,
                ticket="H12R-SYNTHETIC-A",
                target_rule=TARGET_RULE,
            )
            self.assertEqual(candidate_result["decision"], "CANDIDATE_VALIDATED")
            self.assertTrue(candidate_result["candidate_generated_by_workbench"])
            self.assertFalse(candidate_result["manual_target_repair_committed"])
            self.assertEqual(candidate_result["target_rule_before_count"], 1)
            self.assertEqual(candidate_result["target_rule_after_count"], 0)
            attempt_dir = Path(candidate_result["candidate_attempt_dir"])
            self.assertTrue(str(attempt_dir).endswith("workspace/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001"))
            for path in candidate_result["candidate_files"]:
                self.assertIn("candidate_repairs", path)
                self.assertNotIn("app/tools/repair", path)
            self.assertTrue(Path(candidate_result["adoption_proposal_path"]).exists())
            self.assertTrue((attempt_dir / "candidate_result.json").exists())

            candidate_dirs_before = sorted((workspace / "candidate_repairs").glob("**/attempt-*"))
            reuse_result = run_reuse_pipeline(
                input_pdf=fixture_b,
                workspace=workspace,
                ticket="H12R-SYNTHETIC-B",
                adoption_proposal_path=Path(candidate_result["adoption_proposal_path"]),
                target_rule=TARGET_RULE,
            )
            candidate_dirs_after = sorted((workspace / "candidate_repairs").glob("**/attempt-*"))
            self.assertEqual(candidate_dirs_before, candidate_dirs_after)
            self.assertEqual(reuse_result["decision"], "REUSE_VALIDATED")
            self.assertTrue(reuse_result["reused_strategy_from_fixture_a"])
            self.assertFalse(reuse_result["new_candidate_generation_attempted"])
            self.assertTrue(reuse_result["normal_pipeline_used"])
            self.assertEqual(reuse_result["status_json_result"], "PASS")
            self.assertEqual(reuse_result["orchestrator_outcome_result"], "PASS")
            self.assertEqual(reuse_result["target_rule_before_count"], 1)
            self.assertEqual(reuse_result["target_rule_after_count"], 0)

    def test_status_cannot_claim_pass_when_unvalidated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixtures = generate_fixture_pair(root / "fixtures")
            fixture_a = Path(fixtures["fixture_a"])
            request = build_strategy_request("H12R-SYNTHETIC-A", fixture_a)
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request))
            result = run_candidate_workbench(request_path, fixture_a, root / "workspace", "H12R-SYNTHETIC-A")
            candidate_result = json.loads(Path(result["candidate_attempt_dir"]).joinpath("candidate_result.json").read_text())
            self.assertIn(candidate_result["decision"], {"CANDIDATE_VALIDATED", "CANDIDATE_REJECTED"})
            self.assertNotEqual(candidate_result.get("status_json_result"), "PASS_UNVALIDATED")


if __name__ == "__main__":
    unittest.main()
