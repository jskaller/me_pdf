import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_production_test_review import (
    ALLOWED_REVIEW_DECISIONS,
    write_learned_strategy_production_test_review,
)


class LearnedStrategyProductionTestReviewPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        self.status = self.job / "STATUS.json"
        self.status.write_text(json.dumps({"overall_result": "ESCALATION"}, indent=2))
        self.package = self.job / "package"
        self.package.mkdir()
        self.package_status = self.package / "STATUS.json"
        self.package_status.write_text(json.dumps({"overall_result": "ESCALATION", "package": True}, indent=2))
        self.package_report = self.package / "AUDIT_REPORT.md"
        self.package_report.write_text("authoritative package report\n")
        self.repo = self.root
        self.repair_dir = self.repo / "app" / "tools" / "repair"
        self.repair_dir.mkdir(parents=True)
        self.repair_file = self.repair_dir / "fix_existing.py"
        self.repair_file.write_text("# existing repair\n")
        self.rule_map = self.repo / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.rule_map.parent.mkdir(parents=True, exist_ok=True)
        self.rule_map.write_text(json.dumps({"rules": {}}, indent=2))
        self.normal_pdf = self.job / "repair" / "normal.pdf"
        self.normal_pdf.parent.mkdir()
        self.normal_pdf.write_bytes(b"normal-pdf")
        self.learned_pdf = self.audit / "learned_strategy_production_test" / "candidate" / "learned_production_test.pdf"
        self.learned_pdf.parent.mkdir(parents=True)
        self.learned_pdf.write_bytes(b"learned-pdf")
        self.production_report = self.audit / "learned_strategy_production_test_report.json"
        self._write_production_report()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_production_report(self):
        payload = {
            "schema_version": "learned-strategy-production-test.v1",
            "result": "PASS",
            "production_test_performed": True,
            "summary": {
                "production_test_diagnostic_complete": 1,
                "production_test_blocked": 0,
            },
            "policy": {
                "production_test_only": True,
                "candidate_is_adoptable": False,
                "final_pdf_adoption_performed": False,
                "production_repair_replacement_performed": False,
                "verdict_softening_performed": False,
                "package_status_mutation_performed": False,
                "normal_final_pdf_remains_authoritative": True,
            },
            "results": [
                {
                    "rule_id": "PDF/UA-1/7.21.7",
                    "candidate_id": "candidate-1",
                    "attempt_id": "attempt-1",
                    "readiness_decision": "production_testing_evidence_complete",
                    "trial_decision": "trial_needs_manual_review",
                    "production_test_decision": "production_test_diagnostic_complete",
                    "normal_final_pdf": str(self.normal_pdf),
                    "learned_trial_pdf": str(self.learned_pdf),
                    "production_test_sidecar_pdf": str(self.learned_pdf),
                    "normal_final_sha256": hashlib.sha256(b"normal-pdf").hexdigest(),
                    "learned_trial_sha256": hashlib.sha256(b"learned-pdf").hexdigest(),
                    "production_test_sidecar_sha256": hashlib.sha256(b"learned-pdf").hexdigest(),
                    "learned_differs_from_normal": True,
                    "candidate_is_adoptable": False,
                    "final_pdf_adoption_performed": False,
                    "production_repair_replacement_performed": False,
                    "verdict_softening_performed": False,
                    "package_status_mutation_performed": False,
                }
            ],
        }
        self.production_report.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def _review(self, **overrides):
        kwargs = {
            "job_dir": self.job,
            "production_test_report_path": self.production_report,
            "reviewer": "QA Reviewer",
            "candidate_id": "candidate-1",
            "rule_id": "PDF/UA-1/7.21.7",
            "review_decision": "review_requires_followup",
            "manual_review_notes": "Evidence reviewed; diagnostic only.",
            "known_risks": "Manual review remains required.",
            "repo_root": self.repo,
        }
        kwargs.update(overrides)
        return write_learned_strategy_production_test_review(**kwargs)

    def test_missing_production_test_report_blocks_review(self):
        payload = self._review(production_test_report_path=self.audit / "missing.json")
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("missing_production_test_report", payload["blockers"])

    def test_missing_reviewer_blocks_review(self):
        payload = self._review(reviewer="")
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("missing_reviewer", payload["blockers"])

    def test_missing_candidate_id_blocks_review(self):
        payload = self._review(candidate_id="")
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("missing_candidate_id", payload["blockers"])

    def test_missing_rule_id_blocks_review(self):
        payload = self._review(rule_id="")
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("missing_rule_id", payload["blockers"])

    def test_mismatched_report_hash_blocks_review(self):
        payload = self._review(report_sha256="0" * 64)
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("production_test_report_hash_mismatch", payload["blockers"])

    def test_matching_report_hash_allows_review(self):
        actual = hashlib.sha256(self.production_report.read_bytes()).hexdigest()
        payload = self._review(report_sha256=actual)
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["production_test_report_sha256"], actual)

    def test_review_artifact_is_written_for_valid_report(self):
        payload = self._review()
        path = self.audit / "learned_strategy_production_test_review.json"
        self.assertTrue(path.exists())
        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["result"], "PASS")
        self.assertTrue(on_disk["review_performed"])
        self.assertEqual(payload["candidate_id"], "candidate-1")

    def test_review_artifact_includes_no_adoption_flags(self):
        payload = self._review()
        policy = payload["policy"]
        self.assertFalse(policy["review_is_adoption"])
        self.assertFalse(policy["candidate_is_adoptable"])
        self.assertFalse(policy["final_pdf_adoption_performed"])
        self.assertFalse(policy["production_repair_replacement_performed"])
        self.assertFalse(policy["verdict_softening_performed"])
        self.assertFalse(policy["package_status_mutation_performed"])
        self.assertTrue(policy["normal_final_pdf_remains_authoritative"])
        self.assertFalse(policy["rule_map_mutation_performed"])
        self.assertFalse(policy["app_tools_repair_mutation_performed"])
        self.assertFalse(policy["review_makes_candidate_production_ready"])

    def test_review_decisions_cannot_be_approved_or_adoptive(self):
        forbidden = ["approved", "adoptable", "production_ready", "ready_for_adoption"]
        for decision in forbidden:
            with self.subTest(decision=decision):
                payload = self._review(review_decision=decision)
                self.assertEqual(payload["result"], "BLOCKED")
                self.assertTrue(payload["blockers"])
        self.assertEqual(ALLOWED_REVIEW_DECISIONS, {"review_recorded", "review_requires_followup", "review_rejected"})

    def test_review_does_not_mutate_authoritative_status_json(self):
        before = self.status.read_bytes()
        package_before = self.package_status.read_bytes()
        payload = self._review()
        self.assertEqual(self.status.read_bytes(), before)
        self.assertEqual(self.package_status.read_bytes(), package_before)
        self.assertEqual(payload["authoritative_status_json_sha256_before"], payload["authoritative_status_json_sha256_after"])

    def test_review_does_not_mutate_package_deliverables(self):
        before = {p: p.read_bytes() for p in [self.package_status, self.package_report]}
        payload = self._review()
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(payload["protected_mutation_count"], 0)

    def test_review_does_not_mutate_app_tools_repair(self):
        before = self.repair_file.read_bytes()
        payload = self._review()
        self.assertEqual(self.repair_file.read_bytes(), before)
        self.assertEqual(payload["protected_mutation_count"], 0)

    def test_review_does_not_mutate_rule_map(self):
        before = self.rule_map.read_bytes()
        payload = self._review()
        self.assertEqual(self.rule_map.read_bytes(), before)
        self.assertEqual(payload["rule_map_sha256_before"], payload["rule_map_sha256_after"])

    def test_review_records_known_risks_and_manual_notes(self):
        payload = self._review(
            manual_review_notes="Reviewed report hash and sidecar output.",
            known_risks="Manual visual inspection still required.",
        )
        self.assertEqual(payload["manual_review_notes"], ["Reviewed report hash and sidecar output."])
        self.assertEqual(payload["known_risks"], ["Manual visual inspection still required."])
        self.assertTrue(payload["follow_up_required"])


    def test_cli_review_requires_followup_sets_follow_up_required_when_flag_omitted(self):
        script = Path(__file__).resolve().parents[1] / "audit" / "learned_strategy_production_test_review.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--job-dir",
                str(self.job),
                "--production-test-report",
                str(self.production_report),
                "--reviewer",
                "QA Reviewer",
                "--candidate-id",
                "candidate-1",
                "--rule-id",
                "PDF/UA-1/7.21.7",
                "--review-decision",
                "review_requires_followup",
                "--review-notes",
                "Evidence reviewed; diagnostic only.",
                "--known-risks",
                "Manual review remains required.",
                "--repo-root",
                str(self.repo),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["review_decision"], "review_requires_followup")
        self.assertTrue(payload["follow_up_required"])
        self.assertEqual(payload["result"], "PASS")

    def test_missing_notes_and_risks_blocks_review(self):
        payload = self._review(manual_review_notes="", known_risks="")
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertIn("missing_review_notes_or_known_risks", payload["blockers"])


if __name__ == "__main__":
    unittest.main()
