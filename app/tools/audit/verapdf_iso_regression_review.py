#!/usr/bin/env python3
"""Review ISO-32000-1 tagged-profile before/after veraPDF evidence.

H10C uses this helper to compare the informational ISO profile sidecars that
surround the guarded PDF/UA-1/7.18.4 form-widget repair trial. The helper is
strictly evidence-only: it does not mutate PDFs, rule maps, workspace jobs,
packages, or STATUS files.
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SCHEMA = "montefiore.verapdf_iso_regression_review"
VERSION = "1.0.0"
ISO_PROFILE_ID = "PDF_UA/ISO-32000-1-Tagged.xml"

BENIGN_INFORMATIONAL = "BENIGN_INFORMATIONAL"
PROFILE_ACCOUNTING_ARTIFACT = "PROFILE_ACCOUNTING_ARTIFACT"
VALIDATOR_INTERPRETATION_ONLY = "VALIDATOR_INTERPRETATION_ONLY"
STRUCTURAL_SIDE_EFFECT = "STRUCTURAL_SIDE_EFFECT"
INCONCLUSIVE = "INCONCLUSIVE"
ALLOWED_CLASSIFICATIONS = {
    BENIGN_INFORMATIONAL,
    PROFILE_ACCOUNTING_ARTIFACT,
    VALIDATOR_INTERPRETATION_ONLY,
    STRUCTURAL_SIDE_EFFECT,
    INCONCLUSIVE,
}

STRUCTURE_TERMS = {
    "form": ("/Form", "form", "widget", "annotation"),
    "struct_tree_root": ("StructTreeRoot", "/StructTreeRoot"),
    "parent_tree": ("ParentTree", "/ParentTree"),
    "objr": ("OBJR", "/OBJR"),
    "struct_parent": ("StructParent", "/StructParent", "StructParents", "/StructParents"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _iter_tag(root: ET.Element, tag: str) -> Iterable[ET.Element]:
    for elem in root.iter():
        if _strip_ns(elem.tag) == tag:
            yield elem


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _rule_id(rule: ET.Element) -> str:
    explicit = rule.get("id") or rule.get("ruleId") or rule.get("ruleID")
    if explicit:
        return explicit
    specification = rule.get("specification") or rule.get("standard") or "ISO-32000-1"
    clause = rule.get("clause") or rule.get("testNumber") or rule.get("name") or "unknown"
    return f"{specification}/{clause}"


def _collect_context(rule: ET.Element) -> List[str]:
    contexts: List[str] = []
    for key, value in sorted(rule.attrib.items()):
        if value:
            contexts.append(f"{key}={value}")
    for child in rule.iter():
        if child is rule:
            continue
        tag = _strip_ns(child.tag)
        text = (child.text or "").strip()
        if text:
            contexts.append(f"{tag}:{text}")
        for key, value in sorted(child.attrib.items()):
            if value:
                contexts.append(f"{tag}.{key}={value}")
    # Preserve order while deduplicating.
    return list(dict.fromkeys(contexts))


def parse_iso_xml(xml_path: Path) -> Dict[str, Any]:
    if not xml_path.exists():
        return {
            "path": str(xml_path),
            "result": "NOT_RUN",
            "parseable": False,
            "parse_error": "output XML missing",
            "failed_rules": [],
            "failed_rule_counts": {},
            "total_failed_checks": None,
        }
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        return {
            "path": str(xml_path),
            "result": "PARSE_ERROR",
            "parseable": False,
            "parse_error": f"{type(exc).__name__}: {exc}",
            "failed_rules": [],
            "failed_rule_counts": {},
            "total_failed_checks": None,
        }

    saw_report = False
    noncompliant_reports = 0
    failed_rules: Dict[str, Dict[str, Any]] = {}
    for report in list(_iter_tag(root, "validationReport")) + list(_iter_tag(root, "arlingtonReport")):
        saw_report = True
        if report.get("isCompliant", "true").lower() != "true":
            noncompliant_reports += 1
        for details in _iter_tag(report, "details"):
            for rule in _iter_tag(details, "rule"):
                failed_checks = _safe_int(rule.get("failedChecks", rule.get("deviations", 0)))
                if failed_checks <= 0:
                    continue
                rid = _rule_id(rule)
                record = failed_rules.setdefault(
                    rid,
                    {
                        "rule_id": rid,
                        "specification": rule.get("specification", ""),
                        "clause": rule.get("clause", ""),
                        "description": rule.get("description", ""),
                        "failed_checks": 0,
                        "passed_checks": 0,
                        "contexts": [],
                    },
                )
                record["failed_checks"] += failed_checks
                record["passed_checks"] += _safe_int(rule.get("passedChecks", 0))
                record["contexts"].extend(_collect_context(rule))
                record["contexts"] = list(dict.fromkeys(record["contexts"]))

    if not saw_report and xml_path.stat().st_size > 0:
        return {
            "path": str(xml_path),
            "result": "PARSE_ERROR",
            "parseable": False,
            "parse_error": "no recognised veraPDF validation report elements",
            "failed_rules": [],
            "failed_rule_counts": {},
            "total_failed_checks": None,
        }

    failed_rule_list = sorted(failed_rules.values(), key=lambda item: item["rule_id"])
    failed_rule_counts = {item["rule_id"]: item["failed_checks"] for item in failed_rule_list}
    total_failed_checks = sum(failed_rule_counts.values())
    result = "PASS" if total_failed_checks == 0 and noncompliant_reports == 0 else "FAIL"
    return {
        "path": str(xml_path),
        "result": result,
        "parseable": True,
        "parse_error": "",
        "failed_rules": failed_rule_list,
        "failed_rule_counts": failed_rule_counts,
        "total_failed_checks": total_failed_checks,
    }


def _find_iso_record(accounting: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for profile in accounting.get("profiles", []):
        if profile.get("profile_id") == ISO_PROFILE_ID:
            return profile
    return None


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text())


def _accounting_result(accounting: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[bool]]:
    record = _find_iso_record(accounting)
    if not record:
        return None, None, None
    return record.get("result"), record.get("classification"), record.get("verdict_authoritative")


def _changed_rules(before_counts: Mapping[str, int], after_counts: Mapping[str, int]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    all_rules = set(before_counts) | set(after_counts)
    new_ids = sorted(rule for rule in all_rules if before_counts.get(rule, 0) == 0 and after_counts.get(rule, 0) > 0)
    increased_ids = sorted(rule for rule in all_rules if before_counts.get(rule, 0) > 0 and after_counts.get(rule, 0) > before_counts.get(rule, 0))
    changes = [
        {
            "rule_id": rule,
            "before_failed_checks": before_counts.get(rule, 0),
            "after_failed_checks": after_counts.get(rule, 0),
            "delta": after_counts.get(rule, 0) - before_counts.get(rule, 0),
        }
        for rule in sorted(new_ids + increased_ids)
    ]
    return new_ids, increased_ids, changes


def _joined_context(after_failed_rules: List[Mapping[str, Any]], changed_rule_ids: Iterable[str]) -> str:
    changed = set(changed_rule_ids)
    parts: List[str] = []
    for rule in after_failed_rules:
        if rule.get("rule_id") not in changed:
            continue
        parts.append(str(rule.get("rule_id", "")))
        parts.append(str(rule.get("description", "")))
        parts.extend(str(item) for item in rule.get("contexts", []))
    return "\n".join(parts)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _correlations(context_text: str, repair_report: Mapping[str, Any]) -> Dict[str, Any]:
    report_text = json.dumps(repair_report, sort_keys=True) if repair_report else ""
    combined = f"{context_text}\n{report_text}"
    return {
        "correlation_to_form_widget_objects": _contains_any(combined, STRUCTURE_TERMS["form"]),
        "correlation_to_struct_tree_root": _contains_any(combined, STRUCTURE_TERMS["struct_tree_root"]),
        "correlation_to_parent_tree": _contains_any(combined, STRUCTURE_TERMS["parent_tree"]),
        "correlation_to_objr": _contains_any(combined, STRUCTURE_TERMS["objr"]),
        "correlation_to_struct_parent": _contains_any(combined, STRUCTURE_TERMS["struct_parent"]),
    }


def classify_review(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    before_accounting: Mapping[str, Any],
    after_accounting: Mapping[str, Any],
    correlations: Mapping[str, Any],
    new_rule_ids: List[str],
    increased_rule_ids: List[str],
) -> Tuple[str, bool, bool, str]:
    if not before.get("parseable") or not after.get("parseable"):
        return INCONCLUSIVE, True, True, "ISO XML sidecar missing or unparseable; adoption cannot proceed."

    before_acc_result, before_classification, before_authoritative = _accounting_result(before_accounting)
    after_acc_result, after_classification, after_authoritative = _accounting_result(after_accounting)
    if before_accounting or after_accounting:
        if before_classification and before_classification != "informational":
            return PROFILE_ACCOUNTING_ARTIFACT, True, True, "Before accounting does not classify ISO profile as informational."
        if after_classification and after_classification != "informational":
            return PROFILE_ACCOUNTING_ARTIFACT, True, True, "After accounting does not classify ISO profile as informational."
        if before_authoritative or after_authoritative:
            return PROFILE_ACCOUNTING_ARTIFACT, True, True, "ISO profile became authoritative in profile accounting."
        if before_acc_result and before_acc_result != before.get("result"):
            return PROFILE_ACCOUNTING_ARTIFACT, True, True, "Before XML result and profile accounting result disagree."
        if after_acc_result and after_acc_result != after.get("result"):
            return PROFILE_ACCOUNTING_ARTIFACT, True, True, "After XML result and profile accounting result disagree."

    if not new_rule_ids and not increased_rule_ids:
        return BENIGN_INFORMATIONAL, False, True, "ISO sidecars show no new or increased failed checks."

    if any(bool(value) for key, value in correlations.items() if key.startswith("correlation_to_")):
        return STRUCTURAL_SIDE_EFFECT, True, True, "New or increased ISO checks correlate with form-widget or structure-construction evidence."

    if before.get("result") == "PASS" and after.get("result") == "FAIL":
        return INCONCLUSIVE, True, True, "ISO changed PASS to FAIL, but failed-check context is insufficient to classify cause."

    return INCONCLUSIVE, True, True, "ISO failed checks changed without enough evidence to classify as benign or repair-caused."


def build_review(
    before_xml: Path,
    after_xml: Path,
    before_accounting_path: Optional[Path] = None,
    after_accounting_path: Optional[Path] = None,
    repair_report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    before = parse_iso_xml(before_xml)
    after = parse_iso_xml(after_xml)
    before_accounting = _load_json(before_accounting_path)
    after_accounting = _load_json(after_accounting_path)
    repair_report = _load_json(repair_report_path)
    new_rule_ids, increased_rule_ids, changed_checks = _changed_rules(
        before.get("failed_rule_counts", {}) or {},
        after.get("failed_rule_counts", {}) or {},
    )
    changed_ids = sorted(set(new_rule_ids) | set(increased_rule_ids))
    context_text = _joined_context(after.get("failed_rules", []), changed_ids)
    correlations = _correlations(context_text, repair_report)
    classification, blocks_metadata, blocks_runtime, recommendation = classify_review(
        before,
        after,
        before_accounting,
        after_accounting,
        correlations,
        new_rule_ids,
        increased_rule_ids,
    )
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": utc_now(),
        "before_iso_xml": str(before_xml),
        "after_iso_xml": str(after_xml),
        "before_iso_result": before.get("result"),
        "after_iso_result": after.get("result"),
        "before_parseable": before.get("parseable"),
        "after_parseable": after.get("parseable"),
        "before_parse_error": before.get("parse_error"),
        "after_parse_error": after.get("parse_error"),
        "before_failed_rules": before.get("failed_rules", []),
        "after_failed_rules": after.get("failed_rules", []),
        "new_iso_rule_ids": new_rule_ids,
        "increased_iso_rule_ids": increased_rule_ids,
        "new_or_increased_iso_checks": changed_checks,
        "affected_objects_or_contexts_if_extractable": context_text.splitlines(),
        **correlations,
        "classification": classification,
        "allowed_classifications": sorted(ALLOWED_CLASSIFICATIONS),
        "blocks_metadata_adoption": blocks_metadata,
        "blocks_runtime_activation": blocks_runtime,
        "recommendation": recommendation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-xml", required=True)
    parser.add_argument("--after-xml", required=True)
    parser.add_argument("--before-accounting")
    parser.add_argument("--after-accounting")
    parser.add_argument("--repair-report")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    review = build_review(
        Path(args.before_xml),
        Path(args.after_xml),
        Path(args.before_accounting) if args.before_accounting else None,
        Path(args.after_accounting) if args.after_accounting else None,
        Path(args.repair_report) if args.repair_report else None,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n")
    print(json.dumps(review, indent=2, sort_keys=True))
    return 0 if review["classification"] != INCONCLUSIVE else 1


if __name__ == "__main__":
    raise SystemExit(main())
