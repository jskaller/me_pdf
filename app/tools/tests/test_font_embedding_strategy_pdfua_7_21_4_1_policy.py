#!/usr/bin/env python3
"""Policy tests for PDF/UA-1/7.21.4.1 font embedding gap.

Patch E deliberately does not add a fake repair mapping for unembedded Base-14
fonts. Until a deterministic font embedding/substitution script is validated
with veraPDF and preservation evidence, this rule must remain actionable through
HERMES_REQUIRED rather than being silently ignored or mapped to an unrelated
font repair.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEST_FILE = Path(__file__).resolve()
TOOLS_DIR = TEST_FILE.parents[1]
APP_DIR = TOOLS_DIR.parent
AUDIT_DIR = TOOLS_DIR / "audit"
RULE_ID = "PDF/UA-1/7.21.4.1"


def minimal_verapdf_summary(rule_id: str = RULE_ID) -> dict:
    return {
        "result": "FAIL",
        "total_failures": 1,
        "failures_by_rule": [
            {
                "rule_id": rule_id,
                "description": "The font program is not embedded",
                "failures": 1,
                "objects": [
                    {
                        "context": "PDFont",
                        "font": "Helvetica",
                    }
                ],
            }
        ],
    }


class FontEmbeddingStrategyPdfua72141PolicyTests(unittest.TestCase):
    def run_lookup(self, summary_path: Path, map_path: Path) -> dict:
        proc = subprocess.run(
            [
                sys.executable,
                str(AUDIT_DIR / "lookup_repair_plan.py"),
                str(summary_path),
                "--map",
                str(map_path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(APP_DIR)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def test_unmapped_72141_is_actionable_hermes_required_not_silent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="font_embed_gap_") as td:
            root = Path(td)
            summary_path = root / "summary.json"
            map_path = root / "rule_repair_map.json"
            summary_path.write_text(json.dumps(minimal_verapdf_summary(), indent=2))
            map_path.write_text(json.dumps({"rules": {}}, indent=2))

            plan = self.run_lookup(summary_path, map_path)

            self.assertEqual(plan["result"], "ALL_MANUAL")
            self.assertEqual(plan["repair_steps"], [])
            self.assertEqual(plan["unknown_rules"][0]["rule_id"], RULE_ID)
            self.assertEqual(plan["unknown_rules"][0]["reason"], "unknown_rule")
            self.assertEqual(plan["hermes_required"][0]["rule_id"], RULE_ID)
            self.assertEqual(plan["hermes_required"][0]["reason"], "unknown_rule")

    def test_manual_72141_mapping_without_strategy_stays_hermes_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="font_embed_manual_") as td:
            root = Path(td)
            summary_path = root / "summary.json"
            map_path = root / "rule_repair_map.json"
            summary_path.write_text(json.dumps(minimal_verapdf_summary(), indent=2))
            map_path.write_text(json.dumps({
                "rules": {
                    RULE_ID: {
                        "clause": "7.21.4.1",
                        "description": "Font program is not embedded",
                        "manual": True,
                        "strategies": [],
                        "resolvability": "repairable_unbuilt",
                        "emits_review_artifact": True,
                    }
                }
            }, indent=2))

            plan = self.run_lookup(summary_path, map_path)

            self.assertEqual(plan["result"], "ALL_MANUAL")
            self.assertEqual(plan["repair_steps"], [])
            self.assertEqual(plan["unknown_rules"], [])
            self.assertEqual(plan["hermes_required"][0]["rule_id"], RULE_ID)
            self.assertEqual(plan["hermes_required"][0]["reason"], "manual_no_strategies")


if __name__ == "__main__":
    unittest.main()
