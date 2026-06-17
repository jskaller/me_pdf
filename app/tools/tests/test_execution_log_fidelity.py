#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit.execution_log import (
    RECORD_REPAIR_STEP,
    build_execution_log_from_repair_steps,
    new_execution_log,
    record_callable_execution,
    record_subprocess_execution,
    write_execution_log,
)
from tools.audit.residual_analysis import analyze_residuals
from tools.audit.learned_strategy_capture import capture_candidate_result, learned_strategies_path

RULE = "PDF/UA-1/7.21.4.1"


def write_pdf(path: Path, body: bytes = b"%PDF-1.7\n%%EOF\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def summary(*items):
    return {
        "result": "FAIL" if items else "PASS",
        "failures_by_rule": [
            {"rule_id": rule_id, "failures": count, "description": rule_id}
            for rule_id, count in items
        ],
    }


class ExecutionLogFidelityTests(unittest.TestCase):
    def test_successful_callable_repair_step_record(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            input_pdf = write_pdf(job / "in.pdf")
            output_pdf = job / "out.pdf"
            log = new_execution_log(job_dir=job, source_pdf=input_pdf, run_id="run-1")

            def repair():
                output_pdf.write_bytes(input_pdf.read_bytes() + b"\n% fixed")
                return {"result": "PASS"}

            _, record = record_callable_execution(
                log,
                func=repair,
                record_type=RECORD_REPAIR_STEP,
                iteration=1,
                step_name="fix_pdfua_identifier",
                script="tools/repair/fix_pdfua_identifier.py",
                rules_targeted=[RULE],
                input_pdf=input_pdf,
                output_pdf=output_pdf,
            )
            self.assertEqual(record["result"], "PASS")
            self.assertTrue(record["attempt_id"])
            self.assertTrue(record["started_at"])
            self.assertTrue(record["finished_at"])
            self.assertIsInstance(record["duration_ms"], int)
            self.assertTrue(record["input_pdf_sha256"])
            self.assertTrue(record["output_pdf_sha256"])
            self.assertTrue(record["output_exists"])
            self.assertEqual(record["rules_targeted"], [RULE])
            self.assertEqual(log["repair_steps"][0]["attempt_id"], record["attempt_id"])

    def test_failed_callable_repair_step_record(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            input_pdf = write_pdf(job / "in.pdf")
            output_pdf = job / "missing.pdf"
            log = new_execution_log(job_dir=job, source_pdf=input_pdf, run_id="run-1")

            def repair():
                raise ValueError("boom")

            with self.assertRaises(RuntimeError):
                record_callable_execution(
                    log,
                    func=repair,
                    record_type=RECORD_REPAIR_STEP,
                    step_name="bad_callable",
                    rules_targeted=[RULE],
                    input_pdf=input_pdf,
                    output_pdf=output_pdf,
                )
            record = log["records"][0]
            self.assertEqual(record["result"], "FAIL")
            self.assertEqual(record["exception_type"], "ValueError")
            self.assertIn("boom", record["exception_message"])
            self.assertFalse(record["output_exists"])

            analysis = analyze_residuals(
                baseline_failures=summary((RULE, 2)),
                post_failures=summary((RULE, 2)),
                repair_plan={"repair_steps": [{"repair_script": "bad.py", "rules_addressed": [RULE]}]},
                execution_log=log,
                rule_map={"rules": {RULE: {"resolvability": "effective"}}},
                job_dir=job,
            )
            self.assertIn(log["records"][0]["attempt_id"], analysis["rules"][RULE]["execution_attempt_ids"])

    def test_successful_subprocess_record_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            input_pdf = write_pdf(job / "in.pdf")
            output_pdf = job / "out.pdf"
            script = job / "copy.py"
            script.write_text(
                "import pathlib, sys; pathlib.Path(sys.argv[2]).write_bytes(pathlib.Path(sys.argv[1]).read_bytes()); print('ok')"
            )
            log = new_execution_log(job_dir=job, source_pdf=input_pdf, run_id="run-1")
            proc, record = record_subprocess_execution(
                log,
                argv=[sys.executable, script, input_pdf, output_pdf],
                step_name="copy_pdf",
                script=str(script),
                rules_targeted=[RULE],
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                iteration=1,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(record["exit_code"], 0)
            self.assertTrue(Path(record["stdout_path"]).exists())
            self.assertTrue(Path(record["stderr_path"]).exists())
            self.assertTrue(record["stdout_sha256"])
            self.assertTrue(record["stderr_sha256"])
            self.assertTrue(record["output_pdf_sha256"])

    def test_failed_subprocess_record_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            input_pdf = write_pdf(job / "in.pdf")
            output_pdf = job / "missing.pdf"
            script = job / "fail.py"
            script.write_text("import sys; print('bad', file=sys.stderr); sys.exit(7)")
            log = new_execution_log(job_dir=job, source_pdf=input_pdf, run_id="run-1")
            proc, record = record_subprocess_execution(
                log,
                argv=[sys.executable, script],
                step_name="fail_pdf",
                script=str(script),
                rules_targeted=[RULE],
                input_pdf=input_pdf,
                output_pdf=output_pdf,
            )
            self.assertEqual(proc.returncode, 7)
            self.assertEqual(record["result"], "FAIL")
            self.assertEqual(record["exit_code"], 7)
            self.assertFalse(record["output_exists"])
            self.assertIn("bad", Path(record["stderr_path"]).read_text())

    def test_compatibility_view_and_inferred_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            source = write_pdf(job / "source.pdf")
            current = write_pdf(job / "current.pdf")
            log = build_execution_log_from_repair_steps(
                job_dir=job,
                source_pdf=source,
                current_pdf=current,
                repair_steps=[{"repair_script": "tools/repair/fix_x.py", "strategy": "fix_x", "rules_addressed": [RULE]}],
                strategy_attempts={RULE: [{"result": "PASS", "execution_attempt_id": "repair-iter1-fix-x-001"}]},
            )
            self.assertEqual(log["schema_version"], "execution-log.v2")
            self.assertTrue(log["records"])
            self.assertTrue(log["repair_steps"])
            self.assertEqual(log["repair_steps"][0]["rule_ids"], [RULE])
            self.assertTrue(log["records"][0]["inferred"])

    def test_learned_strategy_capture_includes_execution_references(self):
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            output = write_pdf(job / "self_extension" / "rule" / "attempt_01" / "output.pdf")
            script = job / "generated.py"
            script.write_text("print('{}')")
            candidate = {
                "result": "PASS",
                "stage": "validated_candidate",
                "candidate_relative_path": "tools/repair/generated/generated.py",
                "candidate_script": str(script),
                "candidate_output_pdf": str(output),
                "attempt_dir": str(output.parent),
                "execution_attempt_id": "selfext-rule-x-attempt-001",
                "execution_log_path": str(job / "audit" / "execution_log.json"),
                "stdout_path": str(job / "audit" / "execution" / "stdout" / "x.txt"),
                "stderr_path": str(job / "audit" / "execution" / "stderr" / "x.txt"),
                "write_result": {"result": "PASS", "candidate_script": str(script), "script_sha256": "abc123"},
                "execution_contract": {"result": "PASS", "stdout_json": {"result": "MODIFIED"}, "checks": {}},
                "validation": {"result": "PASS", "gate_results": {"preservation": "PASS"}, "artifacts": {}},
                "success_predicate": {
                    "result": "PASS",
                    "target_rule_id": RULE,
                    "target_rule_count_before": 2,
                    "target_rule_count_after": 0,
                    "target_rule_strictly_decreased": True,
                    "new_rule_ids_relative_to_gap_entry": [],
                    "worsened_existing_rules_relative_to_gap_entry": [],
                    "failed_gates": [],
                    "execution_contract_result": "PASS",
                },
            }
            capture_candidate_result(job_dir=job, rule_id=RULE, candidate_result=candidate, attempt_number=1)
            record = json.loads(learned_strategies_path(job).read_text())["records"][0]
            self.assertEqual(record["execution_attempt_id"], "selfext-rule-x-attempt-001")
            self.assertTrue(record["stdout_path"].endswith("x.txt"))
            self.assertTrue(record["stderr_path"].endswith("x.txt"))

    def test_no_canonical_mutation(self):
        root = Path.cwd()
        rule_map = root / "app" / "tools" / "audit" / "rule_repair_map.json"
        repair_dir = root / "app" / "tools" / "repair"
        before_rule_map = rule_map.read_bytes() if rule_map.exists() else b""
        before_repair = {
            p.relative_to(repair_dir): p.read_bytes()
            for p in repair_dir.glob("*.py")
        } if repair_dir.exists() else {}
        with tempfile.TemporaryDirectory() as td:
            job = Path(td)
            source = write_pdf(job / "source.pdf")
            log = new_execution_log(job_dir=job, source_pdf=source)
            write_execution_log(log, job / "audit" / "execution_log.json")
        if rule_map.exists():
            self.assertEqual(rule_map.read_bytes(), before_rule_map)
        if repair_dir.exists():
            after_repair = {p.relative_to(repair_dir): p.read_bytes() for p in repair_dir.glob("*.py")}
            self.assertEqual(after_repair, before_repair)


if __name__ == "__main__":
    unittest.main()
