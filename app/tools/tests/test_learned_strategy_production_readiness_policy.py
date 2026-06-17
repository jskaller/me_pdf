import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.audit.learned_strategy_production_readiness import (
    evaluate_learned_strategy_production_testing_readiness,
)


class LearnedStrategyProductionReadinessPolicyTests(unittest.TestCase):
    def make_job(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        job = root / "workspace" / "jobs" / "JOB"
        audit = job / "audit"
        audit.mkdir(parents=True)
        normal = audit / "normal_final.pdf"
        learned = audit / "learned_trial.pdf"
        normal.write_bytes(b"%PDF-\nnormal")
        learned.write_bytes(b"%PDF-\nlearned")
        deeper = audit / "learned_strategy_deeper_validation_report.json"
        deeper.write_text(json.dumps({"results": [{"candidate_id": "c1", "deeper_validation_decision": "needs_manual_review"}]}))
        trial = audit / "learned_strategy_replacement_trial_report.json"
        trial.write_text(json.dumps({"results": [{
            "rule_id": "PDF/UA-1/7.21.7",
            "candidate_id": "c1",
            "attempt_id": "a1",
            "trial_decision": "trial_needs_manual_review",
            "deeper_validation_decision": "needs_manual_review",
            "normal_final_pdf": str(normal),
            "learned_trial_pdf": str(learned),
        }]}))
        return tmp, job, trial, deeper

    def test_readiness_requires_replacement_trial_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td) / "job"
            (job / "audit").mkdir(parents=True)
            deeper = job / "audit" / "learned_strategy_deeper_validation_report.json"
            deeper.write_text(json.dumps({"results": []}))
            payload = evaluate_learned_strategy_production_testing_readiness(
                job / "audit" / "missing_trial.json",
                deeper,
                job,
            )
        self.assertEqual(payload["result"], "SKIPPED")
        self.assertIn("requires_learned_replacement_trial", payload["readiness_blockers"])
        self.assertFalse(payload["policy"]["final_pdf_adoption_performed"])

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    def test_helper_unavailable_blockers_map_to_manual_review(self, verapdf):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        verapdf.return_value = {
            "check_name": "verapdf_delta",
            "performed": False,
            "result": "SKIPPED",
            "readiness_blocker": "verapdf_delta_unavailable",
            "blockers": ["verapdf_delta_unavailable"],
        }
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        result = payload["results"][0]
        self.assertEqual(result["readiness_decision"], "production_testing_needs_manual_review")
        self.assertIn("verapdf_delta_unavailable", result["readiness_blockers"])
        self.assertFalse(result["candidate_is_adoptable"])

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_render_compare_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_form_field_preservation_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_metadata_check")
    def test_any_hard_failed_check_maps_to_blocked(self, meta, form, render, verapdf):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        meta.return_value = {"check_name": "metadata", "performed": True, "result": "FAIL", "blockers": ["metadata_changed"]}
        form.return_value = {"check_name": "form_field_preservation", "performed": True, "result": "PASS", "blockers": []}
        render.return_value = {"check_name": "render_compare", "performed": True, "result": "PASS", "blockers": []}
        verapdf.return_value = {"check_name": "verapdf_delta", "performed": True, "result": "PASS", "blockers": []}
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        self.assertEqual(payload["results"][0]["readiness_decision"], "production_testing_blocked")
        self.assertEqual(payload["summary"]["production_testing_blocked"], 1)

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_render_compare_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_form_field_preservation_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_metadata_check")
    def test_all_checks_passing_maps_to_evidence_complete_but_not_adoptable(self, meta, form, render, verapdf):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        for mocked, name in (
            (meta, "metadata"),
            (form, "form_field_preservation"),
            (render, "render_compare"),
            (verapdf, "verapdf_delta"),
        ):
            mocked.return_value = {"check_name": name, "performed": True, "result": "PASS", "blockers": []}
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        result = payload["results"][0]
        self.assertEqual(result["readiness_decision"], "production_testing_evidence_complete")
        self.assertFalse(result["candidate_is_adoptable"])
        self.assertFalse(payload["policy"]["final_pdf_adoption_performed"])
        self.assertFalse(payload["policy"]["verdict_softening_performed"])

    def test_report_written_and_summary_counts_manual_review(self):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        report = job / "audit" / "learned_strategy_production_testing_readiness_report.json"
        self.assertTrue(report.exists())
        self.assertEqual(payload["summary"]["production_testing_needs_manual_review"], 1)
        self.assertFalse(payload["policy"]["rule_map_mutation_performed"])
        self.assertFalse(payload["policy"]["app_tools_repair_mutation_performed"])


if __name__ == "__main__":
    unittest.main()

class Patch18BProductionReadinessVeraPDFDeltaTests(unittest.TestCase):
    def make_job(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        job = root / "workspace" / "jobs" / "JOB"
        audit = job / "audit"
        audit.mkdir(parents=True)
        trial_dir = audit / "learned_strategy_replacement_trial" / "c1"
        trial_dir.mkdir(parents=True)
        normal = trial_dir / "normal_final.pdf"
        learned = trial_dir / "learned_trial.pdf"
        normal.write_bytes(b"%PDF-1.7\nnormal")
        learned.write_bytes(b"%PDF-1.7\nlearned")
        deeper = audit / "learned_strategy_deeper_validation_report.json"
        deeper.write_text(json.dumps({"results": [{"candidate_id": "c1", "deeper_validation_decision": "needs_manual_review"}]}))
        trial = audit / "learned_strategy_replacement_trial_report.json"
        trial.write_text(json.dumps({"results": [{
            "rule_id": "PDF/UA-1/7.21.7",
            "candidate_id": "c1",
            "attempt_id": "a1",
            "trial_decision": "trial_needs_manual_review",
            "deeper_validation_decision": "needs_manual_review",
            "normal_final_pdf": str(normal),
            "learned_trial_pdf": str(learned),
        }]}))
        return tmp, job, trial, deeper

    def patch_required_helpers(self, meta, form, render, verapdf_result):
        meta.return_value = {"check_name": "metadata", "performed": True, "result": "PASS", "blockers": []}
        form.return_value = {"check_name": "form_field_preservation", "performed": True, "result": "PASS", "blockers": []}
        render.return_value = {"check_name": "render_compare", "performed": True, "result": "PASS", "blockers": []}
        return verapdf_result

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_render_compare_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_form_field_preservation_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_metadata_check")
    def test_verapdf_delta_pass_plus_other_pass_maps_to_evidence_complete(self, meta, form, render, verapdf):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        verapdf.return_value = self.patch_required_helpers(meta, form, render, {"check_name": "verapdf_delta", "performed": True, "result": "PASS", "readiness_blocker": None, "blockers": [], "introduced_failure_count": 0, "worsened_failure_count": 0})
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        result = payload["results"][0]
        self.assertEqual(result["readiness_decision"], "production_testing_evidence_complete")
        self.assertEqual(payload["summary"]["production_testing_evidence_complete"], 1)
        self.assertFalse(result["candidate_is_adoptable"])
        self.assertFalse(payload["policy"]["final_pdf_adoption_performed"])

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_render_compare_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_form_field_preservation_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_metadata_check")
    def test_verapdf_delta_fail_maps_to_blocked(self, meta, form, render, verapdf):
        tmp, job, trial, deeper = self.make_job()
        self.addCleanup(tmp.cleanup)
        verapdf.return_value = self.patch_required_helpers(meta, form, render, {"check_name": "verapdf_delta", "performed": True, "result": "FAIL", "readiness_blocker": "verapdf_delta_regression_detected", "blockers": ["verapdf_delta_regression_detected"]})
        payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
        self.assertEqual(payload["results"][0]["readiness_decision"], "production_testing_blocked")
        self.assertEqual(payload["summary"]["production_testing_blocked"], 1)

    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_verapdf_delta_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_render_compare_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_form_field_preservation_check")
    @mock.patch("tools.audit.learned_strategy_production_readiness.evaluate_metadata_check")
    def test_verapdf_delta_skipped_or_error_maps_to_manual_review(self, meta, form, render, verapdf):
        for result_name, blocker in (("SKIPPED", "verapdf_delta_unavailable"), ("ERROR", "verapdf_delta_timeout"), ("ERROR", "verapdf_delta_parse_failed")):
            tmp, job, trial, deeper = self.make_job()
            self.addCleanup(tmp.cleanup)
            verapdf.return_value = self.patch_required_helpers(meta, form, render, {"check_name": "verapdf_delta", "performed": result_name != "SKIPPED", "result": result_name, "readiness_blocker": blocker, "blockers": []})
            payload = evaluate_learned_strategy_production_testing_readiness(trial, deeper, job)
            self.assertEqual(payload["results"][0]["readiness_decision"], "production_testing_needs_manual_review")
            self.assertIn(blocker, payload["results"][0]["readiness_blockers"])
            self.assertFalse(payload["policy"]["production_repair_replacement_performed"])
