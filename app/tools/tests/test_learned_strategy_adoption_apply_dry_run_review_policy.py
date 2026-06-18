from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Tuple

from tools.audit import learned_strategy_adoption_apply_dry_run as dry_run
from tools.audit import learned_strategy_adoption_apply_dry_run_review as review

CANDIDATE_ID = "pdf_ua-1_7.21.7__7747531055698f0c"
RULE_ID = "PDF/UA-1/7.21.7"


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ApplyDryRunReviewPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo_root = self.root / "repo"
        self.job_dir = self.root / "job"
        (self.repo_root / "app" / "tools" / "audit").mkdir(parents=True)
        (self.repo_root / "app" / "tools" / "repair").mkdir(parents=True)
        (self.repo_root / "app" / "tools" / "repair" / "README.md").write_text("repair\n", encoding="utf-8")
        write_json(self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json", {"rules": {}})
        write_json(self.job_dir / "STATUS.json", {"overall_result": "ESCALATION"})
        write_json(self.job_dir / "deliverables" / "STATUS.json", {"overall_result": "ESCALATION"})
        write_json(self.job_dir / "output" / "STATUS.json", {"overall_result": "ESCALATION"})
        write_json(self.job_dir / "package" / "STATUS.json", {"overall_result": "ESCALATION"})
        self.apply_dry_run_path = self.job_dir / "audit" / "learned_strategy_adoption_apply_dry_run.json"
        write_json(self.apply_dry_run_path, self.valid_simulation())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def valid_simulation(self) -> Dict[str, Any]:
        return {
            "schema_version": dry_run.SCHEMA_VERSION,
            "mode": "adoption_apply_dry_run_only",
            "result": "PASS",
            "apply_dry_run_simulation_outcome": "apply_dry_run_simulation_recorded",
            "candidate_id": CANDIDATE_ID,
            "rule_id": RULE_ID,
            "operator": "Patch 21B operator",
            "simulation_text_only": True,
            "future_apply_transaction_steps_policy_text_only": ["text only"],
            "future_backup_manifest_entries_policy_text_only": ["text only"],
            "future_rollback_manifest_entries_policy_text_only": ["text only"],
            "safety_flags": dict(dry_run.MANDATORY_SAFETY_FLAGS),
        }

    def build(
        self,
        *,
        reviewer: str = "Patch 21B reviewer",
        candidate_id: str = CANDIDATE_ID,
        rule_id: str = RULE_ID,
        expected_hash: str | None = None,
        review_decision: str = "apply_dry_run_review_recorded",
        review_notes: list[str] | None = None,
        known_risks: list[str] | None = None,
    ) -> Dict[str, Any]:
        return review.build_artifact(
            job_dir=self.job_dir,
            repo_root=self.repo_root,
            apply_dry_run_path=self.apply_dry_run_path,
            reviewer=reviewer,
            candidate_id=candidate_id,
            rule_id=rule_id,
            review_notes=review_notes if review_notes is not None else ["simulation reviewed as dry-run only"],
            known_risks=known_risks if known_risks is not None else ["future apply remains unimplemented"],
            review_decision=review_decision,
            expected_apply_dry_run_sha256=expected_hash,
        )

    def protected_before_after(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        artifact = self.build()
        return artifact["protected_snapshot_before"], artifact["protected_snapshot_after"]

    def test_missing_apply_dry_run_simulation_blocks_review(self) -> None:
        self.apply_dry_run_path.unlink()
        artifact = self.build()
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_apply_dry_run_simulation", artifact["blockers"])

    def test_missing_reviewer_blocks_review(self) -> None:
        artifact = self.build(reviewer="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_reviewer", artifact["blockers"])

    def test_missing_candidate_id_blocks_review(self) -> None:
        artifact = self.build(candidate_id="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_candidate_id", artifact["blockers"])

    def test_missing_rule_id_blocks_review(self) -> None:
        artifact = self.build(rule_id="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_rule_id", artifact["blockers"])

    def test_candidate_mismatch_blocks_review(self) -> None:
        artifact = self.build(candidate_id="other")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("candidate_id_mismatch", artifact["blockers"])

    def test_rule_mismatch_blocks_review(self) -> None:
        artifact = self.build(rule_id="PDF/UA-1/other")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("rule_id_mismatch", artifact["blockers"])

    def test_simulation_hash_mismatch_blocks_review(self) -> None:
        artifact = self.build(expected_hash="0" * 64)
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("apply_dry_run_simulation_hash_mismatch", artifact["blockers"])

    def test_forbidden_review_states_are_rejected(self) -> None:
        artifact = self.build(review_decision="approved")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("review_decision_not_allowed", artifact["blockers"])

    def test_valid_simulation_creates_review_artifact(self) -> None:
        artifact = self.build()
        self.assertEqual("PASS", artifact["result"])
        self.assertEqual("apply_dry_run_review_recorded", artifact["review_decision"])
        review.write_json(review.artifact_path(self.job_dir), artifact)
        self.assertTrue(review.artifact_path(self.job_dir).exists())

    def test_review_artifact_includes_all_no_apply_no_adoption_no_mutation_flags(self) -> None:
        artifact = self.build()
        for key, expected in review.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(expected, artifact["safety_flags"][key])
            self.assertEqual(expected, artifact[key])

    def test_review_artifact_records_simulation_hash(self) -> None:
        artifact = self.build()
        self.assertEqual(review.sha256_file(self.apply_dry_run_path), artifact["apply_dry_run_simulation"]["sha256"])
        self.assertTrue(artifact["safety_flags"]["apply_dry_run_hash_recorded"])

    def test_review_artifact_records_known_risks_and_notes(self) -> None:
        artifact = self.build(review_notes=["note"], known_risks=["risk"])
        self.assertEqual(["note"], artifact["review_notes"])
        self.assertEqual(["risk"], artifact["known_risks"])

    def test_review_artifact_does_not_mark_candidate_approved(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_approved"])

    def test_review_artifact_does_not_mark_candidate_adoptable(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_is_adoptable"])

    def test_review_artifact_does_not_mark_candidate_production_ready(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_production_ready"])

    def test_review_artifact_does_not_mark_candidate_apply_ready(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["safety_flags"]["candidate_apply_ready"])
        self.assertFalse(artifact["apply_ready"])
        self.assertFalse(artifact["freeze_is_apply_ready"])

    def test_review_artifact_does_not_create_backups(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["backup_manifest_created"])
        self.assertFalse(artifact["safety_flags"]["backup_created"])

    def test_review_artifact_does_not_execute_rollback(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["rollback_manifest_created"])
        self.assertFalse(artifact["safety_flags"]["rollback_execution_performed"])

    def test_review_artifact_does_not_mutate_authoritative_status_json(self) -> None:
        before, after = self.protected_before_after()
        status_path = str(self.job_dir / "STATUS.json")
        self.assertEqual(before[status_path], after[status_path])

    def test_review_artifact_does_not_mutate_package_deliverables(self) -> None:
        before, after = self.protected_before_after()
        for rel in ["deliverables/STATUS.json", "output/STATUS.json", "package/STATUS.json"]:
            path = str(self.job_dir / rel)
            self.assertEqual(before[path], after[path])

    def test_review_artifact_does_not_mutate_app_tools_repair(self) -> None:
        before, after = self.protected_before_after()
        repair_path = str(self.repo_root / "app" / "tools" / "repair" / "README.md")
        self.assertEqual(before[repair_path], after[repair_path])

    def test_review_artifact_does_not_mutate_rule_repair_map(self) -> None:
        before, after = self.protected_before_after()
        map_path = str(self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json")
        self.assertEqual(before[map_path], after[map_path])


if __name__ == "__main__":
    unittest.main()
