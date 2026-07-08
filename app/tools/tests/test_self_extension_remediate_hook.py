#!/usr/bin/env python3
"""Regression checks for the guarded residual self-extension hook.

These tests intentionally do not import tools.orchestrate.remediate because
remediate.py is the pipeline entry point and parses CLI args / executes work at
import time. Patch 2 is a guarded wiring patch, so text-level contract checks
are the safest unit-level verification.
"""

from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[2]
REMEDIATE = APP / "tools" / "orchestrate" / "remediate.py"
SMOKE_BOUNDARY = APP / "tools" / "orchestrate" / "self_extension_smoke_boundary.py"
HERMES_SKILL = APP / "hermes_skills" / "pdf-remediation" / "SKILL.md"
V6_SKILL = APP / "skills" / "montefiore-pdfua-unified-v6" / "SKILL.md"
V6_RUNBOOK = APP / "skills" / "montefiore-pdfua-unified-v6" / "docs" / "RUNBOOK.md"


class ResidualSelfExtensionHookTests(unittest.TestCase):

    def test_remediate_defines_guarded_residual_hook(self):
        text = REMEDIATE.read_text()
        self.assertIn("def env_flag(name, default=False):", text)
        self.assertIn("def select_residual_self_extension_rule(", text)
        self.assertIn("def try_residual_self_extension_candidate(", text)
        self.assertIn('env_flag("HERMES_ENABLE_SELF_EXTENSION", False)', text)
        self.assertIn("from tools.orchestrate.self_extension_executor import", text)
        self.assertIn("run_residual_self_extension_attempts", text)
        self.assertIn("self_extension_run_attempts_result.json", text)
        self.assertIn("max_attempts", text)
        self.assertIn('"attempts": attempts', text)

    def test_residual_hook_runs_after_request_written_before_fallback_proposal(self):
        text = REMEDIATE.read_text()
        request_write = text.index("request_path.write_text(json.dumps(request_packet, indent=2))")
        hook_call = text.index("self_extension_record = try_residual_self_extension_candidate(")
        proposal = text.index('"result": "PENDING_AGENT_ACTION"', hook_call)
        self.assertLess(request_write, hook_call)
        self.assertLess(hook_call, proposal)

    def test_existing_hermes_required_fallback_is_preserved(self):
        text = REMEDIATE.read_text()
        hook_call = text.index("self_extension_record = try_residual_self_extension_candidate(")
        fallback_emit = text.index("emit_hermes_required(", hook_call)
        gap_record = text.index('"result": "HERMES_REQUIRED"', hook_call)
        self.assertLess(hook_call, fallback_emit)
        self.assertLess(hook_call, gap_record)
        self.assertIn('"self_extension": self_extension_record', text)

    def test_evidence_only_smoke_boundary_wrapper_and_runbook_policy_exist(self):
        smoke = SMOKE_BOUNDARY.read_text()
        self.assertIn("def surface_smoke_boundary(", smoke)
        self.assertIn("source_repair_creation_allowed", smoke)
        self.assertIn("rule_map_mutation_allowed", smoke)
        self.assertIn("adoption_allowed", smoke)
        self.assertIn("final_pdf_update_from_failed_candidate_allowed", smoke)
        self.assertIn("target_rule_check", smoke)
        self.assertIn("self_extension_enabled_but_target_rule_mismatch", smoke)
        self.assertIn("self_extension_enabled_but_unexpectedly_not_run", smoke)

        for path in (HERMES_SKILL, V6_SKILL, V6_RUNBOOK):
            text = path.read_text()
            self.assertIn("evidence-only self-extension smoke", text)
            self.assertIn("self_extension_smoke_boundary.py", text)
            self.assertIn("do not write", text)
            self.assertIn("do not register", text)
            self.assertIn("rule_repair_map.json", text)
            self.assertIn("do not adopt", text)
            self.assertIn("do not claim self-extension ran", text)


if __name__ == "__main__":
    unittest.main()
