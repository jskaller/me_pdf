#!/usr/bin/env python3
"""H10J guarded runtime flag, lookup, quarantine, and apply policy.

Current scope allows a dedicated guarded apply runtime only behind
--enable-guarded-form-widget-repair and only after guarded lookup emits the
target step. It must still not accept, promote, package, or mutate status.
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

    def test_guarded_lookup_step_is_deferred_from_normal_repair_loop(self) -> None:
        self.assertIn("def is_guarded_form_widget_step", self.text)
        self.assertIn("def guarded_form_widget_step_from_plan", self.text)
        self.assertIn("guarded_form_widget_step = guarded_form_widget_step_from_plan(plan_data)", self.text)
        self.assertIn("DETECTED_DEFERRED_TO_GUARDED_RUNTIME", self.text)
        self.assertIn("'normal_repair_loop_execution': False", self.text)
        self.assertIn("if not is_guarded_form_widget_step(step)", self.text)

    def test_guarded_runtime_apply_is_dedicated_and_opt_in(self) -> None:
        self.assertIn("def execute_guarded_form_widget_runtime", self.text)
        self.assertIn("guarded_form_widget_apply_report = execute_guarded_form_widget_runtime(", self.text)
        self.assertIn("'guarded_form_widget_repair_apply'", self.text)
        self.assertIn('"--apply"', self.text)
        self.assertIn('"--allow-structure-construction-trial"', self.text)
        self.assertIn('"--max-widgets"', self.text)
        self.assertIn('"--output"', self.text)
        self.assertIn('paths["candidate_pdf"]', self.text)
        self.assertIn('"guarded_candidates"', self.text)
        self.assertIn('"status_package_mutation_performed"] = False', self.text)
        self.assertIn('"final_pdf_adoption_performed"] = False', self.text)

    def test_patch_3_does_not_accept_promote_status_or_package_candidate(self) -> None:
        self.assertNotIn("evaluate_guarded_acceptance", self.text)
        self.assertNotIn("build_orchestrator_outcome", self.text)
        self.assertNotIn("package_routing", self.text)
        self.assertNotIn('FINAL_PDF = paths["candidate_pdf"]', self.text)
        self.assertNotIn("FINAL_PDF = guarded_form_widget_apply_report", self.text)
        self.assertIn("'final_pdf_adoption_performed': False", self.text)
        self.assertIn("'status_package_mutation_performed': False", self.text)


if __name__ == "__main__":
    unittest.main()
