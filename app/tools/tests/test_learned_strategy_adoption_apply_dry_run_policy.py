from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Tuple

from tools.audit import learned_strategy_adoption_apply_dry_run as dry_run

CANDIDATE_ID = "pdf_ua-1_7.21.7__7747531055698f0c"
RULE_ID = "PDF/UA-1/7.21.7"


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ApplyDryRunPolicyTests(unittest.TestCase):
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
        self.design_path = self.job_dir / "audit" / "learned_strategy_adoption_apply_policy_design.json"
        write_json(self.design_path, self.valid_design())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def valid_design(self) -> Dict[str, Any]:
        hashes = {key: "a" * 64 for key in dry_run.REQUIRED_DESIGN_HASH_KEYS}
        return {
            "schema_version": dry_run.APPLY_POLICY_DESIGN_SCHEMA_VERSION,
            "mode": "adoption_apply_policy_design_only",
            "result": "PASS",
            "apply_policy_design_outcome": "apply_policy_design_recorded",
            "candidate_id": CANDIDATE_ID,
            "rule_id": RULE_ID,
            "future_apply_requirements": {
                "source_hashes_recorded_for_policy_discussion": hashes,
            },
            "safety_flags": {
                "adoption_apply_policy_design_only": True,
                "apply_policy_design_recorded": True,
                "normal_final_pdf_remains_authoritative": True,
                "future_apply_not_implemented": True,
                "future_rollback_not_implemented": True,
                **{key: False for key in dry_run.REQUIRED_DESIGN_FALSE_FLAGS},
            },
        }

    def build(self, *, operator: str = "Patch 21B operator", candidate_id: str = CANDIDATE_ID, rule_id: str = RULE_ID) -> Dict[str, Any]:
        return dry_run.build_artifact(
            job_dir=self.job_dir,
            repo_root=self.repo_root,
            design_path=self.design_path,
            operator=operator,
            candidate_id=candidate_id,
            rule_id=rule_id,
        )

    def protected_before_after(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        artifact = self.build()
        return artifact["protected_snapshot_before"], artifact["protected_snapshot_after"]

    def test_missing_apply_policy_design_blocks_simulation(self) -> None:
        self.design_path.unlink()
        artifact = self.build()
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_apply_policy_design", artifact["blockers"])

    def test_apply_policy_design_that_is_not_design_only_blocks_simulation(self) -> None:
        design = self.valid_design()
        design["mode"] = "apply_policy_design_mutating"
        write_json(self.design_path, design)
        artifact = self.build()
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("apply_policy_design_not_design_only", artifact["blockers"])

    def test_missing_reviewer_operator_blocks_simulation(self) -> None:
        artifact = self.build(operator="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_operator", artifact["blockers"])

    def test_missing_candidate_id_blocks_simulation(self) -> None:
        artifact = self.build(candidate_id="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_candidate_id", artifact["blockers"])

    def test_missing_rule_id_blocks_simulation(self) -> None:
        artifact = self.build(rule_id="")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("missing_rule_id", artifact["blockers"])

    def test_mismatched_candidate_id_blocks_simulation(self) -> None:
        artifact = self.build(candidate_id="other")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("candidate_id_mismatch", artifact["blockers"])

    def test_mismatched_rule_id_blocks_simulation(self) -> None:
        artifact = self.build(rule_id="PDF/UA-1/other")
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertIn("rule_id_mismatch", artifact["blockers"])

    def test_missing_required_artifact_hashes_records_incomplete(self) -> None:
        design = self.valid_design()
        design["future_apply_requirements"]["source_hashes_recorded_for_policy_discussion"].pop("normal_final_pdf_sha256")
        write_json(self.design_path, design)
        artifact = self.build()
        self.assertEqual("INCOMPLETE", artifact["result"])
        self.assertIn("missing_required_artifact_hash:normal_final_pdf_sha256", artifact["incomplete_reasons"])

    def test_forbidden_terminal_states_are_rejected(self) -> None:
        design = self.valid_design()
        design["candidate_state"] = "approved"
        write_json(self.design_path, design)
        artifact = self.build()
        self.assertEqual("BLOCKED", artifact["result"])
        self.assertTrue(any(item.startswith("forbidden_terminal_state_detected") for item in artifact["blockers"]))

    def test_valid_apply_policy_design_creates_simulation_artifact(self) -> None:
        artifact = self.build()
        self.assertEqual("PASS", artifact["result"])
        self.assertEqual("apply_dry_run_simulation_recorded", artifact["apply_dry_run_simulation_outcome"])
        dry_run.write_json(dry_run.artifact_path(self.job_dir), artifact)
        self.assertTrue(dry_run.artifact_path(self.job_dir).exists())

    def test_artifact_includes_all_no_apply_no_adoption_no_mutation_flags(self) -> None:
        artifact = self.build()
        for key, expected in dry_run.MANDATORY_SAFETY_FLAGS.items():
            self.assertEqual(expected, artifact["safety_flags"][key])
            self.assertEqual(expected, artifact[key])

    def test_artifact_does_not_create_apply_plan(self) -> None:
        artifact = self.build()
        self.assertIsNone(artifact["apply_plan"])
        self.assertFalse(artifact["safety_flags"]["apply_plan_created"])

    def test_artifact_does_not_mark_candidate_approved(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_approved"])

    def test_artifact_does_not_mark_candidate_adoptable(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_is_adoptable"])

    def test_artifact_does_not_mark_candidate_production_ready(self) -> None:
        self.assertFalse(self.build()["safety_flags"]["candidate_production_ready"])

    def test_artifact_does_not_mark_candidate_apply_ready(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["safety_flags"]["candidate_apply_ready"])
        self.assertFalse(artifact["apply_ready"])

    def test_artifact_does_not_create_backups(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["backup_manifest_created"])
        self.assertFalse(artifact["safety_flags"]["backup_created"])

    def test_artifact_does_not_execute_rollback(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact["rollback_manifest_created"])
        self.assertFalse(artifact["safety_flags"]["rollback_execution_performed"])

    def test_artifact_does_not_mutate_authoritative_status_json(self) -> None:
        before, after = self.protected_before_after()
        status_path = str(self.job_dir / "STATUS.json")
        self.assertEqual(before[status_path], after[status_path])

    def test_artifact_does_not_mutate_package_deliverables(self) -> None:
        before, after = self.protected_before_after()
        for rel in ["deliverables/STATUS.json", "output/STATUS.json", "package/STATUS.json"]:
            path = str(self.job_dir / rel)
            self.assertEqual(before[path], after[path])

    def test_artifact_does_not_mutate_app_tools_repair(self) -> None:
        before, after = self.protected_before_after()
        repair_path = str(self.repo_root / "app" / "tools" / "repair" / "README.md")
        self.assertEqual(before[repair_path], after[repair_path])

    def test_artifact_does_not_mutate_rule_repair_map(self) -> None:
        before, after = self.protected_before_after()
        map_path = str(self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json")
        self.assertEqual(before[map_path], after[map_path])

    def test_artifact_lists_future_apply_transaction_steps_as_simulation_text_only(self) -> None:
        artifact = self.build()
        self.assertTrue(artifact["simulation_text_only"])
        self.assertGreater(len(artifact["future_apply_transaction_steps_policy_text_only"]), 0)

    def test_artifact_lists_future_backup_manifest_entries_as_simulation_text_only(self) -> None:
        self.assertGreater(len(self.build()["future_backup_manifest_entries_policy_text_only"]), 0)

    def test_artifact_lists_future_rollback_manifest_entries_as_simulation_text_only(self) -> None:
        self.assertGreater(len(self.build()["future_rollback_manifest_entries_policy_text_only"]), 0)

    def test_artifact_lists_future_post_apply_validation_checks_as_simulation_text_only(self) -> None:
        self.assertGreater(len(self.build()["future_post_apply_validation_checks_policy_text_only"]), 0)

    def test_artifact_lists_future_post_rollback_validation_checks_as_simulation_text_only(self) -> None:
        self.assertGreater(len(self.build()["future_post_rollback_validation_checks_policy_text_only"]), 0)

    def test_artifact_records_abort_conditions_as_simulation_text_only(self) -> None:
        self.assertGreater(len(self.build()["future_abort_conditions_policy_text_only"]), 0)

    def test_artifact_requires_future_explicit_apply(self) -> None:
        self.assertTrue(self.build()["required_future_explicit_apply"])

    def test_artifact_confirms_future_apply_and_rollback_are_not_implemented(self) -> None:
        artifact = self.build()
        self.assertTrue(artifact["safety_flags"]["future_apply_not_implemented"])
        self.assertTrue(artifact["safety_flags"]["future_rollback_not_implemented"])


if __name__ == "__main__":
    unittest.main()
