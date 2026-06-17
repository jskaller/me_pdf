import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.audit.learned_strategy_verapdf_delta import (
    compute_verapdf_delta,
    parse_verapdf_failures,
    run_verapdf_delta_for_trial,
    resolve_verapdf_runner,
)


VERAPDF_XML_ONE = """<?xml version='1.0'?><report><rule status='failed' clause='7.21.7' testNumber='1' failedChecks='2'/></report>"""
VERAPDF_XML_TWO = """<?xml version='1.0'?><report><rule status='failed' clause='7.21.7' testNumber='1' failedChecks='3'/><rule status='failed' clause='7.18.4' failedChecks='1'/></report>"""


class _Completed:
    def __init__(self, stdout, stderr="", returncode=1):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class LearnedStrategyVeraPDFDeltaPolicyTests(unittest.TestCase):
    def make_trial(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        trial_dir = root / "audit" / "learned_strategy_replacement_trial" / "c1"
        trial_dir.mkdir(parents=True)
        normal = trial_dir / "normal_final.pdf"
        learned = trial_dir / "learned_trial.pdf"
        normal.write_bytes(b"%PDF-1.7\nnormal")
        learned.write_bytes(b"%PDF-1.7\nlearned")
        return tmp, trial_dir, normal, learned

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": False, "readiness_blocker": "verapdf_runner_unavailable", "checked": []})
    def test_verapdf_unavailable_maps_to_skipped(self, _which):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "SKIPPED")
        self.assertEqual(payload["readiness_blocker"], "verapdf_runner_unavailable")
        self.assertTrue((trial_dir / "verapdf_delta.json").exists())

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []})
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_verapdf_timeout_maps_to_error(self, run, _which):
        import subprocess
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.side_effect = subprocess.TimeoutExpired(["verapdf"], 1)
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir, timeout_seconds=1)
        self.assertEqual(payload["result"], "ERROR")
        self.assertEqual(payload["readiness_blocker"], "verapdf_delta_timeout")

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []})
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_parse_failure_maps_to_error(self, run, _which):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.return_value = _Completed("not xml", returncode=0)
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "ERROR")
        self.assertEqual(payload["readiness_blocker"], "verapdf_delta_parse_failed")

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []})
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_same_failures_maps_to_pass(self, run, _which):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.side_effect = [_Completed(VERAPDF_XML_ONE, returncode=1), _Completed(VERAPDF_XML_ONE, returncode=1)]
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["introduced_failure_count"], 0)
        self.assertIsNone(payload["readiness_blocker"])
        self.assertTrue((trial_dir / "verapdf_normal_final.xml").exists())
        self.assertTrue((trial_dir / "verapdf_learned_trial.xml").exists())

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []})
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_introduced_rule_maps_to_fail(self, run, _which):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.side_effect = [_Completed(VERAPDF_XML_ONE, returncode=1), _Completed(VERAPDF_XML_TWO, returncode=1)]
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "FAIL")
        self.assertEqual(payload["readiness_blocker"], "verapdf_delta_regression_detected")
        self.assertIn("PDF/UA-1/7.18.4", payload["introduced_rules"])

    def test_worsened_count_maps_to_fail_delta(self):
        normal = parse_verapdf_failures(VERAPDF_XML_ONE)
        learned = parse_verapdf_failures("""<report><rule status='failed' clause='7.21.7' failedChecks='5'/></report>""")
        delta = compute_verapdf_delta(normal, learned)
        self.assertEqual(delta["worsened_rules"], ["PDF/UA-1/7.21.7"])
        self.assertEqual(delta["worsened_failure_count"], 3)

    def test_resolved_rule_pass_with_improvement_evidence(self):
        normal = parse_verapdf_failures(VERAPDF_XML_TWO)
        learned = parse_verapdf_failures(VERAPDF_XML_ONE)
        delta = compute_verapdf_delta(normal, learned)
        self.assertIn("PDF/UA-1/7.18.4", delta["resolved_rules"])
        self.assertIn("PDF/UA-1/7.21.7", delta["improved_rules"])
        self.assertFalse(delta["introduced_rules"])
        self.assertFalse(delta["worsened_rules"])

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner", return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []})
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_verapdf_nonzero_validation_result_is_evidence_not_command_failure(self, run, _which):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.side_effect = [_Completed(VERAPDF_XML_ONE, returncode=1), _Completed(VERAPDF_XML_ONE, returncode=1)]
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["normal_failure_count"], 2)
        self.assertEqual(payload["learned_failure_count"], 2)


if __name__ == "__main__":
    unittest.main()


class Patch18B0VeraPDFRunnerDiscoveryTests(unittest.TestCase):
    def make_trial(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        trial_dir = root / "trial"
        trial_dir.mkdir(parents=True, exist_ok=True)

        normal = root / "normal.pdf"
        learned = root / "learned.pdf"
        normal.write_bytes(b"%PDF-1.7\n% normal test fixture\n")
        learned.write_bytes(b"%PDF-1.7\n% learned test fixture\n")

        return tmp, trial_dir, normal, learned

    def make_executable(self, root: Path, name: str = "verapdf") -> Path:
        exe = root / name
        exe.write_text("#!/bin/sh\necho '<report></report>'\n", encoding="utf-8")
        exe.chmod(0o755)
        return exe

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.shutil.which", return_value=None)
    def test_resolver_uses_greenfield_env_when_executable(self, _which):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = self.make_executable(root)
            with mock.patch("tools.audit.learned_strategy_verapdf_delta.S6_ENV_DIR", root / "missing"), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.FALLBACK_VERAPDF_PATHS", ()): 
                payload = resolve_verapdf_runner({"VERAPDF_GREENFIELD_BIN": str(exe)})
            self.assertTrue(payload["available"])
            self.assertEqual(payload["runner_path"], str(exe))
            self.assertEqual(payload["runner_source"], "VERAPDF_GREENFIELD_BIN")

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.shutil.which", return_value=None)
    def test_resolver_uses_s6_greenfield_when_env_absent(self, _which):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = self.make_executable(root)
            s6 = root / "s6"
            s6.mkdir()
            (s6 / "VERAPDF_GREENFIELD_BIN").write_text(str(exe), encoding="utf-8")
            with mock.patch("tools.audit.learned_strategy_verapdf_delta.S6_ENV_DIR", s6), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.FALLBACK_VERAPDF_PATHS", ()): 
                payload = resolve_verapdf_runner({})
            self.assertTrue(payload["available"])
            self.assertEqual(payload["runner_source"], "s6:VERAPDF_GREENFIELD_BIN")

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.shutil.which", return_value=None)
    def test_resolver_falls_back_to_greenfield_path_when_executable(self, _which):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = self.make_executable(root)
            with mock.patch("tools.audit.learned_strategy_verapdf_delta.S6_ENV_DIR", root / "missing"), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.FALLBACK_VERAPDF_PATHS", (exe,)): 
                payload = resolve_verapdf_runner({})
            self.assertTrue(payload["available"])
            self.assertEqual(payload["runner_path"], str(exe))
            self.assertTrue(str(payload["runner_source"]).startswith("fallback:"))

    def test_resolver_falls_back_to_path_lookup_when_path_has_verapdf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = self.make_executable(root)
            with mock.patch("tools.audit.learned_strategy_verapdf_delta.S6_ENV_DIR", root / "missing"), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.FALLBACK_VERAPDF_PATHS", ()), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.shutil.which", return_value=str(exe)):
                payload = resolve_verapdf_runner({})
            self.assertTrue(payload["available"])
            self.assertEqual(payload["runner_source"], "PATH:verapdf")

    @mock.patch("tools.audit.learned_strategy_verapdf_delta.shutil.which", return_value=None)
    def test_resolver_unavailable_returns_checked_diagnostics(self, _which):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch("tools.audit.learned_strategy_verapdf_delta.S6_ENV_DIR", root / "missing"), \
                 mock.patch("tools.audit.learned_strategy_verapdf_delta.FALLBACK_VERAPDF_PATHS", ()): 
                payload = resolve_verapdf_runner({})
            self.assertFalse(payload["available"])
            self.assertEqual(payload["readiness_blocker"], "verapdf_runner_unavailable")
            self.assertGreaterEqual(len(payload["checked"]), 6)

    @mock.patch(
        "tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner",
        return_value={
            "available": False,
            "readiness_blocker": "verapdf_runner_unavailable",
            "checked": [{"source": "PATH:verapdf", "value": None, "exists": False, "is_file": False, "executable": False}],
        },
    )
    def test_skipped_delta_writes_runner_discovery_artifact(self, _resolver):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        discovery = trial_dir / "verapdf_runner_discovery.json"
        self.assertTrue(discovery.exists())
        self.assertEqual(payload["readiness_blocker"], "verapdf_runner_unavailable")
        self.assertEqual(payload["runner_discovery_artifact"], str(discovery))

    @mock.patch(
        "tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner",
        return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []},
    )
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_missing_verapdf_output_maps_to_output_missing(self, run, _resolver):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.return_value = _Completed("", stderr="", returncode=2)
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "ERROR")
        self.assertEqual(payload["readiness_blocker"], "verapdf_output_missing")

    @mock.patch(
        "tools.audit.learned_strategy_verapdf_delta.resolve_verapdf_runner",
        return_value={"available": True, "runner_path": "verapdf", "runner_source": "test", "checked": []},
    )
    @mock.patch("tools.audit.learned_strategy_verapdf_delta.subprocess.run")
    def test_process_start_failure_maps_to_process_failed(self, run, _resolver):
        tmp, trial_dir, normal, learned = self.make_trial()
        self.addCleanup(tmp.cleanup)
        run.side_effect = OSError("cannot exec")
        payload = run_verapdf_delta_for_trial(normal, learned, trial_dir)
        self.assertEqual(payload["result"], "ERROR")
        self.assertEqual(payload["readiness_blocker"], "verapdf_process_failed")
