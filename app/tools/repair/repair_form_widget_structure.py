#!/usr/bin/env python3
"""Guarded repair/trial tool for PDF/UA-1/7.18.4 form-widget structure.

H9 proved a controlled structure-construction capability on synthetic fixtures.
H10 keeps production behavior disabled while allowing non-mutating non-fixture
dry-runs and an explicitly flagged isolated trial apply for MM-17179-style PDFs.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.audit.form_widget_structure_inspection import TARGET_RULE, inspect_pdf_with_pikepdf

SCHEMA = "montefiore.form_widget_structure_repair"
VERSION = "1.1.0"

H10_TERMINAL_DRY_RUN_BLOCKED = "MM17179_DRY_RUN_BLOCKED"
H10_TERMINAL_ATTEMPTED_NOT_ADOPTED = "MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED"
H10_TERMINAL_VALIDATED = "MM17179_REPAIR_VALIDATED"
H10_TERMINAL_DRY_RUN_READY = "MM17179_DRY_RUN_READY"

POLICY_BASE = {
    "rule_map_mutation_performed": False,
    "workspace_artifacts_mutated": False,
    "safe_to_claim_production_ready": False,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_pikepdf() -> Any:
    try:
        import pikepdf  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"pikepdf unavailable: {type(exc).__name__}: {exc}") from exc
    return pikepdf


def _field_signature(evidence: dict[str, Any]) -> list[tuple[str, str, bool]]:
    fields = evidence.get("acroform_fields") or []
    return sorted((str(f.get("field_name", "")), str(f.get("field_type", "")), bool(f.get("field_value_present"))) for f in fields)


def _widget_signature(evidence: dict[str, Any]) -> list[tuple[int, str, str, tuple[float, ...]]]:
    widgets = evidence.get("widgets") or []
    out: list[tuple[int, str, str, tuple[float, ...]]] = []
    for widget in widgets:
        rect = tuple(float(v) for v in widget.get("rect", [])[:4])
        out.append((int(widget.get("page_index", 0)), str(widget.get("field_name", "")), str(widget.get("field_type", "")), rect))
    return sorted(out)


def _page_boxes(evidence: dict[str, Any]) -> list[tuple[int, tuple[float, ...], tuple[float, ...]]]:
    out: list[tuple[int, tuple[float, ...], tuple[float, ...]]] = []
    for page in evidence.get("page_boxes") or []:
        out.append((
            int(page.get("page_index", 0)),
            tuple(float(v) for v in page.get("media_box", [])[:4]),
            tuple(float(v) for v in page.get("crop_box", [])[:4]),
        ))
    return out


def planned_changes(before: dict[str, Any]) -> dict[str, Any]:
    widget_count = int(before.get("widget_annotation_count", 0) or 0)
    missing = int(before.get("widgets_missing_struct_parent_count", 0) or 0)
    mapped = int(before.get("widgets_with_parent_tree_mapping_count", 0) or 0)
    existing_form = int(before.get("form_struct_element_count", 0) or 0)
    return {
        "assign_struct_parent_count": missing,
        "create_struct_tree_root": not bool(before.get("struct_tree_root_present")),
        "create_parent_tree": not bool(before.get("parent_tree_present")),
        "create_form_struct_elements_count": max(0, widget_count - existing_form),
        "parent_tree_entries_to_create": max(0, widget_count - mapped),
        "k_array_updates_to_create": max(0, widget_count - int(before.get("widgets_already_nested_in_form_count", 0) or 0)),
        "planned_struct_parent_assignments": missing,
        "planned_form_struct_elements": widget_count,
        "planned_parent_tree_entries": widget_count,
        "planned_struct_tree_root_creation": not bool(before.get("struct_tree_root_present")),
        "planned_parent_tree_creation": not bool(before.get("parent_tree_present")),
    }


def _mm17179_summary(before: dict[str, Any]) -> dict[str, Any]:
    return {
        "widget_annotation_count": int(before.get("widget_annotation_count", 0) or 0),
        "widgets_missing_struct_parent_count": int(before.get("widgets_missing_struct_parent_count", 0) or 0),
        "widgets_with_struct_parent_count": int(before.get("widgets_with_struct_parent_count", 0) or 0),
        "struct_tree_root_present": bool(before.get("struct_tree_root_present")),
        "parent_tree_present": bool(before.get("parent_tree_present")),
        "form_struct_element_count": int(before.get("form_struct_element_count", 0) or 0),
        "planned_struct_parent_assignments": int(before.get("widgets_missing_struct_parent_count", 0) or 0),
        "planned_form_struct_elements": int(before.get("widget_annotation_count", 0) or 0),
        "planned_parent_tree_entries": int(before.get("widget_annotation_count", 0) or 0),
        "planned_struct_tree_root_creation": not bool(before.get("struct_tree_root_present")),
        "planned_parent_tree_creation": not bool(before.get("parent_tree_present")),
        "field_count": int(before.get("acroform_field_count", 0) or 0),
        "field_names_types_value_presence_preservation_inputs": _field_signature(before),
        "page_count": int(before.get("page_count", 0) or 0),
        "page_boxes_preservation_inputs": _page_boxes(before),
    }


def _precondition_report(before: dict[str, Any]) -> dict[str, Any]:
    satisfied: list[str] = []
    failed: list[str] = []

    def check(condition: bool, name: str) -> None:
        (satisfied if condition else failed).append(name)

    check(bool(before.get("available")), "input PDF is inspectable")
    check(bool(before.get("acroform_present")), "AcroForm is present")
    check(int(before.get("widget_annotation_count", 0) or 0) > 0, "widget annotations are present")
    check(not bool(before.get("widgets_truncated")), "widget evidence is not truncated")
    check(int(before.get("widgets_referenced_from_non_form_count", 0) or 0) == 0, "widgets are not already mapped to non-Form structure")
    check(not bool(before.get("parent_tree_has_kids")), "ParentTree does not require /Kids number-tree mutation")
    return {"satisfied": satisfied, "failed": failed}


def _apply_blockers(
    before: dict[str, Any],
    *,
    output_pdf: Path | None,
    apply: bool,
    fixture_mode: bool,
    allow_structure_construction_trial: bool,
    input_pdf: Path,
) -> list[str]:
    blockers = list(_precondition_report(before)["failed"])
    if apply and not (fixture_mode or allow_structure_construction_trial):
        blockers.append("non-fixture apply requires --allow-structure-construction-trial")
    if apply and output_pdf is None:
        blockers.append("apply mode requires explicit --output path")
    if apply and output_pdf is not None:
        try:
            if input_pdf.resolve() == output_pdf.resolve():
                blockers.append("output path must not overwrite input PDF")
        except FileNotFoundError:
            if input_pdf.absolute() == output_pdf.absolute():
                blockers.append("output path must not overwrite input PDF")
        output_text = str(output_pdf)
        forbidden_parts = (
            "/app/workspace/jobs/",
            "workspace/jobs/",
            "/final",
            "STATUS.json",
            "orchestrator_outcome.json",
        )
        if any(part in output_text for part in forbidden_parts):
            blockers.append("trial apply output must not target workspace job/final package/status paths")
    return blockers


def _iter_widget_annotations(pdf: Any) -> list[tuple[int, Any, Any]]:
    widgets: list[tuple[int, Any, Any]] = []
    for page_index, page in enumerate(pdf.pages, start=1):
        page_obj = getattr(page, "obj", page)
        annots = page_obj.get("/Annots", []) if hasattr(page_obj, "get") else []
        try:
            annot_list = list(annots or [])
        except Exception:
            annot_list = []
        for annot in annot_list:
            try:
                if annot.get("/Subtype") == "/Widget":
                    widgets.append((page_index, page_obj, annot))
            except Exception:
                continue
    return widgets


def _ensure_struct_tree_root(pdf: Any, pikepdf: Any) -> Any:
    root = pdf.Root
    struct_root = root.get("/StructTreeRoot")
    if struct_root is None:
        struct_root = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructTreeRoot"),
            "/K": pikepdf.Array([]),
        }))
        root["/StructTreeRoot"] = struct_root
    if struct_root.get("/K") is None:
        struct_root["/K"] = pikepdf.Array([])
    parent_tree = struct_root.get("/ParentTree")
    if parent_tree is None:
        parent_tree = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array([])}))
        struct_root["/ParentTree"] = parent_tree
    if parent_tree.get("/Nums") is None:
        parent_tree["/Nums"] = pikepdf.Array([])
    return struct_root


def apply_fixture_repair(input_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    pikepdf = _load_pikepdf()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if input_pdf.resolve() == output_pdf.resolve():
        raise ValueError("output path must differ from input path")

    pdf = pikepdf.Pdf.open(input_pdf)
    with pdf:
        struct_root = _ensure_struct_tree_root(pdf, pikepdf)
        parent_tree = struct_root["/ParentTree"]
        nums = parent_tree["/Nums"]
        root_k = struct_root["/K"]
        widgets = _iter_widget_annotations(pdf)

        next_key = 0
        existing_nums = list(nums)
        if existing_nums:
            keys = []
            for index in range(0, len(existing_nums) - 1, 2):
                try:
                    keys.append(int(existing_nums[index]))
                except Exception:
                    continue
            next_key = max(keys) + 1 if keys else 0

        created = 0
        assigned = 0
        for _page_index, page_obj, widget in widgets:
            try:
                current_struct_parent = widget.get("/StructParent")
            except Exception:
                current_struct_parent = None
            if current_struct_parent is None:
                struct_parent = next_key
                next_key += 1
                widget["/StructParent"] = struct_parent
                assigned += 1
            else:
                struct_parent = int(current_struct_parent)

            objr = pikepdf.Dictionary({
                "/Type": pikepdf.Name("/OBJR"),
                "/Obj": widget,
            })
            form_elem = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Form"),
                "/P": struct_root,
                "/Pg": page_obj,
                "/K": objr,
            }))
            root_k.append(form_elem)
            nums.append(struct_parent)
            nums.append(form_elem)
            created += 1

        parent_tree["/ParentTreeNextKey"] = next_key
        pdf.save(output_pdf)

    return {
        "assigned_struct_parent_count": assigned,
        "created_form_struct_elements_count": created,
        "parent_tree_entries_created": created,
    }


def run_qpdf_check(pdf_path: Path) -> dict[str, Any]:
    qpdf = shutil.which("qpdf")
    if not qpdf:
        return {"result": "NOT_RUN_ENVIRONMENT_LIMITED", "reason": "qpdf not found"}
    proc = subprocess.run([qpdf, "--check", str(pdf_path)], capture_output=True, text=True, timeout=60)
    return {
        "result": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def preservation_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "field_count_preserved": before.get("acroform_field_count") == after.get("acroform_field_count"),
        "field_names_preserved": [x[0] for x in _field_signature(before)] == [x[0] for x in _field_signature(after)],
        "field_types_preserved": [x[1] for x in _field_signature(before)] == [x[1] for x in _field_signature(after)],
        "field_value_presence_preserved": [x[2] for x in _field_signature(before)] == [x[2] for x in _field_signature(after)],
        "widget_count_preserved": before.get("widget_annotation_count") == after.get("widget_annotation_count"),
        "widget_page_membership_preserved": _widget_signature(before) == _widget_signature(after),
        "page_count_preserved": before.get("page_count") == after.get("page_count"),
        "page_boxes_preserved": _page_boxes(before) == _page_boxes(after),
        "semantic_widget_identity_preserved": _widget_signature(before) == _widget_signature(after),
        "exact_object_identity_claimed": False,
        "field_values_not_dumped": bool(after.get("sensitive_field_values_redacted")),
    }


def _all_preserved(preservation: dict[str, Any]) -> bool:
    required = [
        "field_count_preserved",
        "field_names_preserved",
        "field_types_preserved",
        "field_value_presence_preserved",
        "widget_count_preserved",
        "widget_page_membership_preserved",
        "page_count_preserved",
        "page_boxes_preserved",
        "field_values_not_dumped",
    ]
    return all(bool(preservation.get(key)) for key in required)


def _after_object_gate(after: dict[str, Any]) -> bool:
    widget_count = int(after.get("widget_annotation_count", 0) or 0)
    return (
        widget_count > 0
        and int(after.get("widgets_missing_struct_parent_count", 0) or 0) == 0
        and int(after.get("widgets_with_struct_parent_count", 0) or 0) == widget_count
        and bool(after.get("struct_tree_root_present"))
        and bool(after.get("parent_tree_present"))
        and int(after.get("form_struct_element_count", 0) or 0) >= widget_count
        and int(after.get("widgets_with_parent_tree_mapping_count", 0) or 0) == widget_count
        and int(after.get("widgets_already_nested_in_form_count", 0) or 0) == widget_count
    )


def build_report(
    input_pdf: Path,
    *,
    output_pdf: Path | None = None,
    apply: bool = False,
    fixture_mode: bool = False,
    allow_structure_construction_trial: bool = False,
) -> dict[str, Any]:
    mode = "apply" if apply else "dry_run"
    before = inspect_pdf_with_pikepdf(input_pdf)
    preconditions = _precondition_report(before)
    blockers = _apply_blockers(
        before,
        output_pdf=output_pdf,
        apply=apply,
        fixture_mode=fixture_mode,
        allow_structure_construction_trial=allow_structure_construction_trial,
        input_pdf=input_pdf,
    )
    apply_allowed = not blockers
    dry_run_terminal = H10_TERMINAL_DRY_RUN_READY if apply_allowed else H10_TERMINAL_DRY_RUN_BLOCKED
    if not before.get("available"):
        dry_run_terminal = H10_TERMINAL_DRY_RUN_BLOCKED

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": now(),
        "result": "DRY_RUN" if not apply and apply_allowed else ("DRY_RUN_BLOCKED" if not apply else "APPLY_ATTEMPTED"),
        "mode": mode,
        "fixture_mode": fixture_mode,
        "allow_structure_construction_trial": allow_structure_construction_trial,
        "input_pdf": str(input_pdf),
        "output_pdf": str(output_pdf) if output_pdf and apply else None,
        "target_rule": TARGET_RULE,
        "read_only": not apply,
        "repair_performed": False,
        **POLICY_BASE,
        "before": before,
        "before_object_evidence": before,
        "mm17179_evidence_summary": _mm17179_summary(before),
        "planned_changes": planned_changes(before),
        "preconditions_satisfied": preconditions["satisfied"],
        "preconditions_failed": preconditions["failed"],
        "apply_allowed": apply_allowed,
        "apply_blockers": blockers,
        "after": {},
        "preservation": {},
        "validation": {
            "qpdf_result": {"result": "NOT_RUN_NO_OUTPUT"},
            "verapdf_result_if_run": {"result": "NOT_RUN_ENVIRONMENT_LIMITED"},
            "form_widget_diagnostic_result_after": "NOT_RUN_NO_OUTPUT",
        },
        "decision": {
            "terminal_state": dry_run_terminal,
            "adoption_allowed": False,
            "production_default_activation_allowed": False,
            "blockers": blockers,
        },
    }

    if not apply:
        return report

    if not apply_allowed:
        report["result"] = "BLOCKED_BEFORE_IMPLEMENTATION"
        report["read_only"] = True
        report["decision"]["terminal_state"] = H10_TERMINAL_DRY_RUN_BLOCKED
        return report

    if output_pdf is None:  # defensive; should already be blocked above
        report["result"] = "BLOCKED_BEFORE_IMPLEMENTATION"
        report["read_only"] = True
        report["decision"]["terminal_state"] = H10_TERMINAL_DRY_RUN_BLOCKED
        report["decision"]["blockers"].append("apply mode requires explicit --output path")
        return report

    mutation = apply_fixture_repair(input_pdf, output_pdf)
    after = inspect_pdf_with_pikepdf(output_pdf)
    preservation = preservation_summary(before, after)
    qpdf_result = run_qpdf_check(output_pdf)
    object_gate = _after_object_gate(after)
    preservation_gate = _all_preserved(preservation)
    qpdf_gate = qpdf_result.get("result") == "PASS"

    validation_blockers: list[str] = []
    if not object_gate:
        validation_blockers.append("after diagnostic did not prove complete widget-to-Form structure construction")
    if not preservation_gate:
        validation_blockers.append("preservation check failed")
    if not qpdf_gate:
        validation_blockers.append("qpdf did not pass or was not available")

    terminal = H10_TERMINAL_VALIDATED if not validation_blockers else H10_TERMINAL_ATTEMPTED_NOT_ADOPTED
    report.update({
        "result": "APPLIED" if terminal == H10_TERMINAL_VALIDATED else "APPLIED_NOT_ADOPTED",
        "read_only": False,
        "repair_performed": True,
        "mutation_summary": mutation,
        "after": after,
        "after_object_evidence": after,
        "preservation": preservation,
        "validation": {
            "qpdf_result": qpdf_result,
            "verapdf_result_if_run": {"result": "NOT_RUN_ENVIRONMENT_LIMITED"},
            "form_widget_diagnostic_result_after": after.get("result", ""),
        },
        "decision": {
            "terminal_state": terminal,
            "adoption_allowed": terminal == H10_TERMINAL_VALIDATED,
            "production_default_activation_allowed": False,
            "blockers": validation_blockers,
        },
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded PDF/UA-1/7.18.4 form-widget structure repair/trial")
    parser.add_argument("--input", required=True, help="Input PDF path")
    parser.add_argument("--output", default="", help="Output PDF path for apply mode")
    parser.add_argument("--dry-run-report", required=True, help="JSON report path for dry-run/apply")
    parser.add_argument("--apply", action="store_true", help="Write repaired PDF to --output")
    parser.add_argument("--fixture-mode", action="store_true", help="Allow controlled synthetic fixture repair path")
    parser.add_argument(
        "--allow-structure-construction-trial",
        action="store_true",
        help="Allow explicit non-production, non-fixture isolated trial apply",
    )
    args = parser.parse_args(argv)

    output_path = Path(args.output) if args.output else None
    report = build_report(
        Path(args.input),
        output_pdf=output_path,
        apply=bool(args.apply),
        fixture_mode=bool(args.fixture_mode),
        allow_structure_construction_trial=bool(args.allow_structure_construction_trial),
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    report_path = Path(args.dry_run_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
