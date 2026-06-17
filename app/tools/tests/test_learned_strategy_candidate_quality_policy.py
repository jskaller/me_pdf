import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.audit.learned_strategy_candidate_quality import (
    evaluate_learned_strategy_candidate_quality,
    write_learned_strategy_candidate_quality_report,
)


class LearnedStrategyCandidateQualityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.artifact = self.tmp / "learned_strategy_output_comparisons.json"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_comparisons(self, classifications):
        comparisons = []
        for i, classification in enumerate(classifications, start=1):
            comparisons.append(
                {
                    "rule_id": "PDF/UA-1/7.21.7",
                    "candidate_id": f"candidate-{i}",
                    "strategy_id": f"strategy-{i}",
                    "attempt_id": f"attempt-{i}",
                    "classification": classification,
                    "input_output_hash_equal": classification == "no_effect",
                }
            )
        self.artifact.write_text(json.dumps({"comparisons": comparisons}), encoding="utf-8")

    def assert_single_decision(self, classification, expected):
        self.write_comparisons([classification])
        report = evaluate_learned_strategy_candidate_quality(self.artifact, self.tmp)
        self.assertEqual(report["decisions"][0]["comparison_classification"], classification)
        self.assertEqual(report["decisions"][0]["quality_decision"], expected)
        self.assertFalse(report["decisions"][0]["quality_passed"])

    def test_no_effect_maps_to_rejected_no_effect(self):
        self.assert_single_decision("no_effect", "rejected_no_effect")

    def test_missing_output_maps_to_rejected_invalid(self):
        self.assert_single_decision("missing_output", "rejected_invalid")

    def test_changed_invalid_pdf_maps_to_rejected_invalid(self):
        self.assert_single_decision("changed_invalid_pdf", "rejected_invalid")

    def test_execution_failed_maps_to_rejected_execution_failed(self):
        self.assert_single_decision("execution_failed", "rejected_execution_failed")

    def test_needs_deeper_validation_maps_to_needs_deeper_validation(self):
        self.assert_single_decision("needs_deeper_validation", "needs_deeper_validation")

    def test_changed_valid_pdf_maps_to_candidate_valid_changed_but_not_passed(self):
        self.assert_single_decision("changed_valid_pdf", "candidate_valid_changed")

    def test_all_quality_decisions_keep_no_adoption_policy_flags(self):
        self.write_comparisons([
            "no_effect",
            "missing_output",
            "changed_invalid_pdf",
            "execution_failed",
            "needs_deeper_validation",
            "changed_valid_pdf",
        ])
        report = evaluate_learned_strategy_candidate_quality(self.artifact, self.tmp)
        policy = report["policy"]
        self.assertTrue(policy["diagnostic_sidecar_only"])
        self.assertFalse(policy["final_pdf_adoption_performed"])
        self.assertFalse(policy["verdict_softening_performed"])
        self.assertFalse(policy["rule_map_mutation_performed"])
        self.assertFalse(policy["app_tools_repair_mutation_performed"])
        self.assertFalse(policy["production_repair_replacement_performed"])
        self.assertTrue(policy["candidate_quality_is_not_adoption_approval"])
        self.assertTrue(all(d["quality_passed"] is False for d in report["decisions"]))

    def test_summary_counts_decisions_correctly(self):
        self.write_comparisons([
            "no_effect",
            "missing_output",
            "changed_invalid_pdf",
            "execution_failed",
            "needs_deeper_validation",
            "changed_valid_pdf",
        ])
        report = evaluate_learned_strategy_candidate_quality(self.artifact, self.tmp)
        self.assertEqual(report["summary"]["rejected_no_effect"], 1)
        self.assertEqual(report["summary"]["rejected_invalid"], 2)
        self.assertEqual(report["summary"]["rejected_execution_failed"], 1)
        self.assertEqual(report["summary"]["needs_deeper_validation"], 1)
        self.assertEqual(report["summary"]["candidate_valid_changed"], 1)

    def test_malformed_and_missing_comparison_artifact_handled_diagnostically(self):
        report = evaluate_learned_strategy_candidate_quality(self.tmp / "missing.json", self.tmp)
        self.assertEqual(report["decisions"][0]["quality_decision"], "needs_deeper_validation")
        self.assertFalse(report["decisions"][0]["quality_passed"])
        self.assertIn("candidate_quality_comparison_artifact_error", report["blockers"])
        self.artifact.write_text("[]", encoding="utf-8")
        report = evaluate_learned_strategy_candidate_quality(self.artifact, self.tmp)
        self.assertEqual(report["decisions"][0]["quality_decision"], "needs_deeper_validation")

    def test_write_quality_report_artifact(self):
        self.write_comparisons(["no_effect"])
        report = write_learned_strategy_candidate_quality_report(
            comparison_artifact_path=self.artifact,
            audit_dir=self.tmp,
            job_dir=self.tmp,
        )
        path = self.tmp / "learned_strategy_candidate_quality_report.json"
        self.assertTrue(path.exists())
        self.assertEqual(report["summary"]["rejected_no_effect"], 1)


class LearnedStrategyCandidateQualityOrchestratorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.audit_dir = self.tmp / "audit"
        self.audit_dir.mkdir()
        self.rule_map = self.tmp / "rule_repair_map.json"
        self.rule_map.write_text(json.dumps({"rules": {}}), encoding="utf-8")
        self.input_pdf = self.tmp / "input.pdf"
        self.input_pdf.write_bytes(b"%PDF-1.4\n% learned candidate smoke\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake_candidate(self):
        return {
            "rule_id": "PDF/UA-1/7.21.7",
            "candidate_id": "smoke-active-candidate",
            "strategy_id": "smoke-copy",
        }

    def fake_execute(self, candidate, input_pdf, job_dir, repo_root, attempt_id, timeout_seconds, dry_run):
        attempt_dir = job_dir / "audit" / "learned_strategy_execution" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = attempt_dir / "output.pdf"
        shutil.copy2(input_pdf, output_pdf)
        result = {
            "rule_id": candidate["rule_id"],
            "candidate_id": candidate["candidate_id"],
            "strategy_id": candidate["strategy_id"],
            "attempt_id": attempt_id,
            "result": "PASS",
            "exit_code": 0,
            "input_pdf": str(input_pdf),
            "output_pdf": str(output_pdf),
            "output_pdf_sha256": "unused",
            "execution_performed": True,
            "execution_blockers": [],
            "attempt_dir": str(attempt_dir),
        }
        (attempt_dir / "execution_result.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    def test_orchestrator_dry_run_writes_quality_report_and_diagnostics_reference(self):
        from tools.audit import learned_strategy_orchestrator_execution_dry_run as dry_run

        with mock.patch.object(dry_run, "discover_active_learned_strategies", return_value={"discovered_strategies": [self.fake_candidate()]}), \
             mock.patch.object(dry_run, "execute_discovered_learned_strategy", side_effect=self.fake_execute):
            diagnostics = dry_run.run_orchestrator_learned_execution_dry_run(
                rule_map_path=self.rule_map,
                audit_dir=self.audit_dir,
                job_dir=self.tmp,
                repo_root=self.tmp,
                input_pdf=self.input_pdf,
                residual_failures=[{"rule_id": "PDF/UA-1/7.21.7"}],
                limit=1,
                timeout_seconds=1,
            )

        quality_path = self.audit_dir / "learned_strategy_candidate_quality_report.json"
        comparison_path = self.audit_dir / "learned_strategy_output_comparisons.json"
        diagnostics_path = self.audit_dir / "learned_strategy_execution_diagnostics.json"
        self.assertTrue(comparison_path.exists())
        self.assertTrue(quality_path.exists())
        self.assertTrue(diagnostics_path.exists())
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        written_diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        self.assertEqual(quality["summary"]["rejected_no_effect"], 1)
        self.assertFalse(quality["decisions"][0]["quality_passed"])
        self.assertTrue(written_diagnostics["output_comparison_performed"])
        self.assertTrue(written_diagnostics["candidate_quality_performed"])
        self.assertEqual(written_diagnostics["candidate_quality_artifact"], str(quality_path))
        self.assertEqual(diagnostics["candidate_quality_summary"]["rejected_no_effect"], 1)

    def test_quality_gate_does_not_mutate_rule_map_or_repair_dir(self):
        before = self.rule_map.read_text(encoding="utf-8")
        repair_dir = self.tmp / "app" / "tools" / "repair"
        repair_dir.mkdir(parents=True)
        before_repair_files = sorted(p.relative_to(repair_dir) for p in repair_dir.rglob("*"))
        self.artifact = self.audit_dir / "learned_strategy_output_comparisons.json"
        self.artifact.write_text(json.dumps({"comparisons": [{"classification": "changed_valid_pdf"}]}), encoding="utf-8")
        report = write_learned_strategy_candidate_quality_report(
            comparison_artifact_path=self.artifact,
            audit_dir=self.audit_dir,
            job_dir=self.tmp,
        )
        self.assertEqual(report["summary"]["candidate_valid_changed"], 1)
        self.assertEqual(self.rule_map.read_text(encoding="utf-8"), before)
        after_repair_files = sorted(p.relative_to(repair_dir) for p in repair_dir.rglob("*"))
        self.assertEqual(after_repair_files, before_repair_files)


if __name__ == "__main__":
    unittest.main()
