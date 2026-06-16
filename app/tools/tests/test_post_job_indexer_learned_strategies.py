#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.post_job_indexer import IndexingError, main, run_indexing


RULE_ABSENT = "PDF/UA-1/99.1"
RULE_UNBUILT = "PDF/UA-1/99.2"
RULE_REVIEW = "PDF/UA-1/99.3"
RULE_EFFECTIVE = "PDF/UA-1/99.4"


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def base_rule_map():
    return {
        "_meta": {"version": "2.0.0"},
        "rules": {
            RULE_UNBUILT: {
                "clause": "99.2",
                "description": "Known but unbuilt repair",
                "manual": True,
                "resolvability": "repairable_unbuilt",
                "strategies": [],
            },
            RULE_REVIEW: {
                "clause": "99.3",
                "description": "Known review repair",
                "manual": True,
                "resolvability": "repairable_review",
                "strategies": [],
            },
            RULE_EFFECTIVE: {
                "clause": "99.4",
                "description": "Known effective repair",
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
    }


def learned_record(rule_id=RULE_ABSENT, **overrides):
    record = {
        "schema_version": "learned-strategies.v1",
        "created_at": "2026-06-16T00:00:00Z",
        "run_id": "run-1",
        "job_dir": "/tmp/job",
        "rule_id": rule_id,
        "script_path": "tools/repair/generated/fix_generated_rule.py",
        "script_sha256": "abc123",
        "strategy": "generated_strategy",
        "args_pattern": "input.pdf output.pdf [--out results.json]",
        "repair_order": 8,
        "run_last": True,
        "proposed_resolvability": "effective",
        "outcome": "clean_success",
        "clean": True,
        "review_required": False,
        "pre_count": 2,
        "post_count": 0,
        "target_rule_strictly_decreased": True,
        "target_rule_resolved": True,
        "introduced_rules": [],
        "worsened_rules": [],
        "gate_results": {"preservation": "PASS", "render_compare": "PASS"},
        "isolation_snapshot": {"attempt_dir": "attempt_01", "adoption_performed": False},
        "stdout_json": {"result": "MODIFIED", "strategy": "generated_strategy"},
        "generation_request": {"attempt": 1},
        "generation_response": {"strategy": "generated_strategy"},
        "candidate_result": {"result": "PASS"},
        "validation_artifacts": {"candidate_failures_post": "candidate_failures_post.json"},
        "attempt_number": 1,
        "transport_attempts_used": 0,
        "repair_attempts_used": 1,
        "semantic_refusal_count": 0,
        "needs_more_evidence_count": 0,
        "failure_summary": {},
        "indexing_eligible": True,
        "indexing_blockers": [],
    }
    record.update(overrides)
    return record


def learned_artifact(records):
    return {
        "schema_version": "learned-strategies.v1",
        "artifact": "learned_strategies",
        "records": records,
    }


class PostJobIndexerLearnedStrategyTests(unittest.TestCase):
    def setup_job(self, records=None, rule_map=None, residual=True):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        job = root / "workspace" / "jobs" / "JOB1"
        audit = job / "audit"
        audit.mkdir(parents=True)
        rule_map_path = root / "app" / "tools" / "audit" / "rule_repair_map.json"
        write_json(rule_map_path, rule_map if rule_map is not None else base_rule_map())
        if records is not None:
            write_json(audit / "learned_strategies.json", learned_artifact(records))
        if residual:
            write_json(
                audit / "residual_analysis.json",
                {
                    "schema_version": "residual-analysis.v1",
                    "artifact": "residual_analysis",
                    "targetable_failures": [],
                },
            )
        return td, root, job, rule_map_path

    def test_no_learned_strategies_is_successful_noop_report(self):
        td, root, job, rule_map = self.setup_job(records=None)
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            self.assertEqual(report["mode"], "dry_run")
            self.assertEqual(report["proposed_rule_map_changes"], [])
            self.assertIn("learned_strategies.json missing; safe no-op", report["warnings"])
            self.assertTrue((job / "audit" / "strategy_indexing_report.json").exists())

    def test_clean_success_rule_absent_proposes_new_rule_entry_without_mutation(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_ABSENT)])
        before = rule_map.read_text()
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            self.assertEqual(rule_map.read_text(), before)
            self.assertEqual(report["proposed_rule_map_changes"][0]["action"], "add_rule")
            entry = report["proposed_rule_map_changes"][0]["proposed_entry"]
            self.assertEqual(entry["strategies"][0]["source"], "learned_strategy_capture")
            self.assertEqual(entry["strategies"][0]["clean_pass_count"], 1)

    def test_clean_success_repairable_unbuilt_proposes_attach_strategy(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_UNBUILT)])
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            proposal = report["proposed_rule_map_changes"][0]
            self.assertEqual(proposal["action"], "attach_strategy_to_repairable_unbuilt")
            self.assertEqual(proposal["proposed_resolvability"], "effective_if_policy_allows")

    def test_clean_success_repairable_review_preserves_review_semantics(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_REVIEW)])
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            proposal = report["proposed_rule_map_changes"][0]
            self.assertEqual(proposal["action"], "attach_strategy_preserve_review")
            self.assertTrue(proposal["preserve_review_semantics"])
            self.assertEqual(proposal["proposed_resolvability"], "repairable_review")

    def test_clean_success_existing_effective_primary_adds_alternate_not_overwrite(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_EFFECTIVE)])
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            proposal = report["proposed_rule_map_changes"][0]
            self.assertEqual(proposal["action"], "add_alternate_strategy")
            self.assertTrue(proposal["preserve_existing_primary"])
            self.assertEqual(proposal["proposed_container"], "edge_cases_or_lower_ranked_strategy")

    def test_partial_improvement_rejected_as_experiment(self):
        record = learned_record(
            RULE_ABSENT,
            outcome="partial_improvement",
            clean=False,
            indexing_eligible=False,
            target_rule_resolved=False,
            post_count=1,
            indexing_blockers=["target_rule_not_resolved"],
        )
        td, root, job, rule_map = self.setup_job(records=[record])
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            self.assertEqual(report["proposed_rule_map_changes"], [])
            self.assertEqual(report["rejected_experiments"][0]["outcome"], "partial_improvement")
            self.assertIn("target_rule_not_resolved", report["rejected_experiments"][0]["reasons"])

    def test_dirty_success_rejected_for_introduced_rules(self):
        record = learned_record(
            RULE_ABSENT,
            outcome="dirty_success",
            clean=False,
            indexing_eligible=False,
            introduced_rules=["PDF/UA-1/100.1"],
            indexing_blockers=["introduced_rules:PDF/UA-1/100.1"],
        )
        td, root, job, rule_map = self.setup_job(records=[record])
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            rejected = report["rejected_experiments"][0]
            self.assertIn("record_not_clean", rejected["reasons"])
            self.assertIn("introduced_rules_present", rejected["reasons"])

    def test_validation_failed_transport_and_refusal_rejected(self):
        records = [
            learned_record(RULE_ABSENT, outcome="validation_failed", clean=False, indexing_eligible=False, indexing_blockers=["target_rule_not_decreased"]),
            learned_record(RULE_ABSENT, outcome="transport_blocked", clean=False, indexing_eligible=False, script_path=None, target_rule_resolved=False, indexing_blockers=["transport_blocked"]),
            learned_record(RULE_ABSENT, outcome="semantic_refusal", clean=False, indexing_eligible=False, script_path=None, target_rule_resolved=False, indexing_blockers=["semantic_refusal"]),
        ]
        td, root, job, rule_map = self.setup_job(records=records)
        with td:
            report = run_indexing(job_dir=job, rule_map_path=rule_map)
            self.assertEqual(len(report["rejected_experiments"]), 3)
            self.assertEqual(report["proposed_rule_map_changes"], [])

    def test_malformed_learned_strategies_fails_clearly(self):
        td, root, job, rule_map = self.setup_job(records=None)
        with td:
            write_json(job / "audit" / "learned_strategies.json", {"schema_version": "learned-strategies.v1", "records": {}})
            with self.assertRaises(IndexingError):
                run_indexing(job_dir=job, rule_map_path=rule_map)

    def test_cli_emits_report_and_returns_zero(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_ABSENT)])
        with td:
            rc = main([str(job), "--rule-map", str(rule_map), "--dry-run"])
            self.assertEqual(rc, 0)
            report_path = job / "audit" / "strategy_indexing_report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text())
            self.assertEqual(report["indexed_records"][0]["dry_run"], True)

    def test_apply_mode_is_rejected(self):
        td, root, job, rule_map = self.setup_job(records=[learned_record(RULE_ABSENT)])
        before = rule_map.read_text()
        with td:
            rc = main([str(job), "--rule-map", str(rule_map), "--apply"])
            self.assertEqual(rc, 2)
            self.assertEqual(rule_map.read_text(), before)


if __name__ == "__main__":
    unittest.main()
