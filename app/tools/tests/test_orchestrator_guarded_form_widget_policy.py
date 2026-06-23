#!/usr/bin/env python3
"""H10H/H10J policy tests for guarded form-widget orchestrator runtime status.

The orchestrator may now expose an explicit H10J guarded apply runtime and
validation evidence bundle behind --enable-guarded-form-widget-repair, but
default production readiness is still not claimed and acceptance/status/package
adoption remains blocked until the acceptance routing contract is integrated.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR = REPO_ROOT / "app" / "tools" / "orchestrate" / "remediate.py"
RULE_MAP = REPO_ROOT / "app" / "tools" / "audit" / "rule_repair_map.json"
STATUS_DOC = REPO_ROOT / "docs" / "PRODUCTION_REMEDIATION_STATUS.md"
H10H_DOC = REPO_ROOT / "docs" / "H10H_ORCHESTRATOR_GUARDED_FORM_WIDGET_RUNTIME.md"
TARGET_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"


class OrchestratorGuardedFormWidgetPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator_text = ORCHESTRATOR.read_text()
        self.status_text = STATUS_DOC.read_text()
        self.rule_map = json.loads(RULE_MAP.read_text())

    def test_h10h_terminal_state_is_blocked_not_integrated(self) -> None:
        self.assertIn("ORCHESTRATOR_RUNTIME_BLOCKED_BY_STATUS_PACKAGE_CONTRACT", self.status_text)
        self.assertIn("orchestrator guarded runtime implemented: false", self.status_text)
        self.assertIn("guarded runtime default-on: false", self.status_text)
        self.assertTrue(H10H_DOC.exists())

    def test_default_orchestrator_keeps_guarded_lookup_opt_in(self) -> None:
        self.assertIn("--enable-guarded-form-widget-repair", self.orchestrator_text)
        self.assertIn("if args.enable_guarded_form_widget_repair:", self.orchestrator_text)

        flag_branch = self.orchestrator_text.index("if args.enable_guarded_form_widget_repair:")
        self.assertGreater(self.orchestrator_text.index("--enable-guarded-candidates"), flag_branch)
        self.assertGreater(self.orchestrator_text.index("--precondition-report"), flag_branch)

    def test_orchestrator_runs_dedicated_guarded_apply_and_validation_but_not_acceptance_or_package(self) -> None:
        self.assertIn("repair_form_widget_structure.py", self.orchestrator_text)
        self.assertIn("guarded_form_widget_precondition_dry_run", self.orchestrator_text)

        self.assertIn("DETECTED_DEFERRED_TO_GUARDED_RUNTIME", self.orchestrator_text)
        self.assertIn("'normal_repair_loop_execution': False", self.orchestrator_text)
        self.assertIn("'guarded_runtime_execution': True", self.orchestrator_text)
        self.assertIn("guarded_form_widget_repair_apply", self.orchestrator_text)
        self.assertIn('"--apply"', self.orchestrator_text)

        self.assertIn("validate_guarded_form_widget_candidate", self.orchestrator_text)
        self.assertIn("verapdf_profile_accounting.py", self.orchestrator_text)
        self.assertIn("verapdf_iso_regression_review.py", self.orchestrator_text)
        self.assertIn("form_widget_structure_inspection.py", self.orchestrator_text)
        self.assertIn("preservation_audit.py", self.orchestrator_text)

        self.assertNotIn("guarded_form_widget_repair_runtime", self.orchestrator_text)
        self.assertNotIn("evaluate_guarded_acceptance", self.orchestrator_text)
        self.assertNotIn("package_routing(", self.orchestrator_text)
        self.assertIn("'final_pdf_adoption_performed': False", self.orchestrator_text)
        self.assertIn("'status_package_mutation_performed': False", self.orchestrator_text)
        self.assertIn('"acceptance_evaluation_performed": False', self.orchestrator_text)
        self.assertIn('"package_routing_performed": False', self.orchestrator_text)

    def test_active_rule_map_strategy_remains_unchanged(self) -> None:
        entry = self.rule_map.get("rules", {}).get(TARGET_RULE, {})
        self.assertEqual(entry.get("strategies"), [])
        self.assertNotIn(FORM_WIDGET_SCRIPT, json.dumps(entry.get("strategies", [])))
        guarded = entry.get("guarded_strategy_candidates", [])
        self.assertTrue(guarded)
        self.assertFalse(bool(guarded[0].get("runtime_active")))
        self.assertFalse(bool(guarded[0].get("production_default")))

    def test_acceptance_and_production_readiness_are_not_silently_claimed(self) -> None:
        self.assertNotIn("evaluate_guarded_acceptance", self.orchestrator_text)
        self.assertNotIn("build_orchestrator_outcome", self.orchestrator_text)
        self.assertNotIn("package_routing(", self.orchestrator_text)
        self.assertIn("profile accounting", self.status_text.lower())
        self.assertIn("iso no-regression", self.status_text.lower())
        self.assertIn("after-repair form-widget diagnostic", self.status_text.lower())

    def test_production_readiness_not_claimed(self) -> None:
        self.assertIn("Production readiness is not claimed", self.status_text)
        self.assertIn("WebUI production-path evidence collected: false", self.status_text)
        self.assertIn("STATUS/package behavior validated end-to-end: false", self.status_text)


if __name__ == "__main__":
    unittest.main()
