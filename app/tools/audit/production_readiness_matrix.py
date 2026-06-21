#!/usr/bin/env python3
"""Production-readiness matrix harness for PDF remediation artifacts.

Inspection mode is read-only. Optional run mode only invokes the existing
orchestrator for explicitly listed local PDFs and never treats absent artifacts
as proof of production readiness.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CLASSIFICATIONS = ("PASS", "REVIEW_REQUIRED", "FAIL", "ESCALATION", "BLOCKED", "INCOMPLETE_ARTIFACTS", "MISMATCH")
KNOWN_RESULTS = {"PASS", "REVIEW_REQUIRED", "FAIL", "ESCALATION", "BLOCKED"}
EXTERNAL_VALIDATOR_STATUS = "NOT_RUN"

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
    """Return basename-scoped deliverable matches for a ticket output directory.

    Ticket output directories are shared across repeated runs for the same ticket.
    This matcher therefore distinguishes same-basename artifacts from sibling or
    stale artifacts before PASS/REVIEW/false-success decisions are made.
    """
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
    text = f"{ticket} {basename} {source}".lower()
    if "webui-e2e" in text or "smoke" in text:
        return "controlled_fixture"
    if "fixture" in text or "synthetic" in text or "generated" in text:
        return "synthetic_generated_fixture"
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
        "job_dir": str(workspace / "jobs" / f"{ticket}_{basename}"),
        "output_dir": str(out_dir),
        "run_mode": run_mode,
        "final_matrix_classification": classification,
        "risk_flags": risks,
        "matched_output_artifacts": matches,
        "external_validators": {"axesCheck": EXTERNAL_VALIDATOR_STATUS, "PAC_2024": EXTERNAL_VALIDATOR_STATUS},
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


def build_matrix(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.workspace)
    rows: list[dict[str, Any]] = []
    if args.inspect_existing:
        rows.extend(inspect_existing(workspace))
    if args.pdf:
        rows.extend(run_specs(workspace, args.pdf, args.python_bin))
    if not rows:
        rows.append(_minimal_row(workspace, "", "", Path(""), "INCOMPLETE_ARTIFACTS", ["no workspace job artifacts or explicit PDF specs found"], "inspected_existing"))
    return {
        "schema": "montefiore.production_readiness_matrix",
        "version": "1.1.0",
        "created_at": now(),
        "workspace": str(workspace),
        "mode": "mixed" if args.inspect_existing and args.pdf else "inspect_existing" if args.inspect_existing else "orchestrator_run" if args.pdf else "none",
        "records": rows,
        "summary": summarize(rows),
        "policy": {
            "read_only_artifact_inspection": bool(args.inspect_existing),
            "external_validators_default": EXTERNAL_VALIDATOR_STATUS,
            "does_not_modify_repair_scripts": True,
            "does_not_modify_rule_map": True,
            "does_not_claim_10_of_10_production_readiness": True,
            "basename_matched_package_attribution": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--inspect-existing", action="store_true")
    parser.add_argument("--pdf", action="append", default=[], help="ticket:basename:path[:source_kind]")
    parser.add_argument("--python-bin", default=sys.executable)
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
