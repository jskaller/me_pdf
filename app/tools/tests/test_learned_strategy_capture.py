#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_capture import (
    capture_candidate_result,
    capture_generation_event,
    learned_strategies_path,
)


RULE = "PDF/UA-1/7.21.4.1"


def base_candidate(job_dir: Path, post_count: int = 0):
    output = job_dir / "self_extension" / "rule" / "attempt_01" / "output.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"%PDF-1.7\n%%EOF\n")
    script = job_dir / "app" / "tools" / "repair" / "generated" / "fix_generated_rule_attempt_01.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('{}')\n")
    return {
        "result": "PASS" if post_count == 0 else "FAIL",
        "stage": "validated_candidate",
        "candidate_relative_path": "tools/repair/generated/fix_generated_rule_attempt_01.py",
        "candidate_script": str(script),
        "candidate_output_pdf": str(output),
        "attempt_dir": str(output.parent),
        "write_result": {
            "result": "PASS",
            "candidate_script": str(script),
            "script_sha256": "abc123",
        },
        "execution_contract": {
            "result": "PASS",
            "stdout_json": {"result": "MODIFIED", "strategy": "test_strategy"},
            "checks": {
                "input_hash_unchanged": True,
                "stdout_json_object": True,
                "output_pdf_exists": True,
                "output_pdf_nonempty": True,
            },
        },
        "validation": {
            "result": "PASS",
            "gate_results": {
                "preservation": "PASS",
                "form_fields": "PASS",
                "render_compare": "PASS",
            },
            "artifacts": {"candidate_failures_post": str(output.parent / "candidate_failures_post.json")},
        },
        "success_predicate": {
            "result": "PASS" if post_count == 0 else "FAIL",
            "target_rule_id": RULE,
            "target_rule_count_before": 2,
            "target_rule_count_after": post_count,
            "target_rule_strictly_decreased": post_count < 2,
            "new_rule_ids_relative_to_gap_entry": [],
            "worsened_existing_rules_relative_to_gap_entry": [],
            "failed_gates": [],
            "execution_contract_result": "PASS",
        },
    }


class LearnedStrategyCaptureTests(unittest.TestCase):
    def load_records(self, job_dir: Path):
        return json.loads(learned_strategies_path(job_dir).read_text())["records"]

    def test_clean_success_capture_is_indexing_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            result = capture_candidate_result(
                job_dir=job_dir,
                rule_id=RULE,
                candidate_result=base_candidate(job_dir, post_count=0),
                generation_request={"attempt": 1, "script_contract": {"cli": "input output [--out results.json]"}},
                generation_response={"strategy": "test_strategy", "expected_args_pattern": "input output [--out results.json]"},
                run_state={"run_id": "run-1", "self_extension": {"repair_attempts_used": 1}},
                attempt_number=1,
            )
            self.assertTrue(Path(result["artifact_path"]).exists())
            record = self.load_records(job_dir)[0]
            self.assertEqual(record["outcome"], "clean_success")
            self.assertTrue(record["clean"])
            self.assertTrue(record["indexing_eligible"])
            self.assertEqual(record["indexing_blockers"], [])
            self.assertEqual(record["script_sha256"], "abc123")

    def test_partial_improvement_capture_is_not_indexing_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            capture_candidate_result(
                job_dir=job_dir,
                rule_id=RULE,
                candidate_result=base_candidate(job_dir, post_count=1),
                attempt_number=1,
            )
            record = self.load_records(job_dir)[0]
            self.assertEqual(record["outcome"], "partial_improvement")
            self.assertFalse(record["clean"])
            self.assertFalse(record["indexing_eligible"])
            self.assertIn("target_rule_not_resolved", record["indexing_blockers"])

    def test_dirty_success_capture_records_introduced_rules(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            candidate = base_candidate(job_dir, post_count=0)
            candidate["success_predicate"]["new_rule_ids_relative_to_gap_entry"] = ["PDF/UA-1/9.9"]
            capture_candidate_result(job_dir=job_dir, rule_id=RULE, candidate_result=candidate, attempt_number=1)
            record = self.load_records(job_dir)[0]
            self.assertEqual(record["outcome"], "dirty_success")
            self.assertFalse(record["indexing_eligible"])
            self.assertEqual(record["introduced_rules"], ["PDF/UA-1/9.9"])
            self.assertTrue(any(b.startswith("introduced_rules:") for b in record["indexing_blockers"]))

    def test_validation_failure_capture_preserves_failure_summary(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            candidate = base_candidate(job_dir, post_count=2)
            candidate["result"] = "FAIL"
            candidate["reason"] = "target did not improve"
            candidate["success_predicate"]["target_rule_strictly_decreased"] = False
            capture_candidate_result(job_dir=job_dir, rule_id=RULE, candidate_result=candidate, attempt_number=1)
            record = self.load_records(job_dir)[0]
            self.assertEqual(record["outcome"], "validation_failed")
            self.assertFalse(record["indexing_eligible"])
            self.assertEqual(record["failure_summary"]["reason"], "target did not improve")
            self.assertIn("target_rule_not_decreased", record["indexing_blockers"])

    def test_transport_blocked_capture_is_non_script_and_non_indexable(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            capture_generation_event(
                job_dir=job_dir,
                rule_id=RULE,
                failure={"result": "TRANSPORT_BLOCKED", "failure_category": "gateway_rate_limited", "reason": "HTTP 429"},
                generation_request={"attempt": 1},
                run_state={"run_id": "run-transport", "self_extension": {"repair_attempts_used": 0, "transport_retries_used": 3}},
                attempt_number=1,
            )
            record = self.load_records(job_dir)[0]
            self.assertEqual(record["outcome"], "transport_blocked")
            self.assertIsNone(record["script_path"])
            self.assertFalse(record["indexing_eligible"])
            self.assertEqual(record["repair_attempts_used"], 0)

    def test_semantic_refusal_and_needs_more_evidence_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            capture_generation_event(
                job_dir=job_dir,
                rule_id=RULE,
                failure={"result": "FAIL", "failure_category": "llm_semantic_refusal", "llm_result": "NOT_AUTOMATABLE", "reason": "cannot repair"},
                generation_request={"attempt": 1},
                attempt_number=1,
            )
            capture_generation_event(
                job_dir=job_dir,
                rule_id=RULE,
                failure={"result": "FAIL", "failure_category": "llm_semantic_refusal", "llm_result": "NEEDS_MORE_EVIDENCE", "raw_content_prefix": "need xml"},
                generation_request={"attempt": 2},
                attempt_number=2,
            )
            outcomes = [r["outcome"] for r in self.load_records(job_dir)]
            self.assertEqual(outcomes, ["semantic_refusal", "needs_more_evidence"])
            for record in self.load_records(job_dir):
                self.assertFalse(record["indexing_eligible"])
                self.assertIsNone(record["script_path"])

    def test_append_idempotency_preserves_existing_records(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            candidate = base_candidate(job_dir, post_count=0)
            kwargs = dict(
                job_dir=job_dir,
                rule_id=RULE,
                candidate_result=candidate,
                run_state={"run_id": "run-1", "self_extension": {}},
                attempt_number=1,
            )
            capture_candidate_result(**kwargs)
            first_created_at = self.load_records(job_dir)[0]["created_at"]
            capture_candidate_result(**kwargs)
            records = self.load_records(job_dir)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["created_at"], first_created_at)

    def test_no_mutation_contract_is_job_scoped_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rule_map = root / "app" / "tools" / "audit" / "rule_repair_map.json"
            repair_dir = root / "app" / "tools" / "repair"
            repair_dir.mkdir(parents=True)
            rule_map.parent.mkdir(parents=True)
            rule_map.write_text('{"rules": []}')
            repair_file = repair_dir / "fix_existing.py"
            repair_file.write_text("print('existing')")
            before_rule_map = rule_map.read_text()
            before_repair = repair_file.read_text()
            capture_candidate_result(
                job_dir=root / "workspace" / "jobs" / "job1",
                rule_id=RULE,
                candidate_result=base_candidate(root / "workspace" / "jobs" / "job1", post_count=0),
                attempt_number=1,
            )
            self.assertEqual(rule_map.read_text(), before_rule_map)
            self.assertEqual(repair_file.read_text(), before_repair)


if __name__ == "__main__":
    unittest.main()
