#!/usr/bin/env python3
"""H10J opt-in flag, precondition generation, and guarded lookup policy.

Current scope wires guarded lookup only behind --enable-guarded-form-widget-repair.
It must still not execute the guarded repair or route guarded acceptance/status
packages.
"""
from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR = REPO_ROOT / "app" / "tools" / "orchestrate" / "remediate.py"


class H10JGuardedRuntimeFlagPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = ORCHESTRATOR.read_text()

    def test_h10j_flag_exists(self) -> None:
        self.assertIn("--enable-guarded-form-widget-repair", self.text)
        self.assertIn("action='store_true'", self.text)

    def test_h10j_constants_exist(self) -> None:
        self.assertIn('GUARDED_FORM_WIDGET_RULE = "PDF/UA-1/7.18.4"', self.text)
        self.assertIn('GUARDED_FORM_WIDGET_SCRIPT = "tools/repair/repair_form_widget_structure.py"', self.text)
        self.assertIn('GUARDED_FORM_WIDGET_STRATEGY_ID = "form_widget_structure_construction_v1"', self.text)
        self.assertIn('GUARDED_FORM_WIDGET_REPAIR_VERSION = "1.4.0"', self.text)

    def test_safe_intermediate_candidate_paths_are_named(self) -> None:
        self.assertIn("def guarded_form_widget_paths", self.text)
        self.assertIn('"guarded_candidates"', self.text)
        self.assertIn('"form_widget_structure"', self.text)
        self.assertIn('"output.pdf"', self.text)
        self.assertIn('"guarded_acceptance.json"', self.text)
        self.assertIn('"guarded_form_widget_acceptance_evidence.json"', self.text)

    def test_precondition_helpers_and_generator_exist(self) -> None:
        for required in [
            "def write_guarded_json",
            "def guarded_result_value",
            "def guarded_rule_failure_counts",
            "def guarded_new_or_increased_failures",
            "def guarded_build_precondition_report",
            "def generate_guarded_form_widget_precondition",
            "READY_FOR_GUARDED_RUNTIME",
            "explicit_safe_intermediate_required",
            "guarded_form_widget_precondition_dry_run",
            "precondition_dry_run_exit_code",
        ]:
            self.assertIn(required, self.text)

    def test_guarded_lookup_is_explicitly_opt_in(self) -> None:
        self.assertIn("if args.enable_guarded_form_widget_repair:", self.text)
        flag_branch = self.text.index("if args.enable_guarded_form_widget_repair:")
        self.assertGreater(self.text.index("generate_guarded_form_widget_precondition(PASS0)"), flag_branch)
        self.assertGreater(self.text.index("'--enable-guarded-candidates'"), flag_branch)
        self.assertGreater(self.text.index("'--precondition-report'"), flag_branch)

    def test_patch_1e_does_not_execute_guarded_repair_or_acceptance(self) -> None:
        self.assertNotIn("execute_guarded_form_widget_runtime", self.text)
        self.assertNotIn("guarded_form_widget_repair_apply", self.text)
        self.assertNotIn("guarded_form_widget_repair_runtime", self.text)
        self.assertNotIn("\'--apply\'", self.text)
        self.assertNotIn("\"--apply\"", self.text)
        self.assertNotIn("evaluate_guarded_acceptance", self.text)
        self.assertNotIn("build_orchestrator_outcome", self.text)
        self.assertNotIn("package_routing", self.text)


if __name__ == "__main__":
    unittest.main()
