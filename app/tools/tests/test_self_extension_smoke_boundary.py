#!/usr/bin/env python3
"""H13S regression tests for evidence-only WebUI self-extension smoke boundary."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "app"))

from tools.orchestrate.self_extension_smoke_boundary import (  # noqa: E402
    _prepend_pythonpath,
    blocked_action,
    is_prohibited_source_path,
    normalize_self_extension,
    smoke_boundary_summary,
    source_mutation_actions,
    source_snapshot,
    surface_smoke_boundary,
    target_rule_check,
)


class SelfExtensionSmokeBoundaryTests(unittest.TestCase):
    def test_source_repair_and_rule_map_paths_are_prohibited(self):
        self.assertTrue(is_prohibited_source_path("app/tools/repair/fix_embed_nonsymbolic_fonts.py"))
        self.assertTrue(is_prohibited_source_path("app/tools/audit/rule_repair_map.json"))
        self.assertTrue(is_prohibited_source_path("workspace/extract_text.py"))
        self.assertFalse(is_prohibited_source_path("workspace/jobs/JOB1/audit/strategy_gap.json"))
        self.assertFalse(is_prohibited_source_path("docs/H13S_WEBUI_SELF_EXTENSION_SMOKE_BOUNDARY.md"))

    def test_smoke_boundary_forbids_mutation_adoption_and_failed_final_update(self):
        boundary = smoke_boundary_summary([blocked_action("rule_map_mutation", "app/tools/audit/rule_repair_map.json")])
        self.assertTrue(boundary["evidence_only"])
        self.assertFalse(boundary["source_repair_creation_allowed"])
        self.assertFalse(boundary["rule_map_mutation_allowed"])
        self.assertFalse(boundary["adoption_allowed"])
        self.assertFalse(boundary["final_pdf_update_from_failed_candidate_allowed"])
        self.assertEqual(boundary["boundary_result"], "BLOCKED")
        self.assertEqual(boundary["blocked_actions"][0]["action"], "rule_map_mutation")

    def test_target_rule_mismatch_is_explicit(self):
        check = target_rule_check("PDF/UA-1/7.21.7", ["PDF/UA-1/7.21.5"])
        self.assertEqual(check["result"], "MISMATCH")
        self.assertEqual(check["expected_target_rule_id"], "PDF/UA-1/7.21.7")
        self.assertEqual(check["actual_target_rule_id"], "PDF/UA-1/7.21.5")
        self.assertEqual(check["reason"], "actual_residual_did_not_match_expected_self_extension_target")

    def test_enabled_not_run_has_specific_reason(self):
        payload = normalize_self_extension(
            {"result": "NOT_RUN", "attempt_count": 0},
            enabled=True,
            expected_target_rule_id="PDF/UA-1/7.21.7",
            actual_rule_ids=["PDF/UA-1/7.21.5"],
        )
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["result"], "NOT_RUN")
        self.assertEqual(payload["reason"], "self_extension_enabled_but_target_rule_mismatch")
        self.assertEqual(payload["target_rule_id"], "PDF/UA-1/7.21.7")
        self.assertFalse(payload["adoption_performed"])
        self.assertFalse(payload["final_pdf_updated"])
        self.assertFalse(payload["rule_map_mutation_performed"])

    def test_surface_updates_status_and_outcome_for_enabled_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "jobs" / "JOB1"
            audit = job / "audit"
            audit.mkdir(parents=True)
            (job / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "result": "PASS"}))
            (audit / "orchestrator_outcome.json").write_text(json.dumps({"overall_result": "PASS"}))
            (audit / "strategy_gap.json").write_text(json.dumps({
                "result": "HERMES_REQUIRED",
                "rules": ["PDF/UA-1/7.21.5"],
                "self_extension": None,
            }))
            summary = surface_smoke_boundary(
                job,
                expected_target_rule_id="PDF/UA-1/7.21.7",
                self_extension_configured=True,
            )
            status = json.loads((job / "STATUS.json").read_text())
            outcome = json.loads((audit / "orchestrator_outcome.json").read_text())
            for payload in (status, outcome):
                self.assertEqual(payload["overall_result"], "ESCALATION")
                self.assertEqual(payload["self_extension"]["result"], "NOT_RUN")
                self.assertEqual(payload["self_extension"]["reason"], "self_extension_enabled_but_policy_blocked")
                self.assertEqual(payload["target_rule_check"]["result"], "MISMATCH")
                self.assertEqual(payload["smoke_boundary"]["boundary_result"], "BLOCKED")
                self.assertEqual(payload["smoke_boundary"]["blocked_actions"][0]["action"], "target_rule_mismatch")
                self.assertIn("self_extension_not_run_blocker", payload)
            self.assertEqual(summary["target_rule_check"]["result"], "MISMATCH")

    def test_surface_writes_minimal_artifacts_for_child_command_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "jobs" / "JOB1"
            summary = surface_smoke_boundary(
                job,
                expected_target_rule_id="PDF/UA-1/7.21.7",
                self_extension_configured=True,
                transport_unavailable=True,
                child_result={"returncode": 1, "stderr_tail": "ModuleNotFoundError: No module named 'tools'"},
            )
            status = json.loads((job / "STATUS.json").read_text())
            outcome = json.loads((job / "audit" / "orchestrator_outcome.json").read_text())
            for payload in (status, outcome):
                self.assertEqual(payload["overall_result"], "ESCALATION")
                self.assertEqual(payload["self_extension"]["reason"], "self_extension_enabled_but_transport_unavailable")
                self.assertEqual(payload["smoke_boundary"]["boundary_result"], "BLOCKED")
                self.assertIn("self_extension_not_run_blocker", payload)
                self.assertIn("self_extension_smoke_child_result", payload)
            self.assertEqual(summary["self_extension"]["reason"], "self_extension_enabled_but_transport_unavailable")

    def test_wrapper_sets_pythonpath_for_child_orchestrator(self):
        env = {"PYTHONPATH": "existing"}
        _prepend_pythonpath(env, REPO_ROOT / "app")
        parts = env["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(parts[0], str(REPO_ROOT / "app"))
        self.assertIn("existing", parts)

    def test_source_snapshot_detects_prohibited_repair_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            repair = app / "tools" / "repair"
            audit = app / "tools" / "audit"
            repair.mkdir(parents=True)
            audit.mkdir(parents=True)
            (audit / "rule_repair_map.json").write_text("{}")
            before = source_snapshot(app, root / "workspace")
            (repair / "fix_embed_nonsymbolic_fonts.py").write_text("print('unsafe smoke mutation')\n")
            actions = source_mutation_actions(before, app, root / "workspace")
            self.assertEqual(actions[0]["action"], "source_repair_creation")
            self.assertEqual(actions[0]["path"], "app/tools/repair/fix_embed_nonsymbolic_fonts.py")


if __name__ == "__main__":
    unittest.main()
