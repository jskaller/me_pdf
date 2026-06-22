#!/usr/bin/env python3
"""Policy tests for the H7 form-widget structure inspection diagnostic."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.audit.form_widget_structure_inspection import (
    MAX_WIDGETS_DEFAULT,
    build_report,
    decide_from_evidence,
)


BASE_EVIDENCE = {
    "available": True,
    "page_count": 1,
    "acroform_present": True,
    "acroform_field_count": 1,
    "struct_tree_root_present": True,
    "parent_tree_present": True,
    "parent_tree_type": "NumberTree",
    "parent_tree_entry_count": 1,
    "struct_element_count": 2,
    "form_struct_element_count": 1,
    "widget_annotation_count": 1,
    "widgets_missing_struct_parent_count": 0,
    "widgets_with_struct_parent_count": 1,
    "widgets_with_parent_tree_mapping_count": 1,
    "widgets_without_parent_tree_mapping_count": 0,
    "widgets_already_nested_in_form_count": 1,
    "adding_form_elements_would_require_parent_tree_mutation": False,
    "adding_form_elements_would_require_k_array_mutation": False,
    "sensitive_field_values_redacted": True,
    "widgets": [
        {
            "page_index": 1,
            "annotation_objgen": "10 0",
            "field_name": "PatientName",
            "field_type": "Tx",
            "field_value_present": True,
            "field_value_type": "String",
            "rect": [1.0, 2.0, 3.0, 4.0],
            "struct_parent": 7,
            "parent_tree_mapping_present": True,
            "mapped_struct_element_type": "Form",
            "mapped_struct_element_objgen": "20 0",
            "already_nested_in_form": True,
        }
    ],
}


class FormWidgetStructureInspectionPolicyTests(unittest.TestCase):
    def test_missing_pdf_is_insufficient_evidence_and_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h7_form_widget_") as td:
            report = build_report(Path(td) / "missing.pdf")

        self.assertEqual(report["schema"], "montefiore.form_widget_structure_inspection")
        self.assertEqual(report["result"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["decision"]["chosen_option"], "C")
        self.assertFalse(report["decision"]["repair_implementation_safe_now"])

    def test_policy_flags_are_read_only_and_never_claim_production_ready(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h7_form_widget_") as td:
            report = build_report(Path(td) / "missing.pdf", Path(td) / "job")

        self.assertTrue(report["read_only"])
        self.assertFalse(report["repair_performed"])
        self.assertFalse(report["rule_map_mutation_performed"])
        self.assertFalse(report["workspace_artifacts_mutated"])
        self.assertFalse(report["safe_to_claim_production_ready"])

    def test_no_widgets_found_keeps_option_c(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "widget_annotation_count": 0,
            "widgets_with_struct_parent_count": 0,
            "widgets_with_parent_tree_mapping_count": 0,
            "widgets": [],
        })

        decision = decide_from_evidence(evidence)

        self.assertEqual(decision["chosen_option"], "C")
        self.assertIn("no widget annotations found", decision["blockers"])
        self.assertFalse(decision["design_ready_for_future_patch"])

    def test_widgets_without_struct_parent_are_blocked(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "widgets_missing_struct_parent_count": 1,
            "widgets_with_struct_parent_count": 0,
            "widgets_with_parent_tree_mapping_count": 0,
        })

        decision = decide_from_evidence(evidence)

        self.assertEqual(decision["chosen_option"], "C")
        self.assertIn("widgets lack /StructParent values", decision["blockers"])

    def test_missing_parent_tree_is_blocked(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({"parent_tree_present": False, "parent_tree_entry_count": 0})

        decision = decide_from_evidence(evidence)

        self.assertEqual(decision["chosen_option"], "C")
        self.assertIn("/ParentTree missing", decision["blockers"])

    def test_existing_struct_parent_and_parent_tree_evidence_is_design_evidence_not_repair(self) -> None:
        decision = decide_from_evidence(dict(BASE_EVIDENCE))

        self.assertEqual(decision["chosen_option"], "A")
        self.assertTrue(decision["design_ready_for_future_patch"])
        self.assertFalse(decision["repair_implementation_safe_now"])

    def test_partial_evidence_with_missing_form_struct_elements_is_option_b(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "form_struct_element_count": 0,
            "adding_form_elements_would_require_parent_tree_mutation": False,
            "adding_form_elements_would_require_k_array_mutation": True,
        })

        decision = decide_from_evidence(evidence)

        self.assertEqual(decision["chosen_option"], "B")
        self.assertFalse(decision["design_ready_for_future_patch"])
        self.assertIn("safe insertion point for future /Form structure elements", decision["required_next_evidence"])

    def test_sensitive_field_values_are_not_required_or_dumped(self) -> None:
        widget = dict(BASE_EVIDENCE["widgets"][0])
        widget["field_value_present"] = True
        widget["field_value_type"] = "String"
        evidence = dict(BASE_EVIDENCE)
        evidence["widgets"] = [widget]

        serialized = repr(evidence)

        self.assertIn("field_value_present", serialized)
        self.assertIn("field_value_type", serialized)
        self.assertNotIn("John Doe", serialized)
        self.assertNotIn("Sensitive", serialized)

    def test_output_is_bounded_and_does_not_require_unbounded_object_dumps(self) -> None:
        widgets = []
        for index in range(MAX_WIDGETS_DEFAULT + 25):
            widgets.append({
                "page_index": 1,
                "annotation_objgen": f"{index + 1} 0",
                "field_name": f"field_{index}",
                "field_value_present": False,
                "struct_parent": index,
                "parent_tree_mapping_present": True,
                "mapped_struct_element_type": "Form",
            })
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "widget_annotation_count": len(widgets),
            "widgets_bounded_count": MAX_WIDGETS_DEFAULT,
            "widgets_truncated": True,
            "widgets": widgets[:MAX_WIDGETS_DEFAULT],
        })

        decision = decide_from_evidence(evidence)

        self.assertLessEqual(len(evidence["widgets"]), MAX_WIDGETS_DEFAULT)
        self.assertTrue(evidence["widgets_truncated"])
        self.assertFalse(decision["repair_implementation_safe_now"])


if __name__ == "__main__":
    unittest.main()
