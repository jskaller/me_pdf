#!/usr/bin/env python3
"""Policy tests for guarded H9/H10/H10A form-widget structure construction."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.audit.form_widget_structure_inspection import MAX_WIDGETS_DEFAULT, inspect_pdf_with_pikepdf
from tools.dev.generate_form_widget_structure_fixture import generate_fixture
from tools.repair.repair_form_widget_structure import (
    H10_TERMINAL_DRY_RUN_BLOCKED,
    H10_TERMINAL_DRY_RUN_READY,
    build_report,
)


def _pikepdf_available() -> bool:
    try:
        import pikepdf  # noqa: F401  # type: ignore
        return True
    except Exception:
        return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FormWidgetStructureRepairMockPolicyTests(unittest.TestCase):
    def test_repair_passes_requested_max_widgets_to_inspection(self) -> None:
        evidence = {
            "available": True,
            "acroform_present": True,
            "widget_annotation_count": 102,
            "widgets_bounded_count": 102,
            "bounded_widget_records_count": 102,
            "widgets_truncated": False,
            "widget_evidence_complete": True,
            "widgets_referenced_from_non_form_count": 0,
            "parent_tree_has_kids": False,
            "widgets_missing_struct_parent_count": 102,
            "widgets_with_struct_parent_count": 0,
            "widgets_with_parent_tree_mapping_count": 0,
            "form_struct_element_count": 0,
            "struct_tree_root_present": False,
            "parent_tree_present": False,
            "acroform_fields": [],
            "page_boxes": [],
        }
        with mock.patch("tools.repair.repair_form_widget_structure.inspect_pdf_with_pikepdf", return_value=evidence) as inspected:
            report = build_report(Path("/tmp/input.pdf"), max_widgets=1000)

        inspected.assert_called_once_with(Path("/tmp/input.pdf"), max_widgets=1000)
        self.assertTrue(report["apply_allowed"])
        self.assertTrue(report["widget_evidence_complete"])
        self.assertEqual(report["widgets_bounded_count"], 102)
        self.assertEqual(report["terminal_state"], H10_TERMINAL_DRY_RUN_READY)


@unittest.skipUnless(_pikepdf_available(), "pikepdf is required for form-widget repair policy tests")
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
        self.assertEqual(evidence["widget_annotation_count"], 2)
        self.assertEqual(evidence["widgets_missing_struct_parent_count"], 2)
        self.assertFalse(evidence["struct_tree_root_present"])
        self.assertFalse(evidence["parent_tree_present"])

    def test_non_fixture_dry_run_is_allowed_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10_form_widget_nonfixture_dry_run_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)
            before_hash = _sha256(input_pdf)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=False, fixture_mode=False)

            self.assertFalse(output_pdf.exists())
            self.assertEqual(_sha256(input_pdf), before_hash)
            self.assertTrue(report["read_only"])
            self.assertFalse(report["repair_performed"])
            self.assertTrue(report["apply_allowed"])
            self.assertEqual(report["decision"]["terminal_state"], H10_TERMINAL_DRY_RUN_READY)
            self.assertFalse(report["safe_to_claim_production_ready"])
            self.assertFalse(report["rule_map_mutation_performed"])

    def test_repair_dry_run_fails_when_widget_evidence_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_truncated_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=MAX_WIDGETS_DEFAULT + 2)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=False, fixture_mode=False)

            self.assertEqual(report["decision"]["terminal_state"], H10_TERMINAL_DRY_RUN_BLOCKED)
            self.assertFalse(report["apply_allowed"])
            self.assertTrue(report["widgets_truncated"])
            self.assertFalse(report["widget_evidence_complete"])
            self.assertIn("widget evidence is truncated", report["apply_blockers"])
            self.assertNotIn("widget evidence is not truncated", report["apply_blockers"])
            self.assertFalse(output_pdf.exists())

    def test_repair_dry_run_passes_completeness_precondition_with_higher_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_complete_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=MAX_WIDGETS_DEFAULT + 2)

            report = build_report(
                input_pdf,
                output_pdf=output_pdf,
                apply=False,
                fixture_mode=False,
                max_widgets=MAX_WIDGETS_DEFAULT + 10,
            )

            self.assertEqual(report["decision"]["terminal_state"], H10_TERMINAL_DRY_RUN_READY)
            self.assertTrue(report["apply_allowed"])
            self.assertFalse(report["widgets_truncated"])
            self.assertTrue(report["widget_evidence_complete"])
            self.assertIn("widget evidence is complete", report["preconditions_satisfied"])
            self.assertNotIn("widget evidence is truncated", report["preconditions_failed"])

    def test_non_fixture_apply_is_refused_without_explicit_trial_flag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10_form_widget_nonfixture_apply_refused_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)

            report = build_report(input_pdf, output_pdf=output_pdf, apply=True, fixture_mode=False)

            self.assertFalse(output_pdf.exists())
            self.assertEqual(report["decision"]["terminal_state"], H10_TERMINAL_DRY_RUN_BLOCKED)
            self.assertFalse(report["repair_performed"])
            self.assertIn("--allow-structure-construction-trial", " ".join(report["apply_blockers"]))

    def test_trial_apply_uses_explicit_output_and_keeps_non_production_flags(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_trial_apply_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            generate_fixture(input_pdf, field_count=1)
            before_hash = _sha256(input_pdf)

            report = build_report(
                input_pdf,
                output_pdf=output_pdf,
                apply=True,
                fixture_mode=False,
                allow_structure_construction_trial=True,
            )

            self.assertTrue(output_pdf.exists())
            self.assertEqual(_sha256(input_pdf), before_hash)
            self.assertFalse(report["rule_map_mutation_performed"])
            self.assertFalse(report["workspace_artifacts_mutated"])
            self.assertFalse(report["safe_to_claim_production_ready"])
            self.assertFalse(report["decision"]["production_default_activation_allowed"])

    def test_after_diagnostic_uses_same_higher_bound_for_large_trial_apply(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10a_form_widget_large_apply_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            field_count = MAX_WIDGETS_DEFAULT + 2
            generate_fixture(input_pdf, field_count=field_count)

            report = build_report(
                input_pdf,
                output_pdf=output_pdf,
                apply=True,
                fixture_mode=False,
                allow_structure_construction_trial=True,
                max_widgets=MAX_WIDGETS_DEFAULT + 10,
            )

            self.assertTrue(output_pdf.exists())
            self.assertEqual(report["before"]["widgets_bounded_count"], field_count)
            self.assertEqual(report["after"]["widgets_bounded_count"], field_count)
            self.assertFalse(report["before"]["widgets_truncated"])
            self.assertFalse(report["after"]["widgets_truncated"])
            self.assertTrue(report["before"]["widget_evidence_complete"])
            self.assertTrue(report["after"]["widget_evidence_complete"])
            self.assertEqual(report["after"]["widgets_missing_struct_parent_count"], 0)

    def test_apply_requires_explicit_distinct_output_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10_form_widget_output_guard_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            generate_fixture(input_pdf, field_count=1)

            missing_output = build_report(input_pdf, apply=True, fixture_mode=True)
            same_output = build_report(input_pdf, output_pdf=input_pdf, apply=True, fixture_mode=True)

            self.assertIn("apply mode requires explicit --output path", missing_output["decision"]["blockers"])
            self.assertIn("output path must not overwrite input PDF", same_output["decision"]["blockers"])
            self.assertFalse(missing_output["repair_performed"])
            self.assertFalse(same_output["repair_performed"])

    def test_apply_cannot_write_into_workspace_package_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10_form_widget_workspace_guard_") as td:
            root = Path(td)
            input_pdf = root / "input.pdf"
            generate_fixture(input_pdf, field_count=1)
            forbidden_output = Path("/app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable/final/output.pdf")

            report = build_report(
                input_pdf,
                output_pdf=forbidden_output,
                apply=True,
                fixture_mode=False,
                allow_structure_construction_trial=True,
            )

            self.assertEqual(report["decision"]["terminal_state"], H10_TERMINAL_DRY_RUN_BLOCKED)
            self.assertFalse(report["repair_performed"])
            self.assertIn("workspace job/final package/status", " ".join(report["apply_blockers"]))


if __name__ == "__main__":
    unittest.main()
