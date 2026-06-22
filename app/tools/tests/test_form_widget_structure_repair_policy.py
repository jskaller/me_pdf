#!/usr/bin/env python3
"""Policy tests for H9 guarded form-widget structure construction."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.audit.form_widget_structure_inspection import inspect_pdf_with_pikepdf
from tools.dev.generate_form_widget_structure_fixture import generate_fixture
from tools.repair.repair_form_widget_structure import build_report


def _pikepdf_available() -> bool:
    try:
        import pikepdf  # noqa: F401  # type: ignore
        return True
    except Exception:
        return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(_pikepdf_available(), "pikepdf is required for H9 fixture repair policy tests")
class FormWidgetStructureRepairPolicyTests(unittest.TestCase):
    def test_fixture_generator_creates_synthetic_pdf_with_untagged_widgets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_fixture_") as td:
            pdf_path = Path(td) / "input.pdf"
            generation = generate_fixture(pdf_path, field_count=2)
            evidence = inspect_pdf_with_pikepdf(pdf_path)

        self.assertEqual(generation["result"], "GENERATED")
        self.assertTrue(generation["synthetic"])
        self.assertFalse(generation["private_data"])
        self.assertTrue(evidence["acroform_present"])
        self.assertEqual(evidence["acroform_field_count"], 2)
        self.assertEqual(evidence["widget_annotation_count"], 2)
        self.assertEqual(evidence["widgets_missing_struct_parent_count"], 2)
        self.assertFalse(evidence["struct_tree_root_present"])
        self.assertFalse(evidence["parent_tree_present"])
        self.assertEqual(evidence["form_struct_element_count"], 0)

    def test_dry_run_reports_planned_changes_and_writes_no_output_pdf(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_dry_run_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=False, fixture_mode=True)

            self.assertFalse(output_pdf.exists())
            self.assertEqual(report["mode"], "dry_run")
            self.assertTrue(report["read_only"])
            self.assertFalse(report["repair_performed"])
            self.assertFalse(report["rule_map_mutation_performed"])
            self.assertFalse(report["workspace_artifacts_mutated"])
            self.assertFalse(report["safe_to_claim_production_ready"])
            self.assertEqual(report["planned_changes"]["assign_struct_parent_count"], 1)
            self.assertTrue(report["planned_changes"]["create_struct_tree_root"])
            self.assertTrue(report["planned_changes"]["create_parent_tree"])
            self.assertEqual(report["planned_changes"]["create_form_struct_elements_count"], 1)

    def test_apply_writes_only_explicit_output_and_constructs_form_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_apply_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=2)
            input_before_hash = _sha256(input_pdf)
            before = inspect_pdf_with_pikepdf(input_pdf)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=True, fixture_mode=True)
            after = inspect_pdf_with_pikepdf(output_pdf)

            self.assertTrue(output_pdf.exists())
            self.assertEqual(_sha256(input_pdf), input_before_hash)
            self.assertEqual(before["widget_annotation_count"], 2)
            self.assertEqual(after["widget_annotation_count"], 2)
            self.assertEqual(after["widgets_missing_struct_parent_count"], 0)
            self.assertEqual(after["widgets_with_struct_parent_count"], 2)
            self.assertTrue(after["struct_tree_root_present"])
            self.assertTrue(after["parent_tree_present"])
            self.assertGreaterEqual(after["form_struct_element_count"], 2)
            self.assertEqual(after["widgets_with_parent_tree_mapping_count"], 2)
            self.assertEqual(after["widgets_already_nested_in_form_count"], 2)
            self.assertFalse(report["rule_map_mutation_performed"])
            self.assertFalse(report["workspace_artifacts_mutated"])
            self.assertFalse(report["safe_to_claim_production_ready"])
            self.assertIn(report["decision"]["terminal_state"], {
                "IMPLEMENTED_AND_VALIDATED_ON_FIXTURE",
                "IMPLEMENTED_BUT_BLOCKED_FOR_PRODUCTION",
            })

    def test_preservation_summary_confirms_fields_widgets_pages_and_boxes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_preserve_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=2)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=True, fixture_mode=True)
            preservation = report["preservation"]

            self.assertTrue(preservation["field_count_preserved"])
            self.assertTrue(preservation["field_names_preserved"])
            self.assertTrue(preservation["field_types_preserved"])
            self.assertTrue(preservation["field_value_presence_preserved"])
            self.assertTrue(preservation["widget_count_preserved"])
            self.assertTrue(preservation["widget_page_membership_preserved"])
            self.assertTrue(preservation["page_count_preserved"])
            self.assertTrue(preservation["page_boxes_preserved"])
            self.assertTrue(preservation["field_values_not_dumped"])
            self.assertFalse(preservation["exact_object_identity_claimed"])

    def test_report_does_not_dump_synthetic_field_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_redact_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=True, fixture_mode=True)
            serialized = repr(report)

            self.assertIn("field_value_present", serialized)
            self.assertIn("field_value_type", serialized)
            self.assertNotIn("fixture-value-1", serialized)

    def test_non_fixture_mode_refuses_unsafe_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_non_fixture_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=True, fixture_mode=False)

            self.assertFalse(output_pdf.exists())
            self.assertEqual(report["decision"]["terminal_state"], "BLOCKED_BEFORE_IMPLEMENTATION")
            self.assertFalse(report["repair_performed"])
            self.assertIn("non-fixture mode", " ".join(report["decision"]["blockers"]))

    def test_missing_input_pdf_fails_truthfully(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_missing_") as td:
            root = Path(td)
            report = build_report(root / "missing.pdf", output_pdf=root / "output.pdf", apply=True, fixture_mode=True)

            self.assertEqual(report["decision"]["terminal_state"], "BLOCKED_BEFORE_IMPLEMENTATION")
            self.assertFalse(report["repair_performed"])
            self.assertFalse(report["safe_to_claim_production_ready"])
            self.assertIn("input PDF could not be inspected", report["decision"]["blockers"])

    def test_apply_requires_explicit_distinct_output_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h9_form_widget_output_guard_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            generate_fixture(input_pdf, field_count=1)

            missing_output = build_report(input_pdf, apply=True, fixture_mode=True)
            same_output = build_report(input_pdf, output_pdf=input_pdf, apply=True, fixture_mode=True)

            self.assertIn("apply mode requires explicit --output path", missing_output["decision"]["blockers"])
            self.assertIn("output path must not overwrite input PDF", same_output["decision"]["blockers"])
            self.assertFalse(missing_output["repair_performed"])
            self.assertFalse(same_output["repair_performed"])


if __name__ == "__main__":
    unittest.main()
