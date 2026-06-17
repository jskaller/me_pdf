from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_orchestrator_execution_dry_run import run_orchestrator_learned_execution_dry_run
from tools.audit.learned_strategy_output_comparison import (
    compare_learned_execution_output,
    summarize_comparisons,
    write_learned_strategy_output_comparisons,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qpdf_pass(pdf: Path, attempt_dir: Path, timeout_seconds: int = 30) -> dict:
    stdout = attempt_dir / "qpdf_check_stdout.txt"
    stderr = attempt_dir / "qpdf_check_stderr.txt"
    stdout.write_text("ok\n")
    stderr.write_text("")
    return {"performed": True, "result": "PASS", "stdout_path": str(stdout), "stderr_path": str(stderr), "exit_code": 0}


def qpdf_fail(pdf: Path, attempt_dir: Path, timeout_seconds: int = 30) -> dict:
    stdout = attempt_dir / "qpdf_check_stdout.txt"
    stderr = attempt_dir / "qpdf_check_stderr.txt"
    stdout.write_text("")
    stderr.write_text("broken\n")
    return {"performed": True, "result": "FAIL", "stdout_path": str(stdout), "stderr_path": str(stderr), "exit_code": 2}


def qpdf_skip(pdf: Path, attempt_dir: Path, timeout_seconds: int = 30) -> dict:
    stdout = attempt_dir / "qpdf_check_stdout.txt"
    stderr = attempt_dir / "qpdf_check_stderr.txt"
    stdout.write_text("")
    stderr.write_text("qpdf unavailable\n")
    return {"performed": False, "result": "SKIPPED", "stdout_path": str(stdout), "stderr_path": str(stderr), "exit_code": None, "reason": "qpdf_unavailable"}


class LearnedStrategyOutputComparisonPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "job"
        self.audit = self.job / "audit"
        self.attempt = self.audit / "learned_strategy_execution" / "attempt-001"
        self.attempt.mkdir(parents=True)
        self.input_pdf = self.attempt / "input.pdf"
        self.output_pdf = self.attempt / "output.pdf"
        self.normal_pdf = self.job / "repair" / "normal.pdf"
        self.normal_pdf.parent.mkdir(parents=True)
        self.input_pdf.write_bytes(b"%PDF-1.7\noriginal\n%%EOF\n")
        self.normal_pdf.write_bytes(self.input_pdf.read_bytes())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_execution_result(self, *, result: str = "PASS", output_pdf: Path | None = None) -> Path:
        path = self.attempt / "execution_result.json"
        out = output_pdf or self.output_pdf
        payload = {
            "schema_version": "learned-strategy-execution-harness.v1",
            "attempt_id": "attempt-001",
            "rule_id": "PDF/UA-1/TEST",
            "candidate_id": "candidate-1",
            "strategy_id": "strategy-1",
            "input_pdf": str(self.input_pdf),
            "input_pdf_sha256": sha256(self.input_pdf),
            "output_pdf": str(out),
            "output_pdf_sha256": sha256(out) if out.exists() else None,
            "result": result,
            "execution_performed": True,
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    def test_missing_output_classified_as_missing_output(self) -> None:
        comparison = compare_learned_execution_output(self.write_execution_result(), self.job, self.normal_pdf, qpdf_checker=qpdf_pass)
        self.assertEqual(comparison["classification"], "missing_output")
        self.assertFalse(comparison["output_exists"])

    def test_failed_execution_classified_as_execution_failed(self) -> None:
        self.output_pdf.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
        comparison = compare_learned_execution_output(self.write_execution_result(result="FAIL"), self.job, self.normal_pdf, qpdf_checker=qpdf_pass)
        self.assertEqual(comparison["classification"], "execution_failed")

    def test_copy_no_change_output_classified_as_no_effect(self) -> None:
        self.output_pdf.write_bytes(self.input_pdf.read_bytes())
        comparison = compare_learned_execution_output(self.write_execution_result(), self.job, self.normal_pdf, qpdf_checker=qpdf_pass)
        self.assertEqual(comparison["classification"], "no_effect")
        self.assertTrue(comparison["input_output_hash_equal"])

    def test_changed_valid_pdf_like_output_classified_as_changed_valid_pdf(self) -> None:
        self.output_pdf.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
        comparison = compare_learned_execution_output(self.write_execution_result(), self.job, self.normal_pdf, qpdf_checker=qpdf_pass)
        self.assertEqual(comparison["classification"], "changed_valid_pdf")
        self.assertEqual(comparison["basic_pdf_header_check"]["result"], "PASS")
        self.assertEqual(comparison["qpdf_check"]["result"], "PASS")

    def test_changed_invalid_output_classified_as_changed_invalid_pdf(self) -> None:
        self.output_pdf.write_bytes(b"not a pdf")
        comparison = compare_learned_execution_output(self.write_execution_result(), self.job, self.normal_pdf, qpdf_checker=qpdf_fail)
        self.assertEqual(comparison["classification"], "changed_invalid_pdf")
        self.assertEqual(comparison["basic_pdf_header_check"]["result"], "FAIL")

    def test_qpdf_unavailable_changed_output_needs_deeper_validation(self) -> None:
        self.output_pdf.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
        comparison = compare_learned_execution_output(self.write_execution_result(), self.job, self.normal_pdf, qpdf_checker=qpdf_skip)
        self.assertEqual(comparison["classification"], "needs_deeper_validation")
        self.assertEqual(comparison["qpdf_check"]["result"], "SKIPPED")

    def test_comparison_artifact_includes_no_adoption_flags_and_summary(self) -> None:
        self.output_pdf.write_bytes(self.input_pdf.read_bytes())
        result_path = self.write_execution_result()
        payload = write_learned_strategy_output_comparisons(
            execution_summaries=[{"execution_result_path": str(result_path), "attempt_id": "attempt-001"}],
            job_dir=self.job,
            audit_dir=self.audit,
            normal_final_pdf=self.normal_pdf,
            qpdf_checker=qpdf_pass,
        )
        self.assertTrue((self.audit / "learned_strategy_output_comparisons.json").exists())
        self.assertEqual(payload["comparison_count"], 1)
        self.assertEqual(payload["summary"]["no_effect"], 1)
        self.assertTrue(payload["policy"]["diagnostic_sidecar_only"])
        self.assertFalse(payload["policy"]["final_pdf_adoption_performed"])
        self.assertFalse(payload["policy"]["verdict_softening_performed"])
        self.assertFalse(payload["policy"]["rule_map_mutation_performed"])
        self.assertFalse(payload["policy"]["app_tools_repair_mutation_performed"])

    def test_summary_counts_classifications(self) -> None:
        summary = summarize_comparisons([
            {"classification": "no_effect"},
            {"classification": "changed_valid_pdf"},
            {"classification": "changed_valid_pdf"},
            {"classification": "missing_output"},
        ])
        self.assertEqual(summary["no_effect"], 1)
        self.assertEqual(summary["changed_valid_pdf"], 2)
        self.assertEqual(summary["missing_output"], 1)


class LearnedStrategyOutputComparisonIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "job"
        self.audit = self.job / "audit"
        self.staging = self.repo / "app" / "tools" / "repair_staging" / "learned"
        self.repair = self.repo / "app" / "tools" / "repair"
        self.rule_map = self.repo / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.staging.mkdir(parents=True)
        self.repair.mkdir(parents=True)
        self.audit.mkdir(parents=True)
        self.rule_map.parent.mkdir(parents=True)
        self.input_pdf = self.root / "current.pdf"
        self.input_pdf.write_bytes(b"%PDF-1.7\ncopy smoke\n%%EOF\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_script(self, name: str, body: str | None = None) -> Path:
        if body is None:
            body = (
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())\n"
                "print('learned copied')\n"
            )
        path = self.staging / name
        path.write_text(body)
        return path

    def active_entry(self, script: Path, candidate_id: str = "smoke-active-candidate") -> dict:
        return {
            "candidate_id": candidate_id,
            "strategy_id": f"strategy-{candidate_id}",
            "source": "learned_strategy_staged",
            "production_active": True,
            "activation_status": "active",
            "staged_script_path": str(script.relative_to(self.repo)),
            "staged_script_sha256": sha256(script),
        }

    def write_rule_map(self, entries: list[dict]) -> None:
        self.rule_map.write_text(json.dumps({"rules": {"PDF/UA-1/TEST": {"reviewed_learned_strategies": entries}}}, indent=2))

    def run_diag(self) -> dict:
        return run_orchestrator_learned_execution_dry_run(
            rule_map_path=self.rule_map,
            audit_dir=self.audit,
            job_dir=self.job,
            repo_root=self.repo,
            input_pdf=self.input_pdf,
            residual_failures=[{"rule_id": "PDF/UA-1/TEST"}],
            limit=1,
            timeout_seconds=3,
        )

    def test_orchestrator_dry_run_writes_and_references_comparison_artifact(self) -> None:
        script = self.write_script("copy_strategy.py")
        self.write_rule_map([self.active_entry(script)])
        diagnostics = self.run_diag()
        artifact = self.audit / "learned_strategy_output_comparisons.json"
        self.assertTrue(artifact.exists())
        self.assertTrue(diagnostics["output_comparison_performed"])
        self.assertEqual(diagnostics["output_comparison_artifact"], str(artifact))
        payload = json.loads(artifact.read_text())
        self.assertEqual(payload["comparison_count"], 1)
        self.assertEqual(payload["comparisons"][0]["classification"], "no_effect")
        self.assertEqual(payload["summary"]["no_effect"], 1)
        self.assertFalse(payload["policy"]["final_pdf_adoption_performed"])

    def test_comparison_failure_does_not_alter_final_pdf_or_mutate_protected_paths(self) -> None:
        marker = self.repair / "README.md"
        marker.write_text("stable")
        script = self.write_script("fail.py", "import sys\nsys.exit(7)\n")
        self.write_rule_map([self.active_entry(script)])
        before_rule_map = self.rule_map.read_bytes()
        before_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        diagnostics = self.run_diag()
        payload = json.loads((self.audit / "learned_strategy_output_comparisons.json").read_text())
        self.assertEqual(diagnostics["failed_count"], 1)
        self.assertEqual(payload["comparisons"][0]["classification"], "execution_failed")
        self.assertFalse((self.job / "final.pdf").exists())
        self.assertEqual(self.rule_map.read_bytes(), before_rule_map)
        after_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        self.assertEqual(after_repair, before_repair)

    def test_static_contract_mentions_output_comparison_without_staged_import(self) -> None:
        path = Path("app/tools/orchestrate/remediate.py")
        if not path.exists():
            self.skipTest("remediate.py not present in isolated test run")
        text = path.read_text()
        self.assertIn("--learned-execution-dry-run", text)
        self.assertNotIn("repair_staging.learned", text)
        self.assertNotIn("import app.tools.repair_staging", text)


if __name__ == "__main__":
    unittest.main()
