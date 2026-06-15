#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.orchestrate import self_extension


class SelfExtensionSupportTests(unittest.TestCase):
    def test_rule_slug_is_stable_and_collision_resistant(self):
        dotted = self_extension.canonical_rule_slug("PDF/UA-1/7.1")
        underscored = self_extension.canonical_rule_slug("PDF_UA_1_7_1")

        self.assertTrue(dotted.startswith("pdf_ua_1_7_1_"))
        self.assertTrue(underscored.startswith("pdf_ua_1_7_1_"))
        self.assertNotEqual(dotted, underscored)

    def test_generated_paths_stay_quarantined(self):
        relpath = self_extension.generated_repair_script_relpath(
            "PDF/UA-1/7.1",
            attempt=2,
        )

        self.assertTrue(relpath.startswith("tools/repair/generated/"))
        self.assertTrue(relpath.endswith("_attempt_02.py"))

    def test_disabled_gateway_probe_is_side_effect_free_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "probe.json"
            with patch.dict(os.environ, {"HERMES_SELF_EXTENSION_ALLOW_GATEWAY": "0"}):
                result = self_extension.run_gateway_probe(out_path=out_path)

            self.assertEqual(result["result"], "SKIPPED")
            self.assertEqual(
                result["reason"],
                "HERMES_SELF_EXTENSION_ALLOW_GATEWAY is not enabled",
            )
            self.assertTrue(out_path.exists())

    def test_gateway_env_file_fills_missing_process_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "API_SERVER_KEY=file-token",
                        "API_SERVER_PORT=9999",
                        'API_SERVER_MODEL_NAME="Hermes Agent"',
                    ]
                )
            )
            with patch.dict(os.environ, {}, clear=True):
                cfg = self_extension.SelfExtensionConfig.from_env(env_path)

            self.assertEqual(cfg.gateway_api_key, "file-token")
            self.assertEqual(cfg.gateway_base_url, "http://127.0.0.1:9999/v1")
            self.assertEqual(cfg.gateway_model, "Hermes Agent")


if __name__ == "__main__":
    unittest.main()
