#!/usr/bin/env python3
"""
font_tounicode_diagnostics.py

H12 diagnostic gate for PDF/UA-1/7.21.7 candidate repair creation.

This module is intentionally conservative.  A generated ToUnicode repair may only
be attempted when the PDF/font/content evidence proves a deterministic mapping
from character codes to Unicode.  OCR, visual inference, font-name guessing, or
hard-coded mappings are not accepted as authoritative evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TARGET_RULE = "PDF/UA-1/7.21.7"
TERMINAL_BLOCKED_BY_MISSING_EVIDENCE = "AGENT_CANDIDATE_REPAIR_BLOCKED_BY_MISSING_EVIDENCE"
GATE_READY_FOR_CANDIDATE_CREATION = "READY_FOR_AGENT_CANDIDATE_CREATION"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _pdf_name(value: Any) -> str:
    text = _clean(value)
    return text[1:] if text.startswith("/") else text


def _is_font_object(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    type_value = obj.get("/Type", obj.get("Type"))
    subtype = obj.get("/Subtype", obj.get("Subtype"))
    combined = f"{_clean(type_value)} {_clean(subtype)}"
    return _pdf_name(type_value) == "Font" or bool(subtype and "Font" in combined)


def _object_items(qpdf_json: Dict[str, Any]) -> Iterable[tuple[str, Dict[str, Any]]]:
    """Yield object-id/object-payload pairs from common qpdf JSON shapes."""
    objects = qpdf_json.get("objects")
    if isinstance(objects, dict):
        for object_id, payload in objects.items():
            if isinstance(payload, dict):
                value = payload.get("value", payload)
                if isinstance(value, dict):
                    yield str(object_id), value
    elif isinstance(objects, list):
        for idx, payload in enumerate(objects):
            if isinstance(payload, dict):
                object_id = str(payload.get("object") or payload.get("id") or idx)
                value = payload.get("value", payload)
                if isinstance(value, dict):
                    yield object_id, value

    trailer_pages = qpdf_json.get("pages")
    if isinstance(trailer_pages, list):
        for page_index, page in enumerate(trailer_pages):
            resources = (page.get("/Resources") or page.get("resources")) if isinstance(page, dict) else None
            fonts = resources.get("/Font") if isinstance(resources, dict) else None
            if isinstance(fonts, dict):
                for name, value in fonts.items():
                    if isinstance(value, dict):
                        yield f"page:{page_index}:{name}", value


def collect_font_records(qpdf_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for object_id, obj in _object_items(qpdf_json):
        if not _is_font_object(obj):
            continue
        descriptor = obj.get("/FontDescriptor") or obj.get("FontDescriptor") or {}
        if not isinstance(descriptor, dict):
            descriptor = {}
        records.append(
            {
                "object_id": object_id,
                "base_font": _pdf_name(obj.get("/BaseFont", obj.get("BaseFont"))),
                "subtype": _pdf_name(obj.get("/Subtype", obj.get("Subtype"))),
                "encoding": obj.get("/Encoding", obj.get("Encoding")),
                "differences": _extract_differences(obj),
                "to_unicode_present": "/ToUnicode" in obj or "ToUnicode" in obj,
                "font_descriptor_present": bool(descriptor),
                "font_file_present": any(
                    key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3", "FontFile", "FontFile2", "FontFile3")
                ),
                "widths_present": "/Widths" in obj or "Widths" in obj,
                "cid_to_gid_map_present": "/CIDToGIDMap" in obj or "CIDToGIDMap" in obj,
            }
        )
    return records


def _extract_differences(obj: Dict[str, Any]) -> List[Any]:
    encoding = obj.get("/Encoding", obj.get("Encoding"))
    if isinstance(encoding, dict):
        differences = encoding.get("/Differences", encoding.get("Differences", []))
        return differences if isinstance(differences, list) else []
    return []


def target_missing_tounicode_fonts(font_records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(record) for record in font_records if not bool(record.get("to_unicode_present"))]


def deterministic_mapping_evidence(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a per-font evidence verdict for safe ToUnicode creation.

    The gate is deliberately stricter than merely finding an Encoding.  It must
    see a declared font subtype, some authoritative encoding/Differences/CID map
    evidence, and actual character-code usage evidence supplied by the caller.
    """
    missing: List[str] = []
    if not _clean(record.get("subtype")):
        missing.append("font_subtype")
    if record.get("encoding") in (None, "") and not record.get("differences") and not record.get("cid_to_gid_map_present"):
        missing.append("encoding_or_cid_mapping")
    if not record.get("character_code_usage_evidence"):
        missing.append("character_code_usage_evidence")
    if record.get("mapping_source") in {"ocr", "visual_inference", "guess", "hardcoded"}:
        missing.append("authoritative_mapping_source")

    return {
        "object_id": record.get("object_id"),
        "base_font": record.get("base_font"),
        "deterministic_mapping_available": not missing,
        "missing_evidence": missing,
    }


def build_tounicode_repair_readiness_report(
    *,
    font_records: Iterable[Dict[str, Any]],
    active_failure_count: int,
    text_extraction_before: Optional[Dict[str, Any]] = None,
    render_comparison_available: bool = False,
    h11_artifacts_available: bool = False,
) -> Dict[str, Any]:
    records = [dict(record) for record in font_records]
    missing_fonts = target_missing_tounicode_fonts(records)
    per_font = [deterministic_mapping_evidence(record) for record in missing_fonts]
    missing_report_evidence: List[str] = []
    if not h11_artifacts_available:
        missing_report_evidence.append("h11_runtime_artifacts_unavailable_locally")
    if active_failure_count <= 0:
        missing_report_evidence.append("no_active_target_failures_supplied")
    if not missing_fonts:
        missing_report_evidence.append("no_missing_tounicode_font_records_supplied")
    if not text_extraction_before:
        missing_report_evidence.append("actual_text_extraction_before_repair")
    if not render_comparison_available:
        missing_report_evidence.append("rendered_text_comparison_before_after")

    deterministic = bool(missing_fonts) and all(item["deterministic_mapping_available"] for item in per_font)
    repair_allowed = deterministic and not missing_report_evidence

    return {
        "schema": "h12_font_tounicode_repair_readiness_v1",
        "target_rule": TARGET_RULE,
        "active_failure_count": int(active_failure_count),
        "font_count": len(records),
        "missing_tounicode_font_count": len(missing_fonts),
        "missing_tounicode_fonts": missing_fonts,
        "per_font_deterministic_mapping_evidence": per_font,
        "missing_report_evidence": missing_report_evidence,
        "repair_allowed": repair_allowed,
        "candidate_creation_allowed": repair_allowed,
        "candidate_gate_state": GATE_READY_FOR_CANDIDATE_CREATION if repair_allowed else TERMINAL_BLOCKED_BY_MISSING_EVIDENCE,
        "terminal_state_if_stopped_here": None if repair_allowed else TERMINAL_BLOCKED_BY_MISSING_EVIDENCE,
        "forbidden_sources": ["ocr", "visual_inference", "guess", "hardcoded"],
        "safe_to_claim_pass": False,
        "safe_to_claim_production_ready": False,
    }


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="H12 ToUnicode deterministic evidence gate")
    parser.add_argument("qpdf_json", help="qpdf JSON file or a prepared font-record JSON file")
    parser.add_argument("--active-failure-count", type=int, default=0)
    parser.add_argument("--font-records", action="store_true", help="Input is already {'font_records': [...]} rather than qpdf JSON")
    parser.add_argument("--h11-artifacts-available", action="store_true")
    parser.add_argument("--render-comparison-available", action="store_true")
    parser.add_argument("--text-extraction-before", default="", help="Optional JSON text-extraction evidence")
    parser.add_argument("--out", default="")
    ns = parser.parse_args(argv)

    data = load_json(Path(ns.qpdf_json))
    font_records = data.get("font_records", []) if ns.font_records else collect_font_records(data)
    text_before = load_json(Path(ns.text_extraction_before)) if ns.text_extraction_before else None
    report = build_tounicode_repair_readiness_report(
        font_records=font_records,
        active_failure_count=ns.active_failure_count,
        text_extraction_before=text_before,
        render_comparison_available=ns.render_comparison_available,
        h11_artifacts_available=ns.h11_artifacts_available,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if ns.out:
        Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
        Path(ns.out).write_text(text)
    print(text, end="")
    return 0 if report["repair_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
