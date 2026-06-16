#!/usr/bin/env python3

import unittest

from tools.audit.residual_analysis import analyze_residuals


def summary(*items):
    return {
        "result": "FAIL" if items else "PASS",
        "failures_by_rule": [
            {"rule_id": rule_id, "failures": count, "description": rule_id}
            for rule_id, count in items
        ],
    }


def rule_map(**rules):
    return {"rules": rules}


def plan_for(rule_id, script="tools/repair/fix_x.py"):
    return {
        "repair_steps": [
            {
                "step": 1,
                "repair_script": script,
                "strategy": "fix_x",
                "rules_addressed": [rule_id],
            }
        ]
    }


def exec_log(rule_id, *, ran=True, success=True, output=True):
    return {
        "repair_steps": [
            {
                "rule_ids": [rule_id],
                "repair_script": "tools/repair/fix_x.py",
                "strategy": "fix_x",
                "ran": ran,
                "skipped": not ran,
                "result_category": "ran_success" if success else "ran_failed",
                "output_pdf": "/tmp/out.pdf" if output else None,
                "output_pdf_hash": "abc123" if output else None,
            }
        ]
    }


class ResidualAnalysisTests(unittest.TestCase):
    def analyze(self, baseline, post, repair_plan=None, execution_log=None, rules=None):
        return analyze_residuals(
            baseline_failures=baseline,
            post_failures=post,
            repair_plan=repair_plan or {"repair_steps": []},
            execution_log=execution_log or {"repair_steps": []},
            rule_map=rules or {"rules": {}},
            job_dir="/tmp/job",
        )

    def assert_outcome(self, analysis, rule_id, outcome):
        self.assertEqual(analysis["rules"][rule_id]["outcome"], outcome)

    def test_resolved(self):
        rid = "PDF/UA-1/7.1"
        a = self.analyze(summary((rid, 2)), summary(), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "resolved")

    def test_resolved_incidental(self):
        rid = "PDF/UA-1/7.2"
        a = self.analyze(summary((rid, 2)), summary(), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "resolved_incidental")

    def test_persistent(self):
        rid = "PDF/UA-1/7.3"
        a = self.analyze(summary((rid, 2)), summary((rid, 1)), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "persistent")

    def test_partially_resolved_remains_persistent(self):
        rid = "PDF/UA-1/7.4"
        a = self.analyze(summary((rid, 4)), summary((rid, 2)), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "persistent")
        self.assertTrue(a["rules"][rid]["partially_resolved"])
        self.assertFalse(a["policy"]["partially_resolved_softens_verdict"])

    def test_attempted_no_effect_same_count(self):
        rid = "PDF/UA-1/7.5"
        a = self.analyze(summary((rid, 2)), summary((rid, 2)), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "attempted_no_effect")

    def test_attempted_no_effect_increased_count(self):
        rid = "PDF/UA-1/7.6"
        a = self.analyze(summary((rid, 2)), summary((rid, 3)), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "effective"}}))
        self.assert_outcome(a, rid, "attempted_no_effect")

    def test_introduced_is_targetable_per_current_contract(self):
        rid = "PDF/UA-1/7.7"
        a = self.analyze(summary(), summary((rid, 1)), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "repairable_unbuilt"}}))
        self.assert_outcome(a, rid, "introduced")
        self.assertTrue(a["rules"][rid]["targetable_by_self_extension"])
        self.assertIn(rid, a["introduced_rules"])

    def test_never_attempted_repairable_unbuilt_targetable(self):
        rid = "PDF/UA-1/7.8"
        a = self.analyze(summary((rid, 2)), summary((rid, 2)), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "repairable_unbuilt"}}))
        self.assert_outcome(a, rid, "never_attempted")
        self.assertTrue(a["rules"][rid]["targetable_by_self_extension"])
        self.assertEqual(a["targetable_residual_rules"], [rid])

    def test_escalated_not_auto_fixable_not_targetable(self):
        rid = "PDF/UA-1/7.9"
        a = self.analyze(summary((rid, 2)), summary((rid, 2)), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "not_auto_fixable"}}))
        self.assert_outcome(a, rid, "escalated")
        self.assertFalse(a["rules"][rid]["targetable_by_self_extension"])
        self.assertIn(rid, a["escalation_rules"])

    def test_escalated_detector_mislabeled_not_targetable(self):
        rid = "PDF/UA-1/7.10"
        a = self.analyze(summary((rid, 2)), summary((rid, 2)), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "detector_mislabeled"}}))
        self.assert_outcome(a, rid, "escalated")
        self.assertFalse(a["rules"][rid]["targetable_by_self_extension"])

    def test_legacy_hermes_required_style_becomes_repairable_unbuilt(self):
        rid = "PDF/UA-1/7.11"
        a = self.analyze(summary((rid, 1)), summary((rid, 1)), {"repair_steps": [], "hermes_required": [{"rule_id": rid, "reason": "manual_no_strategies"}]}, {"repair_steps": []}, rule_map(**{rid: {"status": "HERMES_REQUIRED", "manual": False, "strategies": []}}))
        self.assert_outcome(a, rid, "never_attempted")
        self.assertEqual(a["rules"][rid]["resolvability"], "repairable_unbuilt")
        self.assertTrue(a["rules"][rid]["targetable_by_self_extension"])

    def test_legacy_manual_no_strategies_escalates(self):
        rid = "PDF/UA-1/7.12"
        a = self.analyze(summary((rid, 1)), summary((rid, 1)), {"repair_steps": [], "hermes_required": [{"rule_id": rid, "reason": "manual_no_strategies"}]}, {"repair_steps": []}, rule_map(**{rid: {"manual": True, "strategies": []}}))
        self.assert_outcome(a, rid, "escalated")
        self.assertEqual(a["rules"][rid]["resolvability"], "legacy_manual_review")
        self.assertFalse(a["rules"][rid]["targetable_by_self_extension"])

    def test_new_resolvability_style_repairable_review_targetable(self):
        rid = "PDF/UA-1/7.13"
        a = self.analyze(summary((rid, 1)), summary((rid, 1)), {"repair_steps": []}, {"repair_steps": []}, rule_map(**{rid: {"resolvability": "repairable_review"}}))
        self.assert_outcome(a, rid, "never_attempted")
        self.assertTrue(a["rules"][rid]["review_required"])
        self.assertTrue(a["rules"][rid]["targetable_by_self_extension"])

    def test_resolved_repairable_review_sets_pending_review(self):
        rid = "PDF/UA-1/7.14"
        a = self.analyze(summary((rid, 1)), summary(), plan_for(rid), exec_log(rid), rule_map(**{rid: {"resolvability": "repairable_review"}}))
        self.assert_outcome(a, rid, "resolved")
        self.assertTrue(a["rules"][rid]["pending_review"])


if __name__ == "__main__":
    unittest.main()
