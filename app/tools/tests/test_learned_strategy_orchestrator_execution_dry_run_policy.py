from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_orchestrator_execution_dry_run import (
    INPUT_UNAVAILABLE_REASON,
    LIMIT_REASON,
    NO_CANDIDATES_REASON,
    run_orchestrator_learned_execution_dry_run,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LearnedStrategyOrchestratorExecutionDryRunPolicyTests(unittest.TestCase):
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
        self.input_pdf.write_bytes(b"%PDF-FAKE-UNIT\n")

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

    def write_rule_map(self, entries: list[dict]) -> None:
        self.rule_map.write_text(json.dumps({
            "rules": {
                "PDF/UA-1/TEST": {
                    "reviewed_learned_strategies": entries,
                }
            }
        }, indent=2))

    def active_entry(self, script: Path, candidate_id: str = "candidate-1", **overrides: object) -> dict:
        data = {
            "candidate_id": candidate_id,
            "strategy_id": f"strategy-{candidate_id}",
            "source": "learned_strategy_staged",
            "production_active": True,
            "activation_status": "active",
            "staged_script_path": str(script.relative_to(self.repo)),
            "staged_script_sha256": sha256(script),
        }
        data.update(overrides)
        return data

    def read_log_records(self) -> list[dict]:
        path = self.audit / "execution_log.json"
        if not path.exists():
            return []
        return json.loads(path.read_text()).get("records", [])

    def run_diag(self, *, limit: int = 1, input_pdf: Path | None = None) -> dict:
        return run_orchestrator_learned_execution_dry_run(
            rule_map_path=self.rule_map,
            audit_dir=self.audit,
            job_dir=self.job,
            repo_root=self.repo,
            input_pdf=input_pdf or self.input_pdf,
            residual_failures=[{"rule_id": "PDF/UA-1/TEST"}],
            limit=limit,
            timeout_seconds=3,
        )

    def test_no_candidates_produces_diagnostics_but_no_execution_log_record(self) -> None:
        self.write_rule_map([])
        diagnostics = self.run_diag()
        self.assertEqual(diagnostics["executed_count"], 0)
        self.assertEqual(diagnostics["candidate_count"], 0)
        self.assertEqual(diagnostics["skipped_candidates"][0]["reason"], NO_CANDIDATES_REASON)
        self.assertTrue((self.audit / "learned_strategy_discovery.json").exists())
        self.assertTrue((self.audit / "learned_strategy_execution_diagnostics.json").exists())
        self.assertEqual(self.read_log_records(), [])

    def test_active_candidate_executes_through_harness_only_and_records_log(self) -> None:
        script = self.write_script("copy_strategy.py")
        self.write_rule_map([self.active_entry(script)])
        diagnostics = self.run_diag()
        self.assertEqual(diagnostics["candidate_count"], 1)
        self.assertEqual(diagnostics["executed_count"], 1)
        self.assertEqual(diagnostics["executions"][0]["execution_log_record_type"], "learned_strategy_execution")
        self.assertFalse(diagnostics["executions"][0]["final_pdf_adoption_performed"])
        self.assertFalse(diagnostics["executions"][0]["orchestrator_final_adoption_performed"])
        records = self.read_log_records()
        self.assertEqual(records[-1]["record_type"], "learned_strategy_execution")
        self.assertFalse(records[-1]["final_pdf_adoption_performed"])
        self.assertFalse(records[-1]["orchestrator_integration_performed"])

    def test_execution_output_not_adopted_and_original_input_unchanged(self) -> None:
        script = self.write_script("copy_strategy.py")
        self.write_rule_map([self.active_entry(script)])
        before = self.input_pdf.read_bytes()
        diagnostics = self.run_diag()
        output_pdf = Path(diagnostics["executions"][0]["output_pdf"])
        self.assertTrue(output_pdf.exists())
        self.assertEqual(self.input_pdf.read_bytes(), before)
        self.assertFalse((self.job / "final.pdf").exists())
        self.assertFalse(diagnostics["policy"]["final_pdf_adoption_performed"])
        self.assertFalse(diagnostics["policy"]["verdict_softening_performed"])

    def test_execution_limit_enforced(self) -> None:
        a = self.write_script("a.py")
        b = self.write_script("b.py")
        self.write_rule_map([self.active_entry(a, "a"), self.active_entry(b, "b")])
        diagnostics = self.run_diag(limit=1)
        self.assertEqual(diagnostics["candidate_count"], 2)
        self.assertEqual(diagnostics["executed_count"], 1)
        self.assertEqual(diagnostics["skipped_count"], 1)
        self.assertEqual(diagnostics["skipped_candidates"][0]["reason"], LIMIT_REASON)

    def test_inactive_hash_or_unsafe_candidates_are_not_executed(self) -> None:
        script = self.write_script("safe.py")
        unsafe = self.write_script("unsafe.py", "import subprocess\nsubprocess.run(['echo','x'])\n")
        self.write_rule_map([
            self.active_entry(script, "inactive", production_active=False, activation_status="inactive"),
            self.active_entry(script, "bad-hash", staged_script_sha256="0" * 64),
            self.active_entry(unsafe, "unsafe"),
        ])
        diagnostics = self.run_diag(limit=3)
        self.assertEqual(diagnostics["candidate_count"], 0)
        self.assertEqual(diagnostics["executed_count"], 0)
        self.assertEqual(self.read_log_records(), [])

    def test_missing_input_pdf_fails_closed_in_diagnostics(self) -> None:
        script = self.write_script("copy_strategy.py")
        self.write_rule_map([self.active_entry(script)])
        diagnostics = self.run_diag(input_pdf=self.root / "missing.pdf")
        self.assertIn(INPUT_UNAVAILABLE_REASON, diagnostics["blockers"])
        self.assertEqual(diagnostics["executed_count"], 0)
        self.assertEqual(self.read_log_records(), [])

    def test_learned_execution_failure_is_diagnostic_not_exception(self) -> None:
        script = self.write_script("fail.py", "import sys\nsys.exit(7)\n")
        self.write_rule_map([self.active_entry(script)])
        diagnostics = self.run_diag()
        self.assertEqual(diagnostics["failed_count"], 1)
        self.assertEqual(diagnostics["executions"][0]["result"], "FAIL")
        self.assertEqual(self.read_log_records()[-1]["result"], "FAIL")
        self.assertFalse(diagnostics["policy"]["verdict_softening_performed"])

    def test_no_rule_map_or_app_tools_repair_mutation(self) -> None:
        marker = self.repair / "README.md"
        marker.write_text("stable")
        script = self.write_script("copy_strategy.py")
        self.write_rule_map([self.active_entry(script)])
        before_rule_map = self.rule_map.read_bytes()
        before_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        diagnostics = self.run_diag()
        after_repair = sorted(p.relative_to(self.repair).as_posix() for p in self.repair.rglob("*"))
        self.assertEqual(self.rule_map.read_bytes(), before_rule_map)
        self.assertEqual(after_repair, before_repair)
        self.assertFalse(diagnostics["policy"]["rule_map_mutation_performed"])
        self.assertFalse(diagnostics["policy"]["app_tools_repair_mutation_performed"])

    def test_remediate_static_contract_has_flag_without_staged_import(self) -> None:
        remediate = Path("app/tools/orchestrate/remediate.py")
        if not remediate.exists():
            self.skipTest("remediate.py not present in this isolated test run")
        text = remediate.read_text()
        self.assertIn("--learned-execution-dry-run", text)
        self.assertIn("--learned-execution-limit", text)
        self.assertNotIn("repair_staging.learned", text)
        self.assertNotIn("import app.tools.repair_staging", text)


if __name__ == "__main__":
    unittest.main()
