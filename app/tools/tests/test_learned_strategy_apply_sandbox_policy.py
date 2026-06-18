from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import learned_strategy_apply_sandbox as sandbox


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LearnedStrategyApplySandboxPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "job"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        (self.job / "repair").mkdir(parents=True)
        (self.job / "package").mkdir(parents=True)
        (self.repo / "app" / "tools" / "audit").mkdir(parents=True)
        (self.repo / "app" / "tools" / "repair").mkdir(parents=True)
        (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").write_text("{}\n")
        (self.repo / "app" / "tools" / "repair" / "README.md").write_text("repair tools\n")
        self.normal_pdf = self.job / "repair" / "pass8_iter1_fix_cidset.pdf"
        self.learned_pdf = self.audit / "learned_trial.pdf"
        self.normal_pdf.write_bytes(b"normal final pdf")
        self.learned_pdf.write_bytes(b"learned trial pdf")
        (self.job / "STATUS.json").write_text(json.dumps({"final_pdf": str(self.normal_pdf)}))
        (self.job / "package" / "STATUS.json").write_text("{}\n")
        self.candidate_id = "pdf_ua-1_7.21.7__candidate"
        self.rule_id = "PDF/UA-1/7.21.7"
        self.operator = "Patch 23A test"
        self.evidence_path = self.audit / "learned_strategy_evidence_hashes.json"
        self.dry_run_path = self.audit / "learned_strategy_adoption_apply_dry_run.json"
        self.review_path = self.audit / "learned_strategy_adoption_apply_dry_run_review.json"
        self.write_required_artifacts()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def base_safety(self, *, mode_flag: str) -> dict:
        flags = {
            mode_flag: True,
            "adoption_apply_performed": False,
            "rollback_execution_performed": False,
            "candidate_is_adoptable": False,
            "candidate_approved": False,
            "candidate_production_ready": False,
            "candidate_apply_ready": False,
            "final_pdf_adoption_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
            "package_status_mutation_performed": False,
            "rule_map_mutation_performed": False,
            "app_tools_repair_mutation_performed": False,
            "normal_final_pdf_remains_authoritative": True,
            "future_apply_not_implemented": True,
        }
        return flags

    def write_required_artifacts(self) -> None:
        normal_hash = sandbox.sha256_file(self.normal_pdf)
        learned_hash = sandbox.sha256_file(self.learned_pdf)
        self.write_json(self.evidence_path, {
            "schema_version": "learned-strategy-evidence-hashes.v1",
            "mode": "evidence_hashes_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "source_evidence_hashes": {
                "normal_final_pdf_sha256": normal_hash,
                "learned_trial_or_test_pdf_sha256": learned_hash,
            },
            "evidence_hashes": {
                "normal_final_pdf_sha256": {
                    "path": str(self.normal_pdf),
                    "sha256": normal_hash,
                },
                "learned_trial_or_test_pdf_sha256": {
                    "path": str(self.learned_pdf),
                    "sha256": learned_hash,
                },
            },
            "safety_flags": self.base_safety(mode_flag="evidence_hashes_only"),
        })
        self.write_json(self.dry_run_path, {
            "schema_version": "learned-strategy-adoption-apply-dry-run.v1",
            "mode": "adoption_apply_dry_run_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "BLOCKED",
            "apply_dry_run_simulation_outcome": "apply_dry_run_simulation_blocked",
            "safety_flags": self.base_safety(mode_flag="adoption_apply_dry_run_only"),
        })
        self.write_json(self.review_path, {
            "schema_version": "learned-strategy-adoption-apply-dry-run-review.v1",
            "mode": "adoption_apply_dry_run_review_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "BLOCKED",
            "review_decision": "apply_dry_run_review_rejected",
            "safety_flags": self.base_safety(mode_flag="adoption_apply_dry_run_review_only"),
        })

    def build(self, **overrides) -> dict:
        args = {
            "job_dir": self.job,
            "repo_root": self.repo,
            "operator": self.operator,
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "evidence_hashes_path": self.evidence_path,
            "apply_dry_run_path": self.dry_run_path,
            "apply_dry_run_review_path": self.review_path,
        }
        args.update(overrides)
        manifest, backup, rollback, verification = sandbox.build_artifacts(**args)
        sandbox.write_artifact_bundle(
            job_dir=self.job,
            sandbox_manifest=manifest,
            backup_manifest=backup,
            rollback_manifest=rollback,
            rollback_verification=verification,
        )
        return manifest

    def assert_blocked_for(self, marker: str, **overrides) -> None:
        manifest = self.build(**overrides)
        self.assertEqual(manifest["result"], "BLOCKED")
        self.assertTrue(any(marker in blocker for blocker in manifest["blockers"]))

    def test_missing_evidence_hash_artifact_blocks_sandbox(self) -> None:
        self.evidence_path.unlink()
        self.assert_blocked_for("missing_evidence_hashes_artifact")

    def test_missing_apply_dry_run_artifact_blocks_sandbox(self) -> None:
        self.dry_run_path.unlink()
        self.assert_blocked_for("missing_apply_dry_run_artifact")

    def test_missing_apply_dry_run_review_artifact_blocks_sandbox(self) -> None:
        self.review_path.unlink()
        self.assert_blocked_for("missing_apply_dry_run_review_artifact")

    def test_missing_operator_blocks_sandbox(self) -> None:
        self.assert_blocked_for("missing_operator", operator="")

    def test_missing_candidate_id_blocks_sandbox(self) -> None:
        self.assert_blocked_for("missing_candidate_id", candidate_id="")

    def test_missing_rule_id_blocks_sandbox(self) -> None:
        self.assert_blocked_for("missing_rule_id", rule_id="")

    def test_candidate_mismatch_blocks_sandbox(self) -> None:
        self.assert_blocked_for("evidence_hashes_candidate_id_mismatch", candidate_id="different")

    def test_rule_mismatch_blocks_sandbox(self) -> None:
        self.assert_blocked_for("evidence_hashes_rule_id_mismatch", rule_id="PDF/UA-1/other")

    def test_missing_normal_final_pdf_hash_or_path_records_incomplete(self) -> None:
        data = json.loads(self.evidence_path.read_text())
        data["source_evidence_hashes"].pop("normal_final_pdf_sha256")
        data["evidence_hashes"]["normal_final_pdf_sha256"].pop("sha256")
        data["evidence_hashes"]["normal_final_pdf_sha256"].pop("path")
        self.write_json(self.evidence_path, data)
        manifest = self.build()
        self.assertEqual(manifest["result"], "INCOMPLETE")
        self.assertIn("missing_normal_final_pdf_hash", manifest["incomplete_reasons"])
        self.assertIn("missing_normal_final_pdf_path", manifest["incomplete_reasons"])

    def test_missing_learned_trial_pdf_hash_or_path_records_incomplete(self) -> None:
        data = json.loads(self.evidence_path.read_text())
        data["source_evidence_hashes"].pop("learned_trial_or_test_pdf_sha256")
        data["evidence_hashes"]["learned_trial_or_test_pdf_sha256"].pop("sha256")
        data["evidence_hashes"]["learned_trial_or_test_pdf_sha256"].pop("path")
        self.write_json(self.evidence_path, data)
        manifest = self.build()
        self.assertEqual(manifest["result"], "INCOMPLETE")
        self.assertIn("missing_learned_trial_or_test_pdf_hash", manifest["incomplete_reasons"])
        self.assertIn("missing_learned_trial_or_test_pdf_path", manifest["incomplete_reasons"])

    def test_sandbox_creates_files_only_under_isolated_dir(self) -> None:
        manifest = self.build()
        root = sandbox.sandbox_dir(self.job).resolve()
        self.assertEqual(manifest["result"], "PASS")
        for copied in manifest["copied_files"]:
            self.assertTrue(sandbox.path_is_inside(Path(copied), root))

    def test_sandbox_copies_normal_final_pdf_without_modifying_original(self) -> None:
        before = self.normal_pdf.read_bytes()
        manifest = self.build()
        copy_path = Path(manifest["backup_manifest_path"]).parent / "backups" / "normal_final_pdf.pdf"
        self.assertTrue(copy_path.exists())
        self.assertEqual(self.normal_pdf.read_bytes(), before)

    def test_sandbox_copies_learned_trial_pdf_without_modifying_original(self) -> None:
        before = self.learned_pdf.read_bytes()
        manifest = self.build()
        copy_path = Path(manifest["backup_manifest_path"]).parent / "backups" / "learned_trial_or_test_pdf.pdf"
        self.assertTrue(copy_path.exists())
        self.assertEqual(self.learned_pdf.read_bytes(), before)

    def test_sandbox_backup_manifest_records_future_backup_targets(self) -> None:
        manifest = self.build()
        backup = json.loads(Path(manifest["backup_manifest_path"]).read_text())
        self.assertTrue(backup["future_backup_targets"])
        self.assertFalse(backup["production_backup_created"])
        self.assertTrue(backup["sandbox_backup_created"])

    def test_sandbox_rollback_manifest_records_future_rollback_targets(self) -> None:
        manifest = self.build()
        rollback = json.loads(Path(manifest["rollback_manifest_path"]).read_text())
        self.assertTrue(rollback["future_rollback_targets"])
        self.assertFalse(rollback["rollback_execution_against_authoritative_files"])
        self.assertFalse(rollback["production_rollback_performed"])

    def test_sandbox_rollback_verification_compares_sandbox_hashes_only(self) -> None:
        manifest = self.build()
        verification = json.loads(Path(manifest["rollback_verification_path"]).read_text())
        self.assertEqual(verification["rollback_verification_scope"], "sandbox_only")
        self.assertTrue(verification["sandbox_rollback_verified"])
        self.assertTrue(all(check["sandbox_only"] for check in verification["checks"]))

    def test_sandbox_artifact_includes_all_no_production_mutation_flags(self) -> None:
        manifest = self.build()
        for key, expected in sandbox.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(manifest["safety_flags"][key], expected)
            self.assertEqual(manifest[key], expected)

    def test_sandbox_does_not_mark_candidate_approved(self) -> None:
        self.assertFalse(self.build()["candidate_approved"])

    def test_sandbox_does_not_mark_candidate_adoptable(self) -> None:
        self.assertFalse(self.build()["candidate_is_adoptable"])

    def test_sandbox_does_not_mark_candidate_production_ready(self) -> None:
        self.assertFalse(self.build()["candidate_production_ready"])

    def test_sandbox_does_not_mark_candidate_apply_ready(self) -> None:
        self.assertFalse(self.build()["candidate_apply_ready"])

    def test_sandbox_does_not_mutate_authoritative_status_json(self) -> None:
        before = (self.job / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "STATUS.json").read_bytes(), before)

    def test_sandbox_does_not_mutate_package_deliverables(self) -> None:
        before = (self.job / "package" / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "package" / "STATUS.json").read_bytes(), before)

    def test_sandbox_does_not_mutate_app_tools_repair(self) -> None:
        before = (self.repo / "app" / "tools" / "repair" / "README.md").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "repair" / "README.md").read_bytes(), before)

    def test_sandbox_does_not_mutate_rule_repair_map(self) -> None:
        before = (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes(), before)

    def test_sandbox_does_not_create_backups_outside_isolated_directory(self) -> None:
        self.build()
        outside = [
            p for p in self.job.rglob("*")
            if p.is_file()
            and "learned_strategy_apply_sandbox" not in str(p)
            and p.name.endswith(".bak")
        ]
        self.assertEqual(outside, [])

    def test_forbidden_terminal_states_are_rejected(self) -> None:
        self.assert_blocked_for("forbidden_terminal_state_detected:candidate_id:approved", candidate_id="approved")

    def test_rollback_verification_is_sandbox_only(self) -> None:
        manifest = self.build()
        verification = json.loads(Path(manifest["rollback_verification_path"]).read_text())
        self.assertEqual(verification["rollback_verification_scope"], "sandbox_only")
        self.assertFalse(verification["rollback_execution_against_authoritative_files"])

    def test_production_rollback_is_not_performed(self) -> None:
        manifest = self.build()
        verification = json.loads(Path(manifest["rollback_verification_path"]).read_text())
        self.assertFalse(manifest["production_rollback_performed"])
        self.assertFalse(verification["production_rollback_performed"])

    def test_future_apply_remains_not_implemented(self) -> None:
        self.assertTrue(self.build()["future_apply_not_implemented"])

    def test_live_artifacts_without_mode_field_are_accepted_when_safety_flag_present(self) -> None:
        for path, flag in (
            (self.evidence_path, "evidence_hashes_only"),
            (self.dry_run_path, "adoption_apply_dry_run_only"),
            (self.review_path, "adoption_apply_dry_run_review_only"),
        ):
            data = json.loads(path.read_text())
            data.pop("mode", None)
            data[flag] = True
            data["safety_flags"][flag] = True
            self.write_json(path, data)
        manifest = self.build()
        self.assertEqual(manifest["result"], "PASS")
        self.assertEqual(manifest["apply_sandbox_outcome"], "apply_sandbox_recorded")
        self.assertTrue(manifest["rollback_verification"]["sandbox_rollback_verified"])


if __name__ == "__main__":
    unittest.main()
