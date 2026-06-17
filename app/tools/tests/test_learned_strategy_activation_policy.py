import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.audit import promote_learned_strategy as promote


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LearnedStrategyActivationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "app"
        self.audit = self.app / "tools" / "audit"
        self.staging = self.app / "tools" / "repair_staging" / "learned"
        self.job = self.tmp / "workspace" / "jobs" / "JOB1"
        self.audit.mkdir(parents=True)
        self.staging.mkdir(parents=True)
        (self.job / "audit").mkdir(parents=True)

        self.script = self.staging / "candidate_fix.py"
        self.script.write_text("def repair():\n    return True\n")
        self.rule_id = "PDF/UA-1/7.21.7"
        self.candidate_id = "candidate-activation-1"
        self.rule_map = self.audit / "rule_repair_map.json"
        self.rule_map.write_text(json.dumps({
            "rules": {
                self.rule_id: {
                    "description": "Existing rule",
                    "resolvability": "effective",
                    "strategies": [
                        {"strategy": "builtin", "repair_script": "tools/repair/existing.py"}
                    ],
                    "reviewed_learned_strategies": [
                        {
                            "candidate_id": self.candidate_id,
                            "production_active": False,
                            "activation_status": "staged_review",
                            "review_required": True,
                            "staged_script_path": "app/tools/repair_staging/learned/candidate_fix.py",
                            "staged_script_sha256": sha(self.script),
                            "evidence": {
                                "source_review_packet": "audit/strategy_promotion_review.json",
                                "source_script_promotion_result": "audit/script_promotion_result.json",
                                "source_rule_map_adoption_review": "audit/rule_map_adoption_review.json",
                            },
                        }
                    ],
                }
            }
        }, indent=2))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def read_map(self):
        return json.loads(self.rule_map.read_text())

    def test_activation_dry_run_writes_audit_artifact_without_mutation(self):
        before = self.rule_map.read_text()
        packet = promote.create_activation_dry_run(
            rule_map_path=self.rule_map,
            rule_id=self.rule_id,
            candidate_id=self.candidate_id,
            job_dir=self.job,
        )
        self.assertTrue(packet["safe_to_activate"])
        self.assertFalse(packet["canonical_rule_map_mutation_performed"])
        self.assertFalse(packet["runtime_discovery_performed"])
        self.assertFalse(packet["runtime_use_performed"])
        self.assertFalse(packet["repair_directory_mutation_performed"])
        self.assertFalse(packet["final_pdf_adoption_performed"])
        self.assertEqual(before, self.rule_map.read_text())
        self.assertTrue((self.job / "audit" / "activation_review.json").exists())

    def test_activation_apply_requires_rule_id_candidate_id_and_reviewer(self):
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id="", candidate_id=self.candidate_id, reviewed_by="operator", job_dir=self.job)
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id="", reviewed_by="operator", job_dir=self.job)
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id=self.candidate_id, reviewed_by="", job_dir=self.job)

    def test_activation_blocks_missing_script_hash_mismatch_and_static_unsafe(self):
        self.script.unlink()
        missing = promote.create_activation_dry_run(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id=self.candidate_id, job_dir=self.job)
        self.assertIn("staged_script_missing", missing["activation_blockers"])

        self.script.write_text("def repair():\n    return True\n")
        data = self.read_map()
        data["rules"][self.rule_id]["reviewed_learned_strategies"][0]["staged_script_sha256"] = "bad"
        self.rule_map.write_text(json.dumps(data, indent=2))
        mismatch = promote.create_activation_dry_run(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id=self.candidate_id, job_dir=self.job)
        self.assertIn("staged_script_hash_mismatch", mismatch["activation_blockers"])

        self.script.write_text("import subprocess\n")
        data["rules"][self.rule_id]["reviewed_learned_strategies"][0]["staged_script_sha256"] = sha(self.script)
        self.rule_map.write_text(json.dumps(data, indent=2))
        unsafe = promote.create_activation_dry_run(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id=self.candidate_id, job_dir=self.job)
        self.assertTrue(any("forbidden_import" in b for b in unsafe["activation_blockers"]))

    def test_activation_apply_mutates_only_selected_metadata_and_preserves_builtins(self):
        result = promote.apply_activation(
            rule_map_path=self.rule_map,
            rule_id=self.rule_id,
            candidate_id=self.candidate_id,
            reviewed_by="operator",
            job_dir=self.job,
        )
        self.assertEqual("ACTIVATED", result["result"])
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertFalse(result["runtime_discovery_performed"])
        self.assertFalse(result["runtime_use_performed"])
        self.assertFalse(result["repair_directory_mutation_performed"])
        self.assertFalse(result["final_pdf_adoption_performed"])

        data = self.read_map()
        entry = data["rules"][self.rule_id]
        self.assertEqual([{"strategy": "builtin", "repair_script": "tools/repair/existing.py"}], entry["strategies"])
        activated = entry["reviewed_learned_strategies"][0]
        self.assertTrue(activated["production_active"])
        self.assertEqual("active", activated["activation_status"])
        self.assertEqual("operator", activated["activated_by"])
        self.assertFalse(activated["activation_review_required"])

    def test_deactivation_marks_inactive_without_deleting_staged_script(self):
        promote.apply_activation(
            rule_map_path=self.rule_map,
            rule_id=self.rule_id,
            candidate_id=self.candidate_id,
            reviewed_by="operator",
            job_dir=self.job,
        )
        result = promote.deactivate_strategy(
            rule_map_path=self.rule_map,
            rule_id=self.rule_id,
            candidate_id=self.candidate_id,
            reviewed_by="operator",
            job_dir=self.job,
        )
        self.assertEqual("DEACTIVATED", result["result"])
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertTrue(self.script.exists())
        self.assertFalse(result["runtime_discovery_performed"])
        self.assertFalse(result["runtime_use_performed"])
        self.assertFalse(result["repair_directory_mutation_performed"])
        self.assertFalse(result["final_pdf_adoption_performed"])

        deactivated = self.read_map()["rules"][self.rule_id]["reviewed_learned_strategies"][0]
        self.assertFalse(deactivated["production_active"])
        self.assertEqual("deactivated", deactivated["activation_status"])
        self.assertEqual("operator", deactivated["deactivated_by"])

    def test_missing_candidate_is_rejected(self):
        with self.assertRaises(promote.PromotionError):
            promote.create_activation_dry_run(rule_map_path=self.rule_map, rule_id=self.rule_id, candidate_id="missing", job_dir=self.job)


if __name__ == "__main__":
    unittest.main()
