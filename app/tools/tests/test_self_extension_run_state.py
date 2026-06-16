#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from tools.orchestrate.self_extension_run_state import (
    RUN_STATE_RELATIVE_PATH,
    TRANSPORT_BLOCKED,
    SelfExtensionRunState,
    generation_call_with_run_state,
    is_retryable_transport_failure,
    summarize_no_adoption_guard,
)


class FakeGenerationRejected(Exception):
    def __init__(self, failure_record):
        super().__init__(failure_record.get("reason", "generation rejected"))
        self.failure_record = failure_record


class SelfExtensionRunStateTests(unittest.TestCase):
    def test_run_state_creation_records_fresh_target_and_zero_counters(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            source = job_dir / "source.pdf"
            current = job_dir / "current.pdf"
            source.write_bytes(b"source")
            current.write_bytes(b"current")

            state = SelfExtensionRunState.start(
                job_dir=job_dir,
                target_rule_id="PDF/UA-1/7.1",
                source_pdf=source,
                current_pdf=current,
                residual_gap_entry_anchor="gap-entry-001",
                repair_attempt_budget=3,
                transport_retry_budget=2,
                generation_call_budget=10,
            )

            self.assertTrue((job_dir / RUN_STATE_RELATIVE_PATH).exists())
            self.assertTrue(state.run_id)
            counters = state.data["self_extension"]
            self.assertEqual(counters["target_rule_id"], "PDF/UA-1/7.1")
            self.assertEqual(counters["repair_attempts_used"], 0)
            self.assertEqual(counters["transport_retries_used"], 0)
            self.assertEqual(counters["transport_failure_count"], 0)
            self.assertEqual(counters["generation_call_count"], 0)
            self.assertEqual(counters["candidate_attempt_count"], 0)
            self.assertEqual(state.data["residual_gap_entry_anchor"], "gap-entry-001")
            self.assertIsNotNone(state.data["source_pdf_hash"])
            self.assertIsNotNone(state.data["current_pdf_hash"])

    def test_stale_copied_budget_is_preserved_but_not_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            stale_state = job_dir / RUN_STATE_RELATIVE_PATH
            stale_state.parent.mkdir(parents=True)
            stale_state.write_text(json.dumps({"run_id": "old-run", "self_extension": {"generation_call_count": 10}}))
            stale_budget = job_dir / "self_extension_call_budget.json"
            stale_budget.write_text(json.dumps({"generation_calls_reserved": 10, "max_generation_calls_per_job": 10}))

            state = SelfExtensionRunState.start(job_dir=job_dir, target_rule_id="7.1")

            self.assertNotEqual(state.run_id, "old-run")
            counters = state.data["self_extension"]
            self.assertEqual(counters["generation_call_count"], 0)
            self.assertEqual(counters["repair_attempts_used"], 0)
            self.assertTrue(state.data["stale_artifacts"]["previous_run_state_existed"])
            self.assertTrue(state.data["stale_artifacts"]["previous_legacy_budget_existed"])
            self.assertTrue(state.data["stale_artifacts"]["ignored_for_budget_accounting"])
            archived = state.data["stale_artifacts"]["archived_artifacts"]
            self.assertIn("previous_run_state", archived)
            self.assertIn("legacy_budget", archived)
            self.assertTrue(Path(archived["previous_run_state"]).exists())
            self.assertTrue(Path(archived["legacy_budget"]).exists())

    def test_429_retry_accounting_does_not_consume_candidate_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SelfExtensionRunState.start(job_dir=Path(tmp), target_rule_id="7.1", transport_retry_budget=1)
            calls = {"count": 0}

            def generate_fn(**kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise FakeGenerationRejected(
                        {
                            "result": "FAIL",
                            "failure_category": "gateway_rate_limited",
                            "retryable": True,
                            "gateway_status_code": 429,
                            "reason": "HTTP 429 Too Many Requests",
                        }
                    )
                return {"result": "SCRIPT_SOURCE", "script_source": "print('ok')", "strategy": "ok"}

            result = generation_call_with_run_state(
                run_state=state,
                generation_request={"target_rule_id": "7.1", "attempt": 1},
                generate_fn=generate_fn,
                sleep_fn=lambda _: None,
            )

            self.assertEqual(result["result"], "SCRIPT_SOURCE")
            counters = SelfExtensionRunState.load(Path(tmp)).data["self_extension"]
            self.assertEqual(counters["generation_call_count"], 2)
            self.assertEqual(counters["transport_failure_count"], 1)
            self.assertEqual(counters["transport_retries_used"], 1)
            self.assertEqual(counters["repair_attempts_used"], 0)
            self.assertEqual(counters["candidate_attempt_count"], 0)
            artifacts = list((Path(tmp) / "audit" / "self_extension_transport_failures").glob("*.json"))
            self.assertEqual(len(artifacts), 1)

    def test_timeout_retry_accounting_does_not_consume_candidate_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SelfExtensionRunState.start(job_dir=Path(tmp), target_rule_id="7.1", transport_retry_budget=1)
            calls = {"count": 0}

            def generate_fn(**kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise FakeGenerationRejected(
                        {
                            "result": "FAIL",
                            "failure_category": "gateway_timeout",
                            "retryable": True,
                            "reason": "gateway timed out",
                        }
                    )
                return {"result": "SCRIPT_SOURCE", "script_source": "print('ok')"}

            generation_call_with_run_state(
                run_state=state,
                generation_request={"target_rule_id": "7.1", "attempt": 1},
                generate_fn=generate_fn,
                sleep_fn=lambda _: None,
            )

            counters = SelfExtensionRunState.load(Path(tmp)).data["self_extension"]
            self.assertEqual(counters["transport_failure_count"], 1)
            self.assertEqual(counters["transport_retries_used"], 1)
            self.assertEqual(counters["repair_attempts_used"], 0)
            self.assertEqual(counters["candidate_attempt_count"], 0)

    def test_exhausted_transport_budget_returns_transport_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SelfExtensionRunState.start(job_dir=Path(tmp), target_rule_id="7.1", transport_retry_budget=1)

            def generate_fn(**kwargs):
                raise FakeGenerationRejected(
                    {
                        "result": "FAIL",
                        "failure_category": "gateway_rate_limited",
                        "retryable": True,
                        "gateway_status_code": 429,
                        "reason": "HTTP 429 Too Many Requests",
                    }
                )

            result = generation_call_with_run_state(
                run_state=state,
                generation_request={"target_rule_id": "7.1", "attempt": 1},
                generate_fn=generate_fn,
                sleep_fn=lambda _: None,
            )

            self.assertEqual(result["result"], TRANSPORT_BLOCKED)
            self.assertNotEqual(result.get("failure_category"), "llm_semantic_refusal")
            counters = SelfExtensionRunState.load(Path(tmp)).data["self_extension"]
            self.assertEqual(counters["transport_retries_used"], 1)
            self.assertEqual(counters["transport_failure_count"], 2)
            self.assertEqual(counters["repair_attempts_used"], 0)
            self.assertEqual(counters["candidate_attempt_count"], 0)

    def test_candidate_validation_failure_consumes_repair_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SelfExtensionRunState.start(job_dir=Path(tmp), target_rule_id="7.1")
            state.record_candidate_attempt(
                {
                    "result": "FAIL",
                    "stage": "validated_candidate",
                    "candidate_relative_path": "tools/repair/generated/fix_generated_x_attempt_01.py",
                }
            )

            counters = SelfExtensionRunState.load(Path(tmp)).data["self_extension"]
            self.assertEqual(counters["repair_attempts_used"], 1)
            self.assertEqual(counters["candidate_attempt_count"], 1)
            self.assertEqual(counters["validation_failure_count"], 1)

    def test_semantic_refusal_is_counted_separately_and_not_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SelfExtensionRunState.start(job_dir=Path(tmp), target_rule_id="7.1")

            def generate_fn(**kwargs):
                raise FakeGenerationRejected(
                    {
                        "result": "NEEDS_MORE_EVIDENCE",
                        "failure_category": "llm_semantic_refusal",
                        "llm_result": "NEEDS_MORE_EVIDENCE",
                        "retryable": False,
                        "reason": "more validator evidence needed",
                    }
                )

            result = generation_call_with_run_state(
                run_state=state,
                generation_request={"target_rule_id": "7.1", "attempt": 1},
                generate_fn=generate_fn,
                sleep_fn=lambda _: None,
            )

            self.assertEqual(result["llm_result"], "NEEDS_MORE_EVIDENCE")
            counters = SelfExtensionRunState.load(Path(tmp)).data["self_extension"]
            self.assertEqual(counters["semantic_refusal_count"], 1)
            self.assertEqual(counters["needs_more_evidence_count"], 1)
            self.assertEqual(counters["transport_retries_used"], 0)
            self.assertEqual(counters["repair_attempts_used"], 0)

    def test_no_adoption_no_mutation_summary(self):
        result = summarize_no_adoption_guard(
            rule_map_before_hash="abc",
            rule_map_after_hash="abc",
            final_pdf_before="/jobs/out/final.pdf",
            final_pdf_after="/jobs/out/final.pdf",
        )
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["rule_map_mutated"])
        self.assertFalse(result["final_pdf_path_changed"])
        self.assertFalse(result["adoption_performed"])

    def test_retryable_transport_classifier_accepts_429_and_timeout(self):
        self.assertTrue(is_retryable_transport_failure({"reason": "HTTP 429 Too Many Requests"}))
        self.assertTrue(is_retryable_transport_failure({"reason": "socket timed out"}))


if __name__ == "__main__":
    unittest.main()
