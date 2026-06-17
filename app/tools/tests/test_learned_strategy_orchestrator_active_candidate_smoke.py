from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_orchestrator_execution_dry_run import (
    run_orchestrator_learned_execution_dry_run,
)
from tools.dev.setup_learned_execution_smoke_candidate import (
    cleanup_smoke_candidate,
    create_smoke_candidate,
)


RULE_ID = "PDF/UA-1/7.21.7"
SECOND_RULE_ID = "PDF/UA-1/7.21.4.1"
CANDIDATE_ID = "smoke-active-candidate"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ActiveCandidateSmokeFixture:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.rule_map = self.repo / "app/tools/audit/rule_repair_map.json"
        self.staging = self.repo / "app/tools/repair_staging/learned"
        self.repair_dir = self.repo / "app/tools/repair"
        self.job = self.repo / "workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable"
        self.audit = self.job / "audit"
        self.input_pdf = self.job / "passes/final.pdf"
        self.rule_map.parent.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.repair_dir.mkdir(parents=True, exist_ok=True)
        self.audit.mkdir(parents=True, exist_ok=True)
        self.input_pdf.parent.mkdir(parents=True, exist_ok=True)
        self.input_pdf.write_bytes(b"%PDF-1.7\n% smoke fixture only\n")
        self.rule_map.write_text(
            json.dumps(
                {
                    "rules": {
                        RULE_ID: {"status": "MANUAL", "reviewed_learned_strategies": []},
                        SECOND_RULE_ID: {"status": "MANUAL", "reviewed_learned_strategies": []},
                    }
                },
                indent=2,
            )
        )
        self.original_rule_map_hash = sha256_path(self.rule_map)
        self.original_repair_files = sorted(p.name for p in self.repair_dir.glob("*") if p.is_file())
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tmp.cleanup()

    def setup(self, *, rule_id: str = RULE_ID, candidate_id: str = CANDIDATE_ID):
        return create_smoke_candidate(
            job_dir=self.job,
            rule_id=rule_id,
            candidate_id=candidate_id,
            repo_root_arg=str(self.repo),
            rule_map_arg=str(self.rule_map),
        )

    def cleanup(self):
        return cleanup_smoke_candidate(
            job_dir=self.job,
            repo_root_arg=str(self.repo),
            rule_map_arg=str(self.rule_map),
        )


class LearnedStrategyOrchestratorActiveCandidateSmokeTests(unittest.TestCase):
    def test_smoke_setup_creates_active_staged_learned_candidate(self):
        with ActiveCandidateSmokeFixture() as fx:
            artifact = fx.setup()
            staged_script = Path(artifact["staged_script_path"])
            self.assertTrue(staged_script.exists())
            self.assertTrue((fx.audit / "learned_execution_smoke_rule_map_backup.json").exists())
            self.assertTrue((fx.audit / "learned_execution_smoke_setup.json").exists())

            rule_map = json.loads(fx.rule_map.read_text())
            learned = rule_map["rules"][RULE_ID]["reviewed_learned_strategies"]
            smoke = [item for item in learned if item.get("candidate_id") == CANDIDATE_ID][0]
            self.assertEqual(smoke["source"], "learned_strategy_staged")
            self.assertTrue(smoke["production_active"])
            self.assertEqual(smoke["activation_status"], "active")
            self.assertFalse(smoke["review_required"])
            self.assertTrue(smoke["runtime_eligible"])
            self.assertEqual(smoke["staged_script_sha256"], sha256_path(staged_script))
            self.assertEqual(smoke["staged_script_path"], f"app/tools/repair_staging/learned/{staged_script.name}")

    def test_cleanup_restores_rule_map_and_removes_staged_smoke_script(self):
        with ActiveCandidateSmokeFixture() as fx:
            artifact = fx.setup()
            staged_script = Path(artifact["staged_script_path"])
            self.assertNotEqual(sha256_path(fx.rule_map), fx.original_rule_map_hash)
            cleanup = fx.cleanup()
            self.assertTrue(cleanup["rule_map_restored_from_backup"])
            self.assertEqual(sha256_path(fx.rule_map), fx.original_rule_map_hash)
            self.assertFalse(staged_script.exists())

    def test_active_candidate_diagnostic_execution_through_orchestrator_helper(self):
        with ActiveCandidateSmokeFixture() as fx:
            fx.setup()
            diagnostics = run_orchestrator_learned_execution_dry_run(
                rule_map_path=fx.rule_map,
                audit_dir=fx.audit,
                job_dir=fx.job,
                repo_root=fx.repo,
                input_pdf=fx.input_pdf,
                residual_failures=[{"rule_id": RULE_ID, "failures": 1}],
                limit=1,
            )
            self.assertEqual(diagnostics["candidate_count"], 1)
            self.assertEqual(diagnostics["executed_count"], 1)
            self.assertEqual(diagnostics["failed_count"], 0)
            self.assertEqual(diagnostics["blocked_count"], 0)
            self.assertFalse(diagnostics["policy"]["final_pdf_adoption_performed"])
            self.assertFalse(diagnostics["policy"]["verdict_softening_performed"])
            self.assertFalse(diagnostics["policy"]["rule_map_mutation_performed"])
            self.assertFalse(diagnostics["policy"]["app_tools_repair_mutation_performed"])

            artifact_path = fx.audit / "learned_strategy_execution_diagnostics.json"
            self.assertTrue(artifact_path.exists())
            execution = diagnostics["executions"][0]
            self.assertEqual(execution["candidate_id"], CANDIDATE_ID)
            self.assertEqual(execution["result"], "PASS")
            self.assertEqual(execution["exit_code"], 0)
            output_pdf = Path(execution["output_pdf"])
            self.assertTrue(output_pdf.exists())
            self.assertTrue(str(output_pdf).startswith(str(fx.audit / "learned_strategy_execution")))
            self.assertNotEqual(output_pdf.resolve(), fx.input_pdf.resolve())

            log = json.loads((fx.audit / "execution_log.json").read_text())
            learned_records = [
                r for r in log.get("records", []) if r.get("record_type") == "learned_strategy_execution"
            ]
            self.assertEqual(len(learned_records), 1)
            record = learned_records[0]
            self.assertEqual(record["rule_id"], RULE_ID)
            self.assertEqual(record["candidate_id"], CANDIDATE_ID)
            self.assertEqual(record["result"], "PASS")
            self.assertFalse(record["final_pdf_adoption_performed"])
            self.assertFalse(record["orchestrator_integration_performed"])

    def test_final_adoption_and_verdict_softening_remain_false(self):
        with ActiveCandidateSmokeFixture() as fx:
            fx.setup()
            diagnostics = run_orchestrator_learned_execution_dry_run(
                rule_map_path=fx.rule_map,
                audit_dir=fx.audit,
                job_dir=fx.job,
                repo_root=fx.repo,
                input_pdf=fx.input_pdf,
                residual_failures=[{"rule_id": RULE_ID}],
                limit=1,
            )
            self.assertFalse(diagnostics["policy"]["final_pdf_adoption_performed"])
            self.assertFalse(diagnostics["policy"]["verdict_softening_performed"])
            execution = diagnostics["executions"][0]
            self.assertFalse(execution["final_pdf_adoption_performed"])
            self.assertFalse(execution["orchestrator_final_adoption_performed"])
            self.assertFalse(execution["orchestrator_integration_performed"])

    def test_execution_limit_is_enforced(self):
        with ActiveCandidateSmokeFixture() as fx:
            fx.setup(rule_id=RULE_ID, candidate_id="smoke-active-candidate-a")
            fx.setup(rule_id=SECOND_RULE_ID, candidate_id="smoke-active-candidate-b")
            diagnostics = run_orchestrator_learned_execution_dry_run(
                rule_map_path=fx.rule_map,
                audit_dir=fx.audit,
                job_dir=fx.job,
                repo_root=fx.repo,
                input_pdf=fx.input_pdf,
                residual_failures=[{"rule_id": RULE_ID}, {"rule_id": SECOND_RULE_ID}],
                limit=1,
            )
            self.assertEqual(diagnostics["candidate_count"], 2)
            self.assertEqual(diagnostics["executed_count"], 1)
            self.assertEqual(diagnostics["skipped_count"], 1)
            self.assertEqual(diagnostics["skipped_candidates"][0]["reason"], "learned_execution_limit_reached")

    def test_cleanup_after_failed_execution_restores_rule_map(self):
        with ActiveCandidateSmokeFixture() as fx:
            artifact = fx.setup()
            Path(artifact["staged_script_path"]).write_text("this is not valid python")
            diagnostics = run_orchestrator_learned_execution_dry_run(
                rule_map_path=fx.rule_map,
                audit_dir=fx.audit,
                job_dir=fx.job,
                repo_root=fx.repo,
                input_pdf=fx.input_pdf,
                residual_failures=[{"rule_id": RULE_ID}],
                limit=1,
            )
            self.assertEqual(diagnostics["candidate_count"], 0)
            cleanup = fx.cleanup()
            self.assertTrue(cleanup["rule_map_restored_from_backup"])
            self.assertEqual(sha256_path(fx.rule_map), fx.original_rule_map_hash)

    def test_no_protected_source_mutation_after_cleanup(self):
        with ActiveCandidateSmokeFixture() as fx:
            fx.setup()
            run_orchestrator_learned_execution_dry_run(
                rule_map_path=fx.rule_map,
                audit_dir=fx.audit,
                job_dir=fx.job,
                repo_root=fx.repo,
                input_pdf=fx.input_pdf,
                residual_failures=[{"rule_id": RULE_ID}],
                limit=1,
            )
            fx.cleanup()
            self.assertEqual(sha256_path(fx.rule_map), fx.original_rule_map_hash)
            self.assertEqual(sorted(p.name for p in fx.repair_dir.glob("*") if p.is_file()), fx.original_repair_files)
            self.assertEqual(list(fx.staging.glob("smoke_*.py")), [])

    def test_helper_cli_setup_and_cleanup(self):
        with ActiveCandidateSmokeFixture() as fx:
            helper = Path(__file__).parents[1] / "dev" / "setup_learned_execution_smoke_candidate.py"
            cmd_base = [
                sys.executable,
                str(helper),
                "--job-dir",
                str(fx.job),
                "--rule-id",
                RULE_ID,
                "--candidate-id",
                CANDIDATE_ID,
                "--repo-root",
                str(fx.repo),
                "--rule-map",
                str(fx.rule_map),
            ]
            setup = subprocess.run(cmd_base + ["--setup"], capture_output=True, text=True, check=False)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            setup_json = json.loads(setup.stdout)
            self.assertTrue(Path(setup_json["staged_script_path"]).exists())
            cleanup = subprocess.run(cmd_base + ["--cleanup"], capture_output=True, text=True, check=False)
            self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
            self.assertEqual(sha256_path(fx.rule_map), fx.original_rule_map_hash)


if __name__ == "__main__":
    unittest.main()
