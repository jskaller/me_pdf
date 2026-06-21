#!/usr/bin/env python3
"""Policy tests for the production-readiness matrix harness."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.production_readiness_matrix import build_matrix, inspect_existing


class Args:
    def __init__(self, **kwargs):
        self.workspace = kwargs.get("workspace")
        self.inspect_existing = kwargs.get("inspect_existing", True)
        self.pdf = kwargs.get("pdf", [])
        self.python_bin = kwargs.get("python_bin", "python3")
        self.out = kwargs.get("out", "")


class ProductionReadinessMatrixPolicyTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))

    def make_job(self, workspace: Path, ticket: str, basename: str, outcome: str, status: str | None = None) -> Path:
        job = workspace / "jobs" / f"{ticket}_{basename}"
        out = workspace / "output" / f"{ticket}_remediated"
        (job / "audit").mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        self.write_json(job / "audit" / "orchestrator_outcome.json", {"overall_result": outcome})
        self.write_json(job / "STATUS.json", {"overall_result": status or outcome, "result": status or outcome})
        self.write_json(job / "audit" / "qpdf.json", {"result": "PASS"})
        self.write_json(job / "audit" / "residual_analysis.json", {"targetable_residual_rules": [], "non_targetable_residual_rules": []})
        (out / "SHA256SUMS.txt").write_text("abc  report.md\n")
        return job

    def test_empty_workspace_is_incomplete_not_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_empty_") as td:
            workspace = Path(td) / "workspace"
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True))
            record = payload["records"][0]
            self.assertEqual(payload["summary"]["jobs_total"], 1)
            self.assertEqual(record["final_matrix_classification"], "INCOMPLETE_ARTIFACTS")
            self.assertEqual(record["external_validators"]["axesCheck"], "NOT_RUN")
            self.assertEqual(record["external_validators"]["PAC_2024"], "NOT_RUN")
            self.assertNotEqual(record["final_matrix_classification"], "PASS")

    def test_status_orchestrator_mismatch_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_mismatch_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-1", "doc", outcome="PASS", status="FAIL")
            records = inspect_existing(workspace)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["final_matrix_classification"], "MISMATCH")
            self.assertFalse(records[0]["status_matches_orchestrator_outcome"])

    def test_pass_requires_matched_top_level_pdf_for_same_basename(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_pass_pkg_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="PASS")
            out = workspace / "output" / "WEBUI-E2E-001_remediated"
            (out / "sibling_remediated.pdf").write_bytes(b"%PDF-sibling")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "INCOMPLETE_ARTIFACTS")
            self.assertIn("PASS lacks matched top-level remediated PDF deliverable", record["risk_flags"])
            self.assertFalse(record["pass_package_exists"])
            self.assertEqual(record["matched_output_artifacts"]["unmatched_pdfs_in_output_dir"], [str(out / "sibling_remediated.pdf")])

            (out / "e2e-smoke_remediated.pdf").write_bytes(b"%PDF-ok")
            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "PASS")
            self.assertTrue(record["pass_package_exists"])
            self.assertEqual(record["matched_output_artifacts"]["matched_top_level_pdfs"], [str(out / "e2e-smoke_remediated.pdf")])
            self.assertEqual(record["source_kind"], "controlled_fixture")
            self.assertEqual(record["external_validators"]["axesCheck"], "NOT_RUN")
            self.assertEqual(record["external_validators"]["PAC_2024"], "NOT_RUN")

    def test_review_required_uses_matched_review_artifacts_for_same_basename(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_review_pkg_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-2", "needs-review", outcome="REVIEW_REQUIRED")
            out = workspace / "output" / "TICKET-2_remediated"
            (out / "review").mkdir(parents=True, exist_ok=True)
            (out / "review" / "other_remediated.pdf").write_bytes(b"%PDF-other")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "INCOMPLETE_ARTIFACTS")
            self.assertIn("REVIEW_REQUIRED lacks matched review/package evidence", record["risk_flags"])
            self.assertFalse(record["review_required_has_review_package"])

            (out / "review" / "needs-review_remediated.pdf").write_bytes(b"%PDF-review")
            (out / "review" / "needs-review_AUDIT_REPORT.md").write_text("review report")
            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "REVIEW_REQUIRED")
            self.assertTrue(record["review_required_has_review_package"])
            self.assertEqual(record["matched_output_artifacts"]["matched_review_pdfs"], [str(out / "review" / "needs-review_remediated.pdf")])
            self.assertEqual(record["matched_output_artifacts"]["matched_review_reports"], [str(out / "review" / "needs-review_AUDIT_REPORT.md")])

    def test_escalation_with_only_sibling_pdf_is_stale_shared_not_confirmed_false_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_stale_shared_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-3", "failed-run", outcome="ESCALATION")
            out = workspace / "output" / "TICKET-3_remediated"
            (out / "sibling-run_remediated.pdf").write_bytes(b"%PDF-sibling")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "ESCALATION")
            self.assertFalse(record["confirmed_false_success_pdf"])
            self.assertFalse(record["fail_escalation_pdf_copied_to_successful_deliverables"])
            self.assertTrue(record["stale_or_shared_output_risk"])
            self.assertIn("FAIL/ESCALATION output directory contains only unmatched sibling/stale PDF deliverable(s)", record["risk_flags"])
            self.assertEqual(record["matched_output_artifacts"]["unmatched_pdfs_in_output_dir"], [str(out / "sibling-run_remediated.pdf")])

    def test_escalation_with_matched_success_like_pdf_is_confirmed_false_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_confirmed_false_success_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-4", "bad", outcome="ESCALATION")
            out = workspace / "output" / "TICKET-4_remediated"
            (out / "bad_remediated.pdf").write_bytes(b"%PDF-risk")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "ESCALATION")
            self.assertTrue(record["confirmed_false_success_pdf"])
            self.assertTrue(record["fail_escalation_pdf_copied_to_successful_deliverables"])
            self.assertFalse(record["stale_or_shared_output_risk"])
            self.assertIn("FAIL/ESCALATION has matched same-basename PDF in success-like deliverable location", record["risk_flags"])
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True))
            self.assertEqual(payload["summary"]["confirmed_false_success_pdf_risks"], [str(workspace / "jobs" / "TICKET-4_bad")])

    def test_fail_pdf_under_failed_directory_is_risk_but_not_success_deliverable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_failed_pdf_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-5", "bad", outcome="FAIL")
            out = workspace / "output" / "TICKET-5_remediated"
            (out / "failed").mkdir(parents=True, exist_ok=True)
            (out / "failed" / "bad_remediated.pdf").write_bytes(b"%PDF-failed")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "FAIL")
            self.assertFalse(record["confirmed_false_success_pdf"])
            self.assertFalse(record["fail_escalation_pdf_copied_to_successful_deliverables"])
            self.assertIn("FAIL/ESCALATION failed package contains matched PDF; not counted as success deliverable", record["risk_flags"])

    def test_residuals_repair_plan_execution_and_hermes_signals_are_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_artifacts_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "TICKET-6", "doc", outcome="ESCALATION")
            self.write_json(job / "audit" / "repair_plan.json", {
                "result": "PLAN_READY",
                "repair_steps": [{"strategy": "fix_example", "rules_addressed": ["PDF/UA-1/1"]}],
                "hermes_required": [],
            })
            self.write_json(job / "audit" / "execution_log.json", {
                "records": [{"script": "tools/repair/fix_example.py", "ran": True, "result_category": "ran_success", "rules_targeted": ["PDF/UA-1/1"]}]
            })
            self.write_json(job / "audit" / "residual_analysis.json", {
                "targetable_residual_rules": ["PDF/UA-1/2"],
                "non_targetable_residual_rules": ["PDF/UA-1/3"],
            })
            self.write_json(job / "audit" / "hermes_signals.json", [
                {"rule_id": "PDF/UA-1/2", "reason": "unknown_rule", "failures": 1, "active_blocker": True}
            ])

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["repair_plan"]["rules"], ["PDF/UA-1/1"])
            self.assertEqual(record["repair_scripts_executed"][0]["script"], "tools/repair/fix_example.py")
            self.assertEqual(record["residual_targetable_rules"], ["PDF/UA-1/2"])
            self.assertEqual(record["non_targetable_rules"], ["PDF/UA-1/3"])
            self.assertEqual(record["active_hermes_required_signals"][0]["rule_id"], "PDF/UA-1/2")


if __name__ == "__main__":
    unittest.main()
