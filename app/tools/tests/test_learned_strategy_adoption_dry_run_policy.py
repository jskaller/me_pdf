from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_adoption_dry_run import (
    DRY_RUN_ARTIFACT_NAME,
    MANDATORY_SAFETY_FLAGS,
    write_learned_strategy_adoption_dry_run_plan,
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LearnedStrategyAdoptionDryRunPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        self.repair = self.root / "app" / "tools" / "repair"
        self.repair.mkdir(parents=True)
        self.rule_map = self.root / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.rule_map.parent.mkdir(parents=True, exist_ok=True)
        self.rule_map.write_text('{"rules": []}\n', encoding="utf-8")
        (self.repair / "README.md").write_text("repair tools\n", encoding="utf-8")
        (self.job / "STATUS.json").write_text('{"overall_result":"ESCALATION"}\n', encoding="utf-8")
        package = self.job / "package"
        package.mkdir()
        (package / "AUDIT_REPORT.md").write_text("audit\n", encoding="utf-8")
        (package / "STATUS.json").write_text('{"overall_result":"ESCALATION"}\n', encoding="utf-8")
        self.design_path = self.audit / "learned_strategy_adoption_policy_design.json"
        self.write_design()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def design_payload(self):
        hashes = {
            "production_readiness_report_sha256": sha256_text("readiness"),
            "production_test_report_sha256": sha256_text("test"),
            "production_test_review_report_sha256": sha256_text("review"),
            "normal_final_pdf_sha256": sha256_text("normal"),
            "learned_trial_or_test_pdf_sha256": sha256_text("learned"),
        }
        artifacts = {
            "production_testing_readiness_report": str(self.audit / "learned_strategy_production_testing_readiness_report.json"),
            "production_test_report": str(self.audit / "learned_strategy_production_test.json"),
            "production_test_review_report": str(self.audit / "learned_strategy_production_test_review.json"),
            "normal_final_pdf": str(self.job / "final.pdf"),
            "learned_trial_or_test_pdf": str(self.audit / "learned_trial.pdf"),
        }
        return {
            "schema_version": "learned-strategy-adoption-policy-design.v1",
            "mode": "adoption_policy_design_only",
            "policy_design_outcome": "policy_design_recorded",
            "adoption_plan": None,
            "reviewer": "qa-reviewer",
            "candidate_id": "candidate-1",
            "rule_id": "pdf_ua-1_7.21.7",
            "policy": {
                "adoption_policy_design_only": True,
                "adoption_plan_created": False,
                "adoption_apply_performed": False,
                "candidate_is_adoptable": False,
                "candidate_approved": False,
                "candidate_production_ready": False,
                "final_pdf_adoption_performed": False,
                "production_repair_replacement_performed": False,
                "verdict_softening_performed": False,
                "package_status_mutation_performed": False,
                "normal_final_pdf_remains_authoritative": True,
                "rule_map_mutation_performed": False,
                "app_tools_repair_mutation_performed": False,
                "rollback_execution_performed": False,
            },
            "evidence_artifacts": artifacts,
            "evidence_hashes": hashes,
            "forbidden_terminal_states": [
                "approved",
                "adoptable",
                "production_ready",
                "ready_for_adoption",
                "adoption_unblocked",
                "apply_ready",
            ],
        }

    def write_design(self, mutate=None):
        payload = self.design_payload()
        if mutate:
            mutate(payload)
        self.design_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def run_plan(self, **kwargs):
        return write_learned_strategy_adoption_dry_run_plan(
            job_dir=self.job,
            repo_root=self.root,
            **kwargs,
        )

    def test_missing_policy_design_artifact_blocks_dry_run_planning(self):
        self.design_path.unlink()
        payload = self.run_plan()
        self.assertEqual(payload["dry_run_outcome"], "adoption_dry_run_blocked")
        self.assertIn("missing_policy_design_artifact", payload["blockers"])

    def test_policy_design_artifact_that_is_not_design_only_blocks(self):
        self.write_design(lambda p: p["policy"].update({"adoption_apply_performed": True}))
        payload = self.run_plan()
        self.assertEqual(payload["dry_run_outcome"], "adoption_dry_run_blocked")
        self.assertIn("policy_design_flag_not_design_only:adoption_apply_performed", payload["blockers"])

    def test_missing_candidate_id_blocks_dry_run_planning(self):
        self.write_design(lambda p: p.__setitem__("candidate_id", ""))
        payload = self.run_plan()
        self.assertIn("missing_candidate_id", payload["blockers"])

    def test_missing_rule_id_blocks_dry_run_planning(self):
        self.write_design(lambda p: p.__setitem__("rule_id", ""))
        payload = self.run_plan()
        self.assertIn("missing_rule_id", payload["blockers"])

    def test_missing_required_evidence_hashes_records_incomplete_dry_run(self):
        self.write_design(lambda p: p["evidence_hashes"].pop("normal_final_pdf_sha256"))
        payload = self.run_plan()
        self.assertEqual(payload["dry_run_outcome"], "adoption_dry_run_incomplete")
        self.assertIn("missing_evidence_hash:normal_final_pdf_sha256", payload["incomplete_reasons"])

    def test_forbidden_terminal_states_are_rejected(self):
        self.write_design(lambda p: p.__setitem__("terminal_state", "apply_ready"))
        payload = self.run_plan()
        self.assertEqual(payload["dry_run_outcome"], "adoption_dry_run_blocked")
        self.assertTrue(any(b.startswith("forbidden_terminal_state_present") for b in payload["blockers"]))

    def test_valid_policy_design_creates_dry_run_plan_artifact(self):
        payload = self.run_plan(operator="operator-1")
        self.assertEqual(payload["dry_run_outcome"], "adoption_dry_run_plan_recorded")
        self.assertTrue((self.audit / DRY_RUN_ARTIFACT_NAME).exists())
        self.assertEqual(payload["candidate_id"], "candidate-1")
        self.assertEqual(payload["rule_id"], "pdf_ua-1_7.21.7")

    def test_dry_run_artifact_includes_all_no_adoption_no_mutation_flags(self):
        payload = self.run_plan(operator="operator-1")
        for key, expected in MANDATORY_SAFETY_FLAGS.items():
            self.assertIs(payload["safety_flags"][key], expected)

    def test_dry_run_includes_future_backup_requirements_but_creates_no_backup(self):
        payload = self.run_plan(operator="operator-1")
        self.assertTrue(payload["files_that_would_need_backups_in_future_apply"])
        self.assertFalse(payload["safety_flags"]["backup_created"])
        self.assertFalse(list(self.root.rglob("*backup*")))

    def test_dry_run_includes_future_rollback_requirements_but_executes_no_rollback(self):
        payload = self.run_plan(operator="operator-1")
        self.assertTrue(payload["rollback_steps_required_for_future_apply"])
        self.assertFalse(payload["safety_flags"]["rollback_execution_performed"])

    def test_lists_files_that_would_change_but_mutates_none(self):
        before = self.rule_map.read_text(encoding="utf-8")
        payload = self.run_plan(operator="operator-1")
        self.assertTrue(payload["files_allowed_to_change_in_future_apply"])
        self.assertEqual(self.rule_map.read_text(encoding="utf-8"), before)
        self.assertEqual(payload["protected_mutation_count"], 0)

    def test_does_not_mark_candidate_approved(self):
        payload = self.run_plan(operator="operator-1")
        self.assertFalse(payload["safety_flags"]["candidate_approved"])

    def test_does_not_mark_candidate_adoptable(self):
        payload = self.run_plan(operator="operator-1")
        self.assertFalse(payload["safety_flags"]["candidate_is_adoptable"])

    def test_does_not_mark_candidate_production_ready(self):
        payload = self.run_plan(operator="operator-1")
        self.assertFalse(payload["safety_flags"]["candidate_production_ready"])

    def test_does_not_mutate_authoritative_status_json(self):
        status = self.job / "STATUS.json"
        before = status.read_bytes()
        self.run_plan(operator="operator-1")
        self.assertEqual(status.read_bytes(), before)

    def test_does_not_mutate_package_deliverables(self):
        package_file = self.job / "package" / "AUDIT_REPORT.md"
        before = package_file.read_bytes()
        self.run_plan(operator="operator-1")
        self.assertEqual(package_file.read_bytes(), before)

    def test_does_not_mutate_app_tools_repair(self):
        repair_file = self.repair / "README.md"
        before = repair_file.read_bytes()
        self.run_plan(operator="operator-1")
        self.assertEqual(repair_file.read_bytes(), before)

    def test_does_not_mutate_rule_repair_map(self):
        before = self.rule_map.read_bytes()
        self.run_plan(operator="operator-1")
        self.assertEqual(self.rule_map.read_bytes(), before)

    def test_requires_explicit_future_apply(self):
        payload = self.run_plan(operator="operator-1")
        self.assertIn("--apply", payload["explicit_future_apply_requirement"])
        self.assertIn("blocked_pending_explicit_future_apply", payload["blockers"])

    def test_says_future_apply_is_not_implemented(self):
        payload = self.run_plan(operator="operator-1")
        self.assertTrue(payload["future_apply_not_implemented"])
        self.assertTrue(payload["plan_is_non_executable_without_future_patch"])
        self.assertFalse(payload["safety_flags"]["adoption_apply_performed"])


if __name__ == "__main__":
    unittest.main()
