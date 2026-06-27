import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.font_tounicode_diagnostics import (
    TERMINAL_BLOCKED_BY_MISSING_EVIDENCE,
    build_tounicode_repair_readiness_report,
)
from tools.orchestrate.self_extension_executor import (
    build_residual_script_generation_request,
    run_residual_self_extension_attempts,
)


class AgentCandidateRepairLoopPolicyTests(unittest.TestCase):
    def test_strategy_request_can_be_converted_to_candidate_generation_request(self):
        request = build_residual_script_generation_request(
            strategy_request={
                "ticket": "MM-17179-H12-CANDIDATE1",
                "job_name": "MM-17179-H12-CANDIDATE1_ROI4987",
                "current_pdf": "/app/workspace/jobs/job/repair/pass.pdf",
                "source_pdf": "/app/workspace/input/MM-17179-H12-CANDIDATE1/ROI4987.pdf",
                "residual_failures": [
                    {
                        "rule_id": "PDF/UA-1/7.21.7",
                        "failures": 4,
                        "description": "font dictionary missing ToUnicode map",
                    },
                    {
                        "rule_id": "PDF/UA-1/7.18.4",
                        "failures": 204,
                        "description": "widget annotation not nested within Form tag",
                    },
                ],
            },
            target_rule_id="PDF/UA-1/7.21.7",
            attempt=1,
            candidate_relative_path="tools/repair/generated/fix_generated_pdf_ua_1_7_21_7_attempt_01.py",
        )

        self.assertEqual(request["request_type"], "pdfua_residual_repair_script_generation")
        self.assertEqual(request["target_rule_id"], "PDF/UA-1/7.21.7")
        self.assertEqual(request["attempt"], 1)
        self.assertEqual(request["required_response_schema"]["result"], "SCRIPT_SOURCE | NEEDS_MORE_EVIDENCE | NOT_AUTOMATABLE")
        self.assertEqual(request["evidence"]["residual_failure_payload"], "target_rule_only")
        serialized = json.dumps(request)
        self.assertIn("font dictionary missing ToUnicode map", serialized)
        self.assertNotIn("widget annotation not nested within Form tag", serialized)

    def test_missing_tounicode_evidence_blocks_before_generated_script_is_allowed(self):
        readiness = build_tounicode_repair_readiness_report(
            font_records=[],
            active_failure_count=4,
            text_extraction_before=None,
            render_comparison_available=False,
            h11_artifacts_available=False,
        )

        self.assertFalse(readiness["candidate_creation_allowed"])
        self.assertEqual(readiness["terminal_state_if_stopped_here"], TERMINAL_BLOCKED_BY_MISSING_EVIDENCE)
        self.assertIn("no_missing_tounicode_font_records_supplied", readiness["missing_report_evidence"])
        self.assertFalse(readiness["safe_to_claim_pass"])

    def test_attempt_loop_records_attempt_cap_and_rejected_candidate_without_adoption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_dir = root / "app"
            job_dir = root / "job"
            app_dir.mkdir()
            job_dir.mkdir()
            strategy_request = job_dir / "hermes_strategy_request.json"
            strategy_request.write_text(json.dumps({
                "ticket": "MM-TEST",
                "job_name": "MM-TEST_doc",
                "current_pdf": str(job_dir / "current.pdf"),
                "source_pdf": str(job_dir / "source.pdf"),
                "residual_failures": [
                    {"rule_id": "PDF/UA-1/7.21.7", "failures": 4},
                ],
            }))
            for name in ["current.pdf", "source.pdf", "reference.pdf"]:
                (job_dir / name).write_bytes(b"%PDF-1.7\n%%EOF\n")

            def fake_generate(*, generation_request, job_dir):
                return {
                    "result": "SCRIPT_SOURCE",
                    "rule_id": generation_request["target_rule_id"],
                    "strategy": "unsafe_dummy_strategy",
                    "script_source": "print('{}')",
                }

            def fake_execute(**kwargs):
                return {
                    "result": "FAIL",
                    "stage": "validated_candidate",
                    "candidate_relative_path": "tools/repair/generated/fix_generated_attempt_01.py",
                    "execution_contract": {"result": "PASS", "stdout_json": {"strategy": "unsafe_dummy_strategy"}},
                    "validation": {"result": "FAIL", "gate_results": {"preservation": "PASS"}},
                    "success_predicate": {
                        "result": "FAIL",
                        "target_rule_id": "PDF/UA-1/7.21.7",
                        "target_rule_count_before": 4,
                        "target_rule_count_after": 4,
                        "target_rule_strictly_decreased": False,
                        "new_rule_ids_relative_to_gap_entry": [],
                        "worsened_existing_rules_relative_to_gap_entry": [],
                        "failed_gates": [],
                        "execution_contract_result": "PASS",
                    },
                }

            result = run_residual_self_extension_attempts(
                app_dir=app_dir,
                job_dir=job_dir,
                strategy_request_path=strategy_request,
                target_rule_id="PDF/UA-1/7.21.7",
                current_pdf=job_dir / "current.pdf",
                source_pdf=job_dir / "source.pdf",
                reference_pdf=job_dir / "reference.pdf",
                max_attempts=1,
                generate_func=fake_generate,
                execute_func=fake_execute,
            )

            self.assertEqual(result["result"], "FAIL")
            self.assertEqual(result["reason"], "max_attempts_exhausted")
            self.assertEqual(result["max_attempts"], 1)
            self.assertEqual(len(result["attempts"]), 1)
            self.assertFalse(result["adoption_performed"])
            self.assertFalse(result["final_pdf_updated"])


if __name__ == "__main__":
    unittest.main()
