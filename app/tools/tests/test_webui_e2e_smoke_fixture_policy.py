#!/usr/bin/env python3
"""Policy tests for the WebUI E2E smoke fixture generator.

The WebUI smoke fixture must not recreate the Base-14 Helvetica blocker that
Patch E/E2 identified. The generator should create a local fixture with an
embedded open font and the repository font inventory should agree.
"""

from __future__ import annotations

import importlib.util
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
REPO_ROOT = APP_DIR.parent
SCRIPT = REPO_ROOT / "scripts" / "generate-webui-e2e-smoke-pdf.py"
FONT_INVENTORY = TOOLS_DIR / "audit" / "font_inventory.py"

HAS_FITZ = importlib.util.find_spec("fitz") is not None


@unittest.skipUnless(HAS_FITZ, "PyMuPDF/fitz is required for fixture generation tests")
class WebUIE2ESmokeFixturePolicyTests(unittest.TestCase):
    def test_generator_creates_fixture_without_unembedded_base14_font(self) -> None:
        with tempfile.TemporaryDirectory(prefix="webui_e2e_fixture_") as td:
            root = Path(td)
            pdf = root / "e2e-smoke.pdf"
            inventory_json = root / "font_inventory.json"
            env = {**os.environ, "PYTHONPATH": str(APP_DIR)}

            generated = subprocess.run(
                [sys.executable, str(SCRIPT), "--out", str(pdf)],
                capture_output=True,
                text=True,
                env=env,
            )
            if generated.returncode != 0 and "no usable .ttf or .otf" in generated.stdout:
                self.skipTest(generated.stdout)
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)

            generated_payload = json.loads(generated.stdout)
            self.assertEqual(generated_payload["result"], "PASS")
            self.assertTrue(pdf.is_file())
            self.assertTrue(Path(generated_payload["font_file"]).is_file())

            inventory = subprocess.run(
                [
                    sys.executable,
                    str(FONT_INVENTORY),
                    str(pdf),
                    "--out",
                    str(inventory_json),
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(inventory.returncode, 0, inventory.stderr + inventory.stdout)

            payload = json.loads(inventory_json.read_text())
            self.assertEqual(payload["result"], "PASS")
            self.assertGreaterEqual(payload["font_count"], 1)
            self.assertFalse(
                any(
                    font["basefont"] == "Helvetica" and font["embedded"] is False
                    for font in payload["fonts"]
                ),
                payload,
            )
            self.assertTrue(all(font["embedded"] for font in payload["fonts"]), payload)
            self.assertEqual(payload["issues"], [])


if __name__ == "__main__":
    unittest.main()
