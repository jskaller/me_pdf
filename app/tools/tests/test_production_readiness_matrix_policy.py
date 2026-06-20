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
            self.assertEqual(payload["summary"]["jobs_total"], 1)
            self.assertEqual(payload["records"][0]["final_matrix_classification"], "INCOMPLETE_ARTIFACTS")
            self.assertNotEqual(payload["records"][0]["final_matrix_classification"], "PASS")

    def test_status_orchestrator_mismatch_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_mismatch_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-1", "doc", outcome="PASS", status="FAIL")
            records = inspect_existing(workspace)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["final_matrix_classification"], "MISMATCH")
            self.assertFalse(records[0]["status_matches_orchestrator_outcome"])

    def test_fail_package_with_pdf_is_false_success_risk(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_false_success_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TICKET-2", "bad", outcome="FAIL")
            out = workspace / "output" / "TICKET-2_remediated"
            (out / "bad_remediated.pdf").write_bytes(b"%PDF-risk")

            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "FAIL")
            self.assertTrue(record["fail_escalation_pdf_copied_to_successful_deliverables"])
            self.assertIn("FAIL/ESCALATION output package contains PDF deliverable(s)", record["risk_flags"])

    def test_pass_requires_remediated_pdf_package(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_pass_pkg_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="PASS")
            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "INCOMPLETE_ARTIFACTS")
            self.assertIn("PASS lacks top-level remediated PDF deliverable", record["risk_flags"])

            out = workspace / "output" / "WEBUI-E2E-001_remediated"
            (out / "e2e-smoke_remediated.pdf").write_bytes(b"%PDF-ok")
            record = inspect_existing(workspace)[0]
            self.assertEqual(record["final_matrix_classification"], "PASS")
            self.assertEqual(record["source_kind"], "controlled_fixture")
            self.assertEqual(record["external_validators"]["axesCheck"], "NOT_RUN")
            self.assertEqual(record["external_validators"]["PAC_2024"], "NOT_RUN")

    def test_residuals_repair_plan_execution_and_hermes_signals_are_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_artifacts_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "TICKET-3", "doc", outcome="ESCALATION")
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
