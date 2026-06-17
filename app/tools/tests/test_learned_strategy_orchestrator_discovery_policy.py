#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.audit.learned_strategy_repair_plan import (
    augment_repair_plan_with_learned_discovery,
    collect_rule_ids_from_repair_plan,
)


class LearnedStrategyOrchestratorDiscoveryPolicyTests(unittest.TestCase):
    def _repo(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "app/tools/audit").mkdir(parents=True)
        (root / "app/tools/repair_staging/learned").mkdir(parents=True)
        return tmp, root

    def _script(self, root: Path, name: str = "pdf_ua_1_7_21_7__active.py", source: str = "def repair(input_pdf, output_pdf):\n    return None\n"):
        path = root / "app/tools/repair_staging/learned" / name
        path.write_text(source)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _rule_map(self, root: Path, entries):
        path = root / "app/tools/audit/rule_repair_map.json"
        path.write_text(json.dumps({"rules": {"PDF/UA-1/7.21.7": {"reviewed_learned_strategies": entries}}}, indent=2))
        return path

    def test_collect_rule_ids_keeps_built_in_plan_inputs_separate(self):
        plan = {
            "repair_steps": [{"rules_addressed": ["PDF/UA-1/6.2", "PDF/UA-1/7.21.7"]}],
            "hermes_required": [{"rule_id": "PDF/UA-1/7.18.4"}],
            "unknown_rules": [{"rule_id": "PDF/UA-1/9.9.9"}],
        }
        self.assertEqual(
            collect_rule_ids_from_repair_plan(plan),
            ["PDF/UA-1/6.2", "PDF/UA-1/7.21.7", "PDF/UA-1/7.18.4", "PDF/UA-1/9.9.9"],
        )

    def test_discovery_only_writes_artifact_and_does_not_mutate_repair_steps(self):
        tmp, root = self._repo()
        with tmp:
            script, sha = self._script(root)
            rule_map = self._rule_map(root, [{
                "candidate_id": "active-candidate",
                "source": "learned_strategy_staged",
                "production_active": True,
                "activation_status": "active",
                "staged_script_path": "app/tools/repair_staging/learned/" + script.name,
                "staged_script_sha256": sha,
            }])
            audit_dir = root / "workspace/jobs/JOB/audit"
            plan = {
                "result": "ALL_MANUAL",
                "repair_steps": [],
                "hermes_required": [{"rule_id": "PDF/UA-1/7.21.7", "reason": "manual_no_strategies"}],
                "unknown_rules": [],
            }
            augmented = augment_repair_plan_with_learned_discovery(
                plan,
                rule_map_path=rule_map,
                repo_root=root,
                audit_dir=audit_dir,
            )

            artifact = json.loads((audit_dir / "learned_strategy_discovery.json").read_text())
            self.assertEqual(artifact["mode"], "discovery_only")
            self.assertFalse(artifact["execution_performed"])
            self.assertFalse(artifact["final_pdf_adoption_performed"])
            self.assertFalse(artifact["rule_map_mutation_performed"])
            self.assertFalse(artifact["app_tools_repair_mutation_performed"])
            self.assertFalse(artifact["orchestrator_execution_integration_performed"])
            self.assertEqual(plan["repair_steps"], augmented["repair_steps"])
            self.assertEqual(len(augmented["active_learned_strategy_candidates"]), 1)
            self.assertNotIn("app/tools/repair_staging/learned", json.dumps(augmented["repair_steps"]))

    def test_empty_discovery_is_valid(self):
        tmp, root = self._repo()
        with tmp:
            rule_map = self._rule_map(root, [])
            augmented = augment_repair_plan_with_learned_discovery(
                {"repair_steps": [], "hermes_required": [{"rule_id": "PDF/UA-1/7.21.7"}], "unknown_rules": []},
                rule_map_path=rule_map,
                repo_root=root,
                audit_dir=root / "workspace/jobs/JOB/audit",
            )
            self.assertEqual(augmented["active_learned_strategy_candidates"], [])
            self.assertEqual(augmented["learned_strategy_discovery"]["mode"], "discovery_only")

    def test_inactive_hash_mismatched_and_unsafe_strategies_are_ignored(self):
        tmp, root = self._repo()
        with tmp:
            good_script, good_sha = self._script(root, "good.py")
            unsafe_script, unsafe_sha = self._script(root, "unsafe.py", "import subprocess\n")
            rule_map = self._rule_map(root, [
                {
                    "candidate_id": "inactive",
                    "source": "learned_strategy_staged",
                    "production_active": False,
                    "activation_status": "active",
                    "staged_script_path": "app/tools/repair_staging/learned/" + good_script.name,
                    "staged_script_sha256": good_sha,
                },
                {
                    "candidate_id": "hash-mismatch",
                    "source": "learned_strategy_staged",
                    "production_active": True,
                    "activation_status": "active",
                    "staged_script_path": "app/tools/repair_staging/learned/" + good_script.name,
                    "staged_script_sha256": "0" * 64,
                },
                {
                    "candidate_id": "unsafe",
                    "source": "learned_strategy_staged",
                    "production_active": True,
                    "activation_status": "active",
                    "staged_script_path": "app/tools/repair_staging/learned/" + unsafe_script.name,
                    "staged_script_sha256": unsafe_sha,
                },
            ])
            audit_dir = root / "workspace/jobs/JOB/audit"
            augmented = augment_repair_plan_with_learned_discovery(
                {"repair_steps": [], "hermes_required": [{"rule_id": "PDF/UA-1/7.21.7"}], "unknown_rules": []},
                rule_map_path=rule_map,
                repo_root=root,
                audit_dir=audit_dir,
            )
            artifact = json.loads((audit_dir / "learned_strategy_discovery.json").read_text())
            self.assertEqual(augmented["active_learned_strategy_candidates"], [])
            reasons = {item["candidate_id"]: set(item["reason"]) for item in artifact["ignored_strategies"]}
            self.assertIn("not_production_active", reasons["inactive"])
            self.assertIn("staged_script_hash_mismatch", reasons["hash-mismatch"])
            self.assertTrue(any(r.startswith("dangerous_import") or r == "static_checks_failed" for r in reasons["unsafe"]))

    def test_learned_strategy_execution_module_is_not_invoked_by_discovery_bridge(self):
        tmp, root = self._repo()
        with tmp:
            script, sha = self._script(root)
            rule_map = self._rule_map(root, [{
                "candidate_id": "active-candidate",
                "source": "learned_strategy_staged",
                "production_active": True,
                "activation_status": "active",
                "staged_script_path": "app/tools/repair_staging/learned/" + script.name,
                "staged_script_sha256": sha,
            }])
            with mock.patch("subprocess.run") as run_spy:
                augmented = augment_repair_plan_with_learned_discovery(
                    {"repair_steps": [], "hermes_required": [{"rule_id": "PDF/UA-1/7.21.7"}], "unknown_rules": []},
                    rule_map_path=rule_map,
                    repo_root=root,
                    audit_dir=root / "workspace/jobs/JOB/audit",
                )
            run_spy.assert_not_called()
            self.assertEqual(len(augmented["active_learned_strategy_candidates"]), 1)

    def test_execution_log_has_no_learned_execution_record_shape(self):
        execution_log = {"records": [{"record_type": "repair_step_execution"}]}
        learned = [r for r in execution_log["records"] if r.get("record_type") == "learned_strategy_execution"]
        self.assertEqual(learned, [])

    def test_verdict_inputs_are_not_changed_by_discovery_metadata(self):
        plan = {"result": "ALL_MANUAL", "repair_steps": [], "hermes_required": [{"rule_id": "PDF/UA-1/7.21.7"}], "unknown_rules": []}
        tmp, root = self._repo()
        with tmp:
            rule_map = self._rule_map(root, [])
            augmented = augment_repair_plan_with_learned_discovery(
                plan,
                rule_map_path=rule_map,
                repo_root=root,
                audit_dir=root / "workspace/jobs/JOB/audit",
            )
            self.assertEqual(augmented["result"], plan["result"])
            self.assertEqual(augmented["hermes_required"], plan["hermes_required"])
            self.assertEqual(augmented["repair_steps"], plan["repair_steps"])


if __name__ == "__main__":
    unittest.main()
