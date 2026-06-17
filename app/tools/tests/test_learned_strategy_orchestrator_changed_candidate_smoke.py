from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_candidate_quality import evaluate_learned_strategy_candidate_quality
from tools.audit.learned_strategy_deeper_validation import run_learned_strategy_deeper_validation
from tools.audit.learned_strategy_discovery import static_check_script
from tools.audit.learned_strategy_execution import execute_discovered_learned_strategy
from tools.audit.learned_strategy_output_comparison import compare_learned_execution_output
from tools.dev.setup_learned_execution_smoke_candidate import (
    create_smoke_candidate,
    cleanup_smoke_candidate,
    main as smoke_setup_main,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qpdf_pass(pdf: Path, attempt_dir: Path, timeout_seconds: int = 30) -> dict:
    stdout = attempt_dir / "qpdf_check_stdout.txt"
    stderr = attempt_dir / "qpdf_check_stderr.txt"
    stdout.write_text("ok\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    return {"performed": True, "result": "PASS", "stdout_path": str(stdout), "stderr_path": str(stderr), "exit_code": 0}


class LearnedStrategyOrchestratorChangedCandidateSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.rule_map = self.repo / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.staging = self.repo / "app" / "tools" / "repair_staging" / "learned"
        self.repair = self.repo / "app" / "tools" / "repair"
        self.rule_map.parent.mkdir(parents=True)
        self.staging.mkdir(parents=True)
        self.repair.mkdir(parents=True)
        self.audit.mkdir(parents=True)
        self.rule_map.write_text(json.dumps({"rules": {"PDF/UA-1/7.21.7": {}}}, indent=2), encoding="utf-8")
        (self.repair / "README.md").write_text("stable repair dir\n", encoding="utf-8")
        self.input_pdf = self.job / "repair" / "pass8_iter1_fix_cidset.pdf"
        self.input_pdf.parent.mkdir(parents=True)
        self.input_pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n")
        self.before_rule_map = self.rule_map.read_bytes()
        self.before_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def setup_candidate(self, mode: str, candidate_id: str = "smoke-changed-valid-candidate") -> dict:
        return create_smoke_candidate(
            job_dir=self.job,
            rule_id="PDF/UA-1/7.21.7",
            candidate_id=candidate_id,
            repo_root_arg=str(self.repo),
            rule_map_arg=str(self.rule_map),
            script_mode=mode,
        )

    def discovered_entry(self, candidate_id: str) -> dict:
        data = json.loads(self.rule_map.read_text(encoding="utf-8"))
        entries = data["rules"]["PDF/UA-1/7.21.7"]["reviewed_learned_strategies"]
        for entry in entries:
            if entry["candidate_id"] == candidate_id:
                return {"rule_id": "PDF/UA-1/7.21.7", **entry}
        raise AssertionError(f"candidate not found: {candidate_id}")

    def run_execution_and_comparison(self, candidate_id: str) -> tuple[dict, dict]:
        result = execute_discovered_learned_strategy(
            self.discovered_entry(candidate_id),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id=candidate_id,
            dry_run=False,
        )
        comparison = compare_learned_execution_output(
            Path(result["attempt_dir"]) / "execution_result.json",
            self.job,
            self.input_pdf,
            qpdf_checker=qpdf_pass,
        )
        return result, comparison

    def write_quality_and_comparison(self, comparison: dict) -> tuple[Path, Path]:
        comparison_path = self.audit / "learned_strategy_output_comparisons.json"
        comparison_path.write_text(json.dumps({"comparisons": [comparison]}, indent=2), encoding="utf-8")
        quality = evaluate_learned_strategy_candidate_quality(comparison_path, self.job)
        quality_path = self.audit / "learned_strategy_candidate_quality_report.json"
        quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
        return quality_path, comparison_path

    def run_deeper(self, quality_path: Path, comparison_path: Path, checks: list[dict]) -> dict:
        def provider(comparison, candidate, attempt_dir, timeout_seconds):
            return checks
        return run_learned_strategy_deeper_validation(
            quality_report_path=quality_path,
            comparison_artifact_path=comparison_path,
            job_dir=self.job,
            check_provider=provider,
        )

    def test_setup_helper_cli_supports_changed_valid_mode(self) -> None:
        rc = smoke_setup_main([
            "--job-dir", str(self.job),
            "--rule-id", "PDF/UA-1/7.21.7",
            "--candidate-id", "smoke-changed-valid-candidate",
            "--repo-root", str(self.repo),
            "--rule-map", str(self.rule_map),
            "--script-mode", "changed-valid",
            "--setup",
        ])
        self.assertEqual(rc, 0)
        artifact = json.loads((self.audit / "learned_execution_smoke_setup.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["script_mode"], "changed-valid")
        self.assertEqual(artifact["expected_comparison_classification"], "changed_valid_pdf")
        self.assertFalse(artifact["final_pdf_adoption_performed"])
        self.assertFalse(artifact["verdict_softening_performed"])

    def test_changed_valid_staged_script_is_static_check_safe(self) -> None:
        artifact = self.setup_candidate("changed-valid")
        staged_script = Path(artifact["staged_script_path"])
        static = static_check_script(staged_script)
        self.assertTrue(static["passed"], static)
        self.assertIn("learned-smoke-changed-valid", staged_script.read_text(encoding="utf-8"))

    def test_changed_valid_cleanup_removes_script_and_restores_rule_map(self) -> None:
        artifact = self.setup_candidate("changed-valid")
        self.assertTrue(Path(artifact["staged_script_path"]).exists())
        cleanup = cleanup_smoke_candidate(job_dir=self.job, repo_root_arg=str(self.repo), rule_map_arg=str(self.rule_map))
        self.assertTrue(cleanup["rule_map_restored_from_backup"])
        self.assertEqual(self.rule_map.read_bytes(), self.before_rule_map)
        self.assertFalse(Path(artifact["staged_script_path"]).exists())

    def test_changed_valid_routes_through_comparison_quality_and_deeper_validation_without_adoption(self) -> None:
        self.setup_candidate("changed-valid")
        execution, comparison = self.run_execution_and_comparison("smoke-changed-valid-candidate")
        self.assertEqual(execution["result"], "PASS")
        self.assertTrue(execution["execution_performed"])
        self.assertNotEqual(sha256(Path(execution["input_pdf"])), sha256(Path(execution["output_pdf"])))
        self.assertEqual(comparison["classification"], "changed_valid_pdf")
        self.assertFalse(comparison["input_output_hash_equal"])
        self.assertEqual(comparison["qpdf_check"]["result"], "PASS")
        self.assertFalse(comparison["final_pdf_adoption_performed"])
        self.assertFalse(comparison["verdict_softening_performed"])
        self.assertFalse(comparison["production_repair_replacement_performed"])

        quality_path, comparison_path = self.write_quality_and_comparison(comparison)
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        decision = quality["decisions"][0]
        self.assertEqual(decision["quality_decision"], "candidate_valid_changed")
        self.assertFalse(decision["quality_passed"])
        self.assertTrue(all(item["quality_passed"] is False for item in quality["decisions"]))
        self.assertFalse(quality["policy"]["final_pdf_adoption_performed"])
        self.assertFalse(quality["policy"]["verdict_softening_performed"])

        deeper = self.run_deeper(quality_path, comparison_path, [
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": True, "result": "PASS"},
        ])
        result = deeper["results"][0]
        self.assertEqual(result["deeper_validation_decision"], "deeper_validation_passed")
        self.assertTrue(result["candidate_may_proceed_to_trial"])
        self.assertFalse(result["candidate_is_adoptable"])
        self.assertFalse(result["final_pdf_adoption_performed"])
        self.assertFalse(deeper["policy"]["verdict_softening_performed"])
        self.assertFalse((self.job / "final.pdf").exists())

    def test_changed_valid_incomplete_deeper_validation_needs_manual_review(self) -> None:
        self.setup_candidate("changed-valid")
        _execution, comparison = self.run_execution_and_comparison("smoke-changed-valid-candidate")
        quality_path, comparison_path = self.write_quality_and_comparison(comparison)
        deeper = self.run_deeper(quality_path, comparison_path, [
            {"check_name": "basic_pdf_header", "performed": True, "result": "PASS"},
            {"check_name": "qpdf", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
        ])
        result = deeper["results"][0]
        self.assertEqual(result["deeper_validation_decision"], "needs_manual_review")
        self.assertFalse(result["candidate_may_proceed_to_trial"])
        self.assertFalse(result["candidate_is_adoptable"])

    def test_copy_noop_smoke_still_rejects_no_effect_and_skips_deeper_validation(self) -> None:
        self.setup_candidate("copy", candidate_id="smoke-copy-candidate")
        _execution, comparison = self.run_execution_and_comparison("smoke-copy-candidate")
        self.assertEqual(comparison["classification"], "no_effect")
        self.assertTrue(comparison["input_output_hash_equal"])
        quality_path, comparison_path = self.write_quality_and_comparison(comparison)
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        self.assertEqual(quality["decisions"][0]["quality_decision"], "rejected_no_effect")
        self.assertFalse(quality["decisions"][0]["quality_passed"])
        deeper = self.run_deeper(quality_path, comparison_path, [
            {"check_name": "should_not_run", "performed": True, "result": "FAIL"},
        ])
        self.assertEqual(deeper["results"][0]["deeper_validation_decision"], "skipped_not_eligible")
        self.assertEqual(deeper["results"][0]["checks"], [])

    def test_no_persistent_rule_map_or_repair_mutation_after_cleanup(self) -> None:
        self.setup_candidate("changed-valid")
        cleanup_smoke_candidate(job_dir=self.job, repo_root_arg=str(self.repo), rule_map_arg=str(self.rule_map))
        self.assertEqual(self.rule_map.read_bytes(), self.before_rule_map)
        after_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        self.assertEqual(after_repair, self.before_repair)
        self.assertEqual(list(self.staging.glob("smoke_*.py")), [])


if __name__ == "__main__":
    unittest.main()
