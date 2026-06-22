#!/usr/bin/env python3
"""Inspect real-PDF blocker evidence for MM-17179 style escalations.

This diagnostic is intentionally read-only. It does not repair PDFs, mutate job
artifacts, weaken validator output, or update the rule map. Its purpose is to
collect the object-level evidence required before a safe strategy can be chosen
for PDF/UA-1/7.18.4 form-widget tagging, PDF/UA-1/7.21.7 ToUnicode gaps, and
PDF/UA-1/7.21.4.1 font embedding/unknown-rule failures.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

TARGET_RULES = ("PDF/UA-1/7.18.4", "PDF/UA-1/7.21.7", "PDF/UA-1/7.21.4.1")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        return {"available": False, "path": str(path), "error": f"{type(exc).__name__}: {exc}"}


def normalize_rule_map_state(rule_map: dict[str, Any], rule_id: str) -> dict[str, Any]:
    rules = rule_map.get("rules", {}) if isinstance(rule_map, dict) else {}
    entry = rules.get(rule_id) if isinstance(rules, dict) else None
    if not isinstance(entry, dict):
        return {
            "rule_id": rule_id,
            "present_in_rule_map": False,
            "reason": "unknown_rule",
            "resolvability": "repairable_unbuilt",
            "has_repair_script": False,
            "strategies_count": 0,
            "safe_to_execute": False,
        }

    strategies = entry.get("strategies") if isinstance(entry.get("strategies"), list) else []
    has_strategy_script = any(isinstance(s, dict) and bool(s.get("repair_script")) for s in strategies)
    has_legacy_script = bool(entry.get("repair_script"))
    resolvability = str(entry.get("resolvability") or "") or (
        "repairable_unbuilt" if not has_strategy_script and not has_legacy_script else "effective"
    )
    reason = "mapped_strategy_available" if has_strategy_script or has_legacy_script else "mapped_without_executable_strategy"
    if entry.get("manual") and not strategies:
        reason = "manual_no_strategies"

    return {
        "rule_id": rule_id,
        "present_in_rule_map": True,
        "description": entry.get("description", ""),
        "reason": reason,
        "resolvability": resolvability,
        "has_repair_script": has_strategy_script or has_legacy_script,
        "strategies_count": len(strategies),
        "safe_to_execute": bool(has_strategy_script or has_legacy_script) and resolvability == "effective",
        "entry_excerpt": {
            key: entry.get(key)
            for key in ("manual", "repair_script", "repair_order", "confidence", "notes", "resolvability", "emits_review_artifact")
            if key in entry
        },
    }


def load_job_artifacts(job_dir: Path) -> dict[str, Any]:
    audit = job_dir / "audit"
    names = {
        "status": job_dir / "STATUS.json",
        "orchestrator_outcome": audit / "orchestrator_outcome.json",
        "hermes_signals": audit / "hermes_signals.json",
        "residual_analysis": audit / "residual_analysis.json",
        "strategy_gap": audit / "strategy_gap.json",
        "hermes_strategy_request": audit / "hermes_strategy_request.json",
        "repair_plan": audit / "repair_plan.json",
        "execution_log": audit / "execution_log.json",
        "post_pdfua_summary": audit / "verapdf_post_pdfua1_summary.json",
    }
    out: dict[str, Any] = {}
    for key, path in names.items():
        out[key] = {"available": path.exists(), "path": str(path)}
        if path.exists():
            data = read_json(path)
            out[key]["data"] = data
    xml = audit / "verapdf_post_pdfua1.xml"
    out["post_pdfua_xml"] = {"available": xml.exists(), "path": str(xml)}
    return out


def _name(value: Any) -> str:
    return str(value) if value is not None else ""


def inspect_pdf_with_pikepdf(pdf_path: Path) -> dict[str, Any]:
    try:
        import pikepdf  # type: ignore
    except Exception as exc:
        return {"available": False, "dependency": "pikepdf", "error": f"{type(exc).__name__}: {exc}"}

    if not pdf_path.exists():
        return {"available": False, "path": str(pdf_path), "error": "pdf not found"}

    try:
        pdf = pikepdf.Pdf.open(pdf_path)
    except Exception as exc:
        return {"available": False, "path": str(pdf_path), "error": f"{type(exc).__name__}: {exc}"}

    with pdf:
        root = pdf.Root
        struct = root.get("/StructTreeRoot")
        parent_tree = struct.get("/ParentTree") if struct else None
        widgets = []
        for page_index, page in enumerate(pdf.pages, start=1):
            for annot in page.obj.get("/Annots", []) or []:
                try:
                    if annot.get("/Subtype") != "/Widget":
                        continue
                    widgets.append({
                        "page": page_index,
                        "objgen": list(getattr(annot, "objgen", ()) or ()),
                        "field_type": _name(annot.get("/FT")),
                        "field_name": _name(annot.get("/T")),
                        "struct_parent": annot.get("/StructParent"),
                        "has_contents": bool(annot.get("/Contents")),
                        "rect": [float(x) for x in (annot.get("/Rect") or [])],
                    })
                except Exception:
                    continue

        form_struct_count = 0
        struct_elements_seen = 0
        for obj in pdf.objects:
            try:
                if not hasattr(obj, "get"):
                    continue
                if obj.get("/Type") == "/StructElem":
                    struct_elements_seen += 1
                    if obj.get("/S") == "/Form":
                        form_struct_count += 1
            except Exception:
                continue

        fonts = []
        for obj in pdf.objects:
            try:
                if not hasattr(obj, "get") or obj.get("/Type") != "/Font":
                    continue
                fd = obj.get("/FontDescriptor")
                embedded_keys = [k for k in ("/FontFile", "/FontFile2", "/FontFile3") if fd and k in fd]
                fonts.append({
                    "objgen": list(getattr(obj, "objgen", ()) or ()),
                    "subtype": _name(obj.get("/Subtype")),
                    "basefont": _name(obj.get("/BaseFont")),
                    "has_to_unicode": bool(obj.get("/ToUnicode")),
                    "has_font_descriptor": bool(fd),
                    "embedded_keys": embedded_keys,
                    "descendant_count": len(obj.get("/DescendantFonts", []) or []),
                })
            except Exception:
                continue

        return {
            "available": True,
            "path": str(pdf_path),
            "page_count": len(pdf.pages),
            "acroform_present": bool(root.get("/AcroForm")),
            "acroform_field_count": len(root.get("/AcroForm", {}).get("/Fields", []) or []) if root.get("/AcroForm") else 0,
            "struct_tree_root_present": bool(struct),
            "parent_tree_present": bool(parent_tree),
            "widget_count": len(widgets),
            "widgets_missing_struct_parent": sum(1 for w in widgets if w.get("struct_parent") is None),
            "widgets": widgets[:100],
            "struct_element_count": struct_elements_seen,
            "form_struct_element_count": form_struct_count,
            "font_count": len(fonts),
            "fonts_missing_to_unicode": [f for f in fonts if not f.get("has_to_unicode")],
            "fonts_without_embedded_program": [f for f in fonts if not f.get("embedded_keys")],
            "fonts": fonts[:100],
        }


def inspect_pdf_with_pymupdf(pdf_path: Path) -> dict[str, Any]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return {"available": False, "dependency": "PyMuPDF", "error": f"{type(exc).__name__}: {exc}"}

    if not pdf_path.exists():
        return {"available": False, "path": str(pdf_path), "error": "pdf not found"}

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        return {"available": False, "path": str(pdf_path), "error": f"{type(exc).__name__}: {exc}"}

    fonts = []
    seen = set()
    for page_num, page in enumerate(doc, start=1):
        for font in page.get_fonts(full=True):
            xref, ext, font_type, basefont, name, enc, referencer = font
            if xref in seen:
                continue
            seen.add(xref)
            normalized_ext = str(ext or "").strip().lower()
            embedded = bool(normalized_ext) and normalized_ext not in {"n/a", "na", "none", "null"}
            has_to_unicode = None
            if xref:
                try:
                    has_to_unicode = doc.xref_get_key(xref, "ToUnicode")[0] != "null"
                except Exception:
                    pass
            fonts.append({
                "page_first_seen": page_num,
                "xref": xref,
                "extension": ext,
                "type": font_type,
                "basefont": basefont,
                "name": name or basefont,
                "encoding": enc,
                "embedded": embedded,
                "has_to_unicode": has_to_unicode,
            })
    return {
        "available": True,
        "path": str(pdf_path),
        "page_count": len(doc),
        "font_count": len(fonts),
        "fonts_missing_to_unicode": [f for f in fonts if f.get("has_to_unicode") is False],
        "fonts_not_embedded": [f for f in fonts if not f.get("embedded")],
        "fonts": fonts,
    }


def summarize_decision(rule_states: dict[str, Any], pike: dict[str, Any], pymu: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if not pike.get("available"):
        blockers.append("pikepdf object inspection unavailable")
    if not pymu.get("available"):
        blockers.append("PyMuPDF font inventory unavailable")
    if pike.get("available"):
        if pike.get("widget_count", 0) == 0:
            blockers.append("no widget annotations found for 7.18.4 inspection")
        if not pike.get("parent_tree_present"):
            blockers.append("ParentTree absent or unavailable; widget tagging repair unsafe")
    if rule_states.get("PDF/UA-1/7.21.4.1", {}).get("present_in_rule_map") is False:
        blockers.append("PDF/UA-1/7.21.4.1 absent from rule map; remains unknown_rule")

    return {
        "chosen_option": "C" if blockers else "B",
        "repair_implementation_safe_now": False,
        "reason": "insufficient object-level evidence for a deterministic repair" if blockers else "strategy design evidence collected; implementation still requires validation",
        "blockers": blockers,
        "required_next_evidence": [
            "post-repair veraPDF XML snippets for the three target rules",
            "widget StructParent to ParentTree mapping",
            "existing /Form structure element paths or proof they are absent",
            "font objects/xrefs causing missing ToUnicode and embedding failures",
            "before/after preservation audit, form field audit, render compare, and veraPDF delta after any repair attempt",
        ],
    }


def build_report(job_dir: Path, pdf_path: Path, rule_map_path: Path) -> dict[str, Any]:
    rule_map = read_json(rule_map_path) if rule_map_path.exists() else {"rules": {}}
    rule_states = {rule: normalize_rule_map_state(rule_map, rule) for rule in TARGET_RULES}
    pike = inspect_pdf_with_pikepdf(pdf_path)
    pymu = inspect_pdf_with_pymupdf(pdf_path)
    return {
        "schema": "montefiore.mm17179_blocker_inspection",
        "result": "INSUFFICIENT_EVIDENCE" if not pike.get("available") or not pymu.get("available") else "INSPECTED",
        "job_dir": str(job_dir),
        "pdf_path": str(pdf_path),
        "rule_map_path": str(rule_map_path),
        "target_rules": list(TARGET_RULES),
        "rule_map_state": rule_states,
        "job_artifacts": load_job_artifacts(job_dir),
        "pdf_object_inspection": pike,
        "font_inventory": pymu,
        "decision": summarize_decision(rule_states, pike, pymu),
        "policy": {
            "read_only": True,
            "repair_performed": False,
            "rule_map_mutation_performed": False,
            "workspace_artifacts_mutated": False,
            "safe_to_claim_production_ready": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--rule-map", default="app/tools/audit/rule_repair_map.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    report = build_report(Path(args.job_dir), Path(args.pdf), Path(args.rule_map))
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
