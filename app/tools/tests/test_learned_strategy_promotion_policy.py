#!/usr/bin/env python3
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.promote_learned_strategy import (
    PromotionError,
    create_review_packet,
    main,
)

RULE_ABSENT = "PDF/UA-1/99.10"
RULE_REVIEW = "PDF/UA-1/99.11"
RULE_EFFECTIVE = "PDF/UA-1/99.12"


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def record_identity(record):
    basis = {
        "run_id": record.get("run_id"),
        "job_dir": record.get("job_dir"),
        "rule_id": record.get("rule_id"),
        "script_path": record.get("script_path"),
        "script_sha256": record.get("script_sha256"),
        "attempt_number": record.get("attempt_number"),
        "outcome": record.get("outcome"),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def sha256_text(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


class LearnedStrategyPromotionPolicyTests(unittest.TestCase):
    def setup_job(self, *, clean=True, rule_id=RULE_ABSENT, script_outside=False, with_execution=True, rejected=None):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        job = root / "workspace" / "jobs" / "JOB1"
        audit = job / "audit"
        quarantine = job / "self_extension" / "quarantine"
        audit.mkdir(parents=True)
        quarantine.mkdir(parents=True)

        rule_map = root / "app" / "tools" / "audit" / "rule_repair_map.json"
        write_json(
            rule_map,
            {
                "_meta": {"version": "2.0.0"},
                "rules": {
                    RULE_REVIEW: {
                        "clause": "99.11",
                        "description": "Review rule",
                        "manual": True,
                        "resolvability": "repairable_review",
                        "strategies": [],
                    },
                    RULE_EFFECTIVE: {
                        "clause": "99.12",
                        "description": "Effective rule",
                        "manual": False,
                        "resolvability": "effective",
                        "strategies": [
                            {
                                "strategy": "existing_primary",
                                "repair_script": "tools/repair/fix_existing.py",
                                "repair_order": 1,
                                "run_last": False,
                                "args_pattern": " ",
                                "pass_count": 3,
                                "fail_count": 0,
                                "pass_rate": 1.0,
                            }
                        ],
                    },
                },
            },
        )

        script = quarantine / "fix_generated.py"
        script.write_text("#!/usr/bin/env python3\nprint('ok')\n")
        script_path = script
        if script_outside:
            script_path = root / "app" / "tools" / "repair" / "generated_bad.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("#!/usr/bin/env python3\nprint('bad')\n")

        stdout = audit / "execution" / "stdout" / "selfext-candidate-001.txt"
        stderr = audit / "execution" / "stderr" / "selfext-candidate-001.txt"
        stdout.parent.mkdir(parents=True)
        stderr.parent.mkdir(parents=True)
        stdout.write_text('{"result":"PASS"}\n')
        stderr.write_text("")

        record = {
            "schema_version": "learned-strategies.v1",
            "created_at": "2026-06-16T00:00:00Z",
            "run_id": "run-1",
            "job_dir": str(job),
            "rule_id": rule_id,
            "script_path": str(script_path),
            "script_sha256": sha256_file(script_path),
            "strategy": "generated_strategy",
            "args_pattern": "input.pdf output.pdf [--out results.json]",
            "repair_order": 8,
            "run_last": True,
            "proposed_resolvability": "effective",
            "outcome": "clean_success" if clean else "dirty_success",
            "clean": clean,
            "review_required": False,
            "pre_count": 2,
            "post_count": 0 if clean else 1,
            "target_rule_strictly_decreased": clean,
            "target_rule_resolved": clean,
            "introduced_rules": [] if clean else ["PDF/UA-1/100.1"],
            "worsened_rules": [],
            "gate_results": {"preservation": "PASS", "render_compare": "PASS"},
            "validation_artifacts": {"candidate_failures_post": "candidate_failures_post.json"},
            "attempt_number": 1,
            "failure_summary": {},
            "indexing_eligible": clean,
            "indexing_blockers": [] if clean else ["introduced_rules:PDF/UA-1/100.1"],
        }
        if with_execution:
            record.update(
                {
                    "execution_attempt_id": "selfext-candidate-001",
                    "execution_log_path": str(audit / "execution_log.json"),
                    "stdout_path": str(stdout),
                    "stderr_path": str(stderr),
                }
            )

        rid = record_identity(record)
        learned_hash = sha256_text(record)
        strategy = {
            "source": "learned_strategy_capture",
            "repair_script": str(script_path),
            "script_path": str(script_path),
            "script_sha256": record["script_sha256"],
            "strategy": "generated_strategy",
            "args_pattern": "input.pdf output.pdf [--out results.json]",
            "repair_order": 8,
            "run_last": True,
            "clean_pass_count": 1,
            "pass_count": 1,
            "fail_count": 0,
            "pass_rate": 1.0 if clean else 0.0,
            "introduced_rules": record["introduced_rules"],
            "worsened_rules": record["worsened_rules"],
            "gate_results": record["gate_results"],
            "review_required": False,
            "evidence": {
                "learned_strategy_record_id": rid,
                "learned_strategy_record_hash": learned_hash,
                "job_dir": str(job),
                "residual_analysis_path": str(audit / "residual_analysis.json"),
                "residual_analysis_sha256": "residual-sha",
                "validation_artifacts": record["validation_artifacts"],
                "attempt_number": 1,
                "run_id": "run-1",
            },
        }

        if rule_id == RULE_ABSENT:
            proposal = {
                "action": "add_rule",
                "rule_id": rule_id,
                "reason": "rule_absent_from_map",
                "proposed_entry": {
                    "clause": "99.10",
                    "description": "Generated rule",
                    "manual": False,
                    "resolvability": "repairable_review",
                    "emits_review_artifact": False,
                    "review_required": True,
                    "strategies": [strategy],
                },
            }
        elif rule_id == RULE_REVIEW:
            proposal = {
                "action": "attach_strategy_preserve_review",
                "rule_id": rule_id,
                "reason": "clean_strategy_for_review_rule",
                "preserve_review_semantics": True,
                "proposed_resolvability": "repairable_review",
                "proposed_strategy": strategy,
            }
        else:
            proposal = {
                "action": "add_alternate_strategy",
                "rule_id": rule_id,
                "reason": "existing_effective_primary_preserved",
                "preserve_existing_primary": True,
                "proposed_container": "edge_cases_or_lower_ranked_strategy",
                "proposed_strategy": strategy,
            }

        write_json(audit / "learned_strategies.json", {"schema_version": "learned-strategies.v1", "artifact": "learned_strategies", "records": [record]})
        write_json(audit / "residual_analysis.json", {"schema_version": "residual-analysis.v1", "artifact": "residual_analysis"})
        write_json(
            audit / "execution_log.json",
            {
                "schema_version": "execution-log.v2",
                "artifact": "execution_log",
                "job_dir": str(job),
                "records": [
                    {
                        "record_type": "self_extension_candidate",
                        "attempt_id": "selfext-candidate-001",
                        "rule_ids": [rule_id],
                        "script": str(script_path),
                        "stdout_path": str(stdout),
                        "stderr_path": str(stderr),
                        "result": "PASS",
                    }
                ],
            },
        )

        index_report = {
            "schema_version": "strategy-indexing-report.v1",
            "mode": "dry_run",
            "job_dir": str(job),
            "rule_map_path": str(rule_map),
            "proposed_rule_map_changes": [proposal] if clean and rejected is None else [],
            "rejected_experiments": rejected or ([] if clean else [
                {
                    "record_id": rid,
                    "rule_id": rule_id,
                    "outcome": record["outcome"],
                    "script_path": str(script_path),
                    "indexing_eligible": False,
                    "clean": False,
                    "reasons": ["record_not_clean", "introduced_rules_present"],
                    "indexing_blockers": record["indexing_blockers"],
                    "introduced_rules": record["introduced_rules"],
                    "worsened_rules": [],
                    "gate_results": record["gate_results"],
                }
            ]),
            "policy": {"canonical_rule_map_mutation_performed": False},
        }
        write_json(audit / "strategy_indexing_report.json", index_report)
        return td, root, job, rule_map

    def test_dry_run_review_packet_from_fake_clean_indexer_report(self):
        td, root, job, rule_map = self.setup_job(clean=True)
        before_rule_map = rule_map.read_text()
        repair_files_before = sorted(p.name for p in (root / "app" / "tools" / "repair").glob("*")) if (root / "app" / "tools" / "repair").exists() else []
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            self.assertTrue((job / "audit" / "strategy_promotion_review.json").exists())
            self.assertEqual(len(packet["promotion_candidates"]), 1)
            candidate = packet["promotion_candidates"][0]
            self.assertEqual(candidate["script_location_status"], "quarantine_only")
            self.assertEqual(candidate["execution_attempt_id"], "selfext-candidate-001")
            self.assertFalse(candidate["safe_to_apply_rule_map_patch"])
            self.assertIn("apply_mode_not_implemented_in_patch_8", candidate["promotion_blockers"])
            self.assertEqual(rule_map.read_text(), before_rule_map)
            repair_files_after = sorted(p.name for p in (root / "app" / "tools" / "repair").glob("*")) if (root / "app" / "tools" / "repair").exists() else []
            self.assertEqual(repair_files_after, repair_files_before)

    def test_dirty_failed_refusal_rejected_with_explicit_reasons(self):
        rejected = [
            {"record_id": "dirty", "rule_id": RULE_ABSENT, "outcome": "dirty_success", "clean": False, "indexing_eligible": False, "reasons": ["record_not_clean"]},
            {"record_id": "failed", "rule_id": RULE_ABSENT, "outcome": "validation_failed", "clean": False, "indexing_eligible": False, "reasons": ["target_rule_not_decreased"]},
            {"record_id": "refusal", "rule_id": RULE_ABSENT, "outcome": "semantic_refusal", "clean": False, "indexing_eligible": False, "reasons": ["semantic_refusal"]},
        ]
        td, root, job, rule_map = self.setup_job(clean=True, rejected=rejected)
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            self.assertEqual(packet["promotion_candidates"], [])
            self.assertEqual(len(packet["rejected_candidates"]), 3)
            for rejected_candidate in packet["rejected_candidates"]:
                self.assertIn("rejected_by_strategy_indexer", rejected_candidate["reasons"])
                self.assertFalse(rejected_candidate["safe_to_apply_rule_map_patch"])

    def test_candidate_requires_execution_evidence(self):
        td, root, job, rule_map = self.setup_job(clean=True, with_execution=False)
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            candidate = packet["promotion_candidates"][0]
            self.assertIn("missing_execution_attempt_id", candidate["promotion_blockers"])
            self.assertIn("missing_stdout_path", candidate["promotion_blockers"])
            self.assertIn("missing_stderr_path", candidate["promotion_blockers"])
            self.assertFalse(candidate["safe_to_apply_rule_map_patch"])

    def test_candidate_script_must_remain_quarantine_only(self):
        td, root, job, rule_map = self.setup_job(clean=True, script_outside=True)
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            candidate = packet["promotion_candidates"][0]
            self.assertEqual(candidate["script_location_status"], "outside_job_quarantine")
            self.assertIn("candidate_script_not_quarantine_only", candidate["promotion_blockers"])
            canonical_script = root / "app" / "tools" / "repair" / "generated_bad.py"
            self.assertTrue(canonical_script.exists())
            self.assertEqual(canonical_script.read_text(), "#!/usr/bin/env python3\nprint('bad')\n")

    def test_existing_effective_primary_is_preserved_as_alternate(self):
        td, root, job, rule_map = self.setup_job(clean=True, rule_id=RULE_EFFECTIVE)
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            candidate = packet["promotion_candidates"][0]
            self.assertEqual(candidate["action"], "add_alternate_strategy")
            self.assertIn("edge_cases", candidate["proposed_rule_map_entry"])
            self.assertEqual(candidate["current_rule_map_entry"]["strategies"][0]["strategy"], "existing_primary")

    def test_repairable_review_semantics_preserved(self):
        td, root, job, rule_map = self.setup_job(clean=True, rule_id=RULE_REVIEW)
        with td:
            packet = create_review_packet(job_dir=job, rule_map_path=rule_map)
            candidate = packet["promotion_candidates"][0]
            self.assertEqual(candidate["action"], "preserve_review_strategy")
            self.assertTrue(candidate["proposed_rule_map_entry"]["review_required"])
            self.assertEqual(candidate["proposed_rule_map_entry"]["resolvability"], "repairable_review")

    def test_apply_mode_fails_closed(self):
        td, root, job, rule_map = self.setup_job(clean=True)
        before = rule_map.read_text()
        with td:
            rc = main(["--job-dir", str(job), "--rule-map", str(rule_map), "--apply-rule-map", "--reviewed-by", "operator"])
            self.assertEqual(rc, 2)
            self.assertEqual(rule_map.read_text(), before)

    def test_cli_dry_run_exits_zero_for_clean_and_no_candidate_jobs(self):
        td, root, job, rule_map = self.setup_job(clean=True)
        with td:
            self.assertEqual(main(["--job-dir", str(job), "--rule-map", str(rule_map), "--dry-run"]), 0)
            self.assertTrue((job / "audit" / "strategy_promotion_review.json").exists())
        td, root, job, rule_map = self.setup_job(clean=False)
        with td:
            self.assertEqual(main(["--job-dir", str(job), "--rule-map", str(rule_map), "--dry-run"]), 0)
            packet = json.loads((job / "audit" / "strategy_promotion_review.json").read_text())
            self.assertEqual(packet["promotion_candidates"], [])
            self.assertTrue(packet["rejected_candidates"])

    def test_missing_indexing_report_fails_clearly(self):
        td, root, job, rule_map = self.setup_job(clean=True)
        with td:
            (job / "audit" / "strategy_indexing_report.json").unlink()
            with self.assertRaises(PromotionError):
                create_review_packet(job_dir=job, rule_map_path=rule_map)


if __name__ == "__main__":
    unittest.main()
