import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_adoption_policy_design import (
    FORBIDDEN_TERMINAL_STATES,
    design_only_policy_flags,
    validate_policy_design_outcome,
    write_learned_strategy_adoption_policy_design,
)


class LearnedStrategyAdoptionPolicyDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_dir = self.root / "workspace" / "jobs" / "JOB1"
        self.audit_dir = self.job_dir / "audit"
        self.audit_dir.mkdir(parents=True)
        self.repo_root = self.root / "repo"
        self.repair_dir = self.repo_root / "app" / "tools" / "repair"
        self.repair_dir.mkdir(parents=True)
        self.rule_map = self.repo_root / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.rule_map.parent.mkdir(parents=True)
        self.rule_map.write_text('{"rules": {}}\n', encoding="utf-8")
        (self.repair_dir / "README.md").write_text("repair files stay unchanged\n", encoding="utf-8")
        self.status = self.job_dir / "STATUS.json"
        self.status.write_text('{"overall_result":"ESCALATION"}\n', encoding="utf-8")
        self.package = self.job_dir / "package"
        self.package.mkdir()
        (self.package / "AUDIT_REPORT.md").write_text("audit\n", encoding="utf-8")
        self.normal_pdf = self.audit_dir / "normal_final.pdf"
        self.learned_pdf = self.audit_dir / "learned_trial.pdf"
        self.normal_pdf.write_bytes(b"normal-final")
        self.learned_pdf.write_bytes(b"learned-trial")
        self.readiness = self.audit_dir / "learned_strategy_production_testing_readiness_report.json"
        self.readiness.write_text('{"summary":{"production_testing_evidence_complete":1}}\n', encoding="utf-8")
        self.prod_test = self.audit_dir / "learned_strategy_production_test_report.json"
        self.prod_test.write_text('{"result":"PASS"}\n', encoding="utf-8")
        self.review = self.audit_dir / "learned_strategy_production_test_review.json"
        self._write_review()

    def tearDown(self):
        self.tmp.cleanup()

    def _sha(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _write_review(self, **overrides):
        payload = {
            "schema_version": "learned-strategy-production-test-review.v1",
            "result": "PASS",
            "review_performed": True,
            "review_decision": "review_requires_followup",
            "candidate_id": "candidate-1",
            "rule_id": "PDF/UA-1/7.21.7",
            "reviewer": "reviewer-a",
            "production_test_report_path": str(self.prod_test),
            "production_test_report_sha256": self._sha(self.prod_test),
            "normal_final_pdf": str(self.normal_pdf),
            "learned_trial_pdf": str(self.learned_pdf),
            "manual_review_notes": ["Reviewed evidence; diagnostic only."],
            "known_risks": ["Manual review remains required."],
            "normal_vs_learned_comparison_summary": {
                "production_test_report_result": "PASS",
                "production_test_decision": "production_test_diagnostic_complete",
                "readiness_decision": "production_testing_evidence_complete",
                "trial_decision": "trial_needs_manual_review",
                "learned_differs_from_normal": True,
                "normal_final_sha256": self._sha(self.normal_pdf),
                "learned_trial_sha256": self._sha(self.learned_pdf),
            },
            "policy": {
                "review_is_adoption": False,
                "candidate_is_adoptable": False,
                "final_pdf_adoption_performed": False,
                "production_repair_replacement_performed": False,
                "verdict_softening_performed": False,
                "package_status_mutation_performed": False,
                "normal_final_pdf_remains_authoritative": True,
            },
        }
        payload.update(overrides)
        self.review.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _run(self, **kwargs):
        args = {
            "job_dir": self.job_dir,
            "production_test_review_report_path": self.review,
            "production_readiness_report_path": self.readiness,
            "reviewer": "policy reviewer",
            "candidate_id": "candidate-1",
            "rule_id": "PDF/UA-1/7.21.7",
            "repo_root": self.repo_root,
        }
        args.update(kwargs)
        return write_learned_strategy_adoption_policy_design(**args)

    def test_missing_production_test_review_report_blocks_policy_design(self):
        missing = self.audit_dir / "missing_review.json"
        result = self._run(production_test_review_report_path=missing)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("missing_production_test_review_report", result["blockers"])

    def test_missing_reviewer_blocks_policy_design(self):
        result = self._run(reviewer="")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("missing_reviewer", result["blockers"])

    def test_missing_candidate_id_blocks_policy_design(self):
        result = self._run(candidate_id="")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("missing_candidate_id", result["blockers"])

    def test_missing_rule_id_blocks_policy_design(self):
        result = self._run(rule_id="")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("missing_rule_id", result["blockers"])

    def test_missing_required_hashes_records_incomplete_policy_design(self):
        self._write_review(normal_vs_learned_comparison_summary={})
        result = self._run()
        self.assertEqual(result["result"], "INCOMPLETE")
        self.assertEqual(result["policy_design_outcome"], "policy_design_incomplete")
        self.assertFalse(result["evidence_package_complete_for_policy_discussion"])
        self.assertIn("normal_vs_learned_comparison_summary", result["missing_policy_discussion_prerequisites"])

    def test_forbidden_terminal_states_are_rejected(self):
        for state in sorted(FORBIDDEN_TERMINAL_STATES):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    validate_policy_design_outcome(state)
                result = self._run(policy_design_outcome=state)
                self.assertEqual(result["result"], "BLOCKED")
                self.assertTrue(any("forbidden_policy_design_outcome" in b for b in result["blockers"]))

    def test_valid_evidence_creates_policy_design_artifact(self):
        result = self._run()
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["policy_design_outcome"], "policy_design_recorded")
        self.assertTrue((self.audit_dir / "learned_strategy_adoption_policy_design.json").exists())
        self.assertTrue(result["evidence_package_complete_for_policy_discussion"])

    def test_artifact_includes_all_design_only_no_adoption_flags(self):
        result = self._run()
        for key, expected in design_only_policy_flags().items():
            self.assertEqual(result["policy"][key], expected)

    def test_artifact_does_not_mark_candidate_approved(self):
        result = self._run()
        self.assertFalse(result["policy"]["candidate_approved"])
        self.assertNotEqual(result["policy_design_outcome"], "approved")

    def test_artifact_does_not_mark_candidate_adoptable(self):
        result = self._run()
        self.assertFalse(result["policy"]["candidate_is_adoptable"])

    def test_artifact_does_not_mark_candidate_production_ready(self):
        result = self._run()
        self.assertFalse(result["policy"]["candidate_production_ready"])

    def test_artifact_does_not_create_adoption_plan(self):
        result = self._run()
        self.assertFalse(result["policy"]["adoption_plan_created"])
        self.assertIsNone(result["adoption_plan"])

    def test_artifact_does_not_mutate_authoritative_status_json(self):
        before = self._sha(self.status)
        result = self._run()
        after = self._sha(self.status)
        self.assertEqual(before, after)
        self.assertEqual(result["authoritative_status_json_sha256_before"], result["authoritative_status_json_sha256_after"])

    def test_artifact_does_not_mutate_package_deliverables(self):
        before = self._sha(self.package / "AUDIT_REPORT.md")
        result = self._run()
        after = self._sha(self.package / "AUDIT_REPORT.md")
        self.assertEqual(before, after)
        self.assertEqual(result["package_deliverable_snapshot_before"], result["package_deliverable_snapshot_after"])

    def test_artifact_does_not_mutate_app_tools_repair(self):
        before = self._sha(self.repair_dir / "README.md")
        result = self._run()
        after = self._sha(self.repair_dir / "README.md")
        self.assertEqual(before, after)
        self.assertEqual(result["protected_mutation_count"], 0)

    def test_artifact_does_not_mutate_rule_repair_map(self):
        before = self._sha(self.rule_map)
        result = self._run()
        after = self._sha(self.rule_map)
        self.assertEqual(before, after)
        self.assertEqual(result["rule_map_sha256_before"], result["rule_map_sha256_after"])

    def test_allowed_future_mutation_list_is_policy_text_only(self):
        result = self._run()
        text = result["allowed_future_mutation_list_policy_text_only"]
        self.assertTrue(text)
        self.assertTrue(all(isinstance(item, str) for item in text))
        self.assertIn("Patch 20A authorizes no mutations", text[0])

    def test_rollback_requirements_are_policy_text_only(self):
        result = self._run()
        rollback = result["rollback_requirements_policy_text_only"]
        self.assertTrue(rollback)
        self.assertFalse(result["policy"]["rollback_execution_performed"])
        self.assertTrue(result["future_rollback_command_required"])

    def test_default_review_path_is_used(self):
        result = write_learned_strategy_adoption_policy_design(
            job_dir=self.job_dir,
            reviewer="policy reviewer",
            candidate_id="candidate-1",
            rule_id="PDF/UA-1/7.21.7",
            repo_root=self.repo_root,
        )
        self.assertEqual(result["result"], "PASS")

    def test_candidate_mismatch_blocks(self):
        result = self._run(candidate_id="other")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("candidate_id_mismatch", result["blockers"])

    def test_rule_mismatch_blocks(self):
        result = self._run(rule_id="PDF/UA-1/9.9.9")
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("rule_id_mismatch", result["blockers"])


if __name__ == "__main__":
    unittest.main()
