import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_deeper_validation import (
    run_learned_strategy_deeper_validation,
)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class LearnedStrategyDeeperValidationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.audit.mkdir(parents=True)
        self.input_pdf = self.job / "input.pdf"
        self.output_pdf = self.job / "output.pdf"
        self.input_pdf.write_bytes(b"%PDF-1.4\ninput\n%%EOF\n")
        self.output_pdf.write_bytes(b"%PDF-1.4\nchanged\n%%EOF\n")
        self.quality_path = self.audit / "learned_strategy_candidate_quality_report.json"
        self.comparison_path = self.audit / "learned_strategy_output_comparisons.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, quality_decision="rejected_no_effect", classification="no_effect", output=True):
        write_json(self.quality_path, {
            "schema_version": "learned-strategy-candidate-quality.v1",
            "decisions": [{
                "rule_id": "PDF/UA-1/7.21.7",
                "candidate_id": "candidate-1",
                "strategy_id": "strategy-1",
                "attempt_id": "attempt-1",
                "comparison_classification": classification,
                "quality_decision": quality_decision,
                "quality_passed": False,
            }],
        })
        write_json(self.comparison_path, {
            "schema_version": "learned-strategy-output-comparisons.v1",
            "comparisons": [{
                "rule_id": "PDF/UA-1/7.21.7",
                "candidate_id": "candidate-1",
                "strategy_id": "strategy-1",
                "attempt_id": "attempt-1",
                "classification": classification,
                "input_pdf": str(self.input_pdf),
                "learned_output_pdf": str(self.output_pdf if output else self.job / "missing.pdf"),
                "normal_final_pdf": str(self.input_pdf),
                "input_pdf_sha256": "input-sha",
                "learned_output_pdf_sha256": "output-sha",
                "normal_final_pdf_sha256": "normal-sha",
                "output_size_bytes": self.output_pdf.stat().st_size if output else 0,
            }],
        })

    def run_case(self, checks=None):
        def provider(comparison, candidate, attempt_dir, timeout_seconds):
            self.assertTrue(attempt_dir.exists())
            return checks if checks is not None else []
        return run_learned_strategy_deeper_validation(
            quality_report_path=self.quality_path,
            comparison_artifact_path=self.comparison_path,
            job_dir=self.job,
            check_provider=provider,
        )

    def decision(self, payload):
        return payload["results"][0]["deeper_validation_decision"]

    def test_rejected_no_effect_is_skipped_not_eligible(self):
        self.write_case("rejected_no_effect", "no_effect")
        payload = self.run_case(checks=[{"check_name": "should_not_run", "performed": True, "result": "FAIL"}])
        self.assertEqual(self.decision(payload), "skipped_not_eligible")
        self.assertEqual(payload["results"][0]["checks"], [])
        self.assertEqual(payload["summary"]["skipped_not_eligible"], 1)

    def test_rejected_invalid_is_skipped_not_eligible(self):
        self.write_case("rejected_invalid", "changed_invalid_pdf")
        payload = self.run_case(checks=[])
        self.assertEqual(self.decision(payload), "skipped_not_eligible")

    def test_rejected_execution_failed_is_skipped_not_eligible(self):
        self.write_case("rejected_execution_failed", "execution_failed")
        payload = self.run_case(checks=[])
        self.assertEqual(self.decision(payload), "skipped_not_eligible")

    def test_candidate_valid_changed_runs_deeper_validation_checks(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
        ])
        self.assertEqual(payload["validated_count"], 1)
        self.assertEqual(self.decision(payload), "deeper_validation_passed")

    def test_needs_deeper_validation_runs_deeper_validation_checks(self):
        self.write_case("needs_deeper_validation", "needs_deeper_validation")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
        ])
        self.assertEqual(payload["validated_count"], 1)
        self.assertEqual(self.decision(payload), "deeper_validation_passed")

    def test_qpdf_or_header_failure_maps_to_failed_integrity(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "FAIL", "exit_code": 2},
        ])
        self.assertEqual(self.decision(payload), "failed_integrity")

    def test_preservation_failure_maps_to_failed_preservation(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
            {"check_name": "form_field_preservation", "performed": True, "result": "FAIL"},
        ])
        self.assertEqual(self.decision(payload), "failed_preservation")

    def test_render_failure_maps_to_failed_render(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
            {"check_name": "render_compare", "performed": True, "result": "FAIL"},
        ])
        self.assertEqual(self.decision(payload), "failed_render")

    def test_verapdf_regression_maps_to_failed_verapdf_regression(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
            {"check_name": "verapdf_delta", "performed": True, "result": "FAIL"},
        ])
        self.assertEqual(self.decision(payload), "failed_verapdf_regression")

    def test_incomplete_checks_without_hard_failures_map_to_manual_review(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
        ])
        self.assertEqual(self.decision(payload), "needs_manual_review")

    def test_all_required_checks_passing_is_not_adoption_approval(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf")
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
        ])
        result = payload["results"][0]
        self.assertEqual(result["deeper_validation_decision"], "deeper_validation_passed")
        self.assertTrue(result["candidate_may_proceed_to_trial"])
        self.assertFalse(result["candidate_is_adoptable"])
        self.assertFalse(result["final_pdf_adoption_performed"])

    def test_report_includes_no_adoption_policy_flags(self):
        self.write_case("rejected_no_effect", "no_effect")
        payload = self.run_case(checks=[])
        policy = payload["policy"]
        self.assertTrue(policy["diagnostic_sidecar_only"])
        self.assertFalse(policy["final_pdf_adoption_performed"])
        self.assertFalse(policy["verdict_softening_performed"])
        self.assertFalse(policy["rule_map_mutation_performed"])
        self.assertFalse(policy["app_tools_repair_mutation_performed"])
        self.assertFalse(policy["production_repair_replacement_performed"])
        self.assertFalse(policy["candidate_is_adoptable"])
        self.assertTrue(policy["deeper_validation_is_not_adoption_approval"])

    def test_summary_counts_decisions_correctly(self):
        write_json(self.quality_path, {
            "decisions": [
                {"rule_id": "r1", "candidate_id": "c1", "strategy_id": "s1", "attempt_id": "a1", "quality_decision": "rejected_no_effect"},
                {"rule_id": "r2", "candidate_id": "c2", "strategy_id": "s2", "attempt_id": "a2", "quality_decision": "candidate_valid_changed"},
            ]
        })
        write_json(self.comparison_path, {
            "comparisons": [
                {"rule_id": "r1", "candidate_id": "c1", "strategy_id": "s1", "attempt_id": "a1", "classification": "no_effect", "learned_output_pdf": str(self.output_pdf)},
                {"rule_id": "r2", "candidate_id": "c2", "strategy_id": "s2", "attempt_id": "a2", "classification": "changed_valid_pdf", "learned_output_pdf": str(self.output_pdf)},
            ]
        })
        payload = self.run_case(checks=[
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
        ])
        self.assertEqual(payload["summary"]["skipped_not_eligible"], 1)
        self.assertEqual(payload["summary"]["deeper_validation_passed"], 1)

    def test_missing_output_blocks_missing_artifact(self):
        self.write_case("candidate_valid_changed", "changed_valid_pdf", output=False)
        payload = self.run_case(checks=[])
        self.assertEqual(self.decision(payload), "blocked_missing_artifact")

    def test_artifact_is_written_under_job_audit(self):
        self.write_case("rejected_no_effect", "no_effect")
        payload = self.run_case(checks=[])
        artifact = self.audit / "learned_strategy_deeper_validation_report.json"
        self.assertTrue(artifact.exists())
        self.assertEqual(payload["artifact_path"], str(artifact))

    def test_orchestrator_diagnostics_reference_deeper_validation_artifact_for_noop(self):
        try:
            from tools.audit import learned_strategy_orchestrator_execution_dry_run as dry_run
        except Exception as exc:
            self.skipTest(f"orchestrator dry-run module unavailable in isolated test bundle: {exc}")
        if not hasattr(dry_run, "_patch16a_previous_run_orchestrator_learned_execution_dry_run"):
            self.skipTest("Patch 16A orchestrator wrapper not installed in this isolated test bundle")

        original = dry_run._patch16a_previous_run_orchestrator_learned_execution_dry_run
        output_pdf = self.output_pdf
        output_pdf.write_bytes(self.input_pdf.read_bytes())

        def fake_previous(**kwargs):
            audit_dir = Path(kwargs["audit_dir"])
            write_json(audit_dir / "learned_strategy_output_comparisons.json", {
                "schema_version": "learned-strategy-output-comparisons.v1",
                "comparison_count": 1,
                "comparisons": [{
                    "rule_id": "PDF/UA-1/7.21.7",
                    "candidate_id": "smoke-active-candidate",
                    "strategy_id": "smoke-copy",
                    "attempt_id": "attempt-1",
                    "classification": "no_effect",
                    "input_pdf": str(self.input_pdf),
                    "learned_output_pdf": str(output_pdf),
                    "normal_final_pdf": str(self.input_pdf),
                    "input_output_hash_equal": True,
                    "output_size_bytes": output_pdf.stat().st_size,
                }],
                "summary": {"no_effect": 1},
                "policy": {"final_pdf_adoption_performed": False},
            })
            return {
                "schema_version": "learned-strategy-orchestrator-execution-dry-run.v1",
                "candidate_count": 1,
                "executed_count": 1,
                "skipped_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
                "executions": [{"rule_id": "PDF/UA-1/7.21.7", "candidate_id": "smoke-active-candidate"}],
                "skipped_candidates": [],
                "blockers": [],
                "policy": dry_run.policy(),
                "artifact_path": str(audit_dir / "learned_strategy_execution_diagnostics.json"),
            }

        dry_run._patch16a_previous_run_orchestrator_learned_execution_dry_run = fake_previous
        try:
            diagnostics = dry_run.run_orchestrator_learned_execution_dry_run(
                rule_map_path=self.root / "rule_repair_map.json",
                audit_dir=self.audit,
                job_dir=self.job,
                repo_root=self.root,
                input_pdf=self.input_pdf,
                residual_failures=[],
                limit=1,
                timeout_seconds=1,
            )
        finally:
            dry_run._patch16a_previous_run_orchestrator_learned_execution_dry_run = original

        self.assertTrue(diagnostics["candidate_quality_performed"])
        self.assertTrue(diagnostics["deeper_validation_performed"])
        self.assertTrue(Path(diagnostics["deeper_validation_artifact"]).exists())
        self.assertEqual(diagnostics["deeper_validation_summary"]["skipped_not_eligible"], 1)
        deeper = json.loads(Path(diagnostics["deeper_validation_artifact"]).read_text())
        self.assertEqual(deeper["results"][0]["deeper_validation_decision"], "skipped_not_eligible")
        self.assertFalse(diagnostics["final_pdf_adoption_performed"])
        self.assertFalse(diagnostics["verdict_softening_performed"])
        self.assertFalse(diagnostics["rule_map_mutation_performed"])
        self.assertFalse(diagnostics["app_tools_repair_mutation_performed"])
        self.assertFalse(diagnostics["production_repair_replacement_performed"])
        self.assertFalse(deeper["results"][0]["candidate_is_adoptable"])


if __name__ == "__main__":
    unittest.main()
