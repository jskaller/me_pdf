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
        self.profile = kwargs.get("profile", "all")
        self.manifest = kwargs.get("manifest", "")


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

    def stage_source_pdf(self, workspace: Path, ticket: str, basename: str) -> None:
        path = workspace / "input" / ticket / f"{basename}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-local")

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
            self.assertIn("corpus_profile", record)
            self.assertIn("corpus_summary", payload)
            self.assertIn("blocker_priority_summary", payload)

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

    def test_production_profile_includes_representative_rows_and_excludes_fixtures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_profiles_prod_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "MM-1", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-1", "real-doc")
            self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="PASS")
            (workspace / "output" / "WEBUI-E2E-001_remediated" / "e2e-smoke_remediated.pdf").write_bytes(b"%PDF-fixture")

            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            self.assertEqual(payload["summary"]["jobs_total"], 1)
            self.assertEqual(payload["records"][0]["ticket"], "MM-1")
            self.assertEqual(payload["records"][0]["corpus_profile"]["primary_profile"], "production_corpus")
            self.assertEqual(payload["corpus_summary"]["production_rows_count"], 1)
            self.assertEqual(payload["corpus_summary"]["fixture_rows_count"], 0)

    def test_fixtures_profile_includes_controlled_and_synthetic_fixtures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_profiles_fixtures_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="PASS")
            (workspace / "output" / "WEBUI-E2E-001_remediated" / "e2e-smoke_remediated.pdf").write_bytes(b"%PDF-fixture")
            self.make_job(workspace, "MM-1", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-1", "real-doc")

            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="fixtures"))
            self.assertEqual(payload["summary"]["jobs_total"], 1)
            self.assertEqual(payload["records"][0]["corpus_profile"]["primary_profile"], "controlled_fixture")

    def test_historical_profile_catches_test_smoke_probe_timestamp_and_incomplete_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_profiles_hist_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TEST-001", "old-fixture", outcome="FAIL")
            self.make_job(workspace, "PROBE-001", "trial", outcome="ESCALATION")
            self.make_job(workspace, "MM-9", "doc.pre-patch-g.20260620-135708", outcome="FAIL")
            incomplete = workspace / "jobs" / "MM-10_missing"
            incomplete.mkdir(parents=True)

            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="historical"))
            self.assertEqual(payload["summary"]["jobs_total"], 4)
            self.assertTrue(all("historical" in r["corpus_profile"]["included_in_profiles"] for r in payload["records"]))

    def test_manifest_include_and_exclude_override_heuristics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_manifest_") as td:
            workspace = Path(td) / "workspace"
            self.make_job(workspace, "TEST-001", "old-fixture", outcome="FAIL")
            manifest = Path(td) / "manifest.json"
            self.write_json(manifest, {
                "version": "1.0.0",
                "profiles": {"production": {"include_jobs": ["TEST-001_old-fixture"]}},
                "jobs": {"TEST-001_old-fixture": {"source_kind": "private_local_or_representative_pdf", "profile": "production_corpus", "notes": "temporary manifest override"}},
            })

            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production", manifest=str(manifest)))
            self.assertEqual(payload["summary"]["jobs_total"], 1)
            self.assertEqual(payload["records"][0]["source_kind"], "private_local_or_representative_pdf")
            self.assertEqual(payload["records"][0]["corpus_profile"]["manifest_source"], "temporary manifest override")

            manifest_exclude = Path(td) / "manifest_exclude.json"
            self.write_json(manifest_exclude, {
                "version": "1.0.0",
                "profiles": {"production": {"exclude_jobs": ["TEST-001_old-fixture"]}},
                "jobs": {"TEST-001_old-fixture": {"source_kind": "private_local_or_representative_pdf", "profile": "production_corpus"}},
            })
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production", manifest=str(manifest_exclude)))
            self.assertEqual(payload["summary"]["jobs_total"], 0)

    def test_blocker_priority_groups_rules_and_prioritizes_production_over_fixture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_blockers_") as td:
            workspace = Path(td) / "workspace"
            prod = self.make_job(workspace, "MM-1", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-1", "real-doc")
            self.write_json(prod / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.18.4"], "non_targetable_residual_rules": []})
            self.write_json(prod / "audit" / "hermes_signals.json", [{"rule_id": "PDF/UA-1/7.18.4", "reason": "manual_no_strategies", "active_blocker": True}])
            fixture = self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="ESCALATION")
            self.write_json(fixture / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.21.4.1"], "non_targetable_residual_rules": []})

            prod_payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rules = prod_payload["blocker_priority_summary"]["rules"]
            self.assertEqual(rules[0]["rule_id"], "PDF/UA-1/7.18.4")
            self.assertEqual(rules[0]["priority_bucket"], "P1_single_production_blocker")
            self.assertEqual(rules[0]["recommended_next_action"], "build_or_repair_strategy")

            all_payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="all"))
            buckets = {r["rule_id"]: r["priority_bucket"] for r in all_payload["blocker_priority_summary"]["rules"]}
            self.assertEqual(buckets["PDF/UA-1/7.18.4"], "P1_single_production_blocker")
            self.assertEqual(buckets["PDF/UA-1/7.21.4.1"], "P2_fixture_only_blocker")

    def test_rule_map_presence_reported_but_not_counted_as_proof_and_external_validators_not_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_guardrails_") as td:
            workspace = Path(td) / "workspace"
            prod = self.make_job(workspace, "MM-1", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-1", "real-doc")
            self.write_json(prod / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/5"], "non_targetable_residual_rules": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            record = payload["records"][0]
            self.assertFalse(record["evidence_policy"]["rule_map_entries_count_as_proven_repairs"])
            self.assertEqual(record["external_validators"]["axesCheck"], "NOT_RUN")
            self.assertEqual(record["external_validators"]["PAC_2024"], "NOT_RUN")
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertIn("present_in_rule_map", rule)
            self.assertIn("mapped_strategies_count", rule)
            self.assertEqual(payload["blocker_priority_summary"]["policy"]["rule_map_entries_count_as_proven_repairs"], False)


    def test_h5_pass_production_pre_repair_failure_is_contextual_not_p0_or_p1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_pass_pre_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "MM-100", "passed-doc", outcome="PASS")
            self.stage_source_pdf(workspace, "MM-100", "passed-doc")
            (workspace / "output" / "MM-100_remediated" / "passed-doc_remediated.pdf").write_bytes(b"%PDF-pass")
            self.write_json(job / "audit" / "verapdf_pre_pdfua1_summary.json", {"failures_by_rule": [{"rule_id": "PDF/UA-1/7.18.4", "failures": 1}]})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertFalse(rule["current_blocker"])
            self.assertEqual(rule["current_production_blocker_rows"], 0)
            self.assertEqual(rule["pre_repair_only_count"], 1)
            self.assertNotIn(rule["priority_bucket"], {"P0_systemic_production_blocker", "P1_single_production_blocker"})

    def test_h5_escalation_active_hermes_signal_creates_p1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_p1_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "MM-101", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-101", "real-doc")
            self.write_json(job / "audit" / "hermes_signals.json", [{"rule_id": "PDF/UA-1/7.18.4", "reason": "manual_no_strategies", "active_blocker": True}])
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertEqual(rule["priority_bucket"], "P1_single_production_blocker")
            self.assertEqual(rule["current_production_blocker_rows"], 1)
            self.assertIn("active_hermes_required_signals", rule["active_blocker_sources"])

    def test_h5_two_production_rows_same_current_blocker_create_p0(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_p0_") as td:
            workspace = Path(td) / "workspace"
            for ticket in ("MM-201", "MM-202"):
                job = self.make_job(workspace, ticket, "real-doc", outcome="ESCALATION")
                self.stage_source_pdf(workspace, ticket, "real-doc")
                self.write_json(job / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.21.7"], "non_targetable_residual_rules": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertEqual(rule["priority_bucket"], "P0_systemic_production_blocker")
            self.assertEqual(rule["current_production_blocker_rows"], 2)

    def test_h5_repair_plan_only_rule_is_contextual_not_active(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_plan_only_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "MM-301", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-301", "real-doc")
            self.write_json(job / "audit" / "repair_plan.json", {"result": "PLAN_READY", "repair_steps": [{"strategy": "planned", "rules_addressed": ["PDF/UA-1/7.3"]}], "hermes_required": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertEqual(rule["repair_plan_only_count"], 1)
            self.assertFalse(rule["current_blocker"])
            self.assertNotIn(rule["priority_bucket"], {"P0_systemic_production_blocker", "P1_single_production_blocker"})

    def test_h5_fixture_only_current_blocker_is_p2_and_historical_only_is_p3(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_fixture_hist_") as td:
            workspace = Path(td) / "workspace"
            fixture = self.make_job(workspace, "WEBUI-E2E-001", "e2e-smoke", outcome="ESCALATION")
            self.write_json(fixture / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.18.4"], "non_targetable_residual_rules": []})
            hist = self.make_job(workspace, "PROBE-001", "trial", outcome="ESCALATION")
            self.write_json(hist / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.21.7"], "non_targetable_residual_rules": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="all"))
            buckets = {r["rule_id"]: r["priority_bucket"] for r in payload["blocker_priority_summary"]["rules"]}
            self.assertEqual(buckets["PDF/UA-1/7.18.4"], "P2_fixture_only_blocker")
            self.assertEqual(buckets["PDF/UA-1/7.21.7"], "P3_historical_or_stale_only")

    def test_h5_mapped_active_blocker_remains_active_not_mapped_but_unproven(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_mapped_active_") as td:
            workspace = Path(td) / "workspace"
            prod = self.make_job(workspace, "MM-401", "real-doc", outcome="ESCALATION")
            self.stage_source_pdf(workspace, "MM-401", "real-doc")
            self.write_json(prod / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/5"], "non_targetable_residual_rules": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertTrue(rule["present_in_rule_map"])
            self.assertEqual(rule["priority_bucket"], "P1_single_production_blocker")
            self.assertTrue(payload["blocker_priority_summary"]["policy"]["p0_p1_require_current_active_production_blocker_evidence"])

    def test_h5_pass_row_with_current_evidence_is_risk_not_priority(self) -> None:
        with tempfile.TemporaryDirectory(prefix="matrix_h5_pass_current_risk_") as td:
            workspace = Path(td) / "workspace"
            job = self.make_job(workspace, "MM-501", "passed-doc", outcome="PASS")
            self.stage_source_pdf(workspace, "MM-501", "passed-doc")
            (workspace / "output" / "MM-501_remediated" / "passed-doc_remediated.pdf").write_bytes(b"%PDF-pass")
            self.write_json(job / "audit" / "residual_analysis.json", {"targetable_residual_rules": ["PDF/UA-1/7.18.4"], "non_targetable_residual_rules": []})
            payload = build_matrix(Args(workspace=str(workspace), inspect_existing=True, profile="production"))
            rule = payload["blocker_priority_summary"]["rules"][0]
            self.assertFalse(rule["current_blocker"])
            self.assertEqual(rule["pass_row_current_blocker_risk_count"], 1)
            self.assertNotIn(rule["priority_bucket"], {"P0_systemic_production_blocker", "P1_single_production_blocker"})
            self.assertEqual(payload["blocker_priority_summary"]["pass_row_current_blocker_risks"][0]["rule_id"], "PDF/UA-1/7.18.4")


if __name__ == "__main__":
    unittest.main()
