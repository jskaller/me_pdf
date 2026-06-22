#!/usr/bin/env python3
"""Production-readiness matrix harness for PDF remediation artifacts.

Inspection mode is read-only. Optional run mode only invokes the existing
orchestrator for explicitly listed local PDFs and never treats absent artifacts
as proof of production readiness.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CLASSIFICATIONS = ("PASS", "REVIEW_REQUIRED", "FAIL", "ESCALATION", "BLOCKED", "INCOMPLETE_ARTIFACTS", "MISMATCH")
KNOWN_RESULTS = {"PASS", "REVIEW_REQUIRED", "FAIL", "ESCALATION", "BLOCKED"}
EXTERNAL_VALIDATOR_STATUS = "NOT_RUN"
PROFILES_AVAILABLE = ("all", "production", "fixtures", "historical", "actionable")
ACTIONABLE_CLASSIFICATIONS = {"ESCALATION", "FAIL", "MISMATCH", "INCOMPLETE_ARTIFACTS", "BLOCKED"}
HISTORICAL_NAME_PATTERNS = (
    "probe", "smoke_", "_smoke", "pre-patch", ".pre-patch", "rerun", "historical",
)
TIMESTAMP_RE = re.compile(r"(?:19|20)\d{6}(?:[-_]\d{6})?")

GATES = {
    "qpdf": ("audit/qpdf.json", "qpdf.json"),
    "verapdf_pdfua": ("audit/verapdf_post_pdfua1_summary.json", "audit/verapdf_pdfua1.json", "verapdf_pdfua1.json"),
    "verapdf_wcag": ("audit/verapdf_post_wcag_summary.json", "audit/verapdf_wcag.json", "verapdf_wcag.json"),
    "verapdf_iso": ("audit/verapdf_post_iso_summary.json", "audit/verapdf_iso.json", "verapdf_iso.json"),
    "metadata_xmp_parity": ("audit/metadata_xmp_parity.json", "metadata_xmp_parity.json", "metadata_parity.json"),
    "preservation": ("qa/preservation.json", "audit/preservation.json", "preservation.json"),
    "table_semantics": ("audit/table_semantics.json", "table_semantics.json"),
    "contrast": ("audit/contrast.json", "contrast.json"),
    "ocr_preflight": ("audit/ocr_detection.json", "audit/ocr_preflight.json", "ocr_detection.json"),
    "render_compare": ("qa/render_compare.json", "render_compare.json"),
    "visual_qa": ("qa/visual_qa.json", "visual_qa.json"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def result_from(data: Any) -> str:
    if isinstance(data, dict):
        value = data.get("overall_result") or data.get("result") or data.get("overall")
        if value is not None:
            return str(value)
    return "NOT_RUN"


def job_parts(job_dir: Path) -> tuple[str, str]:
    if "_" not in job_dir.name:
        return job_dir.name, ""
    return tuple(job_dir.name.split("_", 1))  # type: ignore[return-value]


def first_json_result(job_dir: Path, names: Iterable[str]) -> dict[str, Any]:
    for name in names:
        path = job_dir / name
        if path.exists():
            return {"available": True, "path": str(path), "result": result_from(load_json(path))}
    return {"available": False, "path": "", "result": "NOT_RUN"}


def failures_from(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, dict):
        return []
    value = data.get("failures_by_rule") or data.get("failures") or []
    return value if isinstance(value, list) else []


def pre_failures(job_dir: Path) -> list[dict[str, Any]]:
    for name in ("audit/verapdf_pre_pdfua1_summary.json", "audit/verapdf_pre_summary.json", "audit/verapdf_initial_summary.json"):
        path = job_dir / name
        if path.exists():
            return failures_from(path)
    return []


def repair_plan(job_dir: Path) -> dict[str, Any]:
    for name in ("audit/repair_plan.json", "repair_plan.json"):
        path = job_dir / name
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        steps = [s for s in data.get("repair_steps", []) or [] if isinstance(s, dict)]
        rules = sorted({r for step in steps for r in (step.get("rules_addressed") or []) if r})
        return {
            "path": str(path),
            "result": data.get("result", "UNKNOWN"),
            "rules": rules,
            "strategies": [s.get("strategy") for s in steps if s.get("strategy")],
            "hermes_required": data.get("hermes_required", []) or [],
        }
    return {"path": "", "result": "NOT_RUN", "rules": [], "strategies": [], "hermes_required": []}


def executed_repairs(job_dir: Path) -> list[dict[str, Any]]:
    for name in ("audit/execution_log.json", "execution_log.json"):
        data = load_json(job_dir / name)
        if not isinstance(data, dict):
            continue
        rows: list[dict[str, Any]] = []
        for bucket in ("records", "repair_steps"):
            for item in data.get(bucket, []) or []:
                if not isinstance(item, dict):
                    continue
                script = item.get("script") or item.get("repair_script") or item.get("argv") or ""
                if isinstance(script, list):
                    script = " ".join(str(part) for part in script)
                rows.append({
                    "script": str(script),
                    "ran": bool(item.get("ran", item.get("returncode") in (0, "0"))),
                    "result_category": item.get("result_category", ""),
                    "rules": item.get("rules_targeted") or item.get("rules_addressed") or item.get("rule_ids") or [],
                })
        return rows
    return []


def residuals(job_dir: Path) -> dict[str, Any]:
    data = load_json(job_dir / "audit" / "residual_analysis.json")
    if not isinstance(data, dict):
        return {"available": False, "targetable": [], "non_targetable": []}
    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    return {
        "available": True,
        "targetable": data.get("targetable_residual_rules") or summary.get("targetable_residual_rules") or [],
        "non_targetable": data.get("non_targetable_residual_rules") or summary.get("non_targetable_residual_rules") or [],
    }


def active_signals(job_dir: Path) -> list[dict[str, Any]]:
    data = load_json(job_dir / "audit" / "hermes_signals.json")
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("signals") or data.get("active_actionable_signals") or data.get("raw_signals") or []
    else:
        raw = []
    active = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("active_blocker") is False:
            continue
        if item.get("reconciliation") in {"resolved_incidental", "non_targetable_residual", "suppressed_zero_count"}:
            continue
        active.append(item)
    return active


def _paths(paths: Iterable[Path]) -> list[str]:
    return [str(p) for p in sorted(paths, key=lambda p: str(p))]


def _has_name(files: Iterable[Path], name: str) -> list[Path]:
    return [p for p in files if p.name == name]


def output_artifact_matches(output_dir: Path, basename: str) -> dict[str, Any]:
    """Return basename-scoped deliverable matches for a ticket output directory."""
    expected_pdf = f"{basename}_remediated.pdf"
    expected_report = f"{basename}_AUDIT_REPORT.md"
    expected_checksum = "SHA256SUMS.txt"
    if not output_dir.exists():
        return {
            "expected_basename": basename,
            "output_dir": str(output_dir),
            "matched_pdfs": [],
            "matched_reports": [],
            "matched_checksums": [],
            "matched_top_level_pdfs": [],
            "matched_review_pdfs": [],
            "matched_failed_pdfs": [],
            "matched_top_level_reports": [],
            "matched_review_reports": [],
            "matched_failed_reports": [],
            "unmatched_pdfs_in_output_dir": [],
            "unmatched_reports_in_output_dir": [],
            "shared_output_dir": False,
            "stale_or_shared_output_risk": False,
            "confirmed_false_success_pdf": False,
            "no_false_success_evidence": True,
        }

    files = [p for p in output_dir.rglob("*") if p.is_file()]
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    reports = [p for p in files if p.name.endswith("_AUDIT_REPORT.md") or p.name in {"ESCALATION_REPORT.md", "PACKAGE_CONTENTS.md"}]
    checksums = [p for p in files if p.name == expected_checksum]

    matched_pdfs = _has_name(pdfs, expected_pdf)
    matched_reports = _has_name(reports, expected_report)
    matched_checksums = [p for p in checksums if p.parent in {output_dir, output_dir / "review", output_dir / "failed"}]
    unmatched_pdfs = [p for p in pdfs if p.name != expected_pdf]
    unmatched_reports = [p for p in reports if p.name != expected_report]

    top_level_pdfs = [p for p in matched_pdfs if p.parent == output_dir]
    review_pdfs = [p for p in matched_pdfs if p.parent == output_dir / "review"]
    failed_pdfs = [p for p in matched_pdfs if p.parent == output_dir / "failed"]
    top_level_reports = [p for p in matched_reports if p.parent == output_dir]
    review_reports = [p for p in matched_reports if p.parent == output_dir / "review"]
    failed_reports = [p for p in matched_reports if p.parent == output_dir / "failed"]
    shared_output = bool(unmatched_pdfs or unmatched_reports)

    return {
        "expected_basename": basename,
        "output_dir": str(output_dir),
        "matched_pdfs": _paths(matched_pdfs),
        "matched_reports": _paths(matched_reports),
        "matched_checksums": _paths(matched_checksums),
        "matched_top_level_pdfs": _paths(top_level_pdfs),
        "matched_review_pdfs": _paths(review_pdfs),
        "matched_failed_pdfs": _paths(failed_pdfs),
        "matched_top_level_reports": _paths(top_level_reports),
        "matched_review_reports": _paths(review_reports),
        "matched_failed_reports": _paths(failed_reports),
        "unmatched_pdfs_in_output_dir": _paths(unmatched_pdfs),
        "unmatched_reports_in_output_dir": _paths(unmatched_reports),
        "shared_output_dir": shared_output,
        "stale_or_shared_output_risk": False,
        "confirmed_false_success_pdf": False,
        "no_false_success_evidence": True,
    }


def package_info(output_dir: Path, basename: str) -> dict[str, Any]:
    matches = output_artifact_matches(output_dir, basename)
    if not output_dir.exists():
        return {"exists": False, "path": str(output_dir), "files": [], "pdfs": [], "review_exists": False, "failed_exists": False, "checksums_exists": False, "pass_pdf_exists": False, "matched_output_artifacts": matches}
    files = [p for p in output_dir.rglob("*") if p.is_file()]
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    return {
        "exists": True,
        "path": str(output_dir),
        "files": _paths(files),
        "pdfs": _paths(pdfs),
        "review_exists": (output_dir / "review").exists(),
        "failed_exists": (output_dir / "failed").exists(),
        "checksums_exists": (output_dir / "SHA256SUMS.txt").is_file(),
        "pass_pdf_exists": bool(matches["matched_top_level_pdfs"]),
        "matched_output_artifacts": matches,
    }


def classify(overall: str, status: str, outcome: str, pkg: dict[str, Any], missing: list[str]) -> tuple[str, list[str], dict[str, Any]]:
    matches = dict(pkg.get("matched_output_artifacts") or {})
    matched_success_like = bool(matches.get("matched_top_level_pdfs") or matches.get("matched_review_pdfs"))
    matched_failed_pdf = bool(matches.get("matched_failed_pdfs"))
    unmatched_pdfs = bool(matches.get("unmatched_pdfs_in_output_dir"))
    if status != "NOT_RUN" and outcome != "NOT_RUN" and status != outcome:
        return "MISMATCH", [f"STATUS.json overall_result={status} differs from orchestrator_outcome.json overall_result={outcome}"], matches
    risks: list[str] = []
    if overall in {"FAIL", "ESCALATION"}:
        if matched_success_like:
            matches["confirmed_false_success_pdf"] = True
            matches["no_false_success_evidence"] = False
            risks.append("FAIL/ESCALATION has matched same-basename PDF in success-like deliverable location")
        elif unmatched_pdfs:
            matches["stale_or_shared_output_risk"] = True
            risks.append("FAIL/ESCALATION output directory contains only unmatched sibling/stale PDF deliverable(s)")
        elif matched_failed_pdf:
            matches["no_false_success_evidence"] = True
            risks.append("FAIL/ESCALATION failed package contains matched PDF; not counted as success deliverable")
    if missing:
        return "INCOMPLETE_ARTIFACTS", ["missing required artifacts: " + ", ".join(missing)] + risks, matches
    if overall == "PASS" and not matches.get("matched_top_level_pdfs"):
        return "INCOMPLETE_ARTIFACTS", ["PASS lacks matched top-level remediated PDF deliverable"] + risks, matches
    if overall == "REVIEW_REQUIRED" and not (matches.get("matched_review_pdfs") or matches.get("matched_review_reports") or matches.get("matched_top_level_reports")):
        return "INCOMPLETE_ARTIFACTS", ["REVIEW_REQUIRED lacks matched review/package evidence"] + risks, matches
    if overall in KNOWN_RESULTS:
        return overall, risks, matches
    return "INCOMPLETE_ARTIFACTS", ["no authoritative final outcome artifact"] + risks, matches


def source_kind(ticket: str, basename: str, source: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    text = f"{ticket} {basename}".lower()
    source_text = str(source).lower()
    if "webui-e2e" in text or "smoke" in text:
        return "controlled_fixture"
    if "fixture" in text or "synthetic" in text or "generated" in text:
        return "synthetic_generated_fixture"
    if "webui-e2e" in source_text:
        return "controlled_fixture"
    if source.exists():
        return "private_local_or_representative_pdf"
    return "unknown"


def inspect_job(workspace: Path, job_dir: Path, run_mode: str = "inspected_existing", source_override: Path | None = None, kind: str | None = None) -> dict[str, Any]:
    ticket, basename = job_parts(job_dir)
    source = source_override or workspace / "input" / ticket / f"{basename}.pdf"
    out_dir = workspace / "output" / f"{ticket}_remediated"
    outcome = result_from(load_json(job_dir / "audit" / "orchestrator_outcome.json"))
    status = result_from(load_json(job_dir / "STATUS.json"))
    overall = outcome if outcome != "NOT_RUN" else status
    pkg = package_info(out_dir, basename)
    missing = []
    if not (job_dir / "STATUS.json").exists():
        missing.append("STATUS.json")
    if not (job_dir / "audit" / "orchestrator_outcome.json").exists():
        missing.append("audit/orchestrator_outcome.json")
    if not pkg.get("exists"):
        missing.append("output package directory")
    final, risks, matches = classify(overall, status, outcome, pkg, missing)
    pkg["matched_output_artifacts"] = matches
    res = residuals(job_dir)
    return {
        "ticket": ticket,
        "basename": basename,
        "source_pdf_path": str(source),
        "source_pdf_exists": source.exists(),
        "source_kind": source_kind(ticket, basename, source, kind),
        "job_dir": str(job_dir),
        "output_dir": str(out_dir),
        "run_mode": run_mode,
        "pre_repair_validator_failures": pre_failures(job_dir),
        "repair_plan": repair_plan(job_dir),
        "repair_scripts_executed": executed_repairs(job_dir),
        "post_repair_validator_outcomes": {name: first_json_result(job_dir, paths) for name, paths in GATES.items()},
        "residual_targetable_rules": res["targetable"],
        "non_targetable_rules": res["non_targetable"],
        "active_hermes_required_signals": active_signals(job_dir),
        "orchestrator_outcome_overall_result": outcome,
        "status_json_overall_result": status,
        "status_matches_orchestrator_outcome": status != "NOT_RUN" and outcome != "NOT_RUN" and status == outcome,
        "package": pkg,
        "matched_output_artifacts": matches,
        "fail_escalation_pdf_copied_to_successful_deliverables": bool(matches.get("confirmed_false_success_pdf")),
        "confirmed_false_success_pdf": bool(matches.get("confirmed_false_success_pdf")),
        "stale_or_shared_output_risk": bool(matches.get("stale_or_shared_output_risk")),
        "no_false_success_evidence": bool(matches.get("no_false_success_evidence")),
        "review_required_has_review_package": bool(overall == "REVIEW_REQUIRED" and (matches.get("matched_review_pdfs") or matches.get("matched_review_reports") or matches.get("matched_top_level_reports"))),
        "pass_package_exists": bool(overall == "PASS" and matches.get("matched_top_level_pdfs")),
        "checksums_file_presence": bool(pkg.get("checksums_exists") or matches.get("matched_checksums") or (job_dir / "SHA256SUMS.txt").is_file()),
        "external_validators": {"axesCheck": EXTERNAL_VALIDATOR_STATUS, "PAC_2024": EXTERNAL_VALIDATOR_STATUS},
        "final_matrix_classification": final,
        "risk_flags": risks,
        "evidence_policy": {"rule_map_entries_count_as_proven_repairs": False, "requires_script_execution_and_validator_delta": True},
    }


def inspect_existing(workspace: Path) -> list[dict[str, Any]]:
    root = workspace / "jobs"
    if not root.exists():
        return []
    return [inspect_job(workspace, p) for p in sorted(root.iterdir()) if p.is_dir()]


def parse_pdf_spec(spec: str) -> tuple[str, str, Path, str | None]:
    parts = spec.split(":")
    if len(parts) < 3:
        raise ValueError("--pdf must be ticket:basename:path[:source_kind]")
    return parts[0], parts[1], Path(parts[2]), parts[3] if len(parts) > 3 else None


def _minimal_row(workspace: Path, ticket: str, basename: str, source: Path, classification: str, risks: list[str], run_mode: str) -> dict[str, Any]:
    out_dir = workspace / "output" / f"{ticket}_remediated" if ticket else workspace / "output"
    matches = output_artifact_matches(out_dir, basename)
    return {
        "ticket": ticket,
        "basename": basename,
        "source_pdf_path": str(source),
        "source_kind": source_kind(ticket, basename, source),
        "source_pdf_exists": source.exists() if str(source) else False,
        "job_dir": str(workspace / "jobs" / f"{ticket}_{basename}"),
        "output_dir": str(out_dir),
        "run_mode": run_mode,
        "pre_repair_validator_failures": [],
        "repair_plan": {"path": "", "result": "NOT_RUN", "rules": [], "strategies": [], "hermes_required": []},
        "repair_scripts_executed": [],
        "post_repair_validator_outcomes": {name: {"available": False, "path": "", "result": "NOT_RUN"} for name in GATES},
        "residual_targetable_rules": [],
        "non_targetable_rules": [],
        "active_hermes_required_signals": [],
        "orchestrator_outcome_overall_result": "NOT_RUN",
        "status_json_overall_result": "NOT_RUN",
        "status_matches_orchestrator_outcome": False,
        "package": {"exists": False, "path": str(out_dir), "matched_output_artifacts": matches},
        "final_matrix_classification": classification,
        "risk_flags": risks,
        "matched_output_artifacts": matches,
        "external_validators": {"axesCheck": EXTERNAL_VALIDATOR_STATUS, "PAC_2024": EXTERNAL_VALIDATOR_STATUS},
        "evidence_policy": {"rule_map_entries_count_as_proven_repairs": False, "requires_script_execution_and_validator_delta": True},
    }


def run_specs(workspace: Path, specs: list[str], python_bin: str) -> list[dict[str, Any]]:
    rows = []
    script = Path("app/tools/orchestrate/remediate.py")
    for spec in specs:
        ticket, basename, source, kind = parse_pdf_spec(spec)
        stem = Path(basename).stem
        safe = stem.replace(" ", "_").replace("/", "_")
        job_dir = workspace / "jobs" / f"{ticket}_{safe}"
        expected = workspace / "input" / ticket / f"{stem}.pdf"
        if not source.exists() or not expected.exists():
            rows.append(_minimal_row(workspace, ticket, stem, source, "INCOMPLETE_ARTIFACTS", ["source PDF missing or not staged at expected orchestrator path"], "skipped_missing_input"))
            continue
        proc = subprocess.run([python_bin, str(script), str(workspace), ticket, stem], capture_output=True, text=True)
        if job_dir.exists():
            row = inspect_job(workspace, job_dir, "orchestrator_run", source, kind)
            row["orchestrator_run"] = {"returncode": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:]}
        else:
            row = _minimal_row(workspace, ticket, stem, source, "BLOCKED", ["orchestrator did not create job directory"], "orchestrator_run")
            row["orchestrator_run"] = {"returncode": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:]}
        rows.append(row)
    return rows


def load_manifest(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = load_json(Path(path))
    return data if isinstance(data, dict) else {"_manifest_error": f"unable to read manifest: {path}"}


def row_job_name(row: dict[str, Any]) -> str:
    value = str(row.get("job_dir") or "")
    return Path(value).name if value else f"{row.get('ticket', '')}_{row.get('basename', '')}".strip("_")


def _manifest_job(manifest: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    jobs = manifest.get("jobs") if isinstance(manifest.get("jobs"), dict) else {}
    job_name = row_job_name(row)
    for key in (job_name, row.get("ticket"), row.get("basename")):
        if key and isinstance(jobs.get(str(key)), dict):
            return dict(jobs[str(key)])
    return {}


def _manifest_profile_rules(manifest: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = manifest.get("profiles") if isinstance(manifest.get("profiles"), dict) else {}
    value = profiles.get(profile)
    return value if isinstance(value, dict) else {}


def _profile_name_from_manifest(value: str) -> str:
    aliases = {
        "production": "production_corpus",
        "fixture": "controlled_fixture",
        "fixtures": "controlled_fixture",
        "historical": "historical_probe",
        "stale": "stale_or_incomplete",
    }
    return aliases.get(value, value)


def _is_historical_name(text: str) -> bool:
    lower = text.lower()
    if lower.startswith(("test-", "probe-", "smoke-", "smoke_", "probe_")):
        return True
    if any(pattern in lower for pattern in HISTORICAL_NAME_PATTERNS):
        return True
    return bool(TIMESTAMP_RE.search(lower))


def _base_profile(row: dict[str, Any], manifest_job: dict[str, Any]) -> tuple[str, str]:
    if manifest_job.get("exclude") is True or manifest_job.get("profile") == "excluded":
        return "excluded", "manifest explicitly excludes this job"
    if manifest_job.get("profile"):
        return _profile_name_from_manifest(str(manifest_job["profile"])), "manifest job profile override"

    job_name = row_job_name(row)
    combined = f"{job_name} {row.get('ticket', '')} {row.get('basename', '')}"
    source = str(row.get("source_kind") or "unknown")
    cls = str(row.get("final_matrix_classification") or "INCOMPLETE_ARTIFACTS")
    if "webui-e2e" in combined.lower() or source == "controlled_fixture":
        return "controlled_fixture", f"source_kind={source}"
    if _is_historical_name(combined):
        return "historical_probe", "job name matches development/probe/test/rerun heuristic"
    if source == "synthetic_generated_fixture":
        return "controlled_fixture", f"source_kind={source}"
    if cls == "INCOMPLETE_ARTIFACTS" or row.get("stale_or_shared_output_risk"):
        return "stale_or_incomplete", "missing/stale artifact evidence"
    if source == "private_local_or_representative_pdf":
        return "production_corpus", "representative/private source PDF evidence"
    return "historical_probe", "unknown source kind treated as non-production until manifest classifies it"


def _included_profiles(primary: str, row: dict[str, Any]) -> list[str]:
    profiles = {"all"}
    cls = str(row.get("final_matrix_classification") or "")
    has_blockers = bool(row.get("active_hermes_required_signals") or row.get("residual_targetable_rules") or row.get("non_targetable_rules"))
    if primary == "production_corpus":
        profiles.add("production")
        if cls in ACTIONABLE_CLASSIFICATIONS or has_blockers:
            profiles.add("actionable")
    elif primary in {"controlled_fixture", "synthetic_generated_fixture"}:
        profiles.add("fixtures")
    elif primary in {"historical_probe", "stale_or_incomplete"}:
        profiles.add("historical")
    elif primary == "excluded":
        profiles.add("historical")
    return sorted(profiles, key=lambda x: PROFILES_AVAILABLE.index(x) if x in PROFILES_AVAILABLE else 999)


def apply_corpus_profiles(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    for row in rows:
        job_name = row_job_name(row)
        mjob = _manifest_job(manifest, row)
        if mjob.get("source_kind"):
            row["source_kind"] = str(mjob["source_kind"])
        primary, reason = _base_profile(row, mjob)
        included = set(_included_profiles(primary, row))
        excluded_reasons: list[str] = []
        for profile in PROFILES_AVAILABLE:
            rules = _manifest_profile_rules(manifest, profile)
            include_jobs = {str(v) for v in rules.get("include_jobs", []) or []}
            exclude_jobs = {str(v) for v in rules.get("exclude_jobs", []) or []}
            if job_name in include_jobs:
                included.add(profile)
                reason = f"manifest include_jobs override for profile={profile}"
            if job_name in exclude_jobs:
                included.discard(profile)
                excluded_reasons.append(f"manifest excludes job from profile={profile}")
        if primary == "excluded" and "production" in included:
            included.discard("production")
        production_exclusion = ""
        if "production" not in included:
            production_exclusion = "; ".join(excluded_reasons) or f"primary_profile={primary} is not representative production corpus"
        row["corpus_profile"] = {
            "primary_profile": primary,
            "included_in_profiles": sorted(included, key=lambda x: PROFILES_AVAILABLE.index(x) if x in PROFILES_AVAILABLE else 999),
            "excluded_from_production_reason": production_exclusion,
            "manifest_source": mjob.get("notes", "manifest job entry") if mjob else "heuristic",
            "profile_reason": reason,
        }
    return rows


def select_profile(rows: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    if profile not in PROFILES_AVAILABLE:
        raise ValueError(f"unknown profile {profile}; expected one of {', '.join(PROFILES_AVAILABLE)}")
    return [row for row in rows if profile in (row.get("corpus_profile", {}).get("included_in_profiles") or [])]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {name: 0 for name in CLASSIFICATIONS}
    source_counts: dict[str, int] = {}
    mismatches = []
    confirmed_false_success = []
    stale_shared = []
    for row in rows:
        cls = row.get("final_matrix_classification", "INCOMPLETE_ARTIFACTS")
        counts[cls] = counts.get(cls, 0) + 1
        kind = row.get("source_kind", "unknown")
        source_counts[kind] = source_counts.get(kind, 0) + 1
        if cls == "MISMATCH":
            mismatches.append(row.get("job_dir"))
        if row.get("confirmed_false_success_pdf"):
            confirmed_false_success.append(row.get("job_dir") or row.get("output_dir"))
        if row.get("stale_or_shared_output_risk"):
            stale_shared.append(row.get("job_dir") or row.get("output_dir"))
    return {
        "jobs_total": len(rows),
        "counts_by_classification": counts,
        "counts_by_source_kind": source_counts,
        "status_orchestrator_mismatches": mismatches,
        "packaging_false_success_risks": confirmed_false_success,
        "confirmed_false_success_pdf_risks": confirmed_false_success,
        "stale_or_shared_output_risks": stale_shared,
        "representative_real_pdf_coverage_count": source_counts.get("private_local_or_representative_pdf", 0),
        "synthetic_fixture_coverage_count": source_counts.get("controlled_fixture", 0) + source_counts.get("synthetic_generated_fixture", 0),
    }


def corpus_summary(rows: list[dict[str, Any]], selected_profile: str) -> dict[str, Any]:
    profile_counts: dict[str, int] = {}
    class_counts = {name: 0 for name in CLASSIFICATIONS}
    for row in rows:
        primary = row.get("corpus_profile", {}).get("primary_profile", "unknown")
        profile_counts[primary] = profile_counts.get(primary, 0) + 1
        cls = row.get("final_matrix_classification", "INCOMPLETE_ARTIFACTS")
        class_counts[cls] = class_counts.get(cls, 0) + 1
    production_rows = [r for r in rows if r.get("corpus_profile", {}).get("primary_profile") == "production_corpus"]
    prod_class_counts = {name: 0 for name in CLASSIFICATIONS}
    for row in production_rows:
        cls = row.get("final_matrix_classification", "INCOMPLETE_ARTIFACTS")
        prod_class_counts[cls] = prod_class_counts.get(cls, 0) + 1
    return {
        "profiles_available": list(PROFILES_AVAILABLE),
        "selected_profile": selected_profile,
        "selected_rows_count": len(rows),
        "counts_by_primary_profile": profile_counts,
        "production_rows_count": profile_counts.get("production_corpus", 0),
        "fixture_rows_count": profile_counts.get("controlled_fixture", 0) + profile_counts.get("synthetic_generated_fixture", 0),
        "historical_probe_rows_count": profile_counts.get("historical_probe", 0),
        "stale_or_incomplete_rows_count": profile_counts.get("stale_or_incomplete", 0),
        "excluded_rows_count": profile_counts.get("excluded", 0),
        "representative_real_pdf_coverage_count": sum(1 for r in production_rows if r.get("source_kind") == "private_local_or_representative_pdf"),
        "synthetic_fixture_coverage_count": sum(1 for r in rows if r.get("corpus_profile", {}).get("primary_profile") in {"controlled_fixture", "synthetic_generated_fixture"}),
        "production_pass_count": prod_class_counts.get("PASS", 0),
        "production_review_required_count": prod_class_counts.get("REVIEW_REQUIRED", 0),
        "production_fail_count": prod_class_counts.get("FAIL", 0),
        "production_escalation_count": prod_class_counts.get("ESCALATION", 0),
        "production_mismatch_count": prod_class_counts.get("MISMATCH", 0),
        "production_incomplete_count": prod_class_counts.get("INCOMPLETE_ARTIFACTS", 0) + prod_class_counts.get("BLOCKED", 0),
        "counts_by_classification": class_counts,
    }


def _rule_map_entries(path: Path | None = None) -> dict[str, dict[str, Any]]:
    candidates = []
    if path:
        candidates.append(path)
    candidates.extend([
        Path("app/tools/audit/rule_repair_map.json"),
        Path("tools/audit/rule_repair_map.json"),
        Path("/app/tools/audit/rule_repair_map.json"),
    ])
    for candidate in candidates:
        data = load_json(candidate)
        if isinstance(data, dict) and isinstance(data.get("rules"), dict):
            return data["rules"]
    return {}


def _rule_ids_from_failures(items: Any) -> list[str]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict) and item.get("rule_id"):
            out.append(str(item["rule_id"]))
    return out


def _source_list(flags: dict[str, Any], key: str) -> list[str]:
    values = flags.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        flags[key] = values
    return values


def _append_unique(flags: dict[str, Any], key: str, value: str) -> None:
    if not value:
        return
    values = _source_list(flags, key)
    if value not in values:
        values.append(value)


def _row_is_success(row: dict[str, Any]) -> bool:
    return str(row.get("final_matrix_classification") or "") in {"PASS", "REVIEW_REQUIRED"}


def _finalize_rule_observation(flags: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    active_sources = set(flags.get("active_blocker_sources") or [])
    context_sources = set(flags.get("historical_or_context_sources") or [])
    has_current = bool(active_sources)
    success_row = _row_is_success(row)
    flags["rule_observation_sources"] = sorted(set(flags.get("rule_observation_sources") or []))
    flags["active_blocker_sources"] = sorted(active_sources)
    flags["historical_or_context_sources"] = sorted(context_sources)
    flags["active_hermes_required"] = bool(flags.get("active_hermes_required"))
    flags["post_repair_validator_failure"] = bool(flags.get("post_repair_validator_failure"))
    flags["residual_targetable_current"] = bool(flags.get("residual_targetable_current"))
    flags["residual_non_targetable_current"] = bool(flags.get("residual_non_targetable_current"))
    flags["pre_repair_only"] = bool(flags.get("pre_validator_failure") and not has_current and not flags.get("repair_plan_rule") and not flags.get("repair_plan_hermes_required"))
    flags["repair_plan_only"] = bool((flags.get("repair_plan_rule") or flags.get("repair_plan_hermes_required")) and not has_current and not flags.get("pre_validator_failure"))
    flags["executed_and_cleared"] = bool(flags.get("executed_scripts") and not has_current)
    flags["current_blocker"] = has_current and not success_row
    flags["pass_row_current_blocker_risk"] = has_current and success_row
    if flags.get("active_hermes_required"):
        tier = "T1_active_hermes_required"
    elif flags.get("post_repair_validator_failure"):
        tier = "T2_post_repair_validator_failure"
    elif flags.get("residual_targetable_current"):
        tier = "T3_residual_targetable_current"
    elif flags.get("residual_non_targetable_current"):
        tier = "T4_residual_non_targetable_current"
    elif flags.get("pre_validator_failure") or flags.get("repair_plan_rule") or flags.get("repair_plan_hermes_required"):
        tier = "T5_contextual_pre_repair_or_plan"
    elif flags.get("executed_scripts"):
        tier = "T6_executed_without_current_blocker"
    else:
        tier = "T7_observed_without_priority_evidence"
    flags["priority_evidence_tier"] = tier
    return flags


def _row_rule_observations(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    def mark(rule_id: str, field: str, value: Any = True, *, source: str, current: bool = False, context: bool = False) -> None:
        if not rule_id:
            return
        flags = observations.setdefault(rule_id, {})
        flags[field] = value
        _append_unique(flags, "rule_observation_sources", source)
        if current:
            _append_unique(flags, "active_blocker_sources", source)
        if context:
            _append_unique(flags, "historical_or_context_sources", source)
    for rule_id in _rule_ids_from_failures(row.get("pre_repair_validator_failures")):
        mark(rule_id, "pre_validator_failure", True, source="pre_repair_validator_failures", context=True)
    for gate_name, gate in (row.get("post_repair_validator_outcomes") or {}).items():
        if isinstance(gate, dict) and gate.get("available"):
            path = gate.get("path")
            if path:
                for rule_id in _rule_ids_from_failures(failures_from(Path(path))):
                    mark(rule_id, "post_repair_validator_failure", True, source=f"post_repair_validator_outcomes.{gate_name}", current=True)
    for rule_id in row.get("residual_targetable_rules") or []:
        mark(str(rule_id), "residual_targetable_current", True, source="residual_targetable_rules", current=True)
    for rule_id in row.get("non_targetable_rules") or []:
        mark(str(rule_id), "residual_non_targetable_current", True, source="non_targetable_rules", current=True)
    for rule_id in (row.get("repair_plan") or {}).get("rules", []) or []:
        mark(str(rule_id), "repair_plan_rule", True, source="repair_plan.rules", context=True)
    for item in (row.get("repair_plan") or {}).get("hermes_required", []) or []:
        if isinstance(item, dict):
            mark(str(item.get("rule_id") or ""), "repair_plan_hermes_required", item.get("reason", True), source="repair_plan.hermes_required", context=True)
    for item in row.get("active_hermes_required_signals") or []:
        if isinstance(item, dict):
            mark(str(item.get("rule_id") or ""), "active_hermes_required", item.get("reason", True), source="active_hermes_required_signals", current=True)
    for item in row.get("repair_scripts_executed") or []:
        if not isinstance(item, dict):
            continue
        rules = item.get("rules") or []
        if isinstance(rules, str):
            rules = [rules]
        for rule_id in rules:
            flags = observations.setdefault(str(rule_id), {})
            _append_unique(flags, "rule_observation_sources", "repair_scripts_executed")
            _append_unique(flags, "historical_or_context_sources", "repair_scripts_executed")
            flags.setdefault("executed_scripts", [])
            if item.get("script") and item.get("script") not in flags["executed_scripts"]:
                flags["executed_scripts"].append(item.get("script", ""))
    return {rule_id: _finalize_rule_observation(flags, row) for rule_id, flags in observations.items()}


def _entry_resolvability(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return "missing_map_entry"
    if entry.get("resolvability"):
        return str(entry["resolvability"])
    strategies = entry.get("strategies") if isinstance(entry.get("strategies"), list) else []
    if entry.get("manual") and not strategies:
        return "legacy_manual_review"
    if strategies:
        return "effective"
    return "repairable_unbuilt"


def _priority_bucket(current_production: int, current_fixture: int, current_historical: int, affected_production: int, affected_fixture: int, affected_historical: int, present_in_rule_map: bool, executed_count: int) -> str:
    del affected_fixture, executed_count
    if current_production > 1:
        return "P0_systemic_production_blocker"
    if current_production == 1:
        return "P1_single_production_blocker"
    if current_fixture and not current_production:
        return "P2_fixture_only_blocker"
    if current_historical and not current_production:
        return "P3_historical_or_stale_only"
    if affected_historical and not affected_production:
        return "P3_historical_or_stale_only"
    if present_in_rule_map:
        return "P4_mapped_but_unproven"
    return "P5_external_validation_gap"


def _recommended_next_action(bucket: str, present_in_rule_map: bool) -> str:
    del present_in_rule_map  # Rule-map presence is reported, not counted as proof of repair.
    if bucket in {"P0_systemic_production_blocker", "P1_single_production_blocker"}:
        return "build_or_repair_strategy"
    if bucket == "P2_fixture_only_blocker":
        return "collect_more_corpus_evidence"
    if bucket == "P3_historical_or_stale_only":
        return "exclude_stale_artifact"
    if bucket == "P4_mapped_but_unproven":
        return "audit_rule_map_and_tests"
    return "external_validator_ingestion"


def blocker_priority_summary(rows: list[dict[str, Any]], rule_map_path: Path | None = None) -> dict[str, Any]:
    rule_map = _rule_map_entries(rule_map_path)
    grouped: dict[str, dict[str, Any]] = {}
    pass_row_current_blocker_risks: list[dict[str, Any]] = []
    for row in rows:
        job_name = row_job_name(row)
        primary = row.get("corpus_profile", {}).get("primary_profile", "unknown")
        classification = str(row.get("final_matrix_classification") or "UNKNOWN")
        observations = _row_rule_observations(row)
        for rule_id, flags in observations.items():
            bucket = grouped.setdefault(rule_id, {
                "rule_id": rule_id, "affected_rows": set(), "affected_production_rows": set(), "affected_fixture_rows": set(), "affected_historical_rows": set(),
                "current_blocker_rows": set(), "current_production_blocker_rows": set(), "current_fixture_blocker_rows": set(), "current_historical_blocker_rows": set(), "contextual_only_rows": set(),
                "classifications_seen": set(), "source_kinds_seen": set(), "repair_scripts_seen_executed": set(), "rule_observation_sources": set(), "active_blocker_sources": set(), "historical_or_context_sources": set(), "priority_evidence_tiers": set(),
                "active_hermes_required_count": 0, "post_repair_validator_failure_count": 0, "residual_targetable_current_count": 0, "residual_non_targetable_current_count": 0, "pre_repair_only_count": 0, "repair_plan_only_count": 0, "executed_and_cleared_count": 0, "pass_row_current_blocker_risk_count": 0, "unknown_rule_count": 0,
            })
            bucket["affected_rows"].add(job_name)
            if primary == "production_corpus": bucket["affected_production_rows"].add(job_name)
            elif primary in {"controlled_fixture", "synthetic_generated_fixture"}: bucket["affected_fixture_rows"].add(job_name)
            else: bucket["affected_historical_rows"].add(job_name)
            if flags.get("current_blocker"):
                bucket["current_blocker_rows"].add(job_name)
                if primary == "production_corpus": bucket["current_production_blocker_rows"].add(job_name)
                elif primary in {"controlled_fixture", "synthetic_generated_fixture"}: bucket["current_fixture_blocker_rows"].add(job_name)
                else: bucket["current_historical_blocker_rows"].add(job_name)
            else:
                bucket["contextual_only_rows"].add(job_name)
            if flags.get("pass_row_current_blocker_risk"):
                bucket["pass_row_current_blocker_risk_count"] += 1
                pass_row_current_blocker_risks.append({"rule_id": rule_id, "job": job_name, "classification": classification})
            bucket["classifications_seen"].add(classification)
            bucket["source_kinds_seen"].add(str(row.get("source_kind") or "unknown"))
            for source in flags.get("rule_observation_sources", []) or []: bucket["rule_observation_sources"].add(str(source))
            for source in flags.get("active_blocker_sources", []) or []: bucket["active_blocker_sources"].add(str(source))
            for source in flags.get("historical_or_context_sources", []) or []: bucket["historical_or_context_sources"].add(str(source))
            if flags.get("priority_evidence_tier"): bucket["priority_evidence_tiers"].add(str(flags["priority_evidence_tier"]))
            for script in flags.get("executed_scripts", []) or []:
                if script: bucket["repair_scripts_seen_executed"].add(str(script))
            if flags.get("active_hermes_required"):
                bucket["active_hermes_required_count"] += 1
                if flags.get("active_hermes_required") == "unknown_rule": bucket["unknown_rule_count"] += 1
            if flags.get("post_repair_validator_failure"): bucket["post_repair_validator_failure_count"] += 1
            if flags.get("residual_targetable_current"): bucket["residual_targetable_current_count"] += 1
            if flags.get("residual_non_targetable_current"): bucket["residual_non_targetable_current_count"] += 1
            if flags.get("pre_repair_only"): bucket["pre_repair_only_count"] += 1
            if flags.get("repair_plan_only"): bucket["repair_plan_only_count"] += 1
            if flags.get("executed_and_cleared"): bucket["executed_and_cleared_count"] += 1
            if flags.get("repair_plan_hermes_required") == "unknown_rule": bucket["unknown_rule_count"] += 1
    rules = []
    for rule_id, raw in grouped.items():
        entry = rule_map.get(rule_id)
        present = isinstance(entry, dict)
        strategies = entry.get("strategies", []) if isinstance(entry, dict) and isinstance(entry.get("strategies"), list) else []
        classifications = set(raw["classifications_seen"])
        affected_production = len(raw["affected_production_rows"]); affected_fixture = len(raw["affected_fixture_rows"]); affected_historical = len(raw["affected_historical_rows"])
        current_production = len(raw["current_production_blocker_rows"]); current_fixture = len(raw["current_fixture_blocker_rows"]); current_historical = len(raw["current_historical_blocker_rows"])
        executed = sorted(raw["repair_scripts_seen_executed"])
        priority = _priority_bucket(current_production, current_fixture, current_historical, affected_production, affected_fixture, affected_historical, present, len(executed))
        rules.append({
            "rule_id": rule_id, "affected_rows": sorted(raw["affected_rows"]), "affected_production_rows": affected_production, "affected_fixture_rows": affected_fixture, "affected_historical_or_stale_rows": affected_historical,
            "current_blocker_rows": sorted(raw["current_blocker_rows"]), "current_production_blocker_rows": current_production, "current_fixture_blocker_rows": current_fixture, "current_historical_or_stale_blocker_rows": current_historical, "contextual_only_rows": sorted(raw["contextual_only_rows"]),
            "classifications_seen": sorted(classifications), "source_kinds_seen": sorted(raw["source_kinds_seen"]), "rule_observation_sources": sorted(raw["rule_observation_sources"]), "active_blocker_sources": sorted(raw["active_blocker_sources"]), "historical_or_context_sources": sorted(raw["historical_or_context_sources"]), "priority_evidence_tiers": sorted(raw["priority_evidence_tiers"]),
            "present_in_rule_map": present, "rule_map_resolvability": _entry_resolvability(entry), "mapped_strategies_count": len(strategies), "repair_scripts_seen_executed": executed,
            "active_hermes_required_count": raw["active_hermes_required_count"], "post_repair_validator_failure_count": raw["post_repair_validator_failure_count"], "residual_targetable_current_count": raw["residual_targetable_current_count"], "residual_non_targetable_current_count": raw["residual_non_targetable_current_count"], "pre_repair_only_count": raw["pre_repair_only_count"], "repair_plan_only_count": raw["repair_plan_only_count"], "executed_and_cleared_count": raw["executed_and_cleared_count"], "pass_row_current_blocker_risk_count": raw["pass_row_current_blocker_risk_count"], "unknown_rule_count": raw["unknown_rule_count"],
            "current_blocker": bool(raw["current_blocker_rows"]), "priority_bucket": priority, "recommended_next_action": _recommended_next_action(priority, present),
        })
    priority_order = {"P0_systemic_production_blocker": 0, "P1_single_production_blocker": 1, "P2_fixture_only_blocker": 2, "P3_historical_or_stale_only": 3, "P4_mapped_but_unproven": 4, "P5_external_validation_gap": 5}
    rules.sort(key=lambda r: (priority_order.get(r["priority_bucket"], 99), r["rule_id"]))
    return {"rules": rules, "pass_row_current_blocker_risks": pass_row_current_blocker_risks, "policy": {"rule_map_entries_count_as_proven_repairs": False, "priority_uses_selected_corpus_profile": True, "p0_p1_require_current_active_production_blocker_evidence": True, "pre_repair_and_repair_plan_only_are_contextual": True, "pass_rows_with_current_blockers_are_reported_as_risks": True, "external_validators_default": EXTERNAL_VALIDATOR_STATUS}}


def build_matrix(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.workspace)
    selected_profile = getattr(args, "profile", "all") or "all"
    manifest_path = getattr(args, "manifest", "") or ""
    manifest = load_manifest(manifest_path)
    rows: list[dict[str, Any]] = []
    if args.inspect_existing:
        rows.extend(inspect_existing(workspace))
    if args.pdf:
        rows.extend(run_specs(workspace, args.pdf, args.python_bin))
    if not rows:
        rows.append(_minimal_row(workspace, "", "", Path(""), "INCOMPLETE_ARTIFACTS", ["no workspace job artifacts or explicit PDF specs found"], "inspected_existing"))
    rows = apply_corpus_profiles(rows, manifest)
    selected_rows = select_profile(rows, selected_profile)
    return {
        "schema": "montefiore.production_readiness_matrix",
        "version": "1.2.0",
        "created_at": now(),
        "workspace": str(workspace),
        "mode": "mixed" if args.inspect_existing and args.pdf else "inspect_existing" if args.inspect_existing else "orchestrator_run" if args.pdf else "none",
        "selected_profile": selected_profile,
        "manifest": {"path": manifest_path, "loaded": bool(manifest and not manifest.get("_manifest_error")), "error": manifest.get("_manifest_error", "") if isinstance(manifest, dict) else ""},
        "records": selected_rows,
        "summary": summarize(selected_rows),
        "corpus_summary": corpus_summary(selected_rows, selected_profile),
        "blocker_priority_summary": blocker_priority_summary(selected_rows),
        "policy": {
            "read_only_artifact_inspection": bool(args.inspect_existing),
            "external_validators_default": EXTERNAL_VALIDATOR_STATUS,
            "does_not_modify_repair_scripts": True,
            "does_not_modify_rule_map": True,
            "does_not_claim_10_of_10_production_readiness": True,
            "basename_matched_package_attribution": True,
            "corpus_profiles_enabled": True,
            "manifest_overrides_enabled": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--inspect-existing", action="store_true")
    parser.add_argument("--pdf", action="append", default=[], help="ticket:basename:path[:source_kind]")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--profile", choices=PROFILES_AVAILABLE, default="all")
    parser.add_argument("--manifest", default="", help="Optional corpus manifest JSON with job/profile include and exclude overrides")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if not args.inspect_existing and not args.pdf:
        args.inspect_existing = True
    payload = build_matrix(args)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
