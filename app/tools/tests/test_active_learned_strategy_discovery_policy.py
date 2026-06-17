import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_discovery import discover_active_learned_strategies


RULE_ID = "PDF/UA-1/7.21.7"
OTHER_RULE_ID = "PDF/UA-1/7.18.4"


class ActiveLearnedStrategyDiscoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.rule_map = self.repo / "app/tools/audit/rule_repair_map.json"
        self.staging = self.repo / "app/tools/repair_staging/learned"
        self.audit_dir = self.repo / "workspace/jobs/TEST/audit"
        self.staging.mkdir(parents=True)
        self.rule_map.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_script(self, name="safe.py", text="def repair(*args, **kwargs):\n    return {'result': 'NOOP'}\n"):
        path = self.staging / name
        path.write_text(text)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def write_map(self, learned_entries=None, extra_rules=None):
        rules = {
            RULE_ID: {
                "description": "test rule",
                "strategies": [
                    {"strategy": "builtin", "repair_script": "tools/repair/fix_notdef_glyphs.py"}
                ],
                "reviewed_learned_strategies": learned_entries or [],
            }
        }
        if extra_rules:
            rules.update(extra_rules)
        self.rule_map.write_text(json.dumps({"rules": rules}, indent=2))

    def active_entry(self, **overrides):
        script, sha = self.write_script()
        entry = {
            "candidate_id": "candidate-active",
            "strategy_id": "strategy-active",
            "source": "learned_strategy_staged",
            "production_active": True,
            "activation_status": "active",
            "staged_script_path": "app/tools/repair_staging/learned/safe.py",
            "staged_script_sha256": sha,
            "execution_order": 99,
        }
        entry.update(overrides)
        return entry

    def discover(self, rule_ids=None, audit_dir=None):
        return discover_active_learned_strategies(
            self.rule_map,
            rule_ids=rule_ids,
            repo_root=self.repo,
            audit_dir=audit_dir,
        )

    def reasons(self, result):
        return [reason for item in result["ignored_strategies"] for reason in item.get("reason", [])]

    def test_no_active_learned_strategies_returns_empty_discovery_and_no_mutation(self):
        self.write_map([])
        before = self.rule_map.read_text()
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertEqual([], result["ignored_strategies"])
        self.assertFalse(result["execution_performed"])
        self.assertEqual(before, self.rule_map.read_text())

    def test_inactive_staged_strategy_ignored(self):
        self.write_map([self.active_entry(production_active=False)])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("not_production_active", self.reasons(result))

    def test_deactivated_strategy_ignored(self):
        self.write_map([self.active_entry(activation_status="deactivated")])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("deactivated", self.reasons(result))

    def test_active_hash_valid_static_safe_strategy_discovered(self):
        self.write_map([self.active_entry()])
        result = self.discover()
        self.assertEqual(1, len(result["discovered_strategies"]))
        candidate = result["discovered_strategies"][0]
        self.assertEqual(RULE_ID, candidate["rule_id"])
        self.assertTrue(candidate["runtime_eligible"])
        self.assertTrue(candidate["hash_verified"])
        self.assertTrue(candidate["static_checks"]["passed"])
        self.assertFalse(candidate["execution_performed"])
        self.assertTrue(candidate["run_after_builtin_strategies"])

    def test_missing_staged_script_ignored_without_exception(self):
        self.write_map([self.active_entry(staged_script_path="app/tools/repair_staging/learned/missing.py")])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("staged_script_missing", self.reasons(result))

    def test_hash_mismatch_ignored_without_execution(self):
        self.write_map([self.active_entry(staged_script_sha256="0" * 64)])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("staged_script_hash_mismatch", self.reasons(result))
        self.assertFalse(result["execution_performed"])

    def test_unsafe_static_script_ignored_without_execution(self):
        script, sha = self.write_script("unsafe.py", "import subprocess\ndef repair():\n    return None\n")
        self.write_map([
            self.active_entry(
                staged_script_path="app/tools/repair_staging/learned/unsafe.py",
                staged_script_sha256=sha,
            )
        ])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("static_checks_failed", self.reasons(result))
        self.assertTrue(any(r.startswith("dangerous_import") for r in self.reasons(result)))

    def test_quarantine_path_rejected(self):
        self.write_map([
            self.active_entry(
                staged_script_path="workspace/jobs/TEST/audit/self_extension/quarantine/generated.py"
            )
        ])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("staged_script_path_references_job_quarantine", self.reasons(result))

    def test_absolute_outside_repo_path_rejected(self):
        self.write_map([self.active_entry(staged_script_path="/tmp/outside_learned.py")])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("absolute_staged_script_path_outside_repo", self.reasons(result))

    def test_non_learned_or_builtin_strategies_are_not_included(self):
        self.write_map([self.active_entry(source="builtin")])
        result = self.discover()
        self.assertEqual([], result["discovered_strategies"])
        self.assertIn("source_not_learned_strategy_staged", self.reasons(result))

    def test_dirty_failed_refusal_markers_ignored(self):
        self.write_map([self.active_entry(dirty=True, semantic_refusal=True, promotion_blockers=["dirty_record"])])
        result = self.discover()
        reasons = self.reasons(result)
        self.assertIn("marker_dirty_true", reasons)
        self.assertIn("marker_semantic_refusal_true", reasons)
        self.assertIn("promotion_blockers_present", reasons)

    def test_rule_id_filter_only_evaluates_requested_rules(self):
        other_entry = self.active_entry(candidate_id="candidate-other")
        self.write_map(
            [self.active_entry(production_active=False)],
            extra_rules={OTHER_RULE_ID: {"reviewed_learned_strategies": [other_entry], "strategies": []}},
        )
        result = self.discover(rule_ids=[OTHER_RULE_ID])
        self.assertEqual(1, len(result["discovered_strategies"]))
        self.assertEqual(OTHER_RULE_ID, result["discovered_strategies"][0]["rule_id"])
        self.assertEqual([], result["ignored_strategies"])

    def test_audit_artifact_written_with_no_execution_policy_flags(self):
        self.write_map([self.active_entry()])
        result = self.discover(audit_dir=self.audit_dir)
        artifact = self.audit_dir / "learned_strategy_discovery.json"
        self.assertTrue(artifact.exists())
        data = json.loads(artifact.read_text())
        self.assertEqual(result["schema_version"], data["schema_version"])
        self.assertFalse(data["execution_performed"])
        self.assertFalse(data["final_pdf_adoption_performed"])
        self.assertFalse(data["rule_map_mutation_performed"])
        self.assertFalse(data["app_tools_repair_mutation_performed"])
        self.assertFalse(data["policy"]["production_execution_enabled_by_patch_12a"])

    def test_cli_exits_zero_and_writes_json_for_empty_discovery(self):
        self.write_map([])
        module = self.repo / "app/tools/audit/learned_strategy_discovery.py"
        source_module = Path(__file__).parents[1] / "audit" / "learned_strategy_discovery.py"
        module.write_text(source_module.read_text())
        cmd = [
            sys.executable,
            str(module),
            "--rule-map",
            str(self.rule_map),
            "--repo-root",
            str(self.repo),
            "--audit-dir",
            str(self.audit_dir),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual([], payload["discovered_strategies"])
        self.assertTrue((self.audit_dir / "learned_strategy_discovery.json").exists())


if __name__ == "__main__":
    unittest.main()
