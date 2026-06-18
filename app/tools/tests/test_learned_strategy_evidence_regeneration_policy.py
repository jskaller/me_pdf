from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import learned_strategy_evidence_regeneration as regen
from tools.audit import learned_strategy_evidence_hashes as hashes


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceRegenerationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "job"
        (self.repo / "app" / "tools" / "audit").mkdir(parents=True)
        (self.repo / "app" / "tools" / "repair").mkdir(parents=True)
        (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").write_text("{}\n")
        (self.repo / "app" / "tools" / "repair" / "README.md").write_text("repair tools\n")
        (self.job / "audit").mkdir(parents=True)
        (self.job / "repair").mkdir(parents=True)
        (self.job / "package").mkdir(parents=True)
        (self.job / "STATUS.json").write_text(json.dumps({"final_pdf": str(self.job / "repair" / "pass8_iter1_fix_cidset.pdf")}))
        (self.job / "package" / "STATUS.json").write_text("{}\n")
        (self.job / "repair" / "pass8_iter1_fix_cidset.pdf").write_bytes(b"normal pdf")
        self.candidate_id = "pdf_ua-1_7.21.7__candidate"
        self.rule_id = "PDF/UA-1/7.21.7"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, rel: str, data: dict) -> Path:
        path = self.job / "audit" / rel
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def build(self) -> dict:
        return regen.build_artifact(
            job_dir=self.job,
            repo_root=self.repo,
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )

    def make_complete_artifacts(self) -> tuple[bytes, bytes, bytes]:
        learned = self.job / "audit" / "learned_trial.pdf"
        learned_bytes = b"learned trial pdf"
        readiness_bytes = b'{"readiness": true}\n'
        production_bytes = b'{"production": true}\n'
        learned.write_bytes(learned_bytes)
        self.write_json("learned_strategy_replacement_trial_report.json", {
            "results": [{"learned_trial_pdf": str(learned)}],
        })
        (self.job / "audit" / "learned_strategy_production_testing_readiness_report.json").write_bytes(readiness_bytes)
        (self.job / "audit" / "learned_strategy_production_test_report.json").write_bytes(production_bytes)
        return learned_bytes, readiness_bytes, production_bytes

    def test_missing_learned_trial_pdf_is_incomplete(self) -> None:
        self.write_json("learned_strategy_production_testing_readiness_report.json", {})
        self.write_json("learned_strategy_production_test_report.json", {})
        artifact = self.build()
        self.assertEqual(artifact["result"], "INCOMPLETE")
        self.assertIn("learned_trial_or_test_pdf", artifact["missing_targets"])

    def test_missing_production_readiness_report_is_incomplete(self) -> None:
        learned = self.job / "audit" / "learned.pdf"
        learned.write_bytes(b"pdf")
        self.write_json("learned_strategy_replacement_trial_report.json", {"results": [{"learned_trial_pdf": str(learned)}]})
        self.write_json("learned_strategy_production_test_report.json", {})
        artifact = self.build()
        self.assertIn("production_readiness_report", artifact["missing_targets"])

    def test_missing_production_test_report_is_incomplete(self) -> None:
        learned = self.job / "audit" / "learned.pdf"
        learned.write_bytes(b"pdf")
        self.write_json("learned_strategy_replacement_trial_report.json", {"results": [{"learned_trial_pdf": str(learned)}]})
        self.write_json("learned_strategy_production_testing_readiness_report.json", {})
        artifact = self.build()
        self.assertIn("production_test_report", artifact["missing_targets"])

    def test_existing_learned_trial_pdf_is_hashed_and_recorded(self) -> None:
        learned_bytes, _, _ = self.make_complete_artifacts()
        artifact = self.build()
        record = artifact["artifacts"]["learned_trial_or_test_pdf"]
        self.assertEqual(record["status"], "artifact_reused_existing")
        self.assertEqual(record["sha256"], sha256_bytes(learned_bytes))

    def test_existing_production_readiness_report_is_hashed_and_recorded(self) -> None:
        _, readiness_bytes, _ = self.make_complete_artifacts()
        artifact = self.build()
        self.assertEqual(
            artifact["artifacts"]["production_readiness_report"]["sha256"],
            sha256_bytes(readiness_bytes),
        )

    def test_existing_production_test_report_is_hashed_and_recorded(self) -> None:
        _, _, production_bytes = self.make_complete_artifacts()
        artifact = self.build()
        self.assertEqual(
            artifact["artifacts"]["production_test_report"]["sha256"],
            sha256_bytes(production_bytes),
        )

    def test_existing_artifact_with_unverifiable_path_is_reported_unverifiable(self) -> None:
        self.write_json("learned_strategy_replacement_trial_report.json", {
            "results": [{"learned_trial_pdf": str(self.job / "audit" / "missing.pdf")}],
        })
        self.write_json("learned_strategy_production_testing_readiness_report.json", {})
        self.write_json("learned_strategy_production_test_report.json", {})
        artifact = self.build()
        self.assertEqual(artifact["artifacts"]["learned_trial_or_test_pdf"]["status"], "artifact_unverifiable")
        self.assertIn("learned_trial_or_test_pdf", artifact["unverifiable_targets"])

    def test_records_source_path_hash_source_command_timestamp_and_status(self) -> None:
        self.make_complete_artifacts()
        artifact = self.build()
        for target, record in artifact["artifacts"].items():
            self.assertEqual(record["status"], "artifact_reused_existing", target)
            self.assertTrue(record["artifact_path"], target)
            self.assertTrue(record["sha256"], target)
            self.assertTrue(record["source_command"], target)
            self.assertTrue(record["verified_at"].endswith("Z"), target)

    def test_includes_all_no_apply_no_adoption_no_mutation_flags(self) -> None:
        artifact = self.build()
        for key, expected in regen.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(artifact["safety_flags"][key], expected)
            self.assertEqual(artifact[key], expected)

    def test_does_not_mark_candidate_approved_adoptable_production_or_apply_ready(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["candidate_approved"])
        self.assertFalse(artifact["candidate_is_adoptable"])
        self.assertFalse(artifact["candidate_production_ready"])
        self.assertFalse(artifact["candidate_apply_ready"])

    def test_does_not_create_backups_or_execute_rollback(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["backup_created"])
        self.assertFalse(artifact["rollback_execution_performed"])

    def test_does_not_mutate_authoritative_status(self) -> None:
        before = (self.job / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "STATUS.json").read_bytes(), before)

    def test_does_not_mutate_package_deliverables(self) -> None:
        before = (self.job / "package" / "STATUS.json").read_bytes()
        self.build()
        self.assertEqual((self.job / "package" / "STATUS.json").read_bytes(), before)

    def test_does_not_mutate_app_tools_repair(self) -> None:
        before = (self.repo / "app" / "tools" / "repair" / "README.md").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "repair" / "README.md").read_bytes(), before)

    def test_does_not_mutate_rule_repair_map(self) -> None:
        before = (self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes()
        self.build()
        self.assertEqual((self.repo / "app" / "tools" / "audit" / "rule_repair_map.json").read_bytes(), before)

    def test_evidence_hashing_consumes_current_artifact_names(self) -> None:
        learned_bytes, readiness_bytes, production_bytes = self.make_complete_artifacts()
        artifact = hashes.build_artifact(
            job_dir=self.job,
            repo_root=self.repo,
            candidate_id=self.candidate_id,
            rule_id=self.rule_id,
        )
        self.assertEqual(artifact["evidence_hashes"]["learned_trial_or_test_pdf_sha256"]["sha256"], sha256_bytes(learned_bytes))
        self.assertEqual(artifact["evidence_hashes"]["production_readiness_report_sha256"]["sha256"], sha256_bytes(readiness_bytes))
        self.assertEqual(artifact["evidence_hashes"]["production_test_report_sha256"]["sha256"], sha256_bytes(production_bytes))

    def test_forbidden_terminal_states_are_rejected(self) -> None:
        artifact = regen.build_artifact(
            job_dir=self.job,
            repo_root=self.repo,
            candidate_id="approved",
            rule_id=self.rule_id,
        )
        self.assertEqual(artifact["result"], "BLOCKED")
        self.assertIn("forbidden_terminal_state_detected:candidate_id:approved", artifact["blockers"])

    def test_artifact_writer_writes_sidecar_only(self) -> None:
        self.make_complete_artifacts()
        artifact = self.build()
        out = regen.artifact_path(self.job)
        regen.write_json_atomic(out, artifact)
        self.assertTrue(out.exists())
        self.assertFalse(artifact["package_status_mutation_performed"])
        self.assertEqual(artifact["protected_mutation_count"], 0)


if __name__ == "__main__":
    unittest.main()
