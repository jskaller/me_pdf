import json
import tempfile
import unittest
from pathlib import Path

from tools.lib.residual_verdict import reconcile_hermes_signals, summarize_residual_analysis, summarize_strategy_indexing
from tools.lib.verdict import VerdictInput, verdict


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
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

# Patch 5B: residual summary normalization regression coverage.
class Patch5BResidualSummaryNormalizationTests(unittest.TestCase):
    def test_targetable_remaining_failures_are_targetable_rules(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            (job / "audit").mkdir()
            write_json(job / "audit" / "residual_analysis.json", {
                "targetable_remaining_failures": [
                    {"rule_id": "PDF/UA-1/7.18.4", "post_count": 2},
                    "PDF/UA-1/7.21.4.1",
                ],
                "non_targetable_residual_rules": ["PDF/UA-1/7.18.1"],
            })
            summary = summarize_residual_analysis(job)
            self.assertEqual(summary["targetable_residual_rules"], ["PDF/UA-1/7.18.4", "PDF/UA-1/7.21.4.1"])
            self.assertEqual(summary["non_targetable_residual_rules"], ["PDF/UA-1/7.18.1"])

    def test_rules_list_drives_summary_when_lists_missing(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            (job / "audit").mkdir()
            write_json(job / "audit" / "residual_analysis.json", {
                "rules": [
                    {"rule_id": "PDF/UA-1/7.18.4", "outcome": "persistent", "targetable_by_self_extension": True, "post_count": 4},
                    {"rule_id": "PDF/UA-1/7.21.7", "outcome": "attempted_no_effect", "targetable": True, "post_count": 1},
                    {"rule_id": "PDF/UA-1/7.18.1", "outcome": "non_targetable_residual", "targetable": False, "post_count": 3},
                    {"rule_id": "PDF/UA-1/review", "pending_review": True, "post_count": 1},
                ]
            })
            summary = summarize_residual_analysis(job)
            self.assertEqual(summary["targetable_residual_rules"], ["PDF/UA-1/7.18.4", "PDF/UA-1/7.21.7"])
            self.assertEqual(summary["non_targetable_residual_rules"], ["PDF/UA-1/7.18.1"])
            self.assertEqual(summary["pending_review_rules"], ["PDF/UA-1/review"])
            self.assertEqual(summary["attempted_no_effect_rules"], ["PDF/UA-1/7.21.7"])
            self.assertEqual(summary["persistent_rules"], ["PDF/UA-1/7.18.4"])

    def test_hermes_reconciliation_uses_corrected_targetable_summary(self):
        summary = {
            "targetable_residual_rules": ["PDF/UA-1/7.18.4", "PDF/UA-1/7.21.4.1", "PDF/UA-1/7.21.7"],
            "non_targetable_residual_rules": ["PDF/UA-1/7.18.1"],
            "persistent_rules": ["PDF/UA-1/7.18.4"],
        }
        raw = [
            {"rule_id": "PDF/UA-1/7.18.1", "failures": 0, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.18.4", "failures": 8, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.21.7", "failures": 1, "reason": "all_strategies_exhausted"},
        ]
        reconciled = reconcile_hermes_signals(raw, summary)
        self.assertEqual(reconciled["active_actionable_count"], 3)
        active_ids = {s["rule_id"] for s in reconciled["active_actionable_signals"]}
        self.assertEqual(active_ids, {"PDF/UA-1/7.18.4", "PDF/UA-1/7.21.4.1", "PDF/UA-1/7.21.7"})
        self.assertEqual(reconciled["suppressed_zero_count"], 1)
        self.assertEqual(reconciled["suppressed_zero_count_signals"][0]["rule_id"], "PDF/UA-1/7.18.1")
        self.assertEqual(reconciled["resolved_incidental_count"], 0)
        self.assertEqual(reconciled["raw_emissions"], 4)

    def test_non_targetable_nonzero_signal_is_classified_separately(self):
        summary = {"targetable_residual_rules": [], "non_targetable_residual_rules": ["PDF/UA-1/7.18.1"]}
        reconciled = reconcile_hermes_signals([
            {"rule_id": "PDF/UA-1/7.18.1", "failures": 2, "reason": "manual_only"}
        ], summary)
        self.assertEqual(reconciled["active_actionable_count"], 0)
        self.assertEqual(reconciled["non_targetable_residual_count"], 1)
        self.assertEqual(reconciled["non_targetable_residual_signals"][0]["reconciliation"], "non_targetable_residual")

# Patch 5C: targetability precedence and zero-count Hermes suppression.
class Patch5CTargetabilityPrecedenceTests(unittest.TestCase):
    def test_non_targetable_list_excludes_attempted_no_effect_from_targetable(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            write_json(job / "audit" / "residual_analysis.json", {
                "targetable_residual_rules": ["PDF/UA-1/7.18.1", "PDF/UA-1/7.18.4"],
                "non_targetable_residual_rules": ["PDF/UA-1/7.18.1"],
                "rules": [
                    {"rule_id": "PDF/UA-1/7.18.1", "outcome": "attempted_no_effect", "post_count": 0},
                    {"rule_id": "PDF/UA-1/7.18.4", "outcome": "attempted_no_effect", "targetable": True, "post_count": 2},
                ],
            })
            summary = summarize_residual_analysis(job)
            self.assertEqual(summary["targetable_residual_rules"], ["PDF/UA-1/7.18.4"])
            self.assertEqual(summary["non_targetable_residual_rules"], ["PDF/UA-1/7.18.1"])

    def test_post_count_zero_excluded_from_targetable_residuals(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            write_json(job / "audit" / "residual_analysis.json", {
                "targetable_remaining_failures": ["R-zero", "R-live"],
                "rules": [
                    {"rule_id": "R-zero", "outcome": "attempted_no_effect", "targetable": True, "post_count": 0},
                    {"rule_id": "R-live", "outcome": "attempted_no_effect", "targetable": True, "post_count": 1},
                ],
            })
            summary = summarize_residual_analysis(job)
            self.assertEqual(summary["targetable_residual_rules"], ["R-live"])
            self.assertEqual(summary["zero_count_rules"], ["R-zero"])

    def test_targetable_false_excluded_from_targetable_residuals(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            write_json(job / "audit" / "residual_analysis.json", {
                "targetable_residual_rules": ["R-manual", "R-auto"],
                "rules": [
                    {"rule_id": "R-manual", "outcome": "attempted_no_effect", "targetable_by_self_extension": False, "post_count": 2},
                    {"rule_id": "R-auto", "outcome": "attempted_no_effect", "targetable_by_self_extension": True, "post_count": 2},
                ],
            })
            summary = summarize_residual_analysis(job)
            self.assertEqual(summary["targetable_residual_rules"], ["R-auto"])
            self.assertEqual(summary["non_targetable_residual_rules"], ["R-manual"])

    def test_zero_failure_signal_suppressed_even_when_escalation_attempted_no_effect(self):
        summary = {
            "targetable_residual_rules": ["R1"],
            "escalation_rules": ["R1"],
            "attempted_no_effect_rules": ["R1"],
        }
        rec = reconcile_hermes_signals([
            {"rule_id": "R1", "failures": 0, "reason": "all_strategies_exhausted"}
        ], summary)
        self.assertEqual(rec["active_actionable_count"], 0)
        self.assertEqual(rec["suppressed_zero_count"], 1)
        self.assertEqual(rec["suppressed_zero_count_rules"], ["R1"])

    def test_non_targetable_hermes_residual_not_active(self):
        summary = {
            "targetable_residual_rules": ["R-auto"],
            "non_targetable_residual_rules": ["R-manual"],
        }
        rec = reconcile_hermes_signals([
            {"rule_id": "R-manual", "failures": 3, "reason": "manual_only"},
            {"rule_id": "R-auto", "failures": 2, "reason": "gap"},
        ], summary)
        self.assertEqual(rec["active_actionable_count"], 1)
        self.assertEqual(rec["active_actionable_rules"], ["R-auto"])
        self.assertEqual(rec["non_targetable_residual_count"], 1)
        self.assertEqual(rec["non_targetable_residual_rules"], ["R-manual"])

    def test_smoke_shape_reconciles_three_active_one_suppressed(self):
        summary = {
            "targetable_residual_rules": ["PDF/UA-1/7.18.4", "PDF/UA-1/7.21.4.1", "PDF/UA-1/7.21.7"],
            "non_targetable_residual_rules": ["PDF/UA-1/7.18.1"],
        }
        rec = reconcile_hermes_signals([
            {"rule_id": "PDF/UA-1/7.18.1", "failures": 0, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.18.4", "failures": 4, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.21.7", "failures": 1, "reason": "all_strategies_exhausted"},
            {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2, "reason": "all_strategies_exhausted"},
        ], summary)
        self.assertEqual(rec["active_actionable_count"], 3)
        self.assertEqual(set(rec["active_actionable_rules"]), {"PDF/UA-1/7.18.4", "PDF/UA-1/7.21.4.1", "PDF/UA-1/7.21.7"})
        self.assertEqual(rec["suppressed_zero_count"], 1)
        self.assertEqual(rec["suppressed_zero_count_rules"], ["PDF/UA-1/7.18.1"])
        self.assertEqual(rec["raw_emissions"], 4)

