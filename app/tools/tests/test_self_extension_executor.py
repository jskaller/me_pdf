import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.orchestrate.self_extension_executor import (
    GenerationRejected,
    build_candidate_retry_feedback,
    build_generation_failure_record,
    build_generation_prompt,
    classify_generation_failure,
    build_residual_script_generation_request,
    evaluate_residual_success,
    parse_generation_response,
    prepare_candidate_paths,
    run_residual_self_extension_attempts,
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
        self.assertEqual(record["failure_category"], "gateway_rate_limited")
        self.assertTrue(record["retryable"])
        self.assertEqual(record["gateway_status_code"], 429)

    def test_generation_failure_classification_distinguishes_common_failures(self):
        self.assertEqual(
            classify_generation_failure(
                raw_content="API call failed after 3 retries: HTTP 429: Too Many Requests"
            )["failure_category"],
            "gateway_rate_limited",
        )
        self.assertTrue(
            classify_generation_failure(reason="gateway call failed: TimeoutError: timed out")[
                "retryable"
            ]
        )
        self.assertEqual(
            classify_generation_failure(raw_content="The repair script has been written to /app/x.py")[
                "failure_category"
            ],
            "generation_boundary_violation",
        )
        self.assertEqual(
            classify_generation_failure(raw_content="plain prose, not json")[
                "failure_category"
            ],
            "non_json_generation_response",
        )
        semantic = classify_generation_failure(
            raw_content=json.dumps({"result": "NOT_AUTOMATABLE", "notes": "cannot repair"}),
            reason="generation did not return SCRIPT_SOURCE: NOT_AUTOMATABLE",
        )
        self.assertEqual(semantic["failure_category"], "llm_semantic_refusal")
        self.assertEqual(semantic["llm_result"], "NOT_AUTOMATABLE")
        self.assertFalse(semantic["retryable"])


    def test_candidate_retry_feedback_summarizes_failed_attempt(self):
        feedback = build_candidate_retry_feedback(
            attempt=2,
            generation_response={"rule_id": "PDF/UA-1/7.21.4.1", "strategy": "bad_strategy"},
            candidate_result={
                "result": "FAIL",
                "stage": "validated_candidate",
                "candidate_relative_path": "tools/repair/generated/bad.py",
                "execution_contract": {
                    "result": "PASS",
                    "stdout_json": {
                        "result": "MODIFIED",
                        "strategy": "bad_strategy",
                        "reason": "changed_something_else",
                    },
                },
                "success_predicate": {
                    "result": "FAIL",
                    "target_rule_id": "PDF/UA-1/7.21.4.1",
                    "target_rule_count_before": 2,
                    "target_rule_count_after": 2,
                    "target_rule_strictly_decreased": False,
                    "failed_gates": ["preservation"],
                    "execution_contract_result": "PASS",
                },
                "validation": {
                    "result": "FAIL",
                    "gate_results": {"preservation": "ERROR"},
                    "candidate_post_failures": [
                        {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2},
                        {"rule_id": "PDF/UA-1/7.18.4", "failures": 204},
                    ],
                },
            },
        )

        self.assertEqual(feedback["attempt"], 2)
        self.assertEqual(feedback["strategy"], "bad_strategy")
        self.assertFalse(feedback["success_predicate"]["target_rule_strictly_decreased"])
        self.assertEqual(
            feedback["validation"]["target_rule_candidate_post_failures"],
            [{"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2}],
        )
        self.assertIn("Do not repeat", feedback["instruction"])

    def test_run_attempt_loop_retries_with_prior_feedback(self):
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
                    {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2},
                ],
            }))
            for name in ["current.pdf", "source.pdf", "reference.pdf"]:
                (job_dir / name).write_bytes(b"%PDF-1.7\n%%EOF\n")

            generation_requests = []

            def fake_generate(*, generation_request, job_dir):
                generation_requests.append(generation_request)
                return {
                    "result": "SCRIPT_SOURCE",
                    "rule_id": generation_request["target_rule_id"],
                    "strategy": f"strategy_attempt_{generation_request['attempt']}",
                    "script_source": "print('{}')",
                }

            def fake_execute(**kwargs):
                attempt = kwargs["attempt"]
                if attempt == 1:
                    return {
                        "result": "FAIL",
                        "stage": "validated_candidate",
                        "candidate_relative_path": "tools/repair/generated/a1.py",
                        "execution_contract": {
                            "result": "PASS",
                            "stdout_json": {"result": "MODIFIED", "strategy": "strategy_attempt_1"},
                        },
                        "validation": {
                            "result": "FAIL",
                            "gate_results": {"preservation": "PASS"},
                            "candidate_post_failures": [
                                {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2}
                            ],
                        },
                        "success_predicate": {
                            "result": "FAIL",
                            "target_rule_id": "PDF/UA-1/7.21.4.1",
                            "target_rule_count_before": 2,
                            "target_rule_count_after": 2,
                            "target_rule_strictly_decreased": False,
                            "failed_gates": [],
                            "execution_contract_result": "PASS",
                        },
                    }
                return {
                    "result": "PASS",
                    "stage": "validated_candidate",
                    "candidate_relative_path": "tools/repair/generated/a2.py",
                    "candidate_output_pdf": str(job_dir / "out.pdf"),
                    "execution_contract": {"result": "PASS", "stdout_json": {"strategy": "strategy_attempt_2"}},
                    "validation": {"result": "PASS", "gate_results": {}},
                    "success_predicate": {
                        "result": "PASS",
                        "target_rule_id": "PDF/UA-1/7.21.4.1",
                        "target_rule_count_before": 2,
                        "target_rule_count_after": 1,
                        "target_rule_strictly_decreased": True,
                        "failed_gates": [],
                        "execution_contract_result": "PASS",
                    },
                }

            result = run_residual_self_extension_attempts(
                app_dir=app_dir,
                job_dir=job_dir,
                strategy_request_path=strategy_request,
                target_rule_id="PDF/UA-1/7.21.4.1",
                current_pdf=job_dir / "current.pdf",
                source_pdf=job_dir / "source.pdf",
                reference_pdf=job_dir / "reference.pdf",
                max_attempts=2,
                generate_func=fake_generate,
                execute_func=fake_execute,
            )

            self.assertEqual(result["result"], "PASS")
            self.assertEqual(len(generation_requests), 2)
            self.assertEqual(generation_requests[0]["prior_feedback"], {})
            prior = generation_requests[1]["prior_feedback"]["previous_attempts"]
            self.assertEqual(len(prior), 1)
            self.assertEqual(prior[0]["attempt"], 1)
            self.assertFalse(prior[0]["success_predicate"]["target_rule_strictly_decreased"])

    def test_run_attempt_loop_retries_semantic_refusal_while_attempts_remain(self):
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
                    {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2},
                ],
            }))
            for name in ["current.pdf", "source.pdf", "reference.pdf"]:
                (job_dir / name).write_bytes(b"%PDF-1.7\n%%EOF\n")

            generation_requests = []

            def fake_generate(*, generation_request, job_dir):
                generation_requests.append(generation_request)
                if generation_request["attempt"] == 1:
                    raw = json.dumps({
                        "result": "NOT_AUTOMATABLE",
                        "rule_id": generation_request["target_rule_id"],
                        "notes": "refused instead of generating",
                    })
                    failure = build_generation_failure_record(
                        generation_request=generation_request,
                        prompt="PROMPT",
                        elapsed_seconds=1.0,
                        reason="generation did not return SCRIPT_SOURCE: NOT_AUTOMATABLE",
                        error_type="CandidateRejected",
                        raw_content=raw,
                    )
                    raise GenerationRejected(failure["reason"], failure, raw_content=raw)
                return {
                    "result": "SCRIPT_SOURCE",
                    "rule_id": generation_request["target_rule_id"],
                    "strategy": "strategy_after_refusal",
                    "script_source": "print('{}')",
                }

            def fake_execute(**kwargs):
                return {
                    "result": "PASS",
                    "stage": "validated_candidate",
                    "candidate_relative_path": "tools/repair/generated/a2.py",
                    "candidate_output_pdf": str(job_dir / "out.pdf"),
                    "execution_contract": {"result": "PASS", "stdout_json": {"strategy": "strategy_after_refusal"}},
                    "validation": {"result": "PASS", "gate_results": {}},
                    "success_predicate": {
                        "result": "PASS",
                        "target_rule_id": "PDF/UA-1/7.21.4.1",
                        "target_rule_count_before": 2,
                        "target_rule_count_after": 1,
                        "target_rule_strictly_decreased": True,
                        "failed_gates": [],
                        "execution_contract_result": "PASS",
                    },
                }

            result = run_residual_self_extension_attempts(
                app_dir=app_dir,
                job_dir=job_dir,
                strategy_request_path=strategy_request,
                target_rule_id="PDF/UA-1/7.21.4.1",
                current_pdf=job_dir / "current.pdf",
                source_pdf=job_dir / "source.pdf",
                reference_pdf=job_dir / "reference.pdf",
                max_attempts=2,
                generate_func=fake_generate,
                execute_func=fake_execute,
            )

            self.assertEqual(result["result"], "PASS")
            self.assertEqual(len(generation_requests), 2)
            prior = generation_requests[1]["prior_feedback"]["previous_attempts"]
            self.assertEqual(prior[0]["failure_category"], "llm_semantic_refusal")
            self.assertEqual(prior[0]["llm_result"], "NOT_AUTOMATABLE")
            self.assertIn("not terminal", prior[0]["instruction"])


    def test_run_attempt_loop_transport_blocked_writes_run_state_without_candidate_attempt(self):
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
                    {"rule_id": "PDF/UA-1/7.21.4.1", "failures": 2},
                ],
            }))
            for name in ["current.pdf", "source.pdf", "reference.pdf"]:
                (job_dir / name).write_bytes(b"%PDF-1.7\n%%EOF\n")

            generation_calls = []

            def fake_generate(*, generation_request, job_dir):
                generation_calls.append(generation_request)
                raw = "API call failed after 3 retries: HTTP 429: Too Many Requests"
                failure = build_generation_failure_record(
                    generation_request=generation_request,
                    prompt="PROMPT",
                    elapsed_seconds=1.0,
                    reason="generation response was not strict JSON",
                    error_type="CandidateRejected",
                    raw_content=raw,
                )
                raise GenerationRejected(failure["reason"], failure, raw_content=raw)

            old_retry_budget = os.environ.get("HERMES_SELF_EXTENSION_TRANSPORT_RETRY_BUDGET")
            os.environ["HERMES_SELF_EXTENSION_TRANSPORT_RETRY_BUDGET"] = "0"
            try:
                result = run_residual_self_extension_attempts(
                    app_dir=app_dir,
                    job_dir=job_dir,
                    strategy_request_path=strategy_request,
                    target_rule_id="PDF/UA-1/7.21.4.1",
                    current_pdf=job_dir / "current.pdf",
                    source_pdf=job_dir / "source.pdf",
                    reference_pdf=job_dir / "reference.pdf",
                    max_attempts=2,
                    generate_func=fake_generate,
                    execute_func=lambda **kwargs: self.fail("transport failure must not execute a candidate"),
                )
            finally:
                if old_retry_budget is None:
                    os.environ.pop("HERMES_SELF_EXTENSION_TRANSPORT_RETRY_BUDGET", None)
                else:
                    os.environ["HERMES_SELF_EXTENSION_TRANSPORT_RETRY_BUDGET"] = old_retry_budget

            self.assertEqual(result["result"], "TRANSPORT_BLOCKED")
            self.assertEqual(len(generation_calls), 1)
            self.assertIn("run_state_path", result)

            run_state_path = Path(result["run_state_path"])
            self.assertTrue(run_state_path.exists())
            run_state = json.loads(run_state_path.read_text())

            self.assertEqual(run_state["self_extension"]["repair_attempts_used"], 0)
            self.assertEqual(run_state["self_extension"]["candidate_attempt_count"], 0)
            self.assertEqual(run_state["self_extension"]["transport_failure_count"], 1)
            self.assertEqual(run_state["self_extension"]["last_outcome"], "TRANSPORT_BLOCKED")

if __name__ == "__main__":
    unittest.main()
