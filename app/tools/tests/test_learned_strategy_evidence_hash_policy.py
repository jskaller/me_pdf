import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.tools.audit import learned_strategy_evidence_hashes as evidence
from app.tools.audit import learned_strategy_adoption_apply_dry_run as apply_dry_run
from app.tools.audit import learned_strategy_adoption_apply_dry_run_review as apply_review


class EvidenceHashPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.repair = self.job / "repair"
        self.audit.mkdir(parents=True)
        self.repair.mkdir(parents=True)
        (self.root / "app" / "tools" / "audit").mkdir(parents=True)
        (self.root / "app" / "tools" / "repair").mkdir(parents=True)
        (self.root / "app" / "tools" / "audit" / "rule_repair_map.json").write_text("{}\n")
        (self.root / "app" / "tools" / "repair" / "README.md").write_text("repair readme\n")
        self.candidate_id = "candidate-1"
        self.rule_id = "PDF/UA-1/7.21.7"

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def write_file(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def create_complete_evidence_files(self):
        normal_pdf = self.write_file(self.repair / "normal.pdf", "normal pdf")
        learned_pdf = self.write_file(self.repair / "learned.pdf", "learned pdf")
        self.write_json(self.job / "STATUS.json", {"summary": {"final_pdf": str(normal_pdf)}})
        self.write_json(self.audit / "learned_strategy_production_test.json", {"result": "PASS", "learned_test_pdf": str(learned_pdf)})
        self.write_json(self.audit / "learned_strategy_production_readiness.json", {"result": "PASS"})
        self.write_json(self.audit / "learned_strategy_production_test_review.json", {"result": "PASS"})
        self.write_json(self.audit / "learned_strategy_adoption_policy_design.json", {"result": "PASS"})
        self.write_json(self.audit / "learned_strategy_adoption_dry_run_plan.json", {"result": "PASS"})
        self.write_json(self.audit / "learned_strategy_adoption_dry_run_review.json", {"result": "PASS"})
        self.write_json(self.audit / "learned_strategy_adoption_apply_policy_design.json", self.valid_apply_policy_design())
        return normal_pdf, learned_pdf

    def valid_apply_policy_design(self):
        return {
            "schema_version": "learned-strategy-adoption-apply-policy-design.v1",
            "mode": "adoption_apply_policy_design_only",
            "result": "INCOMPLETE",
            "apply_policy_design_outcome": "apply_policy_design_incomplete",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "safety_flags": {
                "adoption_apply_policy_design_only": True,
                "apply_policy_design_recorded": True,
                "apply_plan_created": False,
                "adoption_apply_performed": False,
                "backup_created": False,
                "rollback_execution_performed": False,
                "candidate_is_adoptable": False,
                "candidate_approved": False,
                "candidate_production_ready": False,
                "candidate_apply_ready": False,
                "final_pdf_adoption_performed": False,
                "production_repair_replacement_performed": False,
                "verdict_softening_performed": False,
                "package_status_mutation_performed": False,
                "normal_final_pdf_remains_authoritative": True,
                "rule_map_mutation_performed": False,
                "app_tools_repair_mutation_performed": False,
                "future_apply_not_implemented": True,
                "future_rollback_not_implemented": True,
            },
            "future_apply_requirements": {
                "source_hashes_recorded_for_policy_discussion": {
                    "dry_run_review_artifact_sha256": None,
                    "dry_run_plan_artifact_sha256": None,
                    "production_readiness_report_sha256": None,
                    "production_test_report_sha256": None,
                    "production_test_review_report_sha256": None,
                    "normal_final_pdf_sha256": None,
                    "learned_trial_or_test_pdf_sha256": None,
                }
            },
        }

    def build(self):
        return evidence.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )

    def test_missing_normal_final_pdf_records_incomplete_evidence(self):
        artifact = self.build()
        self.assertEqual(artifact["result"], "INCOMPLETE")
        entry = artifact["evidence_hashes"]["normal_final_pdf_sha256"]
        self.assertFalse(entry["exists"])
        self.assertIsNone(entry["sha256"])
        self.assertIsNotNone(entry["missing_reason"])

    def test_missing_learned_trial_test_pdf_records_incomplete_evidence(self):
        normal = self.write_file(self.repair / "normal.pdf", "normal")
        self.write_json(self.job / "STATUS.json", {"final_pdf": str(normal)})
        artifact = self.build()
        entry = artifact["evidence_hashes"]["learned_trial_or_test_pdf_sha256"]
        self.assertFalse(entry["exists"])
        self.assertIn("learned_trial_or_test_pdf_sha256", artifact["missing_required_evidence_hashes"])

    def test_missing_production_readiness_report_records_incomplete_evidence(self):
        artifact = self.build()
        self.assertFalse(artifact["evidence_hashes"]["production_readiness_report_sha256"]["exists"])

    def test_missing_production_test_report_records_incomplete_evidence(self):
        artifact = self.build()
        self.assertFalse(artifact["evidence_hashes"]["production_test_report_sha256"]["exists"])

    def test_missing_production_test_review_report_records_incomplete_evidence(self):
        artifact = self.build()
        self.assertFalse(artifact["evidence_hashes"]["production_test_review_report_sha256"]["exists"])

    def test_existing_artifacts_get_sha256_hashes_recorded(self):
        normal, learned = self.create_complete_evidence_files()
        artifact = self.build()
        self.assertEqual(artifact["result"], "PASS")
        self.assertEqual(artifact["evidence_hashes"]["normal_final_pdf_sha256"]["sha256"], self.sha(normal))
        self.assertEqual(artifact["evidence_hashes"]["learned_trial_or_test_pdf_sha256"]["sha256"], self.sha(learned))
        self.assertEqual(artifact["evidence_hashes_outcome"], "evidence_hashes_recorded")

    def test_hash_artifact_records_path_existence_hash_and_missing_reason(self):
        artifact = self.build()
        for key, entry in artifact["evidence_hashes"].items():
            self.assertEqual(entry["key"], key)
            self.assertIn("path", entry)
            self.assertIn("exists", entry)
            self.assertIn("sha256", entry)
            self.assertIn("missing_reason", entry)
            self.assertIn("source_artifact", entry)
            self.assertIn("verified_at", entry)

    def test_hash_artifact_includes_all_no_apply_flags(self):
        artifact = self.build()
        flags = artifact["safety_flags"]
        for key, value in evidence.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(flags[key], value)
            self.assertEqual(artifact[key], value)

    def test_evidence_hash_completion_does_not_mark_candidate_approved(self):
        self.assertFalse(self.build()["candidate_approved"])

    def test_evidence_hash_completion_does_not_mark_candidate_adoptable(self):
        self.assertFalse(self.build()["candidate_is_adoptable"])

    def test_evidence_hash_completion_does_not_mark_candidate_production_ready(self):
        self.assertFalse(self.build()["candidate_production_ready"])

    def test_evidence_hash_completion_does_not_mark_candidate_apply_ready(self):
        self.assertFalse(self.build()["candidate_apply_ready"])

    def test_evidence_hash_completion_does_not_create_backups(self):
        self.assertFalse(self.build()["backup_created"])

    def test_evidence_hash_completion_does_not_execute_rollback(self):
        self.assertFalse(self.build()["rollback_execution_performed"])

    def test_evidence_hash_completion_does_not_mutate_authoritative_status_json(self):
        self.write_json(self.job / "STATUS.json", {"final_pdf": "missing.pdf"})
        before = (self.job / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "STATUS.json").read_bytes(), before)

    def test_evidence_hash_completion_does_not_mutate_package_deliverables(self):
        pkg = self.job / "package" / "STATUS.json"
        self.write_json(pkg, {"result": "ESCALATION"})
        before = pkg.read_bytes()
        self.build()
        self.assertEqual(pkg.read_bytes(), before)

    def test_evidence_hash_completion_does_not_mutate_app_tools_repair(self):
        target = self.root / "app" / "tools" / "repair" / "README.md"
        before = target.read_bytes()
        self.build()
        self.assertEqual(target.read_bytes(), before)

    def test_evidence_hash_completion_does_not_mutate_rule_repair_map(self):
        target = self.root / "app" / "tools" / "audit" / "rule_repair_map.json"
        before = target.read_bytes()
        self.build()
        self.assertEqual(target.read_bytes(), before)

    def test_apply_dry_run_consumes_normalized_hashes_when_present(self):
        self.create_complete_evidence_files()
        evidence_artifact = self.build()
        evidence.write_json(evidence.artifact_path(self.job), evidence_artifact)
        dry_run = apply_dry_run.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            design_path=self.audit / "learned_strategy_adoption_apply_policy_design.json",
            operator="tester",
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )
        self.assertEqual(dry_run["result"], "PASS")
        self.assertEqual(dry_run["apply_dry_run_simulation_outcome"], "apply_dry_run_simulation_recorded")
        self.assertNotIn("missing_required_artifact_hash:normal_final_pdf_sha256", dry_run["incomplete_reasons"])

    def test_apply_dry_run_remains_non_adoptive_even_when_hashes_complete(self):
        self.create_complete_evidence_files()
        evidence.write_json(evidence.artifact_path(self.job), self.build())
        dry_run = apply_dry_run.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            design_path=self.audit / "learned_strategy_adoption_apply_policy_design.json",
            operator="tester",
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )
        self.assertFalse(dry_run["candidate_approved"])
        self.assertFalse(dry_run["candidate_is_adoptable"])
        self.assertFalse(dry_run["candidate_production_ready"])
        self.assertFalse(dry_run["candidate_apply_ready"])
        self.assertTrue(dry_run["future_apply_not_implemented"])
        self.assertTrue(dry_run["future_rollback_not_implemented"])

    def test_apply_dry_run_review_remains_non_adoptive_even_when_hashes_complete(self):
        self.create_complete_evidence_files()
        evidence.write_json(evidence.artifact_path(self.job), self.build())
        dry_run = apply_dry_run.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            design_path=self.audit / "learned_strategy_adoption_apply_policy_design.json",
            operator="tester",
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )
        dry_run_path = self.audit / "learned_strategy_adoption_apply_dry_run.json"
        apply_dry_run.write_json(dry_run_path, dry_run)
        review = apply_review.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            apply_dry_run_path=dry_run_path,
            reviewer="reviewer",
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
            review_notes=["reviewed"],
            known_risks=["future apply remains unimplemented"],
            review_decision="apply_dry_run_review_recorded",
            expected_apply_dry_run_sha256=apply_review.sha256_file(dry_run_path),
        )
        self.assertEqual(review["result"], "PASS")
        self.assertFalse(review["candidate_approved"])
        self.assertFalse(review["candidate_is_adoptable"])
        self.assertFalse(review["candidate_production_ready"])
        self.assertFalse(review["candidate_apply_ready"])

    def test_forbidden_terminal_states_are_rejected(self):
        artifact = evidence.build_artifact(
            job_dir=self.job,
            repo_root=self.root,
            candidate_id="approved",
            rule_id=self.rule_id,
        )
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertTrue(any("forbidden_terminal_state_detected" in b for b in artifact["blockers"]))


if __name__ == "__main__":
    unittest.main()
