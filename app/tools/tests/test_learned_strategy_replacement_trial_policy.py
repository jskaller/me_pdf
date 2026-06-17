import json
import tempfile
import unittest
from pathlib import Path

import tools.audit.learned_strategy_replacement_trial as trial_mod
from tools.audit.learned_strategy_replacement_trial import run_learned_strategy_replacement_trial


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def minimal_pdf(path, marker=b"one"):
    """Write a tiny PDF-like fixture.

    The replacement-trial unit tests validate Patch 17A policy decisions, not
    qpdf's parser. Tests monkeypatch qpdf to PASS so local qpdf strictness does
    not turn a policy fixture into an environment-dependent regression failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% fixture\n" + marker + b"\n%%EOF\n")


def qpdf_pass(path, trial_dir, timeout_seconds):
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "qpdf.stdout.txt"
    stderr_path = trial_dir / "qpdf.stderr.txt"
    stdout_path.write_text("synthetic qpdf pass for unit policy fixture\n", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    return {
        "check_name": "qpdf",
        "performed": True,
        "result": "PASS",
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "exit_code": 0,
    }


class LearnedStrategyReplacementTrialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "job"
        self.audit = self.job / "audit"
        self.normal = self.job / "repair" / "final.pdf"
        self.learned = self.job / "audit" / "learned_strategy_execution" / "attempt" / "output.pdf"
        minimal_pdf(self.normal, b"normal")
        minimal_pdf(self.learned, b"learned")
        self.comparison_path = self.audit / "learned_strategy_output_comparisons.json"
        self.quality_path = self.audit / "learned_strategy_candidate_quality_report.json"
        self.deeper_path = self.audit / "learned_strategy_deeper_validation_report.json"
        self._orig_qpdf_check = trial_mod._qpdf_check
        trial_mod._qpdf_check = qpdf_pass

    def tearDown(self):
        trial_mod._qpdf_check = self._orig_qpdf_check
        self.tmp.cleanup()

    def write_artifacts(self, deeper_decision="needs_manual_review", may_trial=False, output=None):
        output = output or self.learned
        base = {
            "rule_id": "PDF/UA-1/7.21.7",
            "candidate_id": "smoke-changed-valid-candidate",
            "attempt_id": "attempt",
        }
        write_json(self.comparison_path, {"comparisons": [dict(base, classification="changed_valid_pdf", output_pdf=str(output))]})
        write_json(self.quality_path, {"decisions": [dict(base, quality_decision="candidate_valid_changed")]})
        write_json(self.deeper_path, {"results": [dict(base, deeper_validation_decision=deeper_decision, candidate_may_proceed_to_trial=may_trial, candidate_is_adoptable=False)]})

    def run_trial(self, allow=False):
        return run_learned_strategy_replacement_trial(
            deeper_validation_report_path=self.deeper_path,
            comparison_artifact_path=self.comparison_path,
            quality_report_path=self.quality_path,
            job_dir=self.job,
            normal_final_pdf=self.normal,
            allow_manual_review_candidates=allow,
            timeout_seconds=2,
        )

    def test_default_trial_skips_skipped_candidates(self):
        self.write_artifacts(deeper_decision="skipped_not_eligible")
        payload = self.run_trial()
        self.assertEqual(payload["summary"]["trial_skipped_not_eligible"], 1)

    def test_default_trial_skips_manual_review_without_bypass(self):
        self.write_artifacts(deeper_decision="needs_manual_review")
        payload = self.run_trial()
        self.assertEqual(payload["summary"]["trial_skipped_not_eligible"], 1)
        self.assertEqual(payload["trial_count"], 0)

    def test_manual_review_bypass_runs_isolated_trial(self):
        self.write_artifacts(deeper_decision="needs_manual_review")
        payload = self.run_trial(allow=True)
        result = payload["results"][0]
        self.assertEqual(result["trial_decision"], "trial_needs_manual_review")
        self.assertTrue(result["trial_forced_for_diagnostics"])
        self.assertFalse(result["trial_eligible_without_force"])

    def test_deeper_validation_passed_is_trial_eligible_without_bypass(self):
        self.write_artifacts(deeper_decision="deeper_validation_passed", may_trial=True)
        payload = self.run_trial()
        self.assertEqual(payload["trial_count"], 1)
        self.assertEqual(payload["results"][0]["trial_decision"], "trial_evidence_passed")

    def test_trial_copies_pdfs_hashes_and_detects_change(self):
        self.write_artifacts(deeper_decision="needs_manual_review")
        result = self.run_trial(allow=True)["results"][0]
        self.assertTrue(Path(result["normal_final_pdf"]).exists())
        self.assertTrue(Path(result["learned_trial_pdf"]).exists())
        self.assertNotEqual(result["normal_final_sha256"], result["learned_trial_sha256"])
        self.assertTrue(result["learned_differs_from_normal"])

    def test_qpdf_and_header_checks_recorded(self):
        self.write_artifacts(deeper_decision="needs_manual_review")
        checks = self.run_trial(allow=True)["results"][0]["trial_checks"]
        names = {c["check_name"] for c in checks}
        self.assertIn("qpdf", names)
        self.assertIn("basic_pdf_header", names)
        qpdf = next(c for c in checks if c["check_name"] == "qpdf")
        self.assertTrue(qpdf["performed"])
        self.assertEqual(qpdf["result"], "PASS")

    def test_no_adoption_policy_flags_and_candidate_never_adoptable(self):
        self.write_artifacts(deeper_decision="deeper_validation_passed", may_trial=True)
        payload = self.run_trial()
        policy = payload["policy"]
        self.assertTrue(policy["normal_final_pdf_remains_authoritative"])
        self.assertFalse(policy["final_pdf_adoption_performed"])
        self.assertFalse(policy["rule_map_mutation_performed"])
        self.assertFalse(payload["results"][0]["candidate_is_adoptable"])

    def test_copy_noop_candidate_remains_skipped(self):
        self.write_artifacts(deeper_decision="skipped_not_eligible", output=self.normal)
        payload = self.run_trial(allow=True)
        self.assertEqual(payload["trial_count"], 0)
        self.assertEqual(payload["results"][0]["trial_decision"], "trial_skipped_not_eligible")

    def test_report_written(self):
        self.write_artifacts(deeper_decision="needs_manual_review")
        payload = self.run_trial(allow=True)
        report = self.audit / "learned_strategy_replacement_trial_report.json"
        self.assertTrue(report.exists())
        self.assertEqual(json.loads(report.read_text())["schema_version"], payload["schema_version"])


class LearnedStrategyReplacementTrialStaticIntegrationTests(unittest.TestCase):
    def test_orchestrator_patch_markers_are_present(self):
        import tools.audit.learned_strategy_orchestrator_execution_dry_run as mod
        self.assertIn("replacement_trial_enabled", mod.run_orchestrator_learned_execution_dry_run.__code__.co_varnames)
        self.assertIn("replacement_trial_allow_manual_review", mod.run_orchestrator_learned_execution_dry_run.__code__.co_varnames)


if __name__ == "__main__":
    unittest.main()
