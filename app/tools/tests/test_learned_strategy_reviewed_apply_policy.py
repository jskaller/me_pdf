from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import learned_strategy_reviewed_apply as reviewed_apply


def minimal_pdf(marker: str) -> bytes:
    chunks: list[bytes] = [
        b"%PDF-1.4\n",
        f"% Patch 25A fixture: {marker}\n".encode("ascii"),
    ]
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] "
            b"/Resources << >> /Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n",
    ]
    offsets: list[int] = []
    for obj in objects:
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(obj)
    xref_offset = sum(len(chunk) for chunk in chunks)
    xref_lines = ["xref", "0 5", "0000000000 65535 f "]
    xref_lines.extend(f"{offset:010d} 00000 n " for offset in offsets)
    xref = "\n".join([
        *xref_lines,
        "trailer",
        "<< /Size 5 /Root 1 0 R >>",
        "startxref",
        str(xref_offset),
        "%%EOF",
        "",
    ]).encode("ascii")
    chunks.append(xref)
    return b"".join(chunks)


class LearnedStrategyReviewedApplyPolicyTest(unittest.TestCase):
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
        self.normal_pdf.write_bytes(minimal_pdf("normal-authoritative-final"))
        self.learned_pdf.write_bytes(minimal_pdf("learned-trial"))
        (self.job / "STATUS.json").write_text(json.dumps({"final_pdf": str(self.normal_pdf)}))
        (self.job / "package" / "STATUS.json").write_text("{}\n")
        self.candidate_id = "pdf_ua-1_7.21.7__7747531055698f0c"
        self.rule_id = "PDF/UA-1/7.21.7"
        self.operator = "Patch 25A test operator"
        self.reviewer = "Patch 25A reviewer"
        self.approver = "Patch 25A separate approver"
        self.evidence_path = self.audit / "learned_strategy_evidence_hashes.json"
        self.dry_run_path = self.audit / "learned_strategy_adoption_apply_dry_run.json"
        self.review_path = self.audit / "learned_strategy_adoption_apply_dry_run_review.json"
        self.sandbox = self.audit / "learned_strategy_apply_sandbox"
        self.sandbox_manifest_path = self.sandbox / "sandbox_manifest.json"
        self.sandbox_verification_path = self.sandbox / "rollback_verification.json"
        self.simulation = self.audit / "learned_strategy_apply_simulation"
        self.simulation_manifest_path = self.simulation / "simulation_manifest.json"
        self.simulated_validation_path = self.simulation / "simulated_validation_report.json"
        self.simulated_rollback_path = self.simulation / "simulated_rollback_verification.json"
        self.write_required_artifacts()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def base_safety(self, *, mode_flag: str | None = None) -> dict:
        flags = {
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
            "normal_final_pdf_remains_authoritative": True,
            "future_apply_not_implemented": True,
        }
        if mode_flag:
            flags[mode_flag] = True
        return flags

    def write_required_artifacts(self) -> None:
        normal_hash = reviewed_apply.sha256_file(self.normal_pdf)
        learned_hash = reviewed_apply.sha256_file(self.learned_pdf)
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
                "normal_final_pdf_sha256": {"path": str(self.normal_pdf), "sha256": normal_hash},
                "learned_trial_or_test_pdf_sha256": {"path": str(self.learned_pdf), "sha256": learned_hash},
            },
            "safety_flags": self.base_safety(mode_flag="evidence_hashes_only"),
        })
        self.write_json(self.dry_run_path, {
            "schema_version": "learned-strategy-adoption-apply-dry-run.v1",
            "mode": "adoption_apply_dry_run_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "BLOCKED",
            "safety_flags": self.base_safety(mode_flag="adoption_apply_dry_run_only"),
        })
        self.write_json(self.review_path, {
            "schema_version": "learned-strategy-adoption-apply-dry-run-review.v1",
            "mode": "adoption_apply_dry_run_review_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "BLOCKED",
            "review_decision": "apply_dry_run_review_recorded",
            "safety_flags": self.base_safety(mode_flag="adoption_apply_dry_run_review_only"),
        })
        self.write_json(self.sandbox_manifest_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "mode": "apply_sandbox_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "apply_sandbox_outcome": "apply_sandbox_recorded",
            "safety_flags": self.base_safety(mode_flag="apply_sandbox_only"),
        })
        self.write_json(self.sandbox_verification_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "manifest_type": "sandbox_rollback_verification",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "rollback_verification_scope": "sandbox_only",
            "rollback_execution_against_authoritative_files": False,
            "sandbox_rollback_verified": True,
            "production_rollback_performed": False,
        })
        self.write_json(self.simulation_manifest_path, {
            "schema_version": "learned-strategy-apply-simulation.v1",
            "mode": "apply_simulation_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "apply_simulation_outcome": "apply_simulation_recorded",
            "adoption_apply_performed": False,
            "safety_flags": self.base_safety(mode_flag="apply_simulation_only"),
        })
        self.write_json(self.simulated_validation_path, {
            "schema_version": "learned-strategy-apply-simulation.v1",
            "manifest_type": "simulated_validation_report",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "validation_scope": "simulation_only",
            "simulated_final_sha256": learned_hash,
            "hashes_verified": True,
            "validation_details": {"valid": True, "qpdf_checked": True},
            "safety_flags": self.base_safety(),
        })
        self.write_json(self.simulated_rollback_path, {
            "schema_version": "learned-strategy-apply-simulation.v1",
            "manifest_type": "simulated_rollback_verification",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "rollback_verification_scope": "simulation_only",
            "rollback_execution_against_authoritative_files": False,
            "simulation_rollback_verified": True,
            "production_rollback_performed": False,
            "safety_flags": self.base_safety(),
        })
        self.expected_normal = normal_hash
        self.expected_learned = learned_hash
        self.expected_simulation_artifact = reviewed_apply.sha256_file(self.simulation_manifest_path)
        self.expected_evidence_artifact = reviewed_apply.sha256_file(self.evidence_path)

    def build(self, **overrides) -> dict:
        args = {
            "job_dir": self.job,
            "repo_root": self.repo,
            "explicit_apply_requested": True,
            "operator": self.operator,
            "reviewer": self.reviewer,
            "approver": self.approver,
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "expected_normal_final_pdf_sha256": self.expected_normal,
            "expected_learned_trial_or_test_pdf_sha256": self.expected_learned,
            "expected_simulation_artifact_sha256": self.expected_simulation_artifact,
            "expected_evidence_hash_artifact_sha256": self.expected_evidence_artifact,
            "evidence_hashes_path": self.evidence_path,
            "apply_dry_run_path": self.dry_run_path,
            "apply_dry_run_review_path": self.review_path,
            "sandbox_manifest_path": self.sandbox_manifest_path,
            "sandbox_rollback_verification_path": self.sandbox_verification_path,
            "simulation_manifest_path_arg": self.simulation_manifest_path,
            "simulated_validation_report_path_arg": self.simulated_validation_path,
            "simulated_rollback_verification_path_arg": self.simulated_rollback_path,
        }
        args.update(overrides)
        manifest, backup, rollback, validation, audit = reviewed_apply.build_artifacts(**args)
        reviewed_apply.write_artifact_bundle(
            job_dir=self.job,
            apply_manifest=manifest,
            backup_manifest=backup,
            rollback_manifest=rollback,
            post_apply_validation=validation,
            apply_audit=audit,
        )
        return manifest

    def assert_blocked_for(self, marker: str, **overrides) -> None:
        manifest = self.build(**overrides)
        self.assertIn(manifest["result"], {"BLOCKED", "FAILED_CLOSED", "INCOMPLETE"})
        self.assertTrue(
            any(marker in blocker for blocker in manifest["blockers"])
            or marker in manifest["incomplete_reasons"],
            {"blockers": manifest["blockers"], "incomplete_reasons": manifest["incomplete_reasons"]},
        )

    def test_missing_apply_flag_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_explicit_apply", explicit_apply_requested=False)

    def test_missing_operator_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_operator", operator="")

    def test_missing_reviewer_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_reviewer", reviewer="")

    def test_missing_approver_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_approver", approver="")

    def test_same_reviewer_and_approver_blocks_apply(self) -> None:
        self.assert_blocked_for("reviewer_and_approver_must_be_separate", approver=self.reviewer)

    def test_missing_candidate_id_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_candidate_id", candidate_id="")

    def test_missing_rule_id_blocks_apply(self) -> None:
        self.assert_blocked_for("missing_rule_id", rule_id="")

    def test_candidate_mismatch_blocks_apply(self) -> None:
        self.assert_blocked_for("evidence_hashes_candidate_id_mismatch", candidate_id="different")

    def test_rule_mismatch_blocks_apply(self) -> None:
        self.assert_blocked_for("evidence_hashes_rule_id_mismatch", rule_id="PDF/UA-1/other")

    def test_missing_evidence_hash_artifact_blocks_apply(self) -> None:
        self.evidence_path.unlink()
        self.assert_blocked_for("missing_evidence_hashes_artifact")

    def test_missing_apply_dry_run_review_blocks_apply(self) -> None:
        self.review_path.unlink()
        self.assert_blocked_for("missing_apply_dry_run_review_artifact")

    def test_missing_sandbox_rollback_verification_blocks_apply(self) -> None:
        self.sandbox_verification_path.unlink()
        self.assert_blocked_for("missing_sandbox_rollback_verification_artifact")

    def test_missing_simulation_validation_blocks_apply(self) -> None:
        self.simulated_validation_path.unlink()
        self.assert_blocked_for("missing_simulated_validation_artifact")

    def test_expected_normal_final_pdf_hash_mismatch_blocks_apply(self) -> None:
        self.assert_blocked_for("expected_normal_final_pdf_hash_mismatch", expected_normal_final_pdf_sha256="0" * 64)

    def test_expected_learned_trial_hash_mismatch_blocks_apply(self) -> None:
        self.assert_blocked_for("expected_learned_trial_or_test_pdf_hash_mismatch", expected_learned_trial_or_test_pdf_sha256="0" * 64)

    def test_missing_backup_target_blocks_apply(self) -> None:
        bad_target = reviewed_apply.reviewed_apply_dir(self.job) / "backups"
        bad_target.mkdir(parents=True)
        self.assert_blocked_for("backup_target_is_directory", backup_path_arg=bad_target)

    def test_backup_is_created_before_adopted_output(self) -> None:
        manifest = self.build()
        self.assertEqual(manifest["result"], "PASS")
        self.assertEqual(manifest["write_order"][:3], ["backup", "rollback_manifest", "adopted_output"])

    def test_rollback_manifest_is_created_before_adopted_output(self) -> None:
        manifest = self.build()
        self.assertLess(manifest["write_order"].index("rollback_manifest"), manifest["write_order"].index("adopted_output"))

    def test_adopted_output_is_written_only_under_reviewed_apply_dir(self) -> None:
        manifest = self.build()
        self.assertTrue(reviewed_apply.path_is_inside(Path(manifest["adopted_output_path"]), reviewed_apply.reviewed_apply_dir(self.job)))

    def test_adopted_output_hash_matches_learned_trial_hash(self) -> None:
        manifest = self.build()
        self.assertEqual(manifest["adopted_output_sha256"], self.expected_learned)

    def test_post_apply_qpdf_validation_is_recorded(self) -> None:
        manifest = self.build()
        validation = manifest["post_apply_validation"]
        self.assertEqual(validation["validation_scope"], "job_scoped_reviewed_apply")
        self.assertTrue(validation["qpdf_checked"])
        self.assertTrue(validation["validation_details"]["valid"])

    def test_apply_artifact_includes_all_mandatory_flags(self) -> None:
        manifest = self.build()
        for key, expected in reviewed_apply.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(manifest["safety_flags"][key], expected)
            self.assertEqual(manifest[key], expected)

    def test_apply_does_not_mark_candidate_globally_approved(self) -> None:
        self.assertFalse(self.build()["candidate_approved"])

    def test_apply_does_not_mark_candidate_globally_adoptable(self) -> None:
        self.assertFalse(self.build()["candidate_is_adoptable"])

    def test_apply_does_not_mark_candidate_globally_production_ready(self) -> None:
        self.assertFalse(self.build()["candidate_production_ready"])

    def test_apply_does_not_mark_candidate_apply_ready(self) -> None:
        self.assertFalse(self.build()["candidate_apply_ready"])

    def test_apply_does_not_enable_default_learned_execution(self) -> None:
        self.assertFalse(self.build()["default_learned_execution_enabled"])

    def test_apply_does_not_mutate_app_tools_repair(self) -> None:
        before = (self.repo / "app" / "tools" / "repair" / "README.md").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "repair" / "README.md").read_bytes(), before)

    def test_apply_does_not_mutate_rule_repair_map(self) -> None:
        before = (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes(), before)

    def test_apply_does_not_soften_verdict(self) -> None:
        self.assertFalse(self.build()["verdict_softening_performed"])

    def test_apply_does_not_mutate_package_status(self) -> None:
        before = (self.job / "package" / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "package" / "STATUS.json").read_bytes(), before)

    def test_apply_fails_closed_on_qpdf_validation_failure(self) -> None:
        self.learned_pdf.write_bytes(b"not a pdf\n")
        new_hash = reviewed_apply.sha256_file(self.learned_pdf)
        data = json.loads(self.evidence_path.read_text())
        data["source_evidence_hashes"]["learned_trial_or_test_pdf_sha256"] = new_hash
        data["evidence_hashes"]["learned_trial_or_test_pdf_sha256"]["sha256"] = new_hash
        self.write_json(self.evidence_path, data)
        sim = json.loads(self.simulated_validation_path.read_text())
        sim["simulated_final_sha256"] = new_hash
        self.write_json(self.simulated_validation_path, sim)
        self.expected_evidence_artifact = reviewed_apply.sha256_file(self.evidence_path)
        manifest = self.build(
            expected_learned_trial_or_test_pdf_sha256=new_hash,
            expected_evidence_hash_artifact_sha256=self.expected_evidence_artifact,
        )
        self.assertEqual(manifest["result"], "FAILED_CLOSED")
        self.assertTrue(any("post_apply_qpdf_validation_failed" in blocker for blocker in manifest["blockers"]))

    def test_apply_fails_closed_on_backup_failure(self) -> None:
        self.normal_pdf.unlink()
        self.assert_blocked_for("missing_normal_final_pdf_path")

    def test_apply_fails_closed_on_rollback_manifest_failure(self) -> None:
        bad_target = self.job / "outside" / "normal.pdf"
        self.assert_blocked_for("backup_target_outside_reviewed_apply_dir", backup_path_arg=bad_target)

    def test_apply_records_exact_reviewer_and_approver_identities(self) -> None:
        manifest = self.build()
        self.assertEqual(manifest["reviewer"], self.reviewer)
        self.assertEqual(manifest["approver"], self.approver)

    def test_apply_records_locked_hashes_used_for_verification(self) -> None:
        locked = self.build()["locked_hashes"]
        self.assertEqual(locked["expected_normal_final_pdf_sha256"], self.expected_normal)
        self.assertEqual(locked["expected_learned_trial_or_test_pdf_sha256"], self.expected_learned)
        self.assertEqual(locked["expected_simulation_artifact_sha256"], self.expected_simulation_artifact)
        self.assertEqual(locked["expected_evidence_hash_artifact_sha256"], self.expected_evidence_artifact)

    def test_apply_records_rollback_instructions(self) -> None:
        manifest = self.build()
        rollback = manifest["rollback_manifest"]
        self.assertTrue(rollback["rollback_instructions"])
        self.assertIn("normal final PDF", " ".join(rollback["rollback_instructions"]))

    def test_forbidden_terminal_global_states_are_rejected(self) -> None:
        self.assert_blocked_for("forbidden_terminal_state_detected:candidate_id:rule_map_mutated", candidate_id="rule_map_mutated")


if __name__ == "__main__":
    unittest.main()
