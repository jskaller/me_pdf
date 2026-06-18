import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_adoption_dry_run_review import (
    FORBIDDEN_TERMINAL_STATES,
    MANDATORY_SAFETY_FLAGS,
    write_learned_strategy_adoption_dry_run_review,
)


CANDIDATE_ID = "smoke-changed-valid-candidate"
RULE_ID = "PDF/UA-1/7.21.7"
REVIEWER = "Patch 20C reviewer"
DECISION = "dry_run_review_recorded"


class LearnedStrategyAdoptionDryRunReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        self.rule_map = self.root / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.repair_dir = self.root / "app" / "tools" / "repair"
        self.rule_map.parent.mkdir(parents=True)
        self.repair_dir.mkdir(parents=True)
        self.rule_map.write_text('{"rules": []}\n', encoding="utf-8")
        (self.repair_dir / "README.md").write_text("repair files\n", encoding="utf-8")
        self.status = self.job / "STATUS.json"
        self.status.write_text('{"overall_result": "ESCALATION"}\n', encoding="utf-8")
        self.package_status = self.job / "package" / "STATUS.json"
        self.package_status.parent.mkdir(parents=True)
        self.package_status.write_text('{"package": true}\n', encoding="utf-8")
        self.plan_path = self.audit / "learned_strategy_adoption_dry_run_plan.json"
        self.write_plan()

    def tearDown(self):
        self.tmp.cleanup()

    def sha(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def write_json(self, path, payload):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_plan(self, **overrides):
        payload = {
            "schema_version": "learned-strategy-adoption-dry-run.v1",
            "created_at": "2026-06-18T12:00:00Z",
            "mode": "adoption_dry_run_planner_only",
            "dry_run_outcome": "adoption_dry_run_plan_recorded",
            "candidate_id": CANDIDATE_ID,
            "rule_id": RULE_ID,
            "protected_mutation_count": 0,
            "blockers": [
                "blocked_pending_explicit_future_apply",
                "dry_run_only_no_apply_performed",
            ],
            "safety_flags": {
                "adoption_dry_run_only": True,
                "adoption_plan_created": True,
                "adoption_apply_performed": False,
                "backup_created": False,
                "rollback_execution_performed": False,
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
                "plan_is_non_executable_without_future_patch": True,
                "future_apply_not_implemented": True,
            },
        }
        payload.update(overrides)
        self.write_json(self.plan_path, payload)
        return payload

    def review(self, **overrides):
        kwargs = {
            "job_dir": self.job,
            "dry_run_plan_path": self.plan_path,
            "dry_run_plan_sha256": self.sha(self.plan_path),
            "reviewer": REVIEWER,
            "candidate_id": CANDIDATE_ID,
            "rule_id": RULE_ID,
            "review_decision": DECISION,
            "review_notes": ["Evidence reviewed for future discussion only."],
            "known_risks": ["No risk acceptance; risk list recorded only."],
            "repo_root": self.root,
        }
        kwargs.update(overrides)
        return write_learned_strategy_adoption_dry_run_review(**kwargs)

    def assertBlocked(self, payload, blocker):
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn(blocker, payload["blockers"])

    def test_missing_dry_run_plan_blocks_review(self):
        missing = self.audit / "missing.json"
        payload = self.review(dry_run_plan_path=missing, dry_run_plan_sha256="abc")
        self.assertBlocked(payload, "missing_dry_run_plan")

    def test_missing_reviewer_blocks_review(self):
        payload = self.review(reviewer="")
        self.assertBlocked(payload, "missing_reviewer_identity")

    def test_missing_candidate_id_blocks_review(self):
        payload = self.review(candidate_id="")
        self.assertBlocked(payload, "missing_candidate_id")

    def test_missing_rule_id_blocks_review(self):
        payload = self.review(rule_id="")
        self.assertBlocked(payload, "missing_rule_id")

    def test_mismatched_candidate_id_blocks_review(self):
        payload = self.review(candidate_id="other-candidate")
        self.assertBlocked(payload, "candidate_id_mismatch")

    def test_mismatched_rule_id_blocks_review(self):
        payload = self.review(rule_id="PDF/UA-1/other")
        self.assertBlocked(payload, "rule_id_mismatch")

    def test_mismatched_dry_run_plan_hash_blocks_review(self):
        payload = self.review(dry_run_plan_sha256="0" * 64)
        self.assertBlocked(payload, "dry_run_plan_hash_mismatch")

    def test_forbidden_terminal_states_are_rejected(self):
        for state in sorted(FORBIDDEN_TERMINAL_STATES):
            with self.subTest(state=state):
                payload = self.review(review_decision=state)
                self.assertEqual(payload["result"], "BLOCKED")

    def test_valid_dry_run_plan_creates_review_artifact(self):
        payload = self.review()
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["review_decision"], DECISION)
        self.assertTrue((self.audit / "learned_strategy_adoption_dry_run_review.json").exists())

    def test_review_artifact_includes_all_no_adoption_no_mutation_flags(self):
        payload = self.review()
        for name, expected in MANDATORY_SAFETY_FLAGS.items():
            self.assertIs(payload["safety_flags"][name], expected)
            self.assertIs(payload[name], expected)

    def test_review_artifact_records_plan_hash(self):
        payload = self.review()
        self.assertTrue(payload["dry_run_plan_hash_recorded"])
        self.assertEqual(payload["dry_run_plan"]["sha256"], self.sha(self.plan_path))
        self.assertTrue(payload["dry_run_plan"]["hash_match"])

    def test_review_artifact_records_known_risks_and_notes(self):
        payload = self.review(
            review_notes=["note one", "note two"],
            known_risks=["risk one", "risk two"],
        )
        self.assertEqual(payload["review_notes"], ["note one", "note two"])
        self.assertEqual(payload["known_risks"], ["risk one", "risk two"])

    def test_review_artifact_does_not_mark_candidate_approved(self):
        self.assertFalse(self.review()["candidate_approved"])

    def test_review_artifact_does_not_mark_candidate_adoptable(self):
        self.assertFalse(self.review()["candidate_is_adoptable"])

    def test_review_artifact_does_not_mark_candidate_production_ready(self):
        self.assertFalse(self.review()["candidate_production_ready"])

    def test_review_artifact_does_not_mark_candidate_apply_ready(self):
        self.assertFalse(self.review()["candidate_apply_ready"])

    def test_review_artifact_does_not_create_backups(self):
        payload = self.review()
        self.assertFalse(payload["backup_created"])
        self.assertEqual(list(self.job.rglob("*backup*")), [])

    def test_review_artifact_does_not_execute_rollback(self):
        payload = self.review()
        self.assertFalse(payload["rollback_execution_performed"])
        self.assertEqual(list(self.job.rglob("*rollback*")), [])

    def test_review_artifact_does_not_mutate_authoritative_status_json(self):
        before = self.sha(self.status)
        payload = self.review()
        self.assertEqual(self.sha(self.status), before)
        self.assertFalse(payload["package_status_mutation_performed"])

    def test_review_artifact_does_not_mutate_package_deliverables(self):
        before = self.sha(self.package_status)
        payload = self.review()
        self.assertEqual(self.sha(self.package_status), before)
        self.assertFalse(payload["package_status_mutation_performed"])

    def test_review_artifact_does_not_mutate_app_tools_repair(self):
        repair_file = self.repair_dir / "README.md"
        before = self.sha(repair_file)
        payload = self.review()
        self.assertEqual(self.sha(repair_file), before)
        self.assertFalse(payload["app_tools_repair_mutation_performed"])

    def test_review_artifact_does_not_mutate_rule_repair_map(self):
        before = self.sha(self.rule_map)
        payload = self.review()
        self.assertEqual(self.sha(self.rule_map), before)
        self.assertFalse(payload["rule_map_mutation_performed"])
        self.assertEqual(payload["protected_mutation_count"], 0)


if __name__ == "__main__":
    unittest.main()
