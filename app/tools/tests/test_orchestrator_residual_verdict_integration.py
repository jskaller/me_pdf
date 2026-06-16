import json
import tempfile
import unittest
from pathlib import Path

from tools.lib.residual_verdict import summarize_residual_analysis, summarize_strategy_indexing, reconcile_hermes_signals
from tools.lib.verdict import VerdictInput, verdict


class ResidualVerdictIntegrationTests(unittest.TestCase):
    def make_job(self):
        td = tempfile.TemporaryDirectory()
        job = Path(td.name)
        (job / "audit").mkdir()
        self.addCleanup(td.cleanup)
        return job

    def write_residual(self, job, summary=None, by_rule=None):
        payload = {
            "summary": summary or {},
            "by_rule": by_rule or {},
            "policy": {
                "partially_resolved_softens_verdict": False,
                "repair_script_promotion_performed": False,
                "rule_map_mutation_performed": False,
            },
        }
        (job / "audit" / "residual_analysis.json").write_text(json.dumps(payload))
        return payload

    def test_verdict_input_contains_residual_summary(self):
        job = self.make_job()
        self.write_residual(job, {"counts_by_outcome": {"persistent": 1}, "targetable_residual_rules": ["PDF/UA-1/7.18.1"]})
        summary = summarize_residual_analysis(job)
        self.assertTrue(summary["available"])
        self.assertIn("residual_analysis_sha256", summary)
        self.assertEqual(summary["targetable_residual_rules"], ["PDF/UA-1/7.18.1"])

    def test_zero_failure_resolved_signal_is_inactive(self):
        job = self.make_job()
        self.write_residual(job, by_rule={"PDF/UA-1/7.18.1": {"outcome": "resolved", "post_count": 0}})
        rec = reconcile_hermes_signals([{"rule_id": "PDF/UA-1/7.18.1", "failures": 0, "reason": "all_strategies_exhausted"}], summarize_residual_analysis(job))
        self.assertEqual(rec["active_actionable_count"], 0)
        self.assertEqual(rec["suppressed_zero_count"], 1)

    def test_targetable_residual_remains_actionable(self):
        job = self.make_job()
        self.write_residual(job, {"targetable_residual_rules": ["R1"]})
        rec = reconcile_hermes_signals([{"rule_id": "R1", "failures": 3, "reason": "gap"}], summarize_residual_analysis(job))
        self.assertEqual(rec["active_actionable_count"], 1)

    def test_non_targetable_classified_separately(self):
        job = self.make_job()
        self.write_residual(job, {"non_targetable_residual_rules": ["R2"]})
        rec = reconcile_hermes_signals([{"rule_id": "R2", "failures": 1, "reason": "gap"}], summarize_residual_analysis(job))
        self.assertEqual(rec["active_actionable_count"], 0)
        self.assertEqual(rec["non_targetable_residual_count"], 1)

    def test_pending_review_yields_review_required(self):
        vi = VerdictInput.from_gate_dict({"verapdf_pdfua1": "PASS", "verapdf_wcag": "PASS", "metadata_post": "PASS", "preservation_post": "PASS", "form_fields_post": "PASS"}, pending_review_rules=["R3"])
        self.assertEqual(verdict(vi).overall, "REVIEW_REQUIRED")

    def test_introduced_rule_blocks_pass(self):
        vi = VerdictInput.from_gate_dict({"verapdf_pdfua1": "PASS", "verapdf_wcag": "PASS", "metadata_post": "PASS", "preservation_post": "PASS", "form_fields_post": "PASS"}, introduced_rules=["R4"])
        self.assertNotEqual(verdict(vi).overall, "PASS")

    def test_partial_improvement_does_not_soften(self):
        vi = VerdictInput.from_gate_dict({"verapdf_pdfua1": "PASS", "verapdf_wcag": "PASS", "metadata_post": "PASS", "preservation_post": "PASS", "form_fields_post": "PASS"}, targetable_residual_rules=["R5"], partially_resolved_rules=["R5"])
        self.assertEqual(verdict(vi).overall, "ESCALATION")

    def test_strategy_indexing_report_referenced_without_adoption(self):
        job = self.make_job()
        (job / "audit" / "strategy_indexing_report.json").write_text(json.dumps({
            "eligible_strategies": [{"rule_id": "R1"}],
            "proposed_rule_map_changes": [{"rule_id": "R1"}],
            "rejected_experiments": [{"rule_id": "R2"}],
            "policy": {"repair_script_promotion_performed": False, "rule_map_mutation_performed": False, "final_pdf_adoption_performed": False},
        }))
        summary = summarize_strategy_indexing(job)
        self.assertTrue(summary["available"])
        self.assertEqual(summary["eligible_count"], 1)
        self.assertFalse(summary["rule_map_mutation_performed"])




# Patch 5 regression coverage appended by patch5_regression_repair_v5.py.
class Patch5PublicContractRegressionTests(unittest.TestCase):
    def test_gate_result_remains_dataclass_constructible(self):
        from tools.lib.gates import GateName
        from tools.lib.verdict import GateResult
        gate = GateResult(GateName.verapdf_pdfua1, "PASS", "test")
        self.assertEqual(gate.value, "PASS")
        self.assertEqual(gate.source, "test")

if __name__ == "__main__":
    unittest.main()
