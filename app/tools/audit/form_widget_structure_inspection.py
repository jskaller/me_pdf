#!/usr/bin/env python3
"""Read-only object-level diagnostic for PDF/UA-1/7.18.4 form-widget evidence.

Patch H7 is design-first. This module inspects widget annotations,
AcroForm metadata, StructParent values, ParentTree mappings, and /Form structure
presence so a later patch can decide whether a deterministic repair is safe.
It never mutates PDFs, workspace artifacts, repair scripts, rule maps, status
files, or deliverable packages.

Patch H10A keeps the default bounded report behavior, but records explicit
widget evidence completeness fields so guarded repair dry-runs can request a
higher bound and refuse to apply when widget records are still truncated.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "montefiore.form_widget_structure_inspection"
VERSION = "1.1.0"
TARGET_RULE = "PDF/UA-1/7.18.4"
MAX_WIDGETS_DEFAULT = 100
MAX_FIELDS_DEFAULT = 100
MAX_STRUCT_ELEMENTS_DEFAULT = 100


POLICY = {
    "read_only": True,
    "repair_performed": False,
    "rule_map_mutation_performed": False,
    "workspace_artifacts_mutated": False,
    "safe_to_claim_production_ready": False,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[1:] if text.startswith("/") else text


def _safe_bool(value: Any) -> bool:
    try:
        return bool(value)
    except Exception:
        return False


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _safe_float_list(value: Any, limit: int = 8) -> list[float]:
    out: list[float] = []
    try:
        for item in list(value or [])[:limit]:
            out.append(float(item))
    except Exception:
        return []
    return out


def _safe_objgen(obj: Any) -> str:
    try:
        objgen = getattr(obj, "objgen", None)
        if objgen:
            values = list(objgen)
            if len(values) >= 2:
                return f"{values[0]} {values[1]}"
            if values:
                return str(values[0])
    except Exception:
        pass
    return ""


def _get(obj: Any, key: str, default: Any = None) -> Any:
    try:
        if hasattr(obj, "get"):
            return obj.get(key, default)
    except Exception:
        return default
    return default


def _has_key(obj: Any, key: str) -> bool:
    try:
        return key in obj
    except Exception:
        return False


def _field_name_from_widget(widget: Any) -> str:
    name = _get(widget, "/T")
    if name is not None:
        return str(name)
    parent = _get(widget, "/Parent")
    parent_name = _get(parent, "/T")
    return str(parent_name) if parent_name is not None else ""


def _field_type_from_widget(widget: Any) -> str:
    value = _get(widget, "/FT")
    if value is not None:
        return _name(value)
    parent = _get(widget, "/Parent")
    parent_value = _get(parent, "/FT")
    return _name(parent_value)


def _field_value_present(widget: Any) -> bool:
    if _get(widget, "/V") is not None:
        return True
    parent = _get(widget, "/Parent")
    return _get(parent, "/V") is not None


def _field_value_type(widget: Any) -> str:
    value = _get(widget, "/V")
    if value is None:
        value = _get(_get(widget, "/Parent"), "/V")
    if value is None:
        return ""
    return type(value).__name__


def _parent_tree_shape(parent_tree: Any) -> dict[str, Any]:
    if not parent_tree:
        return {"present": False, "type": "", "has_nums": False, "has_kids": False, "entry_count": 0, "next_key": None}
    nums = _get(parent_tree, "/Nums") or []
    kids = _get(parent_tree, "/Kids") or []
    entry_count = 0
    try:
        entry_count = len(nums) // 2 if nums else 0
    except Exception:
        entry_count = 0
    return {
        "present": True,
        "type": _name(_get(parent_tree, "/Type")) or type(parent_tree).__name__,
        "has_nums": bool(nums),
        "has_kids": bool(kids),
        "entry_count": entry_count,
        "next_key": _safe_int(_get(parent_tree, "/ParentTreeNextKey")),
    }


def _parent_tree_lookup(parent_tree: Any) -> dict[int, Any]:
    """Best-effort lookup for simple ParentTree /Nums arrays.

    This intentionally avoids mutating the tree and does not attempt to rewrite
    number-tree /Kids. If a PDF uses /Kids, the diagnostic reports the shape but
    may not resolve every mapping.
    """
    lookup: dict[int, Any] = {}
    nums = _get(parent_tree, "/Nums") or []
    try:
        values = list(nums)
    except Exception:
        values = []
    for index in range(0, len(values) - 1, 2):
        key = _safe_int(values[index])
        if key is not None:
            lookup[key] = values[index + 1]
    return lookup


def _struct_ancestor_types(struct_elem: Any, limit: int = 25) -> list[str]:
    types: list[str] = []
    seen: set[str] = set()
    current = struct_elem
    for _ in range(limit):
        if not current:
            break
        objgen = _safe_objgen(current)
        if objgen and objgen in seen:
            break
        if objgen:
            seen.add(objgen)
        kind = _name(_get(current, "/S"))
        if kind:
            types.append(kind)
        current = _get(current, "/P")
    return types


def _walk_struct_k_for_widget_reference(value: Any, target_objgen: str, depth: int = 0) -> bool:
    if depth > 12 or not target_objgen:
        return False
    if _safe_objgen(value) == target_objgen:
        return True
    try:
        if isinstance(value, (list, tuple)):
            return any(_walk_struct_k_for_widget_reference(item, target_objgen, depth + 1) for item in value)
    except Exception:
        return False
    nested = _get(value, "/Obj")
    if nested is not None and _safe_objgen(nested) == target_objgen:
        return True
    nested_k = _get(value, "/K")
    if nested_k is not None and nested_k is not value:
        return _walk_struct_k_for_widget_reference(nested_k, target_objgen, depth + 1)
    return False


def _widget_referenced_by_struct_element(struct_elem: Any, widget_objgen: str) -> bool:
    return _walk_struct_k_for_widget_reference(_get(struct_elem, "/K"), widget_objgen)


def _iter_pdf_objects(pdf: Any) -> list[Any]:
    try:
        return list(pdf.objects)
    except Exception:
        return []


def _collect_struct_elements(pdf: Any, limit: int) -> tuple[int, list[Any], list[dict[str, Any]]]:
    form_objects: list[Any] = []
    bounded: list[dict[str, Any]] = []
    count = 0
    for obj in _iter_pdf_objects(pdf):
        if _get(obj, "/Type") != "/StructElem":
            continue
        count += 1
        kind = _name(_get(obj, "/S"))
        if kind == "Form":
            form_objects.append(obj)
        if len(bounded) < limit:
            bounded.append({
                "objgen": _safe_objgen(obj),
                "type": kind,
                "parent_objgen": _safe_objgen(_get(obj, "/P")),
                "has_k": _get(obj, "/K") is not None,
            })
    return count, form_objects, bounded


def _collect_acroform_fields(acroform: Any, limit: int) -> tuple[int, list[dict[str, Any]]]:
    fields = _get(acroform, "/Fields") or []
    try:
        field_list = list(fields)
    except Exception:
        field_list = []
    bounded: list[dict[str, Any]] = []
    for field in field_list[:limit]:
        bounded.append({
            "field_objgen": _safe_objgen(field),
            "field_name": str(_get(field, "/T") or ""),
            "field_type": _name(_get(field, "/FT")),
            "field_value_present": _get(field, "/V") is not None,
            "field_value_type": type(_get(field, "/V")).__name__ if _get(field, "/V") is not None else "",
            "kid_count": len(list(_get(field, "/Kids") or [])) if _get(field, "/Kids") is not None else 0,
        })
    return len(field_list), bounded


def inspect_pdf_with_pikepdf(pdf_path: Path, *, max_widgets: int = MAX_WIDGETS_DEFAULT) -> dict[str, Any]:
    max_widgets = max(1, int(max_widgets or MAX_WIDGETS_DEFAULT))
    if not pdf_path.exists():
        return {
            "available": False,
            "path": str(pdf_path),
            "error": "pdf not found",
            "result": "INSUFFICIENT_EVIDENCE",
        }
    try:
        import pikepdf  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "path": str(pdf_path),
            "dependency": "pikepdf",
            "error": f"{type(exc).__name__}: {exc}",
            "result": "INSUFFICIENT_EVIDENCE",
        }
    try:
        pdf = pikepdf.Pdf.open(pdf_path)
    except Exception as exc:
        return {
            "available": False,
            "path": str(pdf_path),
            "error": f"{type(exc).__name__}: {exc}",
            "result": "INSUFFICIENT_EVIDENCE",
        }

    with pdf:
        root = pdf.Root
        acroform = _get(root, "/AcroForm")
        struct_tree_root = _get(root, "/StructTreeRoot")
        parent_tree = _get(struct_tree_root, "/ParentTree") if struct_tree_root else None
        parent_tree_info = _parent_tree_shape(parent_tree)
        parent_tree_lookup = _parent_tree_lookup(parent_tree)
        struct_element_count, form_struct_objects, bounded_structs = _collect_struct_elements(pdf, MAX_STRUCT_ELEMENTS_DEFAULT)
        acroform_field_count, bounded_fields = _collect_acroform_fields(acroform, MAX_FIELDS_DEFAULT) if acroform else (0, [])

        widgets: list[dict[str, Any]] = []
        total_widgets = 0
        missing_struct_parent = 0
        with_struct_parent = 0
        with_mapping = 0
        without_mapping = 0
        already_nested_count = 0
        non_form_reference_count = 0
        page_count = len(pdf.pages)
        page_boxes: list[dict[str, Any]] = []

        for page_index, page in enumerate(pdf.pages, start=1):
            page_obj = getattr(page, "obj", page)
            if len(page_boxes) < 20:
                page_boxes.append({
                    "page_index": page_index,
                    "media_box": _safe_float_list(_get(page_obj, "/MediaBox"), 4),
                    "crop_box": _safe_float_list(_get(page_obj, "/CropBox"), 4),
                    "struct_parents": _safe_int(_get(page_obj, "/StructParents")),
                })
            annots = _get(page_obj, "/Annots") or []
            try:
                annot_list = list(annots)
            except Exception:
                annot_list = []
            for annot in annot_list:
                if _get(annot, "/Subtype") != "/Widget":
                    continue
                total_widgets += 1
                struct_parent = _safe_int(_get(annot, "/StructParent"))
                if struct_parent is None:
                    missing_struct_parent += 1
                else:
                    with_struct_parent += 1
                mapped = parent_tree_lookup.get(struct_parent) if struct_parent is not None else None
                mapping_present = mapped is not None
                if mapping_present:
                    with_mapping += 1
                elif struct_parent is not None:
                    without_mapping += 1
                mapped_type = _name(_get(mapped, "/S"))
                ancestor_types = _struct_ancestor_types(mapped)
                already_nested = "Form" in ancestor_types
                if already_nested:
                    already_nested_count += 1
                referenced_from_form = any(_widget_referenced_by_struct_element(form, _safe_objgen(annot)) for form in form_struct_objects)
                referenced_from_non_form = bool(mapping_present and mapped_type and "Form" not in ancestor_types)
                if referenced_from_non_form:
                    non_form_reference_count += 1
                if len(widgets) < max_widgets:
                    widgets.append({
                        "page_index": page_index,
                        "annotation_objgen": _safe_objgen(annot),
                        "field_name": _field_name_from_widget(annot),
                        "field_type": _field_type_from_widget(annot),
                        "field_value_present": _field_value_present(annot),
                        "field_value_type": _field_value_type(annot),
                        "rect": _safe_float_list(_get(annot, "/Rect"), 4),
                        "struct_parent": struct_parent,
                        "parent_tree_mapping_present": mapping_present,
                        "mapped_struct_element_type": mapped_type,
                        "mapped_struct_element_objgen": _safe_objgen(mapped),
                        "mapped_struct_ancestor_types": ancestor_types[:10],
                        "already_nested_in_form": already_nested or referenced_from_form,
                        "referenced_from_form_element": referenced_from_form,
                        "referenced_from_non_form_element": referenced_from_non_form,
                        "parent_field_objgen": _safe_objgen(_get(annot, "/Parent")),
                        "page_annotation_membership": True,
                    })

        widgets_bounded_count = len(widgets)
        widgets_truncated = total_widgets > widgets_bounded_count
        widget_evidence_complete = (not widgets_truncated) and widgets_bounded_count == total_widgets
        return {
            "available": True,
            "result": "INSPECTED",
            "path": str(pdf_path),
            "page_count": page_count,
            "page_boxes": page_boxes,
            "acroform_present": bool(acroform),
            "acroform_field_count": acroform_field_count,
            "acroform_fields": bounded_fields,
            "struct_tree_root_present": bool(struct_tree_root),
            "parent_tree_present": bool(parent_tree),
            "parent_tree_type": parent_tree_info["type"],
            "parent_tree_has_nums": parent_tree_info["has_nums"],
            "parent_tree_has_kids": parent_tree_info["has_kids"],
            "parent_tree_entry_count": parent_tree_info["entry_count"],
            "parent_tree_next_key": parent_tree_info["next_key"],
            "struct_element_count": struct_element_count,
            "struct_elements": bounded_structs,
            "form_struct_element_count": len(form_struct_objects),
            "form_struct_elements": [
                {"objgen": _safe_objgen(obj), "has_k": _get(obj, "/K") is not None}
                for obj in form_struct_objects[:MAX_STRUCT_ELEMENTS_DEFAULT]
            ],
            "widget_annotation_count": total_widgets,
            "widgets_missing_struct_parent_count": missing_struct_parent,
            "widgets_with_struct_parent_count": with_struct_parent,
            "widgets_with_parent_tree_mapping_count": with_mapping,
            "widgets_without_parent_tree_mapping_count": without_mapping,
            "widgets_already_nested_in_form_count": already_nested_count,
            "widgets_referenced_from_non_form_count": non_form_reference_count,
            "widgets_bounded_count": widgets_bounded_count,
            "bounded_widget_records_count": widgets_bounded_count,
            "widgets_truncated": widgets_truncated,
            "widget_evidence_complete": widget_evidence_complete,
            "max_widgets_requested": max_widgets,
            "widgets": widgets,
            "adding_form_elements_would_require_parent_tree_mutation": total_widgets > with_mapping or len(form_struct_objects) == 0,
            "adding_form_elements_would_require_k_array_mutation": total_widgets > already_nested_count,
            "sensitive_field_values_redacted": True,
        }


def decide_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    required_next_evidence: list[str] = []

    if not evidence.get("available"):
        blockers.append("pikepdf object inspection unavailable")
    if evidence.get("widget_annotation_count", 0) == 0:
        blockers.append("no widget annotations found")
    if evidence.get("widgets_truncated"):
        blockers.append("widget evidence is truncated")
    if evidence.get("widget_annotation_count", 0) > 0 and evidence.get("widgets_with_struct_parent_count", 0) == 0:
        blockers.append("widgets lack /StructParent values")
    if not evidence.get("struct_tree_root_present"):
        blockers.append("/StructTreeRoot missing")
    if not evidence.get("parent_tree_present"):
        blockers.append("/ParentTree missing")
    if evidence.get("widgets_with_struct_parent_count", 0) > evidence.get("widgets_with_parent_tree_mapping_count", 0):
        blockers.append("one or more widget /StructParent values do not map through /ParentTree")
    if not evidence.get("acroform_present"):
        required_next_evidence.append("AcroForm presence or proof that widgets are not interactive form fields")
    if evidence.get("form_struct_element_count", 0) == 0:
        required_next_evidence.append("safe insertion point for future /Form structure elements")
    if evidence.get("adding_form_elements_would_require_parent_tree_mutation"):
        required_next_evidence.append("ParentTree mutation plan with before/after object evidence")
    if evidence.get("adding_form_elements_would_require_k_array_mutation"):
        required_next_evidence.append("K-array mutation plan preserving existing structure children")

    if blockers:
        option = "C"
        design_ready = False
        reason = "insufficient or unsafe object-level evidence for a deterministic future repair"
    elif required_next_evidence:
        option = "B"
        design_ready = False
        reason = "partial object-level evidence exists, but more design evidence is required before implementation"
    else:
        option = "A"
        design_ready = True
        reason = "object-level evidence suggests a deterministic repair may be designable in a later patch"

    return {
        "chosen_option": option,
        "repair_implementation_safe_now": False,
        "design_ready_for_future_patch": design_ready,
        "reason": reason,
        "blockers": blockers,
        "required_next_evidence": required_next_evidence,
    }


def build_report(pdf_path: Path, job_dir: Path | None = None, *, max_widgets: int = MAX_WIDGETS_DEFAULT) -> dict[str, Any]:
    evidence = inspect_pdf_with_pikepdf(pdf_path, max_widgets=max_widgets)
    decision = decide_from_evidence(evidence)
    result = "INSPECTED" if evidence.get("available") else "INSUFFICIENT_EVIDENCE"
    if decision["chosen_option"] == "C":
        result = "INSUFFICIENT_EVIDENCE"
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": now(),
        "result": result,
        "target_rule": TARGET_RULE,
        "pdf_path": str(pdf_path),
        "job_dir": str(job_dir) if job_dir else "",
        "max_widgets": max(1, int(max_widgets or MAX_WIDGETS_DEFAULT)),
        **POLICY,
        "pdf_object_evidence": evidence,
        "decision": decision,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only PDF/UA-1/7.18.4 form-widget structure diagnostic")
    parser.add_argument("pdf", help="PDF path to inspect")
    parser.add_argument("--job-dir", default="", help="Optional workspace job directory for report context")
    parser.add_argument("--out", default="", help="Optional JSON output path")
    parser.add_argument("--max-widgets", type=int, default=MAX_WIDGETS_DEFAULT, help="Maximum widget entries to include")
    args = parser.parse_args(argv)

    report = build_report(Path(args.pdf), Path(args.job_dir) if args.job_dir else None, max_widgets=max(1, args.max_widgets))
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
