#!/usr/bin/env python3
"""Text-level integration checks for Patch 2 orchestrator wiring."""

from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[2]
REMEDIATE = APP / "tools" / "orchestrate" / "remediate.py"


class ResidualAnalysisRemediateHookTests(unittest.TestCase):
    def test_remediate_imports_residual_and_execution_helpers(self):
        text = REMEDIATE.read_text()
        self.assertIn("from tools.audit.execution_log import", text)
        self.assertIn("from tools.audit.residual_analysis import", text)
        self.assertIn("build_execution_log_from_repair_steps", text)
        self.assertIn("analyze_residuals", text)
        self.assertIn("targetable_failures_from_analysis", text)

    def test_remediate_writes_execution_log_and_residual_analysis(self):
        text = REMEDIATE.read_text()
        self.assertIn("execution_log_path = AUDIT_DIR / 'execution_log.json'", text)
        self.assertIn("residual_analysis_path = AUDIT_DIR / 'residual_analysis.json'", text)
        self.assertIn("write_execution_log(", text)
        self.assertIn("analyze_residuals(", text)

    def test_residual_analysis_happens_after_failures_post(self):
        text = REMEDIATE.read_text()
        post = text.index("post_failures_path = AUDIT_DIR / 'failures_post.json'")
        residual = text.index("residual_analysis_path = AUDIT_DIR / 'residual_analysis.json'", post)
        self.assertLess(post, residual)

    def test_strategy_gap_prefers_targetable_residuals_with_fallback(self):
        text = REMEDIATE.read_text()
        self.assertIn("targetable_remaining_failures", text)
        self.assertIn("self_extension_failures", text)
        self.assertIn("targetable_remaining_failures if residual_analysis else remaining_failures", text)


if __name__ == "__main__":
    unittest.main()
