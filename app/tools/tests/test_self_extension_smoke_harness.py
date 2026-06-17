#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.dev.self_extension_smoke import MODES, run_smoke
from tools.audit.post_job_indexer import resolve_default_rule_map


REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_MAP_PATH = resolve_default_rule_map()
REPAIR_DIR = REPO_ROOT / "app" / "tools" / "repair"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def repair_tree_snapshot() -> set[str]:
    if not REPAIR_DIR.exists():
        return set()
    return {str(p.relative_to(REPAIR_DIR)) for p in REPAIR_DIR.rglob("*") if p.is_file()}


class SelfExtensionSmokeHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rule_map_before = sha256_file(Path(RULE_MAP_PATH))
        self.repair_before = repair_tree_snapshot()

    def assert_no_canonical_mutation(self) -> None:
        self.assertEqual(self.rule_map_before, sha256_file(Path(RULE_MAP_PATH)))
        self.assertEqual(self.repair_before, repair_tree_snapshot())

    def run_mode(self, mode: str) -> tuple[Path, dict]:
        job_dir = self.root / mode
        summary = run_smoke(job_dir=job_dir, mode=mode, rule_map_path=Path(RULE_MAP_PATH))
        self.assertEqual(summary["result"], "PASS")
        self.assert_no_canonical_mutation()
        return job_dir, summary

    def test_fake_clean_candidate_path_proposes_dry_run_change(self) -> None:
        job_dir, summary = self.run_mode("fake-clean")
        self.assertEqual(summary["outcome"], "clean_success")
        self.assertTrue(summary["clean"])
        self.assertTrue(summary["indexing_eligible"])
        self.assertEqual(summary["proposed_rule_map_change_count"], 1)

        execution_log = read_json(job_dir / "audit" / "execution_log.json")
        candidate_records = [r for r in execution_log["records"] if r.get("record_type") == "self_extension_candidate"]
        self.assertEqual(len(candidate_records), 1)
        record = candidate_records[0]
        self.assertEqual(record["result"], "PASS")
        self.assertEqual(record["exit_code"], 0)
        self.assertIn("audit/self_extension/quarantine", record["script_path"].replace("\\", "/"))
        self.assertIsNotNone(record["script_sha256"])
        self.assertIsNotNone(record["stdout_sha256"])
        self.assertIsNotNone(record["stderr_sha256"])

        learned = read_json(job_dir / "audit" / "learned_strategies.json")
        learned_record = learned["records"][0]
        self.assertEqual(learned_record["outcome"], "clean_success")
        self.assertTrue(learned_record["clean"])
        self.assertTrue(learned_record["indexing_eligible"])
        self.assertEqual(learned_record["execution_attempt_id"], record["attempt_id"])
        self.assertEqual(learned_record["execution_log_path"], "audit/execution_log.json")
        self.assertEqual(learned_record["stdout_path"], record["stdout_path"])
        self.assertEqual(learned_record["stderr_path"], record["stderr_path"])

        report = read_json(job_dir / "audit" / "strategy_indexing_report.json")
        self.assertEqual(len(report["proposed_rule_map_changes"]), 1)
        self.assertEqual(report["policy"]["canonical_rule_map_mutation_performed"], False)

    def test_fake_dirty_candidate_is_rejected_experiment(self) -> None:
        job_dir, summary = self.run_mode("fake-dirty")
        self.assertEqual(summary["outcome"], "dirty_success")
        self.assertFalse(summary["clean"])
        self.assertFalse(summary["indexing_eligible"])
        self.assertEqual(summary["proposed_rule_map_change_count"], 0)
        self.assertEqual(summary["rejected_experiment_count"], 1)

        execution_log = read_json(job_dir / "audit" / "execution_log.json")
        self.assertEqual(execution_log["records"][0]["record_type"], "self_extension_candidate")
        learned = read_json(job_dir / "audit" / "learned_strategies.json")["records"][0]
        self.assertIn("PDF/UA-1/7.18.4", learned["introduced_rules"])
        report = read_json(job_dir / "audit" / "strategy_indexing_report.json")
        self.assertEqual(len(report["rejected_experiments"]), 1)
        self.assertIn("record_not_clean", report["rejected_experiments"][0]["reasons"])

    def test_fake_failed_candidate_captures_nonzero_execution(self) -> None:
        job_dir, summary = self.run_mode("fake-failed")
        self.assertEqual(summary["outcome"], "validation_failed")
        self.assertFalse(summary["indexing_eligible"])
        execution_log = read_json(job_dir / "audit" / "execution_log.json")
        record = execution_log["records"][0]
        self.assertEqual(record["record_type"], "self_extension_candidate")
        self.assertNotEqual(record["exit_code"], 0)
        self.assertEqual(record["result"], "FAIL")
        learned = read_json(job_dir / "audit" / "learned_strategies.json")["records"][0]
        self.assertEqual(learned["outcome"], "validation_failed")
        self.assertIn("candidate_execution_failed", learned["indexing_blockers"])
        self.assertIsNotNone(learned["failure_summary"])

    def test_fake_refusal_captures_no_script_non_indexable_event(self) -> None:
        job_dir, summary = self.run_mode("fake-refusal")
        self.assertEqual(summary["outcome"], "needs_more_evidence")
        self.assertIsNone(summary["execution_attempt_id"])
        self.assertFalse((job_dir / "audit" / "execution_log.json").exists())
        learned = read_json(job_dir / "audit" / "learned_strategies.json")["records"][0]
        self.assertEqual(learned["outcome"], "needs_more_evidence")
        self.assertFalse(learned["indexing_eligible"])
        self.assertIn("no_script_source_generated", learned["indexing_blockers"])
        run_state = read_json(job_dir / "audit" / "self_extension" / "run_state.json")
        self.assertEqual(run_state["generation_events"][0]["result"], "NEEDS_MORE_EVIDENCE")
        report = read_json(job_dir / "audit" / "strategy_indexing_report.json")
        self.assertEqual(len(report["rejected_experiments"]), 1)

    def test_quarantine_boundary_and_no_repair_promotion(self) -> None:
        job_dir, _summary = self.run_mode("fake-clean")
        generated = list((job_dir / "audit" / "self_extension" / "quarantine").rglob("*.py"))
        self.assertEqual(len(generated), 1)
        self.assertTrue(str(generated[0].resolve()).startswith(str(job_dir.resolve())))
        self.assertFalse((REPO_ROOT / "app" / "tools" / "repair" / generated[0].name).exists())
        self.assert_no_canonical_mutation()

    def test_cli_exits_successfully_for_all_controlled_modes(self) -> None:
        script = REPO_ROOT / "app" / "tools" / "dev" / "self_extension_smoke.py"
        for mode in MODES:
            with self.subTest(mode=mode):
                job_dir = self.root / f"cli-{mode}"
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--job-dir",
                        str(job_dir),
                        "--mode",
                        mode,
                        "--rule-map",
                        str(RULE_MAP_PATH),
                    ],
                    cwd=str(REPO_ROOT),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                payload = json.loads(proc.stdout)
                self.assertEqual(payload["result"], "PASS")
        self.assert_no_canonical_mutation()


if __name__ == "__main__":
    unittest.main()
