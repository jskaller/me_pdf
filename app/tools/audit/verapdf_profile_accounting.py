#!/usr/bin/env python3
"""Profile accounting and delta helper for repo-approved veraPDF runs.

This helper records which validation profiles exist, which runner sidecars were
produced, whether required XML sidecars are parseable, and whether a target rule
improved between before/after parsed veraPDF evidence. It is evidence-only: it
never mutates PDFs, rule maps, packages, workspace artifacts, or STATUS files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SCHEMA = "montefiore.verapdf_profile_accounting"
VERSION = "1.0.0"
TARGET_PDFUA_VERSION = "PDF/UA-1"

TERMINAL_DELTA_VALIDATED = "VERAPDF_DELTA_VALIDATED"
TERMINAL_DELTA_FAILED = "VERAPDF_DELTA_FAILED"
TERMINAL_PROFILE_ACCOUNTING_FAILED = "VERAPDF_PROFILE_ACCOUNTING_FAILED"
TERMINAL_RUN_FAILED = "VERAPDF_RUN_FAILED"

VERDICT_VALIDATED = "VALIDATED_FOR_ADOPTION_CONSIDERATION"
VERDICT_REJECTED = "REJECTED_BY_VERAPDF_DELTA"
VERDICT_PROFILE_BLOCKED = "PROFILE_ACCOUNTING_BLOCKED"

REQUIRED_AUTHORITATIVE = "required_authoritative"
OPTIONAL_AUTHORITATIVE_IF_PRESENT = "optional_authoritative_if_present"
INFORMATIONAL = "informational"
EXPERIMENTAL_DIAGNOSTIC = "experimental_diagnostic"
PROHIBITED_FOR_PDFUA1 = "prohibited_for_pdfua1"
SKIPPED_BY_POLICY = "skipped_by_policy"
MISSING_REQUIRED = "missing_required"

REQUIRED_PDFUA1_PROFILES = ("PDF_UA/PDFUA-1.xml", "PDF_UA/WCAG-2-2-Machine.xml")
INFORMATIONAL_PROFILES = ("PDF_UA/ISO-32000-1-Tagged.xml",)
SKIPPED_PDFUA1_PROFILES = ("PDF_UA/PDFUA-2.xml",)
PROHIBITED_PDFUA1_PROFILES = ("PDF_UA/WCAG-2-2-Machine-PDF20.xml",)
RUNNER_OUTPUTS = {
    "PDF_UA/PDFUA-1.xml": "verapdf_pdfua_ua1.xml",
    "PDF_UA/WCAG-2-2-Machine.xml": "verapdf_wcag_2_2_machine.xml",
    "PDF_UA/ISO-32000-1-Tagged.xml": "verapdf_iso_32000_1_tagged.xml",
    "PDF_UA/PDFUA-2.xml": "verapdf_pdfua2.xml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_profile(profile_id: str, *, target_pdfua_version: str = TARGET_PDFUA_VERSION,
                     include_pdfua2: bool = False) -> str:
    if target_pdfua_version == "PDF/UA-1" and profile_id in REQUIRED_PDFUA1_PROFILES:
        return REQUIRED_AUTHORITATIVE
    if profile_id in INFORMATIONAL_PROFILES:
        return INFORMATIONAL
    if profile_id in PROHIBITED_PDFUA1_PROFILES:
        return PROHIBITED_FOR_PDFUA1
    lowered = profile_id.lower()
    if "pdf20" in lowered or "pdf-2" in lowered or "pdf_2" in lowered:
        return PROHIBITED_FOR_PDFUA1
    if profile_id in SKIPPED_PDFUA1_PROFILES or "pdfua-2" in lowered or "pdf/ua-2" in lowered:
        return OPTIONAL_AUTHORITATIVE_IF_PRESENT if include_pdfua2 else SKIPPED_BY_POLICY
    return EXPERIMENTAL_DIAGNOSTIC


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _iter_tag(root: ET.Element, tag: str) -> Iterable[ET.Element]:
    for elem in root.iter():
        if _strip_ns(elem.tag) == tag:
            yield elem


def parse_profile_xml_counts(xml_path: Path) -> Dict[str, Any]:
    if not xml_path.exists():
        return {"result": "NOT_RUN", "parseable": False, "failed_rules": None,
                "failed_checks": None, "passed_rules": None, "passed_checks": None,
                "parse_error": "output XML missing"}
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        return {"result": "PARSE_ERROR", "parseable": False, "failed_rules": None,
                "failed_checks": None, "passed_rules": None, "passed_checks": None,
                "parse_error": f"{type(exc).__name__}: {exc}"}
    failed_rules = failed_checks = passed_rules = passed_checks = 0
    saw_report = saw_rule = False
    noncompliant_reports = 0
    for report in list(_iter_tag(root, "validationReport")) + list(_iter_tag(root, "arlingtonReport")):
        saw_report = True
        if report.get("isCompliant", "true").lower() != "true":
            noncompliant_reports += 1
        for details in _iter_tag(report, "details"):
            for rule in _iter_tag(details, "rule"):
                saw_rule = True
                fc = int(rule.get("failedChecks", rule.get("deviations", 0)) or 0)
                pc = int(rule.get("passedChecks", 0) or 0)
                if fc > 0:
                    failed_rules += 1
                    failed_checks += fc
                else:
                    passed_rules += 1
                passed_checks += pc
    if not saw_report and not saw_rule and xml_path.stat().st_size > 0:
        return {"result": "PARSE_ERROR", "parseable": False, "failed_rules": None,
                "failed_checks": None, "passed_rules": None, "passed_checks": None,
                "parse_error": "no recognised veraPDF validation report elements"}
    return {"result": "PASS" if failed_checks == 0 and noncompliant_reports == 0 else "FAIL",
            "parseable": True, "failed_rules": failed_rules, "failed_checks": failed_checks,
            "passed_rules": passed_rules, "passed_checks": passed_checks, "parse_error": ""}


def profile_output_name(profile_id: str) -> str:
    if profile_id in RUNNER_OUTPUTS:
        return RUNNER_OUTPUTS[profile_id]
    safe = profile_id.replace("/", "_").replace("-", "_").replace(".", "_").lower()
    return f"verapdf_{safe}.xml"


def base_record(profile_id: str, profile_path: Optional[Path], classification: str,
                run_dir: Path, *, verapdf_bin: Path) -> Dict[str, Any]:
    output_xml = run_dir / profile_output_name(profile_id)
    stderr_sidecar = Path(str(output_xml) + ".stderr")
    was_run = output_xml.exists()
    counts = parse_profile_xml_counts(output_xml) if was_run else parse_profile_xml_counts(Path("/__missing_verapdf_output__.xml"))
    required = classification == REQUIRED_AUTHORITATIVE
    if classification == SKIPPED_BY_POLICY:
        skip_reason = "PDF/UA-2 profile is skipped for PDF/UA-1 unless explicitly requested"
    elif classification == PROHIBITED_FOR_PDFUA1:
        skip_reason = "prohibited for PDF/UA-1 verdict"
    elif required and not was_run:
        skip_reason = "missing required profile output"
    elif not was_run and classification == EXPERIMENTAL_DIAGNOSTIC:
        skip_reason = "experimental/custom profile not run by default"
    else:
        skip_reason = ""
    return {
        "profile_id": profile_id,
        "profile_path": str(profile_path) if profile_path else "",
        "profile_sha256": sha256_file(profile_path) if profile_path and profile_path.exists() else "",
        "profile_name_or_filename": Path(profile_id).name,
        "classification": classification,
        "required": required,
        "run_by_default": classification in {REQUIRED_AUTHORITATIVE, INFORMATIONAL},
        "was_run": was_run,
        "was_skipped": not was_run,
        "skip_reason": skip_reason,
        "verdict_authoritative": classification == REQUIRED_AUTHORITATIVE,
        "parse_for_rule_map": classification == REQUIRED_AUTHORITATIVE,
        "command": [str(verapdf_bin), "--format", "xml", "--verbose", "--maxfailuresdisplayed", "-1", "--profile", str(profile_path) if profile_path else ""],
        "output_xml": str(output_xml),
        "stderr_sidecar": str(stderr_sidecar) if stderr_sidecar.exists() else "",
        "exit_code": None,
        "result": counts["result"],
        "parseable": counts["parseable"],
        "parse_error": counts.get("parse_error", ""),
        "failed_rules": counts["failed_rules"],
        "failed_checks": counts["failed_checks"],
        "passed_rules": counts["passed_rules"],
        "passed_checks": counts["passed_checks"],
    }


def account_profiles(profiles_root: Path, run_dir: Path, *, verapdf_bin: Path,
                     target_pdfua_version: str = TARGET_PDFUA_VERSION,
                     include_pdfua2: bool = False) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    if profiles_root.exists():
        for path in sorted(profiles_root.rglob("*.xml")):
            profile_id = path.relative_to(profiles_root).as_posix()
            records.append(base_record(profile_id, path, classify_profile(profile_id,
                target_pdfua_version=target_pdfua_version, include_pdfua2=include_pdfua2),
                run_dir, verapdf_bin=verapdf_bin))
            seen.add(profile_id)
    for required in REQUIRED_PDFUA1_PROFILES:
        if required not in seen:
            records.append(base_record(required, None, MISSING_REQUIRED, run_dir, verapdf_bin=verapdf_bin))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": utc_now(),
        "target_pdfua_version": target_pdfua_version,
        "profiles_root": str(profiles_root),
        "run_dir": str(run_dir),
        "profiles": records,
        "required_profiles_missing": [r["profile_id"] for r in records if r["classification"] == MISSING_REQUIRED],
        "required_profiles_run": [r["profile_id"] for r in records if r["required"] and r["was_run"]],
        "required_profiles_parseable": [r["profile_id"] for r in records if r["required"] and r["parseable"]],
        "experimental_profiles": [r["profile_id"] for r in records if r["classification"] == EXPERIMENTAL_DIAGNOSTIC],
        "prohibited_profiles_seen": [r["profile_id"] for r in records if r["classification"] == PROHIBITED_FOR_PDFUA1],
    }


def load_parsed_failures(path: Path) -> Dict[str, int]:
    data = json.loads(path.read_text()) if path.exists() else {}
    return {str(i.get("rule_id")): int(i.get("failures", 0) or 0)
            for i in data.get("failures_by_rule", []) if i.get("rule_id")}


def _required_accounting_ok(accounting: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    blockers: List[str] = []
    profiles = {p.get("profile_id"): p for p in accounting.get("profiles", [])}
    for required in REQUIRED_PDFUA1_PROFILES:
        rec = profiles.get(required)
        if not rec:
            blockers.append(f"required profile not accounted: {required}")
            continue
        if rec.get("classification") != REQUIRED_AUTHORITATIVE:
            blockers.append(f"required profile misclassified: {required}")
        if not rec.get("profile_sha256"):
            blockers.append(f"required profile hash missing: {required}")
        if not rec.get("was_run"):
            blockers.append(f"required profile not run: {required}")
        if not rec.get("parseable"):
            blockers.append(f"required profile XML not parseable: {required}")
    pdf20 = profiles.get("PDF_UA/WCAG-2-2-Machine-PDF20.xml")
    if pdf20 and pdf20.get("was_run"):
        blockers.append("PDF20 WCAG profile was run for PDF/UA-1 verdict")
    return not blockers, blockers


def _profile_result(accounting: Mapping[str, Any], profile_id: str) -> Optional[str]:
    for record in accounting.get("profiles", []):
        if record.get("profile_id") == profile_id:
            return record.get("result")
    return None


def build_delta(profiles_root: Path, before_dir: Path, after_dir: Path,
                before_parsed: Path, after_parsed: Path, target_rule: str,
                *, verapdf_bin: Path = Path("/opt/verapdf-greenfield/verapdf"),
                before_pdf: str = "/app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf",
                after_pdf: str = "/tmp/h10a-mm17179-form-widget-trial/output.pdf") -> Dict[str, Any]:
    before_acc = account_profiles(profiles_root, before_dir, verapdf_bin=verapdf_bin)
    after_acc = account_profiles(profiles_root, after_dir, verapdf_bin=verapdf_bin)
    before_failures = load_parsed_failures(before_parsed)
    after_failures = load_parsed_failures(after_parsed)
    _, before_blockers = _required_accounting_ok(before_acc)
    _, after_blockers = _required_accounting_ok(after_acc)
    accounting_blockers = before_blockers + after_blockers
    before_count = before_failures.get(target_rule, 0)
    after_count = after_failures.get(target_rule, 0)
    if before_count == 0 and after_count == 0:
        target_status = "NOT_PRESENT_BEFORE"
    elif after_count == 0:
        target_status = "CLEARED"
    elif after_count < before_count:
        target_status = "IMPROVED"
    elif after_count == before_count:
        target_status = "UNCHANGED"
    else:
        target_status = "REGRESSED"
    all_rules = set(before_failures) | set(after_failures)
    new_rule_ids = sorted(r for r in all_rules if before_failures.get(r, 0) == 0 and after_failures.get(r, 0) > 0)
    increased_rule_ids = sorted(r for r in all_rules if before_failures.get(r, 0) > 0 and after_failures.get(r, 0) > before_failures.get(r, 0))
    cleared_rule_ids = sorted(r for r in all_rules if before_failures.get(r, 0) > 0 and after_failures.get(r, 0) == 0)
    improved_rule_ids = sorted(r for r in all_rules if after_failures.get(r, 0) > 0 and after_failures.get(r, 0) < before_failures.get(r, 0))
    unchanged_rule_ids = sorted(r for r in all_rules if before_failures.get(r, 0) > 0 and after_failures.get(r, 0) == before_failures.get(r, 0))
    regressed_rule_ids = sorted(r for r in all_rules if before_failures.get(r, 0) > 0 and after_failures.get(r, 0) > before_failures.get(r, 0))
    total_before = sum(before_failures.values())
    total_after = sum(after_failures.values())
    authoritative_regression = bool(new_rule_ids or increased_rule_ids or total_after > total_before)
    if accounting_blockers:
        terminal = TERMINAL_PROFILE_ACCOUNTING_FAILED
        verdict = VERDICT_PROFILE_BLOCKED
    elif target_status in {"CLEARED", "IMPROVED"} and not authoritative_regression:
        terminal = TERMINAL_DELTA_VALIDATED
        verdict = VERDICT_VALIDATED
    else:
        terminal = TERMINAL_DELTA_FAILED
        verdict = VERDICT_REJECTED
    return {
        "schema": "montefiore.verapdf_delta",
        "created_at": utc_now(),
        "target_pdfua_version": TARGET_PDFUA_VERSION,
        "before_pdf": before_pdf,
        "after_pdf": after_pdf,
        "verapdf_binary": str(verapdf_bin),
        "profiles_root": str(profiles_root),
        "profile_accounting_before": before_acc,
        "profile_accounting_after": after_acc,
        "required_profiles": list(REQUIRED_PDFUA1_PROFILES),
        "optional_profiles": list(INFORMATIONAL_PROFILES),
        "experimental_profiles": sorted(set(before_acc["experimental_profiles"]) | set(after_acc["experimental_profiles"])),
        "prohibited_profiles_seen": sorted(set(before_acc["prohibited_profiles_seen"]) | set(after_acc["prohibited_profiles_seen"])),
        "required_profiles_missing": sorted(set(before_acc["required_profiles_missing"]) | set(after_acc["required_profiles_missing"])),
        "required_profiles_run": sorted(set(before_acc["required_profiles_run"]) & set(after_acc["required_profiles_run"])),
        "required_profiles_parseable": sorted(set(before_acc["required_profiles_parseable"]) & set(after_acc["required_profiles_parseable"])),
        "target_rule": target_rule,
        "target_rule_before_count": before_count,
        "target_rule_after_count": after_count,
        "target_rule_delta": after_count - before_count,
        "target_rule_status": target_status,
        "total_failures_before": total_before,
        "total_failures_after": total_after,
        "new_rule_ids": new_rule_ids,
        "increased_rule_ids": increased_rule_ids,
        "cleared_rule_ids": cleared_rule_ids,
        "improved_rule_ids": improved_rule_ids,
        "unchanged_rule_ids": unchanged_rule_ids,
        "regressed_rule_ids": regressed_rule_ids,
        "pdfua1_profile_result_before": _profile_result(before_acc, "PDF_UA/PDFUA-1.xml"),
        "pdfua1_profile_result_after": _profile_result(after_acc, "PDF_UA/PDFUA-1.xml"),
        "wcag_profile_result_before": _profile_result(before_acc, "PDF_UA/WCAG-2-2-Machine.xml"),
        "wcag_profile_result_after": _profile_result(after_acc, "PDF_UA/WCAG-2-2-Machine.xml"),
        "iso_profile_result_before": _profile_result(before_acc, "PDF_UA/ISO-32000-1-Tagged.xml"),
        "iso_profile_result_after": _profile_result(after_acc, "PDF_UA/ISO-32000-1-Tagged.xml"),
        "experimental_profile_failures": [],
        "experimental_profile_failures_authoritative": False,
        "accounting_blockers": accounting_blockers,
        "verdict_candidate": verdict,
        "terminal_state": terminal,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles-root", required=True)
    parser.add_argument("--before-dir", required=True)
    parser.add_argument("--after-dir", required=True)
    parser.add_argument("--before-parsed", required=True)
    parser.add_argument("--after-parsed", required=True)
    parser.add_argument("--target-rule", default="PDF/UA-1/7.18.4")
    parser.add_argument("--verapdf-bin", default="/opt/verapdf-greenfield/verapdf")
    parser.add_argument("--before-pdf", default="/app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf")
    parser.add_argument("--after-pdf", default="/tmp/h10a-mm17179-form-widget-trial/output.pdf")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    delta = build_delta(Path(args.profiles_root), Path(args.before_dir), Path(args.after_dir),
                        Path(args.before_parsed), Path(args.after_parsed), args.target_rule,
                        verapdf_bin=Path(args.verapdf_bin), before_pdf=args.before_pdf,
                        after_pdf=args.after_pdf)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(delta, indent=2, sort_keys=True) + "\n")
    Path(args.before_dir, "profile_accounting.json").write_text(json.dumps(delta["profile_accounting_before"], indent=2, sort_keys=True) + "\n")
    Path(args.after_dir, "profile_accounting.json").write_text(json.dumps(delta["profile_accounting_after"], indent=2, sort_keys=True) + "\n")
    print(json.dumps(delta, indent=2, sort_keys=True))
    return 0 if delta["terminal_state"] == TERMINAL_DELTA_VALIDATED else 1


if __name__ == "__main__":
    raise SystemExit(main())
