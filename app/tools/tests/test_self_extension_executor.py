import json
import tempfile
import unittest
from pathlib import Path

from tools.orchestrate.self_extension_executor import (
    build_generation_failure_record,
    build_generation_prompt,
    build_residual_script_generation_request,
    evaluate_residual_success,
    parse_generation_response,
    prepare_candidate_paths,
)


class SelfExtensionExecutorTests(unittest.TestCase):
    def test_success_predicate_anchors_new_failures_to_gap_entry_residual(self):
        gap_entry = [
            {"rule_id": "PDF/UA-1/7.18.4", "failures": 5},
            {"rule_id": "PDF/UA-1/7.1", "failures": 2},
        ]
        candidate_post = [
            {"rule_id": "PDF/UA-1/7.18.4", "failures": 3},
            {"rule_id": "PDF/UA-1/7.1", "failures": 2},
        ]
        result = evaluate_residual_success(
            target_rule_id="PDF/UA-1/7.18.4",
            gap_entry_failures=gap_entry,
            candidate_post_failures=candidate_post,
            gate_results={
                "preservation": "PASS",
                "form_fields": "PASS",
                "render_compare": "PASS",
            },
            execution_contract={"result": "PASS"},
        )
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["comparison_anchor"], "gap_entry_residual_failures")

    def test_success_predicate_rejects_new_rule_relative_to_gap_entry(self):
        result = evaluate_residual_success(
            target_rule_id="PDF/UA-1/7.18.4",
            gap_entry_failures=[{"rule_id": "PDF/UA-1/7.18.4", "failures": 5}],
            candidate_post_failures=[
                {"rule_id": "PDF/UA-1/7.18.4", "failures": 3},
                {"rule_id": "PDF/UA-1/7.99", "failures": 1},
            ],
            gate_results={
                "preservation": "PASS",
                "form_fields": "PASS",
                "render_compare": "PASS",
            },
            execution_contract={"result": "PASS"},
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["new_rule_ids_relative_to_gap_entry"], ["PDF/UA-1/7.99"])

    def test_generation_request_requires_script_source_not_repair_script_path(self):
        request = build_residual_script_generation_request(
            strategy_request={
                "ticket": "MM-TEST",
                "job_name": "MM-TEST_doc",
                "current_pdf": "/job/repair/pass.pdf",
                "source_pdf": "/workspace/input/MM-TEST/doc.pdf",
                "residual_failures": [
                    {"rule_id": "PDF/UA-1/7.18.4", "failures": 5, "description": "Widget issue"}
                ],
            },
            target_rule_id="PDF/UA-1/7.18.4",
            attempt=1,
            candidate_relative_path="tools/repair/generated/fix_generated_x.py",
        )
        schema = request["required_response_schema"]
        self.assertIn("script_source", schema)
        self.assertNotIn("repair_script", schema)
        self.assertEqual(schema["result"], "SCRIPT_SOURCE | NEEDS_MORE_EVIDENCE | NOT_AUTOMATABLE")


    def test_generation_request_is_compact_target_rule_only(self):
        request = build_residual_script_generation_request(
            strategy_request={
                "ticket": "MM-TEST",
                "job_name": "MM-TEST_doc",
                "current_pdf": "/job/repair/pass.pdf",
                "source_pdf": "/workspace/input/MM-TEST/doc.pdf",
                "residual_failures": [
                    {
                        "rule_id": "PDF/UA-1/7.21.4.1",
                        "failures": 2,
                        "description": "Target font embedding issue",
                    },
                    {
                        "rule_id": "PDF/UA-1/7.18.4",
                        "failures": 204,
                        "description": "UNRELATED_WIDGET_CONTEXT_SHOULD_NOT_BE_SENT",
                    },
                ],
                "validator_rule_xml_snippets": [
                    {"rule_id": "PDF/UA-1/7.21.4.1", "snippet": "target xml"},
                    {"rule_id": "PDF/UA-1/7.18.4", "snippet": "unrelated xml"},
                ],
            },
            target_rule_id="PDF/UA-1/7.21.4.1",
            attempt=1,
            candidate_relative_path="tools/repair/generated/fix_generated_x.py",
        )

        evidence = request["evidence"]
        self.assertEqual(request["request_payload_profile"], "compact_target_rule_only")
        self.assertEqual(evidence["residual_failure_payload"], "target_rule_only")
        self.assertEqual(evidence["total_residual_rule_count"], 2)
        self.assertEqual(evidence["omitted_non_target_residual_rule_count"], 1)
        self.assertEqual(len(evidence["residual_failures"]), 1)
        self.assertEqual(evidence["residual_failures"][0]["rule_id"], "PDF/UA-1/7.21.4.1")
        self.assertEqual(len(evidence["validator_rule_xml_snippets"]), 1)
        serialized = json.dumps(request)
        self.assertIn("Target font embedding issue", serialized)
        self.assertNotIn("UNRELATED_WIDGET_CONTEXT_SHOULD_NOT_BE_SENT", serialized)
        self.assertNotIn("unrelated xml", serialized)

    def test_candidate_paths_use_generated_quarantine_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = prepare_candidate_paths(
                root / "app",
                root / "job",
                "PDF/UA-1/7.1",
                2,
            )
            self.assertIn("tools/repair/generated", paths.candidate_relative_path)
            self.assertTrue(paths.candidate_script.parent.name == "generated")
            self.assertTrue(paths.candidate_script.name.endswith("_attempt_02.py"))

    def test_parse_generation_response_rejects_plan_without_source(self):
        with self.assertRaises(Exception):
            parse_generation_response(json.dumps({"result": "PROPOSE_NEW_SCRIPT", "repair_script": "tools/repair/x.py"}))


    def test_generation_prompt_forbids_agent_side_effects(self):
        prompt = build_generation_prompt({"target_rule_id": "PDF/UA-1/7.21.4.1"})
        self.assertIn("source-generation mode only", prompt)
        self.assertIn("Do not write files", prompt)
        self.assertIn("Do not execute commands", prompt)
        self.assertIn("Do not run validation", prompt)
        self.assertIn("executor is the only component allowed", prompt)
        self.assertIn("script_source", prompt)

    def test_parse_generation_response_rejects_side_effect_claims(self):
        raw = (
            "The repair script has been written to `/app/tools/repair/generated/x.py` "
            "and verified end-to-end on the target PDF.\n\n"
            "Live execution result: {\"result\": \"SUCCESS\"}"
        )
        with self.assertRaises(Exception) as ctx:
            parse_generation_response(raw)
        self.assertIn("claimed external side effects", str(ctx.exception))

    def test_generation_failure_record_preserves_gateway_error_content(self):
        request = {
            "target_rule_id": "PDF/UA-1/7.21.4.1",
            "attempt": 1,
            "candidate_relative_path": "tools/repair/generated/fix_generated_x.py",
        }
        raw = "API call failed after 3 retries: HTTP 429: Too Many Requests"
        record = build_generation_failure_record(
            generation_request=request,
            prompt="PROMPT",
            elapsed_seconds=9.25,
            reason="generation response was not strict JSON",
            error_type="CandidateRejected",
            response={
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "response_model": "Hermes Agent",
                "gateway_model": "Hermes Agent",
                "gateway_base_url": "http://127.0.0.1:8642/v1",
            },
            raw_content=raw,
        )

        self.assertEqual(record["result"], "FAIL")
        self.assertEqual(record["phase"], "generation")
        self.assertEqual(record["target_rule_id"], "PDF/UA-1/7.21.4.1")
        self.assertIn("HTTP 429", record["raw_content_prefix"])
        self.assertEqual(record["raw_content_chars"], len(raw))
        self.assertEqual(record["reported_usage"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
