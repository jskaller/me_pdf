import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.tools.audit import promote_learned_strategy as promo


class LearnedRuleMapAdoptionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "app"
        self.rule_map = self.app / "tools" / "audit" / "rule_repair_map.json"
        self.rule_map.parent.mkdir(parents=True, exist_ok=True)
        self.job = self.tmp / "workspace" / "jobs" / "JOB1"
        self.audit = self.job / "audit"
        self.quarantine = self.audit / "self_extension" / "quarantine"
        self.quarantine.mkdir(parents=True, exist_ok=True)
        (self.audit / "residual_analysis.json").write_text(json.dumps({"ok": True}))
        self.script = self.quarantine / "fix_rule.py"
        self.script.write_text("def repair(input_pdf, output_pdf):\n    return {'ok': True}\n")
        self.script_sha = promo.sha256_file(self.script)
        self.rule_id = "PDF/UA-1/9.9.9"
        self._write_rule_map({"rules": {}})
        self._write_source_artifacts()
        self.review = promo.create_review_packet(self.job, self.rule_map)
        self.cid = self.review["promotion_candidates"][0]["candidate_id"]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write_rule_map(self, data):
        self.rule_map.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def _write_source_artifacts(self, *, clean=True, outcome="PASS", rule_id=None, script_path=None, script_sha=None, action="add_rule"):
        rule_id = rule_id or self.rule_id
        script_path = script_path if script_path is not None else str(self.script.relative_to(self.job))
        script_sha = script_sha or self.script_sha
        record = {
            "run_id": "run1",
            "job_dir": str(self.job),
            "rule_id": rule_id,
            "script_path": script_path,
            "script_sha256": script_sha,
            "attempt_number": 1,
            "outcome": outcome,
            "clean": clean,
            "indexing_eligible": clean,
            "introduced_rules": [],
            "worsened_rules": [],
            "execution_attempt_id": "attempt-1",
            "stdout_path": "stdout.txt",
            "stderr_path": "stderr.txt",
        }
        rid = promo.record_identity(record)
        strategy = {
            "name": "learned_fix",
            "script_path": script_path,
            "repair_script": script_path,
            "script_sha256": script_sha,
            "pass_rate": 1.0,
            "evidence": {"learned_strategy_record_id": rid},
        }
        proposal = {
            "rule_id": rule_id,
            "action": action,
            "proposed_strategy": strategy,
            "proposed_entry": {
                "manual": True,
                "resolvability": "repairable_review",
                "review_required": True,
                "strategies": [strategy],
            },
        }
        (self.audit / "learned_strategies.json").write_text(json.dumps({"records": [record]}, indent=2))
        (self.audit / "strategy_indexing_report.json").write_text(json.dumps({"proposed_rule_map_changes": [proposal], "rejected_experiments": []}, indent=2))

    def _stage(self):
        return promo.stage_script(self.job, self.rule_map, self.cid, "tester")

    def _load_map(self):
        return json.loads(self.rule_map.read_text())

    def test_a_rule_map_dry_run_for_staged_clean_candidate_writes_review_and_no_mutation(self):
        before = self.rule_map.read_text()
        self._stage()
        out = promo.dry_run_rule_map(self.job, self.rule_map, self.cid)
        self.assertTrue((self.audit / "rule_map_adoption_review.json").exists())
        self.assertEqual(before, self.rule_map.read_text())
        self.assertTrue(out["safe_to_apply_rule_map_patch"])
        self.assertFalse(out["canonical_rule_map_mutation_performed"])

    def test_b_apply_requires_candidate_id(self):
        self._stage()
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, "", "tester")

    def test_c_apply_requires_reviewed_by(self):
        self._stage()
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, self.cid, "")

    def test_d_apply_requires_staged_script_result(self):
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertEqual({}, self._load_map()["rules"])

    def test_e_apply_requires_staged_script_exists(self):
        staged = self._stage()
        (self.app / staged["staged_script_path"]).unlink()
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertEqual({}, self._load_map()["rules"])

    def test_f_staged_script_hash_mismatch_blocks_apply(self):
        staged = self._stage()
        (self.app / staged["staged_script_path"]).write_text("def repair():\n    return False\n")
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertEqual({}, self._load_map()["rules"])

    def test_g_candidate_quarantine_path_blocks_apply(self):
        self._stage()
        result_path = self.audit / "script_promotion_result.json"
        data = json.loads(result_path.read_text())
        data["staged_script_path"] = str(self.script)
        data["staged_script_sha256"] = self.script_sha
        result_path.write_text(json.dumps(data, indent=2))
        with self.assertRaises(promo.PromotionError):
            promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")

    def test_h_dirty_failed_refusal_candidates_blocked(self):
        self._write_source_artifacts(clean=False, outcome="FAIL")
        review = promo.create_review_packet(self.job, self.rule_map)
        cid = review["promotion_candidates"][0]["candidate_id"]
        with self.assertRaises(promo.PromotionError):
            promo.stage_script(self.job, self.rule_map, cid, "tester")

    def test_i_rule_absent_adoption_creates_review_staged_rule_entry_not_active(self):
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        entry = self._load_map()["rules"][self.rule_id]
        self.assertEqual("repairable_review", entry["resolvability"])
        self.assertEqual([], entry["strategies"])
        learned = entry["reviewed_learned_strategies"][0]
        self.assertFalse(learned["production_active"])
        self.assertEqual("staged_review", learned["activation_status"])

    def test_j_existing_repairable_unbuilt_adoption_preserves_review_semantics(self):
        self._write_rule_map({"rules": {self.rule_id: {"manual": True, "resolvability": "repairable_unbuilt", "strategies": []}}})
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        entry = self._load_map()["rules"][self.rule_id]
        self.assertEqual("repairable_review", entry["resolvability"])
        self.assertTrue(entry["review_required"])

    def test_k_existing_repairable_review_adoption_preserves_review_semantics(self):
        self._write_rule_map({"rules": {self.rule_id: {"manual": True, "resolvability": "repairable_review", "review_required": True, "strategies": []}}})
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        entry = self._load_map()["rules"][self.rule_id]
        self.assertEqual("repairable_review", entry["resolvability"])
        self.assertTrue(entry["review_required"])

    def test_l_existing_effective_primary_preserved(self):
        primary = [{"name": "primary", "repair_script": "tools/repair/fix_existing.py", "pass_rate": 1.0}]
        self._write_rule_map({"rules": {self.rule_id: {"manual": False, "resolvability": "effective", "strategies": primary}}})
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        entry = self._load_map()["rules"][self.rule_id]
        self.assertEqual(primary, entry["strategies"])
        self.assertEqual(1, len(entry["reviewed_learned_strategies"]))

    def test_m_backup_created_on_apply_and_hashes_recorded(self):
        self._stage()
        out = promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertTrue(Path(out["rule_map_backup_path"]).exists())
        self.assertTrue(out["rule_map_sha256_before"])
        self.assertTrue(out["rule_map_sha256_after"])
        self.assertNotEqual(out["rule_map_sha256_before"], out["rule_map_sha256_after"])

    def test_n_apply_result_artifact_written_with_policy_flags(self):
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        data = json.loads((self.audit / "rule_map_apply_result.json").read_text())
        self.assertTrue(data["canonical_rule_map_mutation_performed"])
        self.assertFalse(data["production_repair_activation_performed"])
        self.assertFalse(data["final_pdf_adoption_performed"])

    def test_o_app_tools_repair_unchanged(self):
        repair_dir = self.app / "tools" / "repair"
        repair_dir.mkdir(parents=True)
        before = sorted(p.name for p in repair_dir.glob("*"))
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        after = sorted(p.name for p in repair_dir.glob("*"))
        self.assertEqual(before, after)

    def test_p_final_pdf_adoption_unchanged(self):
        self._stage()
        out = promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertFalse(out["final_pdf_adoption_performed"])

    def test_q_resulting_rule_map_json_parseable(self):
        self._stage()
        promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        parsed = json.loads(self.rule_map.read_text())
        self.assertIn("rules", parsed)

    def test_r_rollback_instructions_present(self):
        self._stage()
        out = promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertTrue(out["rollback_instructions"])
        self.assertIn("cp ", out["rollback_instructions"][0])

    def test_s_generated_backup_location_is_under_ignored_directory(self):
        self._stage()
        out = promo.apply_rule_map(self.job, self.rule_map, self.cid, "tester")
        self.assertIn("tools/audit/backups", out["rule_map_backup_path"])


if __name__ == "__main__":
    unittest.main()
