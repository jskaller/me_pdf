#!/usr/bin/env python3
"""Policy tests for H7/H10A form-widget structure inspection."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.audit.form_widget_structure_inspection import (
    MAX_WIDGETS_DEFAULT,
    build_report,
    decide_from_evidence,
    inspect_pdf_with_pikepdf,
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
    "widgets_bounded_count": 1,
    "bounded_widget_records_count": 1,
    "widgets_truncated": False,
    "widget_evidence_complete": True,
    "widgets": [
        {
            "page_index": 1,
            "annotation_objgen": "10 0",
            "field_name": "Field1",
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


def _pikepdf_available() -> bool:
    try:
        import pikepdf  # noqa: F401  # type: ignore
        return True
    except Exception:
        return False


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

    def test_truncated_widget_evidence_is_reported_clearly(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "widget_annotation_count": 102,
            "widgets_bounded_count": 100,
            "bounded_widget_records_count": 100,
            "widgets_truncated": True,
            "widget_evidence_complete": False,
        })

        decision = decide_from_evidence(evidence)

        self.assertEqual(decision["chosen_option"], "C")
        self.assertIn("widget evidence is truncated", decision["blockers"])
        self.assertNotIn("widget evidence is not truncated", decision["blockers"])

    def test_complete_widget_evidence_has_no_truncation_blocker(self) -> None:
        decision = decide_from_evidence(dict(BASE_EVIDENCE))

        self.assertNotIn("widget evidence is truncated", decision["blockers"])

    def test_default_bound_metadata_identifies_incomplete_widget_output(self) -> None:
        evidence = dict(BASE_EVIDENCE)
        evidence.update({
            "widget_annotation_count": MAX_WIDGETS_DEFAULT + 5,
            "widgets_bounded_count": MAX_WIDGETS_DEFAULT,
            "bounded_widget_records_count": MAX_WIDGETS_DEFAULT,
            "widgets_truncated": True,
            "widget_evidence_complete": False,
            "widgets": [{} for _ in range(MAX_WIDGETS_DEFAULT)],
        })

        decision = decide_from_evidence(evidence)

        self.assertLessEqual(len(evidence["widgets"]), MAX_WIDGETS_DEFAULT)
        self.assertTrue(evidence["widgets_truncated"])
        self.assertIn("widget evidence is truncated", decision["blockers"])

    def test_sensitive_field_values_are_not_dumped(self) -> None:
        serialized = repr(BASE_EVIDENCE)

        self.assertIn("field_value_present", serialized)
        self.assertIn("field_value_type", serialized)
        self.assertNotIn("fixture-value", serialized)


@unittest.skipUnless(_pikepdf_available(), "pikepdf is required for max-widget bound inspection tests")
class FormWidgetStructureInspectionMaxWidgetTests(unittest.TestCase):
    def test_higher_bound_can_produce_complete_widget_evidence(self) -> None:
        from tools.dev.generate_form_widget_structure_fixture import generate_fixture

        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_bound_") as td:
            input_pdf = Path(td) / "input.pdf"
            generate_fixture(input_pdf, field_count=MAX_WIDGETS_DEFAULT + 5)

            bounded = inspect_pdf_with_pikepdf(input_pdf)
            complete = inspect_pdf_with_pikepdf(input_pdf, max_widgets=MAX_WIDGETS_DEFAULT + 10)

        self.assertEqual(bounded["widgets_bounded_count"], MAX_WIDGETS_DEFAULT)
        self.assertTrue(bounded["widgets_truncated"])
        self.assertFalse(bounded["widget_evidence_complete"])
        self.assertEqual(complete["widgets_bounded_count"], MAX_WIDGETS_DEFAULT + 5)
        self.assertEqual(complete["bounded_widget_records_count"], MAX_WIDGETS_DEFAULT + 5)
        self.assertFalse(complete["widgets_truncated"])
        self.assertTrue(complete["widget_evidence_complete"])

    def test_build_report_accepts_max_widgets(self) -> None:
        from tools.dev.generate_form_widget_structure_fixture import generate_fixture

        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_report_bound_") as td:
            input_pdf = Path(td) / "input.pdf"
            generate_fixture(input_pdf, field_count=MAX_WIDGETS_DEFAULT + 2)
            report = build_report(input_pdf, max_widgets=MAX_WIDGETS_DEFAULT + 5)

        evidence = report["pdf_object_evidence"]
        self.assertEqual(report["max_widgets"], MAX_WIDGETS_DEFAULT + 5)
        self.assertTrue(evidence["widget_evidence_complete"])
        self.assertFalse(evidence["widgets_truncated"])


if __name__ == "__main__":
    unittest.main()
