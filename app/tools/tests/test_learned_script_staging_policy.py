#!/usr/bin/env python3
"""Patch 9 tests for reviewed learned-script staging policy."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import promote_learned_strategy as promote

RULE_ID = "PDF/UA-1/7.21.7"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class LearnedScriptStagingPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN"
        self.audit = self.job / "audit"
        self.quarantine = self.job / "self_extension/quarantine"
        self.quarantine.mkdir(parents=True)
        self.audit.mkdir(parents=True)
        self.staging = self.root / "app/tools/repair_staging/learned"
        self.repair = self.root / "app/tools/repair"
        self.repair.mkdir(parents=True)
        (self.repair / "README.md").write_text("production repair scripts stay untouched\n")
        self.rule_map = self.root / "app/tools/audit/rule_repair_map.json"
        self.rule_map.parent.mkdir(parents=True)
        self.rule_map.write_text(json.dumps({"rules": {RULE_ID: {"resolvability": "repairable_unbuilt", "strategies": []}}}))
        self.script = self.quarantine / "candidate_fix.py"
        self.script.write_text("def repair(input_pdf, output_pdf):\n    return output_pdf\n")
        self.stdout = self.audit / "candidate.stdout.txt"
        self.stderr = self.audit / "candidate.stderr.txt"
        self.stdout.write_text("ok\n")
        self.stderr.write_text("")
        self.write_artifacts()
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        self.candidate_id = packet["promotion_candidates"][0]["candidate_id"]
        self.repair_before = {p.relative_to(self.repair): sha256_file(p) for p in self.repair.rglob("*") if p.is_file()}
        self.rule_map_before = self.rule_map.read_text()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_artifacts(self, *, clean: bool = True, failed: bool = False, include_execution: bool = True, script_path: Path | None = None, script_sha: str | None = None) -> None:
        script_path = script_path or self.script
        script_sha = script_sha or sha256_file(script_path)
        record = {
            "run_id": "run-1",
            "job_dir": str(self.job),
            "rule_id": RULE_ID,
            "script_path": str(script_path),
            "script_sha256": script_sha,
            "attempt_number": 1,
            "outcome": "failed" if failed else "success",
            "clean": clean,
            "indexing_eligible": clean and not failed,
            "introduced_rules": [],
            "worsened_rules": [],
            "execution_attempt_id": "attempt-1" if include_execution else "",
            "execution_log_path": str(self.audit / "execution_log.json") if include_execution else "",
            "stdout_path": str(self.stdout) if include_execution else "",
            "stderr_path": str(self.stderr) if include_execution else "",
            "validation_artifacts": {},
            "gate_results": {"verapdf_pdfua1": "PASS"},
        }
        self.audit.joinpath("learned_strategies.json").write_text(json.dumps({"records": [record]}))
        self.audit.joinpath("residual_analysis.json").write_text(json.dumps({"overall_result": "PASS"}))
        if include_execution:
            self.audit.joinpath("execution_log.json").write_text(json.dumps({"records": [{"attempt_id": "attempt-1", "outcome": "success"}]}))
        else:
            self.audit.joinpath("execution_log.json").write_text(json.dumps({"records": []}))
        proposal = {
            "rule_id": RULE_ID,
            "action": "attach_strategy_to_repairable_unbuilt",
            "proposed_strategy": {
                "repair_script": str(script_path),
                "script_path": str(script_path),
                "script_sha256": script_sha,
                "evidence": {},
            },
        }
        self.audit.joinpath("strategy_indexing_report.json").write_text(json.dumps({"proposed_rule_map_changes": [proposal], "rejected_experiments": []}))

    def assert_no_canonical_mutation(self) -> None:
        self.assertEqual(self.rule_map_before, self.rule_map.read_text())
        after = {p.relative_to(self.repair): sha256_file(p) for p in self.repair.rglob("*") if p.is_file()}
        self.assertEqual(self.repair_before, after)

    def test_stage_dry_run_for_fake_clean_candidate_no_copy(self) -> None:
        result = promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=True)
        self.assertEqual("dry_run", result["mode"])
        self.assertTrue(result["script_staging_ready"])
        self.assertFalse(result["generated_script_promotion_performed"])
        self.assertFalse(Path(result["staged_script_path"]).exists())
        review = json.loads((self.audit / "strategy_promotion_review.json").read_text())
        candidate = review["promotion_candidates"][0]
        self.assertTrue(candidate["script_staging_ready"])
        self.assertEqual([], candidate["script_staging_blockers"])
        self.assertIn("static_checks", candidate)
        self.assert_no_canonical_mutation()

    def test_stage_apply_copies_to_staging_and_writes_manifest_result(self) -> None:
        result = promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        staged = Path(result["staged_script_path"])
        self.assertTrue(staged.exists())
        self.assertEqual(sha256_file(self.script), result["source_script_sha256"])
        self.assertEqual(result["source_script_sha256"], result["staged_script_sha256"])
        self.assertFalse(result["production_repair_activation_performed"])
        self.assertFalse(result["rule_map_apply_performed"])
        self.assertFalse(result["final_pdf_adoption_performed"])
        saved = json.loads((self.audit / "script_promotion_result.json").read_text())
        self.assertEqual(result["staged_script_path"], saved["staged_script_path"])
        manifest = json.loads((self.staging / "manifest.json").read_text())
        self.assertEqual("staged_reviewed", manifest["staged_scripts"][0]["status"])
        self.assertFalse(manifest["staged_scripts"][0]["production_active"])
        self.assertFalse(manifest["staged_scripts"][0]["rule_map_applied"])
        self.assert_no_canonical_mutation()

    def test_stage_apply_requires_candidate_id_and_reviewer(self) -> None:
        with self.assertRaises(promote.PromotionError):
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id="", reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        with self.assertRaises(promote.PromotionError):
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="", staging_dir=self.staging, dry_run=False)

    def test_idempotent_restage_same_candidate(self) -> None:
        first = promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        second = promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertEqual(first["staged_script_path"], second["staged_script_path"])
        self.assertEqual(first["staged_script_sha256"], second["staged_script_sha256"])
        self.assertTrue(second["generated_script_promotion_performed"])

    def test_different_hash_conflict_fails_closed(self) -> None:
        first = promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        Path(first["staged_script_path"]).write_text("different\n")
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("staged_script_hash_conflict", str(ctx.exception))

    def test_dirty_candidate_blocked(self) -> None:
        self.write_artifacts(clean=False)
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("record_not_clean", str(ctx.exception))

    def test_failed_candidate_blocked(self) -> None:
        self.write_artifacts(clean=False, failed=True)
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("record_not_clean", str(ctx.exception))

    def test_missing_execution_evidence_blocked(self) -> None:
        self.write_artifacts(include_execution=False)
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("missing_execution_attempt_id", str(ctx.exception))

    def test_script_outside_quarantine_blocked(self) -> None:
        outside = self.root / "outside.py"
        outside.write_text("def repair(a, b):\n    return b\n")
        self.write_artifacts(script_path=outside)
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("candidate_script_not_quarantine_only", str(ctx.exception))

    def test_hash_mismatch_blocked(self) -> None:
        self.write_artifacts(script_sha="0" * 64)
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("candidate_script_hash_mismatch", str(ctx.exception))

    def test_static_unsafe_script_blocked(self) -> None:
        self.script.write_text("import os\ndef repair(a, b):\n    os.system('echo unsafe')\n")
        self.write_artifacts()
        packet = promote.create_review_packet(job_dir=self.job, rule_map_path=self.rule_map)
        cid = packet["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promote.PromotionError) as ctx:
            promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=cid, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assertIn("script_ast_safety_failed", str(ctx.exception))

    def test_apply_rule_map_still_fails_closed(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = promote.main(["--job-dir", str(self.job), "--rule-map", str(self.rule_map), "--apply-rule-map"])
        self.assertNotEqual(0, rc)
        self.assertIn("Rule-map apply is not implemented in this patch", stderr.getvalue())
        self.assert_no_canonical_mutation()

    def test_no_canonical_repair_mutation(self) -> None:
        promote.stage_script(job_dir=self.job, rule_map_path=self.rule_map, candidate_id=self.candidate_id, reviewed_by="operator", staging_dir=self.staging, dry_run=False)
        self.assert_no_canonical_mutation()


if __name__ == "__main__":
    unittest.main()
