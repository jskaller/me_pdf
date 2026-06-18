import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "audit" / "learned_strategy_post_apply_validation.py"
spec = importlib.util.spec_from_file_location("learned_strategy_post_apply_validation", MODULE_PATH)
post_apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(post_apply)


class PostApplyValidationPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "job"
        (self.repo / "app" / "tools" / "audit").mkdir(parents=True)
        (self.repo / "app" / "tools" / "repair").mkdir(parents=True)
        (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").write_text("{}\n", encoding="utf-8")
        (self.repo / "app" / "tools" / "repair" / "README.md").write_text("repair\n", encoding="utf-8")
        self.apply_dir = self.job / "audit" / "learned_strategy_reviewed_apply"
        (self.apply_dir / "backups").mkdir(parents=True)
        self.qpdf_ok = self.root / "qpdf_ok.sh"
        self.qpdf_ok.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.qpdf_ok.chmod(0o755)
        self.qpdf_fail = self.root / "qpdf_fail.sh"
        self.qpdf_fail.write_text("#!/bin/sh\necho bad >&2\nexit 7\n", encoding="utf-8")
        self.qpdf_fail.chmod(0o755)
        self.operator = "operator-a"
        self.reviewer = "reviewer-a"
        self.approver = "approver-a"
        self.candidate = "PDF/UA-1/7.21.7:candidate-a"
        self.rule = "PDF/UA-1/7.21.7"
        self._write_valid_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_json(self, name, data):
        path = self.apply_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _write_valid_fixture(self):
        self.adopted_pdf = self.apply_dir / "adopted_final.pdf"
        self.backup_pdf = self.apply_dir / "backups" / "normal_final_backup.pdf"
        self.adopted_pdf.write_bytes(b"%PDF-1.7\nlearned\n%%EOF\n")
        self.backup_pdf.write_bytes(b"%PDF-1.7\nnormal\n%%EOF\n")
        self.expected_adopted_hash = post_apply.sha256_file(self.adopted_pdf)
        self.expected_backup_hash = post_apply.sha256_file(self.backup_pdf)
        safety = {
            "reviewer_identity_recorded": True,
            "approver_identity_recorded": True,
            "separate_reviewer_and_approver": True,
            "candidate_is_adoptable": False,
            "candidate_approved": False,
            "candidate_production_ready": False,
            "candidate_apply_ready": False,
            "default_learned_execution_enabled": False,
            "rule_map_mutation_performed": False,
            "app_tools_repair_mutation_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
            "package_status_mutation_performed": False,
        }
        self.apply_manifest = {
            "schema_version": "learned-strategy-reviewed-apply.v1",
            "mode": "job_scoped_reviewed_apply",
            "operator": self.operator,
            "reviewer": self.reviewer,
            "approver": self.approver,
            "candidate_id": self.candidate,
            "rule_id": self.rule,
            "result": "PASS",
            "reviewed_apply_outcome": "reviewed_apply_performed",
            "adopted_output_sha256": self.expected_adopted_hash,
            "safety_flags": safety,
        }
        self.apply_audit = {
            "operator": self.operator,
            "reviewer": self.reviewer,
            "approver": self.approver,
            "candidate_id": self.candidate,
            "rule_id": self.rule,
            "package_status_mutation_performed": False,
            "locked_hashes": {
                "expected_learned_trial_or_test_pdf_sha256": self.expected_adopted_hash,
                "expected_normal_final_pdf_sha256": self.expected_backup_hash,
            },
        }
        self.backup_manifest = {
            "entries": [{"backup_path": str(self.backup_pdf), "backup_sha256": self.expected_backup_hash}],
            "candidate_id": self.candidate,
            "rule_id": self.rule,
        }
        self.rollback_manifest = {
            "entries": [{"sandbox_backup_path": str(self.backup_pdf), "expected_restored_sha256": self.expected_backup_hash}],
            "rollback_execution_against_authoritative_files": False,
            "candidate_id": self.candidate,
            "rule_id": self.rule,
        }
        self.source_validation = {
            "result": "PASS",
            "post_apply_validation_passed": True,
            "validation_details": {"valid": True},
            "candidate_id": self.candidate,
            "rule_id": self.rule,
        }
        self._write_json("apply_manifest.json", self.apply_manifest)
        self._write_json("apply_audit.json", self.apply_audit)
        self._write_json("backup_manifest.json", self.backup_manifest)
        self._write_json("rollback_manifest.json", self.rollback_manifest)
        self._write_json("post_apply_validation.json", self.source_validation)
        self.expected_manifest_hash = post_apply.sha256_file(self.apply_dir / "apply_manifest.json")
        self.expected_validation_hash = post_apply.sha256_file(self.apply_dir / "post_apply_validation.json")

    def _validate(self, **overrides):
        kwargs = {
            "job_dir": self.job,
            "repo_root": self.repo,
            "operator": self.operator,
            "reviewer": self.reviewer,
            "approver": self.approver,
            "candidate_id": self.candidate,
            "rule_id": self.rule,
            "expected_adopted_output_hash": self.expected_adopted_hash,
            "expected_normal_backup_hash": self.expected_backup_hash,
            "expected_apply_manifest_hash": self.expected_manifest_hash,
            "expected_post_apply_validation_hash": self.expected_validation_hash,
            "qpdf_command": str(self.qpdf_ok),
        }
        kwargs.update(overrides)
        return post_apply.build_post_apply_report(**kwargs)

    def test_happy_path_records_required_safety_flags(self):
        report = self._validate()
        self.assertEqual(report["result"], "PASS")
        self.assertTrue(report["post_apply_validation_only"])
        self.assertTrue(report["reviewed_sidecar_adoption_validated"])
        self.assertFalse(report["package_integrated_adoption_enabled"])
        self.assertTrue(report["normal_pipeline_final_pdf_remains_authoritative"])

    def test_missing_reviewed_apply_manifest_blocks_validation(self):
        (self.apply_dir / "apply_manifest.json").unlink()
        report = self._validate(expected_apply_manifest_hash="missing")
        self.assertIn("missing_reviewed_apply_manifest", report["blockers"])

    def test_missing_apply_audit_blocks_validation(self):
        (self.apply_dir / "apply_audit.json").unlink()
        self.assertIn("missing_apply_audit", self._validate()["blockers"])

    def test_missing_backup_manifest_blocks_validation(self):
        (self.apply_dir / "backup_manifest.json").unlink()
        self.assertIn("missing_backup_manifest", self._validate()["blockers"])

    def test_missing_rollback_manifest_blocks_validation(self):
        (self.apply_dir / "rollback_manifest.json").unlink()
        self.assertIn("missing_rollback_manifest", self._validate()["blockers"])

    def test_missing_post_apply_validation_blocks_validation(self):
        (self.apply_dir / "post_apply_validation.json").unlink()
        report = self._validate(expected_post_apply_validation_hash="missing")
        self.assertIn("missing_post_apply_validation", report["blockers"])

    def test_missing_adopted_final_pdf_blocks_validation(self):
        self.adopted_pdf.unlink()
        self.assertIn("missing_adopted_final_pdf", self._validate()["blockers"])

    def test_missing_normal_backup_blocks_validation(self):
        self.backup_pdf.unlink()
        self.assertIn("missing_normal_backup", self._validate()["blockers"])

    def test_adopted_output_hash_mismatch_blocks_validation(self):
        report = self._validate(expected_adopted_output_hash="0" * 64)
        self.assertIn("adopted_output_hash_mismatch", report["blockers"])

    def test_backup_hash_mismatch_blocks_validation(self):
        report = self._validate(expected_normal_backup_hash="1" * 64)
        self.assertIn("normal_backup_hash_mismatch", report["blockers"])

    def test_missing_operator_blocks_validation(self):
        self.assertIn("missing_operator", self._validate(operator="")["blockers"])

    def test_missing_reviewer_blocks_validation(self):
        self.assertIn("missing_reviewer", self._validate(reviewer="")["blockers"])

    def test_missing_approver_blocks_validation(self):
        self.assertIn("missing_approver", self._validate(approver="")["blockers"])

    def test_reviewer_approver_mismatch_with_apply_artifact_blocks_validation(self):
        self.assertIn("apply_manifest_reviewer_mismatch", self._validate(reviewer="other-reviewer")["blockers"])

    def test_candidate_mismatch_blocks_validation(self):
        self.assertIn("apply_manifest_candidate_id_mismatch", self._validate(candidate_id="different")["blockers"])

    def test_rule_mismatch_blocks_validation(self):
        self.assertIn("apply_manifest_rule_id_mismatch", self._validate(rule_id="different-rule")["blockers"])

    def test_qpdf_validation_failure_fails_closed(self):
        report = self._validate(qpdf_command=str(self.qpdf_fail))
        self.assertEqual(report["result"], "FAILED_CLOSED")
        self.assertIn("qpdf_validation_failed", report["failed_closed_reasons"])

    def test_rollback_proof_runs_only_in_isolated_validation_directory(self):
        report = post_apply.build_rollback_proof_report(
            job_dir=self.job,
            repo_root=self.repo,
            operator=self.operator,
            reviewer=self.reviewer,
            approver=self.approver,
            candidate_id=self.candidate,
            rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash,
        )
        self.assertEqual(report["rollback_proof_scope"], "isolated_validation_directory_only")
        self.assertIn("rollback_proof_isolated", report["proof_dir"])

    def test_rollback_proof_restored_hash_equals_backup_hash(self):
        report = post_apply.build_rollback_proof_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash)
        self.assertTrue(report["rollback_restored_hash_matches_backup"])

    def test_rollback_proof_does_not_delete_real_adopted_final_pdf(self):
        post_apply.build_rollback_proof_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash)
        self.assertTrue(self.adopted_pdf.exists())

    def test_rollback_proof_does_not_overwrite_authoritative_normal_final_pdf(self):
        normal = self.job / "output" / "final.pdf"
        normal.parent.mkdir(parents=True)
        normal.write_bytes(b"normal authoritative")
        before = post_apply.sha256_file(normal)
        post_apply.build_rollback_proof_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash)
        self.assertEqual(post_apply.sha256_file(normal), before)

    def test_validation_does_not_mutate_rule_map(self):
        rule_map = self.repo / "app" / "tools" / "audit" / "rule_repair_map.json"
        before = post_apply.sha256_file(rule_map)
        self._validate()
        self.assertEqual(post_apply.sha256_file(rule_map), before)

    def test_validation_does_not_mutate_app_tools_repair(self):
        before = post_apply.snapshot_tree(self.repo / "app" / "tools" / "repair")
        self._validate()
        after = post_apply.snapshot_tree(self.repo / "app" / "tools" / "repair")
        self.assertEqual(after, before)

    def test_validation_does_not_mutate_package_status(self):
        status = self.job / "package" / "STATUS.json"
        status.parent.mkdir(parents=True)
        status.write_text('{"normal": true}\n', encoding="utf-8")
        before = post_apply.sha256_file(status)
        self._validate()
        self.assertEqual(post_apply.sha256_file(status), before)

    def test_validation_does_not_enable_default_learned_execution(self):
        self.assertFalse(self._validate()["default_learned_execution_enabled"])

    def test_validation_does_not_mark_candidate_globally_approved(self):
        self.assertFalse(self._validate()["global_candidate_approved"])

    def test_validation_does_not_mark_candidate_globally_production_ready(self):
        self.assertFalse(self._validate()["global_candidate_production_ready"])

    def test_validation_does_not_mark_global_apply_ready(self):
        self.assertFalse(self._validate()["global_apply_ready"])

    def test_sidecar_production_readiness_gate_can_be_recorded(self):
        validation = self._validate()
        rollback = post_apply.build_rollback_proof_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash)
        post_apply.write_selected_reports(self.job, [validation, rollback])
        gate = post_apply.build_readiness_gate_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule)
        self.assertEqual(gate["production_readiness_terminal_state"], "sidecar_reviewed_adoption_production_ready")

    def test_package_integrated_adoption_readiness_is_not_emitted(self):
        validation = self._validate()
        rollback = post_apply.build_rollback_proof_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule,
            expected_normal_backup_hash=self.expected_backup_hash)
        post_apply.write_selected_reports(self.job, [validation, rollback])
        gate = post_apply.build_readiness_gate_report(
            job_dir=self.job, repo_root=self.repo, operator=self.operator, reviewer=self.reviewer,
            approver=self.approver, candidate_id=self.candidate, rule_id=self.rule)
        self.assertFalse(gate["package_integrated_adoption_ready"])
        self.assertNotEqual(gate["production_readiness_terminal_state"], "package_integrated_adoption_ready")

    def test_forbidden_terminal_global_states_are_rejected(self):
        self.apply_manifest["readiness_state"] = "global_learned_execution_ready"
        self._write_json("apply_manifest.json", self.apply_manifest)
        self.expected_manifest_hash = post_apply.sha256_file(self.apply_dir / "apply_manifest.json")
        report = self._validate()
        self.assertTrue(any("forbidden_terminal_state_detected" in item for item in report["blockers"]))


if __name__ == "__main__":
    unittest.main()
