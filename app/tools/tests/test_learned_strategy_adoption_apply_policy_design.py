import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "audit" / "learned_strategy_adoption_apply_policy_design.py"
spec = importlib.util.spec_from_file_location("learned_strategy_adoption_apply_policy_design", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ApplyPolicyDesignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo_root = self.root
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        (self.repo_root / "app" / "tools" / "audit").mkdir(parents=True)
        (self.repo_root / "app" / "tools" / "repair").mkdir(parents=True)
        (self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json").write_text("{}\n")
        (self.repo_root / "app" / "tools" / "repair" / "README.md").write_text("repair tools\n")
        self.job.mkdir(parents=True, exist_ok=True)
        (self.job / "STATUS.json").write_text('{"overall_result":"ESCALATION"}\n')
        (self.job / "deliverables").mkdir()
        (self.job / "deliverables" / "STATUS.json").write_text('{"overall_result":"ESCALATION"}\n')
        self.candidate_id = "smoke-changed-valid-candidate"
        self.rule_id = "PDF/UA-1/7.21.7"
        self.review_path = self.audit / "learned_strategy_adoption_dry_run_review.json"
        self.write_review(self.valid_review())

    def tearDown(self):
        self.tmp.cleanup()

    def valid_review(self):
        return {
            "schema_version": "learned-strategy-adoption-dry-run-review.v1",
            "mode": "adoption_dry_run_review_only",
            "result": "PASS",
            "review_decision": "dry_run_review_recorded",
            "review_scope": "dry_run_evidence_review_only_not_approval",
            "reviewer": "Patch 21A source reviewer",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "dry_run_plan": {
                "path": str(self.audit / "learned_strategy_adoption_dry_run_plan.json"),
                "sha256": "a" * 64,
            },
            "production_readiness_report": {"path": "readiness.json", "sha256": "b" * 64},
            "production_test_report": {"path": "production_test.json", "sha256": "c" * 64},
            "production_test_review_report": {"path": "review.json", "sha256": "d" * 64},
            "normal_final_pdf": {"path": "normal.pdf", "sha256": "e" * 64, "authoritative": True},
            "learned_trial_or_test_pdf": {"path": "learned.pdf", "sha256": "f" * 64},
            "source_dry_run_outcome": "adoption_dry_run_plan_recorded",
            "source_dry_run_blockers": [
                "blocked_pending_explicit_future_apply",
                "dry_run_only_no_apply_performed",
            ],
            "source_plan_safety_flags": {
                "adoption_apply_performed": False,
                "adoption_dry_run_only": True,
                "adoption_plan_created": True,
                "app_tools_repair_mutation_performed": False,
                "backup_created": False,
                "candidate_approved": False,
                "candidate_is_adoptable": False,
                "candidate_production_ready": False,
                "final_pdf_adoption_performed": False,
                "future_apply_not_implemented": True,
                "normal_final_pdf_remains_authoritative": True,
                "package_status_mutation_performed": False,
                "plan_is_non_executable_without_future_patch": True,
                "production_repair_replacement_performed": False,
                "rollback_execution_performed": False,
                "rule_map_mutation_performed": False,
                "verdict_softening_performed": False,
            },
            "safety_flags": {
                "adoption_apply_performed": False,
                "adoption_dry_run_review_only": True,
                "app_tools_repair_mutation_performed": False,
                "backup_created": False,
                "candidate_apply_ready": False,
                "candidate_approved": False,
                "candidate_is_adoptable": False,
                "candidate_production_ready": False,
                "dry_run_plan_hash_recorded": True,
                "dry_run_plan_reviewed": True,
                "final_pdf_adoption_performed": False,
                "future_apply_not_implemented": True,
                "normal_final_pdf_remains_authoritative": True,
                "package_status_mutation_performed": False,
                "production_repair_replacement_performed": False,
                "rollback_execution_performed": False,
                "rule_map_mutation_performed": False,
                "verdict_softening_performed": False,
            },
        }

    def write_review(self, data):
        self.review_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def run_build(self, reviewer="Patch 21A test", candidate_id=None, rule_id=None, review_path=None):
        return mod.build_artifact(
            job_dir=self.job,
            repo_root=self.repo_root,
            review_path=review_path or self.review_path,
            reviewer=reviewer,
            candidate_id=self.candidate_id if candidate_id is None else candidate_id,
            rule_id=self.rule_id if rule_id is None else rule_id,
        )

    def run_main(self):
        code = mod.main([
            "--job-dir", str(self.job),
            "--dry-run-review", str(self.review_path),
            "--reviewer", "Patch 21A test",
            "--candidate-id", self.candidate_id,
            "--rule-id", self.rule_id,
            "--repo-root", str(self.repo_root),
        ])
        self.assertEqual(code, 0)
        return json.loads((self.audit / "learned_strategy_adoption_apply_policy_design.json").read_text())

    def protected_hashes(self):
        paths = [
            self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json",
            self.repo_root / "app" / "tools" / "repair" / "README.md",
            self.job / "STATUS.json",
            self.job / "deliverables" / "STATUS.json",
        ]
        return {str(p): mod.sha256_file(p) for p in paths}

    def test_missing_dry_run_review_blocks_apply_policy_design(self):
        artifact = self.run_build(review_path=self.audit / "missing.json")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("missing_dry_run_review", artifact["blockers"])

    def test_dry_run_review_that_is_not_review_only_blocks_apply_policy_design(self):
        data = self.valid_review()
        data["mode"] = "something_else"
        data["safety_flags"]["adoption_dry_run_review_only"] = False
        self.write_review(data)
        artifact = self.run_build()
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("dry_run_review_not_review_only", artifact["blockers"])

    def test_missing_reviewer_blocks_apply_policy_design(self):
        artifact = self.run_build(reviewer="")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("missing_reviewer", artifact["blockers"])

    def test_missing_candidate_id_blocks_apply_policy_design(self):
        artifact = self.run_build(candidate_id="")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("missing_candidate_id", artifact["blockers"])

    def test_missing_rule_id_blocks_apply_policy_design(self):
        artifact = self.run_build(rule_id="")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("missing_rule_id", artifact["blockers"])

    def test_mismatched_candidate_id_blocks_apply_policy_design(self):
        artifact = self.run_build(candidate_id="other-candidate")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("candidate_id_mismatch", artifact["blockers"])

    def test_mismatched_rule_id_blocks_apply_policy_design(self):
        artifact = self.run_build(rule_id="other-rule")
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("rule_id_mismatch", artifact["blockers"])

    def test_missing_required_artifact_hashes_records_incomplete_or_blocks(self):
        data = self.valid_review()
        del data["production_test_report"]["sha256"]
        self.write_review(data)
        artifact = self.run_build()
        self.assertEqual(artifact["result"], "INCOMPLETE")
        self.assertIn("missing_required_hash:production_test_report_sha256", artifact["incomplete_reasons"])

    def test_forbidden_terminal_states_are_rejected(self):
        data = self.valid_review()
        data["review_decision"] = "approved"
        self.write_review(data)
        artifact = self.run_build()
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertTrue(any(item.startswith("forbidden_terminal_state_detected") for item in artifact["blockers"]))

    def test_policy_text_mentions_of_forbidden_states_do_not_block_design(self):
        data = self.valid_review()
        data["forbidden_terminal_states"] = [
            "approved",
            "adoptable",
            "production_ready",
            "ready_for_adoption",
            "adoption_unblocked",
            "apply_ready",
            "approved_for_apply",
            "frozen_for_apply",
        ]
        data["future_discussion_only"] = {
            "notes": [
                "future apply must not mark candidate approved",
                "future discussion must not make candidate adoptable",
                "future freeze is evidence-only and not frozen_for_apply",
            ]
        }
        self.write_review(data)
        artifact = self.run_build()
        blockers = artifact.get("blockers", [])
        self.assertFalse(
            any(str(blocker).startswith("forbidden_terminal_state_detected") for blocker in blockers),
            blockers,
        )

    def test_valid_dry_run_review_creates_apply_policy_design_artifact(self):
        artifact = self.run_main()
        self.assertEqual(artifact["result"], "PASS")
        self.assertEqual(artifact["apply_policy_design_outcome"], "apply_policy_design_recorded")
        self.assertTrue((self.audit / "learned_strategy_adoption_apply_policy_design.json").exists())

    def test_artifact_includes_all_no_apply_no_adoption_no_mutation_flags(self):
        artifact = self.run_main()
        flags = artifact["safety_flags"]
        for key, expected in mod.MANDATORY_SAFETY_FLAGS.items():
            self.assertIn(key, flags)
            self.assertEqual(flags[key], expected)

    def test_artifact_does_not_create_apply_plan(self):
        artifact = self.run_main()
        self.assertIsNone(artifact["apply_plan"])
        self.assertFalse(artifact["apply_plan_created"])
        self.assertFalse(artifact["safety_flags"]["apply_plan_created"])

    def test_artifact_does_not_mark_candidate_approved(self):
        artifact = self.run_main()
        self.assertFalse(artifact["candidate_approved"])
        self.assertFalse(artifact["safety_flags"]["candidate_approved"])

    def test_artifact_does_not_mark_candidate_adoptable(self):
        artifact = self.run_main()
        self.assertFalse(artifact["candidate_is_adoptable"])
        self.assertFalse(artifact["safety_flags"]["candidate_is_adoptable"])

    def test_artifact_does_not_mark_candidate_production_ready(self):
        artifact = self.run_main()
        self.assertFalse(artifact["candidate_production_ready"])
        self.assertFalse(artifact["safety_flags"]["candidate_production_ready"])

    def test_artifact_does_not_mark_candidate_apply_ready(self):
        artifact = self.run_main()
        self.assertFalse(artifact["candidate_apply_ready"])
        self.assertFalse(artifact["safety_flags"]["candidate_apply_ready"])
        self.assertFalse(artifact["apply_ready"])

    def test_artifact_does_not_create_backups(self):
        artifact = self.run_main()
        self.assertFalse(artifact["backup_created"])
        self.assertFalse(artifact["safety_flags"]["backup_created"])
        self.assertFalse(any("backup_manifest" in str(p) for p in self.audit.rglob("*")))

    def test_artifact_does_not_execute_rollback(self):
        artifact = self.run_main()
        self.assertFalse(artifact["rollback_execution_performed"])
        self.assertFalse(artifact["safety_flags"]["rollback_execution_performed"])
        self.assertFalse(artifact["rollback_ready"])

    def test_artifact_does_not_mutate_authoritative_status_json(self):
        before = self.protected_hashes()
        artifact = self.run_main()
        after = self.protected_hashes()
        self.assertEqual(before[str(self.job / "STATUS.json")], after[str(self.job / "STATUS.json")])
        self.assertFalse(artifact["package_status_mutation_performed"])

    def test_artifact_does_not_mutate_package_deliverables(self):
        before = self.protected_hashes()
        artifact = self.run_main()
        after = self.protected_hashes()
        path = str(self.job / "deliverables" / "STATUS.json")
        self.assertEqual(before[path], after[path])
        self.assertFalse(artifact["package_status_mutation_performed"])

    def test_artifact_does_not_mutate_app_tools_repair(self):
        before = self.protected_hashes()
        artifact = self.run_main()
        after = self.protected_hashes()
        path = str(self.repo_root / "app" / "tools" / "repair" / "README.md")
        self.assertEqual(before[path], after[path])
        self.assertFalse(artifact["app_tools_repair_mutation_performed"])
        self.assertEqual(artifact["protected_mutation_count"], 0)

    def test_artifact_does_not_mutate_rule_repair_map(self):
        before = self.protected_hashes()
        artifact = self.run_main()
        after = self.protected_hashes()
        path = str(self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json")
        self.assertEqual(before[path], after[path])
        self.assertFalse(artifact["rule_map_mutation_performed"])
        self.assertEqual(artifact["protected_mutation_count"], 0)

    def test_artifact_defines_future_backup_requirements_as_policy_text_only(self):
        artifact = self.run_main()
        self.assertTrue(artifact["future_backup_requirements_policy_text_only"])
        reqs = artifact["future_apply_requirements"]["future_backup_manifest_requirements_policy_text_only"]
        self.assertGreaterEqual(len(reqs), 1)
        self.assertFalse(artifact["backup_created"])

    def test_artifact_defines_future_rollback_requirements_as_policy_text_only(self):
        artifact = self.run_main()
        self.assertTrue(artifact["future_rollback_requirements_policy_text_only"])
        reqs = artifact["future_apply_requirements"]["future_rollback_manifest_requirements_policy_text_only"]
        self.assertGreaterEqual(len(reqs), 1)
        self.assertFalse(artifact["rollback_execution_performed"])

    def test_artifact_defines_future_post_apply_validation_requirements_as_policy_text_only(self):
        artifact = self.run_main()
        self.assertTrue(artifact["future_post_apply_validation_requirements_policy_text_only"])
        reqs = artifact["future_apply_requirements"]["future_post_apply_validation_requirements_policy_text_only"]
        self.assertGreaterEqual(len(reqs), 1)
        self.assertTrue(artifact["future_apply_not_implemented"])

    def test_artifact_defines_future_post_rollback_validation_requirements_as_policy_text_only(self):
        artifact = self.run_main()
        self.assertTrue(artifact["future_post_rollback_validation_requirements_policy_text_only"])
        reqs = artifact["future_apply_requirements"]["future_post_rollback_validation_requirements_policy_text_only"]
        self.assertGreaterEqual(len(reqs), 1)
        self.assertTrue(artifact["future_rollback_not_implemented"])


if __name__ == "__main__":
    unittest.main()
