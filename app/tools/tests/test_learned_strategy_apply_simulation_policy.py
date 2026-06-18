from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import learned_strategy_apply_simulation as simulation


def minimal_pdf(marker: str) -> bytes:
    """Return a tiny one-page PDF accepted by qpdf --check.

    qpdf is stricter than the fallback header check used on systems without
    qpdf. The fixture therefore includes a valid page tree, page object, empty
    content stream, and exact xref offsets instead of only a Catalog object.
    """
    chunks: list[bytes] = [
        b"%PDF-1.4\n",
        f"% Patch 24A fixture: {marker}\n".encode("ascii"),
    ]
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
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
    xref_lines = [
        "xref",
        f"0 {len(objects) + 1}",
        "0000000000 65535 f ",
        *(f"{offset:010d} 00000 n " for offset in offsets),
        "trailer",
        f"<< /Size {len(objects) + 1} /Root 1 0 R >>",
        "startxref",
        str(xref_offset),
        "%%EOF",
    ]
    chunks.append(("\n".join(xref_lines) + "\n").encode("ascii"))
    return b"".join(chunks)


class LearnedStrategyApplySimulationPolicyTest(unittest.TestCase):
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
        self.candidate_id = "pdf_ua-1_7.21.7__candidate"
        self.rule_id = "PDF/UA-1/7.21.7"
        self.operator = "Patch 24A test operator"
        self.reviewer = "Patch 24A test reviewer"
        self.evidence_path = self.audit / "learned_strategy_evidence_hashes.json"
        self.dry_run_path = self.audit / "learned_strategy_adoption_apply_dry_run.json"
        self.review_path = self.audit / "learned_strategy_adoption_apply_dry_run_review.json"
        self.sandbox = self.audit / "learned_strategy_apply_sandbox"
        self.sandbox_manifest_path = self.sandbox / "sandbox_manifest.json"
        self.sandbox_backup_path = self.sandbox / "backup_manifest.json"
        self.sandbox_rollback_path = self.sandbox / "rollback_manifest.json"
        self.sandbox_verification_path = self.sandbox / "rollback_verification.json"
        self.write_required_artifacts()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def base_safety(self, *, mode_flag: str | None = None) -> dict:
        flags = {
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
        if mode_flag:
            flags[mode_flag] = True
        return flags

    def write_required_artifacts(self) -> None:
        normal_hash = simulation.sha256_file(self.normal_pdf)
        learned_hash = simulation.sha256_file(self.learned_pdf)
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
        self.write_json(self.sandbox_manifest_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "mode": "apply_sandbox_only",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "result": "PASS",
            "apply_sandbox_outcome": "apply_sandbox_recorded",
            "safety_flags": self.base_safety(mode_flag="apply_sandbox_only"),
        })
        self.write_json(self.sandbox_backup_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "manifest_type": "sandbox_backup_manifest",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "entries": [],
            "production_backup_created": False,
            "safety_flags": self.base_safety(),
        })
        self.write_json(self.sandbox_rollback_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "manifest_type": "sandbox_rollback_manifest",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "entries": [],
            "rollback_execution_against_authoritative_files": False,
            "production_rollback_performed": False,
            "safety_flags": self.base_safety(),
        })
        self.write_json(self.sandbox_verification_path, {
            "schema_version": "learned-strategy-apply-sandbox.v1",
            "manifest_type": "sandbox_rollback_verification",
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "checks": [{"matches": True, "sandbox_only": True}],
            "rollback_verification_scope": "sandbox_only",
            "rollback_execution_against_authoritative_files": False,
            "sandbox_rollback_verified": True,
            "production_rollback_performed": False,
            "safety_flags": self.base_safety(),
        })

    def build(self, **overrides) -> dict:
        args = {
            "job_dir": self.job,
            "repo_root": self.repo,
            "operator": self.operator,
            "reviewer": self.reviewer,
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "evidence_hashes_path": self.evidence_path,
            "apply_dry_run_path": self.dry_run_path,
            "apply_dry_run_review_path": self.review_path,
            "sandbox_manifest_path_arg": self.sandbox_manifest_path,
            "sandbox_backup_manifest_path": self.sandbox_backup_path,
            "sandbox_rollback_manifest_path": self.sandbox_rollback_path,
            "sandbox_rollback_verification_path": self.sandbox_verification_path,
        }
        args.update(overrides)
        manifest, apply_report, validation, rollback = simulation.build_artifacts(**args)
        simulation.write_artifact_bundle(
            job_dir=self.job,
            simulation_manifest=manifest,
            simulated_apply_report=apply_report,
            simulated_validation_report=validation,
            simulated_rollback_verification=rollback,
        )
        return manifest

    def assert_blocked_for(self, marker: str, **overrides) -> None:
        manifest = self.build(**overrides)
        self.assertEqual(manifest["result"], "BLOCKED")
        self.assertTrue(any(marker in blocker for blocker in manifest["blockers"]), manifest["blockers"])

    def test_missing_evidence_hash_artifact_blocks_simulation(self) -> None:
        self.evidence_path.unlink()
        self.assert_blocked_for("missing_evidence_hashes_artifact")

    def test_missing_apply_dry_run_artifact_blocks_simulation(self) -> None:
        self.dry_run_path.unlink()
        self.assert_blocked_for("missing_apply_dry_run_artifact")

    def test_missing_apply_dry_run_review_artifact_blocks_simulation(self) -> None:
        self.review_path.unlink()
        self.assert_blocked_for("missing_apply_dry_run_review_artifact")

    def test_missing_sandbox_manifest_blocks_simulation(self) -> None:
        self.sandbox_manifest_path.unlink()
        self.assert_blocked_for("missing_sandbox_manifest_artifact")

    def test_missing_rollback_verification_blocks_simulation(self) -> None:
        self.sandbox_verification_path.unlink()
        self.assert_blocked_for("missing_sandbox_rollback_verification_artifact")

    def test_missing_operator_blocks_simulation(self) -> None:
        self.assert_blocked_for("missing_operator", operator="")

    def test_missing_reviewer_blocks_simulation(self) -> None:
        self.assert_blocked_for("missing_reviewer", reviewer="")

    def test_missing_candidate_id_blocks_simulation(self) -> None:
        self.assert_blocked_for("missing_candidate_id", candidate_id="")

    def test_missing_rule_id_blocks_simulation(self) -> None:
        self.assert_blocked_for("missing_rule_id", rule_id="")

    def test_candidate_mismatch_blocks_simulation(self) -> None:
        self.assert_blocked_for("evidence_hashes_candidate_id_mismatch", candidate_id="different")

    def test_rule_mismatch_blocks_simulation(self) -> None:
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

    def test_stale_normal_final_pdf_hash_blocks_simulation(self) -> None:
        self.normal_pdf.write_bytes(minimal_pdf("normal-authoritative-final-stale"))
        self.assert_blocked_for("normal_final_pdf_hash_mismatch")

    def test_stale_learned_trial_pdf_hash_blocks_simulation(self) -> None:
        self.learned_pdf.write_bytes(minimal_pdf("learned-trial-stale"))
        self.assert_blocked_for("learned_trial_or_test_pdf_hash_mismatch")

    def test_simulation_creates_files_only_under_isolated_dir(self) -> None:
        manifest = self.build()
        root = simulation.simulation_dir(self.job).resolve()
        self.assertEqual(manifest["result"], "PASS")
        for copied in manifest["copied_files"]:
            self.assertTrue(simulation.path_is_inside(Path(copied), root))

    def test_simulation_creates_simulated_final_without_modifying_authoritative_final(self) -> None:
        before = self.normal_pdf.read_bytes()
        manifest = self.build()
        simulated_final = Path(manifest["simulated_final_path"])
        self.assertTrue(simulated_final.exists())
        self.assertEqual(simulated_final.read_bytes(), self.learned_pdf.read_bytes())
        self.assertEqual(self.normal_pdf.read_bytes(), before)

    def test_simulation_validates_simulated_final_with_qpdf_or_safe_validation(self) -> None:
        manifest = self.build()
        validation = json.loads(Path(manifest["simulated_validation_report_path"]).read_text())
        self.assertEqual(validation["validation_scope"], "simulation_only")
        self.assertTrue(validation["qpdf_checked"])
        self.assertTrue(validation["validation_details"]["valid"])

    def test_simulation_records_normal_vs_learned_hash_comparison(self) -> None:
        manifest = self.build()
        comparison = manifest["normal_vs_learned_hash_comparison"]
        self.assertIn("normal_final_pdf_sha256", comparison)
        self.assertIn("learned_trial_or_test_pdf_sha256", comparison)
        self.assertTrue(comparison["simulated_matches_learned"])

    def test_simulation_records_sandbox_rollback_verification_reference(self) -> None:
        manifest = self.build()
        rollback = json.loads(Path(manifest["simulated_rollback_verification_path"]).read_text())
        self.assertEqual(rollback["sandbox_rollback_verification_reference"]["path"], str(self.sandbox_verification_path))
        self.assertTrue(rollback["sandbox_rollback_verification_reference"]["sandbox_rollback_verified"])

    def test_sandbox_rollback_verification_without_safety_flags_is_supported(self) -> None:
        data = json.loads(self.sandbox_verification_path.read_text())
        data.pop("safety_flags")
        self.write_json(self.sandbox_verification_path, data)
        manifest = self.build()
        self.assertEqual(manifest["result"], "PASS")
        rollback = json.loads(Path(manifest["simulated_rollback_verification_path"]).read_text())
        self.assertTrue(rollback["sandbox_rollback_verification_reference"]["sandbox_rollback_verified"])
        self.assertTrue(rollback["simulation_rollback_verified"])

    def test_simulation_artifact_includes_all_no_production_apply_flags(self) -> None:
        manifest = self.build()
        for key, expected in simulation.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(manifest["safety_flags"][key], expected)
            self.assertEqual(manifest[key], expected)

    def test_simulation_does_not_mark_candidate_approved(self) -> None:
        self.assertFalse(self.build()["candidate_approved"])

    def test_simulation_does_not_mark_candidate_adoptable(self) -> None:
        self.assertFalse(self.build()["candidate_is_adoptable"])

    def test_simulation_does_not_mark_candidate_production_ready(self) -> None:
        self.assertFalse(self.build()["candidate_production_ready"])

    def test_simulation_does_not_mark_candidate_apply_ready(self) -> None:
        self.assertFalse(self.build()["candidate_apply_ready"])

    def test_simulation_does_not_mutate_authoritative_status_json(self) -> None:
        before = (self.job / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "STATUS.json").read_bytes(), before)

    def test_simulation_does_not_mutate_package_deliverables(self) -> None:
        before = (self.job / "package" / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "package" / "STATUS.json").read_bytes(), before)

    def test_simulation_does_not_mutate_app_tools_repair(self) -> None:
        before = (self.repo / "app" / "tools" / "repair" / "README.md").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "repair" / "README.md").read_bytes(), before)

    def test_simulation_does_not_mutate_rule_repair_map(self) -> None:
        before = (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes(), before)

    def test_simulation_does_not_create_production_backups(self) -> None:
        self.build()
        outside = [
            p for p in self.job.rglob("*")
            if p.is_file()
            and "learned_strategy_apply_simulation" not in str(p)
            and p.name.endswith(".bak")
        ]
        self.assertEqual(outside, [])

    def test_simulation_does_not_execute_rollback_against_authoritative_files(self) -> None:
        manifest = self.build()
        rollback = json.loads(Path(manifest["simulated_rollback_verification_path"]).read_text())
        self.assertFalse(manifest["rollback_execution_against_authoritative_files"])
        self.assertFalse(rollback["rollback_execution_against_authoritative_files"])

    def test_forbidden_terminal_states_are_rejected(self) -> None:
        self.assert_blocked_for("forbidden_terminal_state_detected:candidate_id:approved", candidate_id="approved")

    def test_simulated_validation_is_simulation_only(self) -> None:
        manifest = self.build()
        validation = json.loads(Path(manifest["simulated_validation_report_path"]).read_text())
        self.assertEqual(validation["validation_scope"], "simulation_only")
        self.assertFalse(validation["validated_pdf_is_authoritative_final"])
        self.assertFalse(validation["package_status_mutation_performed"])
        self.assertFalse(validation["verdict_softening_performed"])

    def test_simulated_rollback_verification_is_simulation_only(self) -> None:
        manifest = self.build()
        rollback = json.loads(Path(manifest["simulated_rollback_verification_path"]).read_text())
        self.assertEqual(rollback["rollback_verification_scope"], "simulation_only")
        self.assertTrue(rollback["simulation_rollback_verified"])
        self.assertFalse(rollback["production_rollback_performed"])

    def test_future_apply_remains_not_implemented(self) -> None:
        self.assertTrue(self.build()["future_apply_not_implemented"])


if __name__ == "__main__":
    unittest.main()
