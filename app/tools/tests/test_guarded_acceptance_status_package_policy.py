#!/usr/bin/env python3
"""H10I tests for guarded acceptance/status/package contract."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STATUS_WRITER = REPO_ROOT / "app" / "tools" / "packaging" / "status_json_writer.py"
PACKAGER = REPO_ROOT / "app" / "tools" / "packaging" / "package_deliverables.py"

if str(REPO_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "app"))

from tools.orchestrate.guarded_acceptance import (  # noqa: E402
    TARGET_RULE,
    build_orchestrator_outcome,
    evaluate_guarded_acceptance,
    package_routing,
    status_fragment,
)


class GuardedAcceptanceStatusPackagePolicyTests(unittest.TestCase):
    def base_evidence(self) -> dict:
        return {
            "repair_strategy_id": "form_widget_structure_construction_v1",
            "target_rule": TARGET_RULE,
            "input_pdf": "/tmp/job/repair/pass0_source.pdf",
            "candidate_pdf": "/tmp/job/repair/guarded/pass1_form_widget_candidate.pdf",
            "final_pdf": "/tmp/job/pdf/final.pdf",
            "status_path": "/tmp/job/STATUS.json",
            "package_path": "/tmp/job/package",
            "orchestrator_outcome_path": "/tmp/job/audit/orchestrator_outcome.json",
            "qpdf_result": "PASS",
            "verapdf_pdfua1_result": "PASS",
            "verapdf_wcag_result": "PASS",
            "verapdf_iso_result": "PASS",
            "profile_accounting_result": "PASS",
            "iso_regression_result": "PASS",
            "post_form_widget_inspection_result": "PASS",
            "preservation_result": "PASS",
            "residual_failures": [],
            "new_authoritative_failures": [],
            "increased_authoritative_failures": [],
            "target_rule_before_count": 204,
            "target_rule_after_count": 0,
            "target_rule_status": "CLEARED",
        }

    def decide(self, **overrides):
        evidence = self.base_evidence()
        evidence.update(overrides)
        return evaluate_guarded_acceptance(evidence)

    def test_pass_allowed_only_when_all_authoritative_gates_pass_and_no_residuals(self):
        decision = self.decide()
        self.assertEqual(decision["status_result"], "PASS")
        self.assertTrue(decision["pass_allowed"])
        self.assertTrue(decision["promote_candidate_to_final"])
        self.assertEqual(decision["package_policy"], "PASS_FINAL_ALLOWED")

    def test_target_clears_but_residual_authoritative_failures_are_review_required(self):
        decision = self.decide(
            verapdf_pdfua1_result="FAIL",
            residual_failures=[{"rule_id": "PDF/UA-1/7.1", "failed_checks": 2}],
        )
        self.assertEqual(decision["status_result"], "REVIEW_REQUIRED")
        self.assertFalse(decision["pass_allowed"])
        self.assertFalse(decision["promote_candidate_to_final"])
        self.assertEqual(decision["package_policy"], "REVIEW_REQUIRED_WITH_CANDIDATE")

    def test_qpdf_failure_rejects_pass(self):
        decision = self.decide(qpdf_result="FAIL")
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_QPDF")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertFalse(decision["pass_allowed"])

    def test_pdfua_regression_rejects_pass(self):
        decision = self.decide(new_authoritative_failures=["PDF/UA-1/7.99"])
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_VERAPDF_REGRESSION")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertFalse(decision["pass_allowed"])

    def test_pinned_wcag_regression_rejects_pass(self):
        decision = self.decide(increased_authoritative_failures=["WCAG/1.4.3"])
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_VERAPDF_REGRESSION")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertFalse(decision["pass_allowed"])

    def test_iso_no_regression_failure_rejects_pass(self):
        decision = self.decide(iso_regression_result="FAIL", new_iso_rule_ids=["ISO 19005-2:2011/Annex_L"])
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_ISO_REGRESSION")
        self.assertEqual(decision["status_result"], "REVIEW_REQUIRED")
        self.assertFalse(decision["pass_allowed"])

    def test_missing_profile_accounting_rejects_pass(self):
        decision = self.decide(profile_accounting_result="MISSING")
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_PROFILE_ACCOUNTING")
        self.assertEqual(decision["status_result"], "ESCALATION")
        self.assertFalse(decision["pass_allowed"])

    def test_post_repair_form_widget_inspection_failure_rejects_pass(self):
        decision = self.decide(post_form_widget_inspection_result="FAIL")
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertFalse(decision["pass_allowed"])

    def test_preservation_failure_rejects_pass(self):
        decision = self.decide(preservation_result="FAIL")
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_PRESERVATION")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertFalse(decision["pass_allowed"])

    def test_source_overwrite_is_refused(self):
        decision = self.decide(candidate_pdf="/tmp/job/repair/pass0_source.pdf")
        self.assertEqual(decision["terminal_state"], "GUARDED_CANDIDATE_REJECTED_ARTIFACT_POLICY")
        self.assertEqual(decision["status_result"], "FAIL")
        self.assertIn("candidate_overwrites_input_pdf", decision["blockers"])

    def test_status_fragment_records_guarded_decision_truthfully(self):
        decision = self.decide(residual_failures=[{"rule_id": "PDF/UA-1/7.1"}])
        fragment = status_fragment(decision)
        self.assertFalse(fragment["guarded_pass_allowed"])
        self.assertTrue(fragment["guarded_candidate_intermediate"])
        self.assertEqual(fragment["guarded_acceptance_terminal_state"], "GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED")

    def test_orchestrator_outcome_cannot_claim_pass_when_guarded_says_review(self):
        decision = self.decide(residual_failures=[{"rule_id": "PDF/UA-1/7.1"}])
        outcome = build_orchestrator_outcome(decision, base={"overall_result": "PASS"})
        self.assertEqual(outcome["overall_result"], "REVIEW_REQUIRED")
        self.assertFalse(outcome["guarded_candidate_promoted_to_final"])

    def test_package_routing_distinguishes_pass_review_and_report_only(self):
        pass_route = package_routing(self.decide())
        review_route = package_routing(self.decide(residual_failures=[{"rule_id": "PDF/UA-1/7.1"}]))
        fail_route = package_routing(self.decide(qpdf_result="FAIL"))
        self.assertEqual(pass_route["label"], "successful final PDF")
        self.assertEqual(review_route["label"], "review-required candidate")
        self.assertEqual(fail_route["label"], "report-only")
        self.assertTrue(pass_route["copy_pdf_to_deliverables"])
        self.assertTrue(review_route["copy_pdf_to_deliverables"])
        self.assertFalse(fail_route["copy_pdf_to_deliverables"])

    def test_status_writer_overrides_false_pass_from_guarded_review_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            decision = self.decide(residual_failures=[{"rule_id": "PDF/UA-1/7.1"}])
            (audit / "orchestrator_outcome.json").write_text(json.dumps({
                "overall_result": "PASS",
                "guarded_acceptance": decision,
            }))
            proc = subprocess.run(
                [sys.executable, str(STATUS_WRITER), str(job), "--pdf", "candidate.pdf"],
                cwd=str(REPO_ROOT),
                env={"PYTHONPATH": str(REPO_ROOT / "app")},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            status = json.loads((job / "STATUS.json").read_text())
            self.assertEqual(status["overall_result"], "REVIEW_REQUIRED")
            self.assertIn("guarded_acceptance_overrode_pass", status)
            self.assertEqual(status["guarded_acceptance_terminal_state"], "GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED")

    def test_packager_report_only_for_guarded_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            pdf = job / "repair" / "candidate.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.7\n%test\n")
            decision = self.decide(qpdf_result="FAIL")
            (job / "STATUS.json").write_text(json.dumps({"overall_result": "FAIL", "guarded_acceptance": decision}))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({"overall_result": "FAIL", "guarded_acceptance": decision}))
            output_dir = root / "out"
            proc = subprocess.run(
                [sys.executable, str(PACKAGER), str(job), str(pdf), "--output-dir", str(output_dir)],
                cwd=str(REPO_ROOT),
                env={"PYTHONPATH": str(REPO_ROOT / "app")},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["effective_skip_pdf"])
            self.assertNotIn("pdf", payload["deliverables"])

    def test_packager_allows_review_required_candidate_but_not_as_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            pdf = job / "repair" / "candidate.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.7\n%test\n")
            decision = self.decide(residual_failures=[{"rule_id": "PDF/UA-1/7.1"}])
            (job / "STATUS.json").write_text(json.dumps({"overall_result": "REVIEW_REQUIRED", "guarded_acceptance": decision}))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({"overall_result": "REVIEW_REQUIRED", "guarded_acceptance": decision}))
            output_dir = root / "out"
            proc = subprocess.run(
                [sys.executable, str(PACKAGER), str(job), str(pdf), "--output-dir", str(output_dir)],
                cwd=str(REPO_ROOT),
                env={"PYTHONPATH": str(REPO_ROOT / "app")},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["overall_result"], "REVIEW_REQUIRED")
            self.assertFalse(payload["effective_skip_pdf"])
            self.assertIn("pdf", payload["deliverables"])
            report = Path(payload["deliverables"]["audit_report"]).read_text()
            self.assertIn("Guarded package label: review-required candidate", report)


if __name__ == "__main__":
    unittest.main()
