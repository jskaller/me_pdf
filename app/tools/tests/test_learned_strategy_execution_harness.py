from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_execution import execute_discovered_learned_strategy


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LearnedStrategyExecutionHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.job = self.root / "job"
        self.staging = self.repo / "app" / "tools" / "repair_staging" / "learned"
        self.repair = self.repo / "app" / "tools" / "repair"
        self.audit = self.job / "audit"
        self.staging.mkdir(parents=True)
        self.repair.mkdir(parents=True)
        self.audit.mkdir(parents=True)
        self.input_pdf = self.root / "input.pdf"
        self.input_pdf.write_bytes(b"%PDF-FAKE-UNIT\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_script(self, name: str, body: str) -> Path:
        path = self.staging / name
        path.write_text(body)
        return path

    def discovered(self, script: Path, **overrides: object) -> dict:
        data = {
            "rule_id": "PDF/UA-1/TEST",
            "candidate_id": "candidate-1",
            "strategy_id": "strategy-1",
            "source": "learned_strategy_staged",
            "production_active": True,
            "activation_status": "active",
            "runtime_eligible": True,
            "staged_script_path": str(script.relative_to(self.repo)),
            "staged_script_sha256": sha256(script),
            "execution_performed": False,
        }
        data.update(overrides)
        return data

    def safe_copy_script(self) -> Path:
        return self.write_script(
            "copy_strategy.py",
            "from pathlib import Path\n"
            "import sys\n"
            "src = Path(sys.argv[1])\n"
            "dst = Path(sys.argv[2])\n"
            "dst.write_bytes(src.read_bytes())\n"
            "print('copied')\n",
        )

    def read_result(self, result: dict) -> dict:
        return json.loads((Path(result["attempt_dir"]) / "execution_result.json").read_text())

    def read_log_records(self) -> list[dict]:
        return json.loads((self.job / "audit" / "execution_log.json").read_text()).get("records", [])

    def test_dry_run_checks_active_discovered_strategy_without_execution(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="dry", dry_run=True
        )
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["execution_performed"])
        self.assertFalse(Path(result["output_pdf"]).exists())
        self.assertTrue((Path(result["attempt_dir"]) / "execution_result.json").exists())
        self.assertFalse(result["final_pdf_adoption_performed"])
        self.assertFalse(result["orchestrator_integration_performed"])
        self.assertFalse(result["rule_map_mutation_performed"])
        self.assertFalse(result["app_tools_repair_mutation_performed"])

    def test_execute_active_safe_strategy_records_output_and_execution_log(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="run", dry_run=False
        )
        self.assertEqual(result["result"], "PASS")
        self.assertTrue(result["execution_performed"])
        self.assertTrue(Path(result["output_pdf"]).exists())
        self.assertTrue(Path(result["stdout_path"]).exists())
        self.assertTrue(Path(result["stderr_path"]).exists())
        self.assertEqual(Path(result["output_pdf"]).read_bytes(), self.input_pdf.read_bytes())
        records = self.read_log_records()
        self.assertEqual(records[-1]["record_type"], "learned_strategy_execution")
        self.assertEqual(records[-1]["result"], "PASS")
        self.assertFalse(records[-1]["final_pdf_adoption_performed"])
        self.assertFalse(records[-1]["orchestrator_integration_performed"])

    def test_inactive_or_non_runtime_eligible_discovery_blocked(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script, runtime_eligible=False, production_active=False, activation_status="inactive"),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id="inactive",
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertFalse(result["execution_performed"])
        self.assertIn("not_runtime_eligible", result["execution_blockers"])
        self.assertIn("not_production_active", result["execution_blockers"])
        self.assertFalse(Path(result["output_pdf"]).exists())

    def test_missing_staged_script_blocked(self) -> None:
        script = self.safe_copy_script()
        missing = self.staging / "missing.py"
        result = execute_discovered_learned_strategy(
            self.discovered(script, staged_script_path=str(missing.relative_to(self.repo))),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id="missing-script",
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("staged_script_missing", result["execution_blockers"])
        self.assertFalse(result["execution_performed"])

    def test_hash_mismatch_blocked(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script, staged_script_sha256="0" * 64),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id="hash-mismatch",
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("staged_script_hash_mismatch", result["execution_blockers"])
        self.assertFalse(result["execution_performed"])

    def test_unsafe_static_script_blocked(self) -> None:
        script = self.write_script("unsafe.py", "import subprocess\nsubprocess.run(['echo', 'bad'])\n")
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="unsafe"
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("static_checks_failed", result["execution_blockers"])
        self.assertFalse(result["execution_performed"])

    def test_quarantine_or_outside_path_blocked(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script, staged_script_path="workspace/jobs/JOB/audit/self_extension/quarantine/bad.py"),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id="quarantine",
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("staged_script_path_references_job_quarantine", result["execution_blockers"])
        self.assertFalse(result["execution_performed"])

    def test_missing_input_pdf_blocked(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.root / "missing.pdf", self.job, repo_root=self.repo, attempt_id="missing-input"
        )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("input_pdf_missing", result["execution_blockers"])
        self.assertFalse(result["execution_performed"])

    def test_script_nonzero_exit_recorded_as_fail(self) -> None:
        script = self.write_script(
            "fail.py",
            "import sys\n"
            "print('before fail')\n"
            "print('bad', file=sys.stderr)\n"
            "sys.exit(7)\n",
        )
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="nonzero"
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["exit_code"], 7)
        self.assertTrue(result["execution_performed"])
        self.assertIn("before fail", Path(result["stdout_path"]).read_text())
        self.assertIn("bad", Path(result["stderr_path"]).read_text())
        self.assertEqual(self.read_log_records()[-1]["result"], "FAIL")
        self.assertFalse(result["final_pdf_adoption_performed"])

    def test_script_timeout_recorded_as_fail(self) -> None:
        script = self.write_script("timeout.py", "import time\ntime.sleep(5)\n")
        result = execute_discovered_learned_strategy(
            self.discovered(script),
            self.input_pdf,
            self.job,
            repo_root=self.repo,
            attempt_id="timeout",
            timeout_seconds=1,
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["exit_code"], 124)
        self.assertIn("script_timeout", result["execution_blockers"])
        self.assertIn("timeout_after_seconds=1", Path(result["stderr_path"]).read_text())

    def test_output_path_is_controlled_under_attempt_dir(self) -> None:
        script = self.write_script(
            "path_control.py",
            "from pathlib import Path\n"
            "import sys\n"
            "Path('final.pdf').write_bytes(b'not adopted')\n"
            "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())\n",
        )
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="path-control"
        )
        attempt_dir = Path(result["attempt_dir"])
        self.assertEqual(result["result"], "PASS")
        self.assertTrue(Path(result["output_pdf"]).resolve().is_relative_to(attempt_dir.resolve()))
        self.assertTrue((attempt_dir / "final.pdf").exists())
        self.assertFalse((self.job / "final.pdf").exists())

    def test_no_rule_map_mutation(self) -> None:
        rule_map = self.repo / "app" / "tools" / "audit" / "rule_repair_map.json"
        rule_map.parent.mkdir(parents=True)
        rule_map.write_text('{"rules": {}}')
        before = rule_map.read_bytes()
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="no-rule-map"
        )
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(rule_map.read_bytes(), before)
        self.assertFalse(result["rule_map_mutation_performed"])

    def test_no_app_tools_repair_mutation(self) -> None:
        existing = self.repair / "README.md"
        existing.write_text("stable")
        before = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="no-repair-mutation"
        )
        after = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(after, before)
        self.assertFalse(result["app_tools_repair_mutation_performed"])

    def test_no_final_pdf_adoption(self) -> None:
        final_pdf = self.job / "final.pdf"
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="no-final"
        )
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(final_pdf.exists())
        self.assertFalse(result["final_pdf_adoption_performed"])
        self.assertFalse(result["orchestrator_integration_performed"])

    def test_result_artifact_contains_required_no_mutation_flags(self) -> None:
        script = self.safe_copy_script()
        result = execute_discovered_learned_strategy(
            self.discovered(script), self.input_pdf, self.job, repo_root=self.repo, attempt_id="flags"
        )
        artifact = self.read_result(result)
        self.assertFalse(artifact["final_pdf_adoption_performed"])
        self.assertFalse(artifact["orchestrator_integration_performed"])
        self.assertFalse(artifact["rule_map_mutation_performed"])
        self.assertFalse(artifact["app_tools_repair_mutation_performed"])
        self.assertFalse(artifact["validation_performed"])
        self.assertEqual(artifact["validation_artifacts"], {})


if __name__ == "__main__":
    unittest.main()
