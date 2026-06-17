import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.learned_strategy_production_test import evaluate_learned_strategy_production_test


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LearnedStrategyProductionTestPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = self.root / "job"
        self.audit = self.job / "audit"
        self.repair = self.root / "app" / "tools" / "repair"
        self.rule_map = self.root / "app" / "tools" / "audit" / "rule_repair_map.json"
        self.audit.mkdir(parents=True)
        self.repair.mkdir(parents=True)
        self.rule_map.parent.mkdir(parents=True)
        self.status = self.job / "STATUS.json"
        self.status.write_text(json.dumps({"overall_result": "ESCALATION", "active_actionable_count": 3, "suppressed_zero_count": 1}), encoding="utf-8")
        self.package = self.job / "package"
        self.package.mkdir()
        (self.package / "AUDIT_REPORT.md").write_text("normal package", encoding="utf-8")
        (self.package / "CHECKSUMS.json").write_text("{}", encoding="utf-8")
        self.normal_pdf = self.job / "normal_final.pdf"
        self.learned_pdf = self.audit / "learned_strategy_replacement_trial" / "attempt-1" / "learned_trial.pdf"
        self.normal_pdf.write_bytes(b"%PDF-normal\n")
        self.learned_pdf.parent.mkdir(parents=True)
        self.learned_pdf.write_bytes(b"%PDF-learned\n")
        self.readiness = self.audit / "learned_strategy_production_testing_readiness_report.json"
        self.trial = self.audit / "learned_strategy_replacement_trial_report.json"
        self.rule_map.write_text(json.dumps({"rules": {}}), encoding="utf-8")
        (self.repair / "README.md").write_text("stable", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_complete_inputs(self, *, learned_pdf: Path | None = None, readiness_decision: str = "production_testing_evidence_complete") -> None:
        write_json(self.readiness, {
            "results": [{
                "rule_id": "PDF/UA-1/7.21.7",
                "candidate_id": "smoke-changed-valid-candidate",
                "attempt_id": "attempt-1",
                "readiness_decision": readiness_decision,
            }]
        })
        write_json(self.trial, {
            "results": [{
                "rule_id": "PDF/UA-1/7.21.7",
                "candidate_id": "smoke-changed-valid-candidate",
                "attempt_id": "attempt-1",
                "trial_decision": "trial_evidence_passed",
                "normal_final_pdf": str(self.normal_pdf),
                "learned_trial_pdf": str(learned_pdf or self.learned_pdf),
            }]
        })

    def run_prod_test(self) -> dict:
        return evaluate_learned_strategy_production_test(
            readiness_report_path=self.readiness,
            replacement_trial_report_path=self.trial,
            job_dir=self.job,
            normal_final_pdf=self.normal_pdf,
        )

    def test_missing_readiness_report_blocks_production_test(self) -> None:
        write_json(self.trial, {"results": []})
        payload = self.run_prod_test()
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertFalse(payload["production_test_performed"])
        self.assertIn("missing_production_test_prerequisite_artifact", payload["blockers"])

    def test_readiness_not_complete_blocks_production_test(self) -> None:
        self.write_complete_inputs(readiness_decision="production_testing_needs_manual_review")
        payload = self.run_prod_test()
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertFalse(payload["production_test_performed"])
        self.assertIn("production_testing_evidence_not_complete", payload["blockers"])

    def test_missing_learned_trial_output_blocks_production_test(self) -> None:
        self.write_complete_inputs(learned_pdf=self.root / "missing.pdf")
        payload = self.run_prod_test()
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertEqual(payload["missing_trial_output_count"], 1)
        self.assertIn("missing_learned_trial_output", payload["results"][0]["blockers"])

    def test_complete_readiness_creates_production_test_report(self) -> None:
        self.write_complete_inputs()
        payload = self.run_prod_test()
        report = self.audit / "learned_strategy_production_test_report.json"
        self.assertTrue(report.exists())
        self.assertEqual(payload["result"], "PASS")
        self.assertTrue(payload["production_test_performed"])
        self.assertTrue(Path(payload["results"][0]["production_test_sidecar_pdf"]).exists())

    def test_report_includes_all_no_adoption_no_mutation_flags(self) -> None:
        self.write_complete_inputs()
        payload = self.run_prod_test()
        policy = payload["policy"]
        self.assertTrue(policy["production_test_only"])
        self.assertTrue(policy["normal_final_pdf_remains_authoritative"])
        self.assertFalse(policy["candidate_is_adoptable"])
        self.assertFalse(policy["final_pdf_adoption_performed"])
        self.assertFalse(policy["production_repair_replacement_performed"])
        self.assertFalse(policy["verdict_softening_performed"])
        self.assertFalse(policy["package_status_mutation_performed"])

    def test_normal_final_pdf_remains_authoritative(self) -> None:
        self.write_complete_inputs()
        before = self.normal_pdf.read_bytes()
        payload = self.run_prod_test()
        self.assertEqual(self.normal_pdf.read_bytes(), before)
        self.assertEqual(payload["results"][0]["normal_final_pdf"], str(self.normal_pdf))
        self.assertFalse(payload["results"][0]["final_pdf_adoption_performed"])

    def test_no_authoritative_status_json_mutation(self) -> None:
        self.write_complete_inputs()
        before = sha256(self.status)
        payload = self.run_prod_test()
        self.assertEqual(sha256(self.status), before)
        self.assertEqual(payload["authoritative_status_json_sha256_before"], before)
        self.assertEqual(payload["authoritative_status_json_sha256_after"], before)

    def test_no_package_deliverable_mutation(self) -> None:
        self.write_complete_inputs()
        before = {p.name: sha256(p) for p in self.package.iterdir()}
        payload = self.run_prod_test()
        after = {p.name: sha256(p) for p in self.package.iterdir()}
        self.assertEqual(after, before)
        self.assertEqual(payload["protected_mutation_count"], 0)

    def test_no_app_tools_repair_mutation(self) -> None:
        self.write_complete_inputs()
        before = {p.relative_to(self.repair).as_posix(): sha256(p) for p in self.repair.rglob("*") if p.is_file()}
        self.run_prod_test()
        after = {p.relative_to(self.repair).as_posix(): sha256(p) for p in self.repair.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_no_rule_map_mutation(self) -> None:
        self.write_complete_inputs()
        before = sha256(self.rule_map)
        self.run_prod_test()
        self.assertEqual(sha256(self.rule_map), before)

    def test_static_orchestrator_contract_has_production_test_flag_when_repo_present(self) -> None:
        remediate = Path("app/tools/orchestrate/remediate.py")
        if not remediate.exists():
            self.skipTest("remediate.py not present in isolated test run")
        text = remediate.read_text(encoding="utf-8")
        self.assertIn("--learned-production-test", text)
        self.assertIn("requires_learned_production_readiness", text)


if __name__ == "__main__":
    unittest.main()
