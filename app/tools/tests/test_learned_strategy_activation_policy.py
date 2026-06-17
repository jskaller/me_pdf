import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit import promote_learned_strategy as promote


RULE_ID = "PDF/UA-1/7.21.7"
CID = "candidate-clean-1"


class LearnedStrategyActivationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rule_map = self.root / "app/tools/audit/rule_repair_map.json"
        self.stage_dir = self.root / "app/tools/repair_staging/learned"
        self.repair_dir = self.root / "app/tools/repair"
        self.job_dir = self.root / "workspace/jobs/JOB1"
        self.stage_dir.mkdir(parents=True)
        self.repair_dir.mkdir(parents=True)
        (self.repair_dir / "README.md").write_text("production repair directory\n")
        self.script = self.stage_dir / "pdf_ua-1_7.21.7__candidate_clean.py"
        self.script.write_text("def remediate(input_pdf, output_pdf):\n    return output_pdf\n")
        self.sha = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.initial_map = {
            "schema_version": "test",
            "rules": {
                RULE_ID: {
                    "description": "test rule",
                    "strategies": [
                        {
                            "repair_script": "tools/repair/existing_primary.py",
                            "strategy": "existing_primary",
                            "pass_rate": 1.0,
                            "pass_count": 10,
                            "fail_count": 0,
                        }
                    ],
                    "reviewed_learned_strategies": [
                        {
                            "candidate_id": CID,
                            "strategy": "learned_clean_candidate",
                            "staged_script_path": "app/tools/repair_staging/learned/pdf_ua-1_7.21.7__candidate_clean.py",
                            "staged_script_sha256": self.sha,
                            "production_active": False,
                            "activation_status": "staged_review",
                            "review_required": True,
                            "activation_review_required": True,
                            "evidence": {
                                "rule_map_adoption_review_path": "workspace/jobs/JOB1/audit/rule_map_adoption_review.json",
                                "script_promotion_result_path": "workspace/jobs/JOB1/audit/script_promotion_result.json",
                            },
                        },
                        {
                            "candidate_id": "other-candidate",
                            "strategy": "other",
                            "staged_script_path": "app/tools/repair_staging/learned/pdf_ua-1_7.21.7__candidate_clean.py",
                            "staged_script_sha256": self.sha,
                            "production_active": False,
                            "activation_status": "staged_review",
                            "review_required": True,
                            "activation_review_required": True,
                            "evidence": {"rule_map_adoption_review_path": "x"},
                        },
                    ],
                }
            },
        }
        self.write_rule_map(self.initial_map)

    def tearDown(self):
        self.tmp.cleanup()

    def write_rule_map(self, data):
        self.rule_map.parent.mkdir(parents=True, exist_ok=True)
        self.rule_map.write_text(json.dumps(data, indent=2, sort_keys=True))

    def read_rule_map(self):
        return json.loads(self.rule_map.read_text())

    def test_activation_dry_run_writes_review_artifact_without_mutation(self):
        before = self.rule_map.read_text()
        packet = promote.create_activation_dry_run(
            rule_map_path=self.rule_map,
            rule_id=RULE_ID,
            candidate_id=CID,
            job_dir=self.job_dir,
        )
        self.assertTrue(packet["safe_to_activate"])
        self.assertFalse(packet["canonical_rule_map_mutation_performed"])
        self.assertFalse(packet["production_activation_performed"])
        self.assertFalse(packet["final_pdf_adoption_performed"])
        self.assertEqual(before, self.rule_map.read_text())
        artifact = self.job_dir / "audit/activation_review.json"
        self.assertTrue(artifact.exists())
        saved = json.loads(artifact.read_text())
        self.assertEqual(saved["mode"], "activation_dry_run")

    def test_activation_apply_requires_rule_id_candidate_id_and_reviewed_by(self):
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id="", candidate_id=CID, reviewed_by="operator")
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id="", reviewed_by="operator")
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="")

    def test_activation_blocks_strategy_not_in_rule_map(self):
        with self.assertRaises(promote.PromotionError):
            promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id="missing", reviewed_by="operator")
        self.assertEqual(self.initial_map, self.read_rule_map())

    def test_activation_blocks_missing_script_without_mutation(self):
        self.script.unlink()
        packet = promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        self.assertEqual(packet["result"], "BLOCKED")
        self.assertIn("staged_script_missing", packet["activation_blockers"])
        self.assertEqual(self.initial_map, self.read_rule_map())

    def test_activation_blocks_hash_mismatch_without_mutation(self):
        data = self.read_rule_map()
        data["rules"][RULE_ID]["reviewed_learned_strategies"][0]["staged_script_sha256"] = "0" * 64
        self.write_rule_map(data)
        packet = promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        self.assertEqual(packet["result"], "BLOCKED")
        self.assertIn("staged_script_hash_mismatch", packet["activation_blockers"])
        after = self.read_rule_map()
        self.assertFalse(after["rules"][RULE_ID]["reviewed_learned_strategies"][0]["production_active"])

    def test_activation_blocks_static_checks_fail_without_mutation(self):
        self.script.write_text("def broken(:\n")
        data = self.read_rule_map()
        data["rules"][RULE_ID]["reviewed_learned_strategies"][0]["staged_script_sha256"] = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.write_rule_map(data)
        packet = promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        self.assertEqual(packet["result"], "BLOCKED")
        self.assertTrue(any(b.startswith("python_ast_parse_failed") for b in packet["activation_blockers"]))
        after = self.read_rule_map()
        self.assertFalse(after["rules"][RULE_ID]["reviewed_learned_strategies"][0]["production_active"])

    def test_activation_apply_mutates_only_selected_strategy_and_preserves_primary(self):
        before = self.read_rule_map()
        packet = promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        self.assertEqual(packet["result"], "ACTIVATED")
        after = self.read_rule_map()
        self.assertEqual(before["rules"][RULE_ID]["strategies"], after["rules"][RULE_ID]["strategies"])
        selected = after["rules"][RULE_ID]["reviewed_learned_strategies"][0]
        other = after["rules"][RULE_ID]["reviewed_learned_strategies"][1]
        self.assertTrue(selected["production_active"])
        self.assertEqual(selected["activation_status"], "active")
        self.assertEqual(selected["activated_by"], "operator")
        self.assertIn("activated_at", selected)
        self.assertFalse(selected["activation_review_required"])
        self.assertFalse(selected["review_required"])
        self.assertFalse(other["production_active"])
        self.assertEqual(other["activation_status"], "staged_review")
        self.assertTrue(Path(packet["backup_path"]).exists())
        self.assertTrue((self.job_dir / "audit/activation_apply_result.json").exists())

    def test_deactivation_marks_inactive_preserves_script_and_evidence(self):
        promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        packet = promote.deactivate_strategy(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        self.assertEqual(packet["result"], "DEACTIVATED")
        after = self.read_rule_map()
        selected = after["rules"][RULE_ID]["reviewed_learned_strategies"][0]
        self.assertFalse(selected["production_active"])
        self.assertEqual(selected["activation_status"], "deactivated")
        self.assertEqual(selected["deactivated_by"], "operator")
        self.assertTrue(self.script.exists())
        self.assertIn("evidence", selected)
        self.assertTrue(Path(packet["backup_path"]).exists())
        self.assertTrue((self.job_dir / "audit/activation_deactivate_result.json").exists())

    def test_no_repair_mutation_no_final_pdf_adoption_and_rule_map_parseable(self):
        before_repair = sorted(p.name for p in self.repair_dir.iterdir())
        packet = promote.apply_activation(rule_map_path=self.rule_map, rule_id=RULE_ID, candidate_id=CID, reviewed_by="operator", job_dir=self.job_dir)
        after_repair = sorted(p.name for p in self.repair_dir.iterdir())
        self.assertEqual(before_repair, after_repair)
        self.assertFalse(packet["final_pdf_adoption_performed"])
        self.assertFalse(packet["repair_directory_mutation_performed"])
        parsed = self.read_rule_map()
        self.assertIn("rules", parsed)


if __name__ == "__main__":
    unittest.main()
