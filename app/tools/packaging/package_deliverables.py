#!/usr/bin/env python3
"""package_deliverables.py

Assembles final deliverables. Authoritative routing is orchestrator_outcome.json
first, then STATUS.json, then shared verdict_input.json. FAIL/ESCALATION are
report-only; REVIEW_REQUIRED still passes through with PDF for human review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.lib.verdict import VerdictInput, verdict
from tools.lib.residual_verdict import summarize_residual_analysis, summarize_strategy_indexing


parser = argparse.ArgumentParser()
parser.add_argument("job_dir")
parser.add_argument("remediated_pdf")
parser.add_argument("--output-dir", default=None, help="Final deliverables destination")
parser.add_argument("--source-pdf", default="")
parser.add_argument("--skip-pdf", action="store_true", help="Write audit report only, do not copy PDF")
args = parser.parse_args()

job_dir = Path(args.job_dir)
pdf_src = Path(args.remediated_pdf)
if not job_dir.exists():
    print(json.dumps({"result": "ERROR", "error": f"Job dir not found: {job_dir}"}))
    sys.exit(2)
if not pdf_src.exists():
    print(json.dumps({"result": "ERROR", "error": f"PDF not found: {pdf_src}"}))
    sys.exit(2)

if args.output_dir:
    output_dir = Path(args.output_dir)
else:
    ticket_part = job_dir.name.split("_")[0]
    workspace = job_dir.parent.parent
    output_dir = workspace / "output" / f"{ticket_part}_remediated"
output_dir.mkdir(parents=True, exist_ok=True)

for sub in ("pdf", "reports", "qa", "logs", "audit"):
    (job_dir / sub).mkdir(exist_ok=True)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Keep the internal package complete; final handoff routing below decides whether
# the PDF is copied to the deliverables directory.
dest_pdf_internal = job_dir / "pdf" / pdf_src.name
shutil.copy2(pdf_src, dest_pdf_internal)

checksum_lines = []
for file_path in sorted(job_dir.rglob("*")):
    if file_path.is_file() and file_path.name != "SHA256SUMS.txt":
        try:
            rel = file_path.relative_to(job_dir)
            checksum_lines.append(f"{sha256(file_path)} {rel}\n")
        except Exception:
            pass
(job_dir / "SHA256SUMS.txt").write_text("".join(checksum_lines))

contents = f"""# Package Contents

**Job:** {job_dir.name}
**Assembled:** {datetime.now(timezone.utc).isoformat()}
**Remediated PDF:** {pdf_src.name}
{"**Source PDF:** " + args.source_pdf if args.source_pdf else ""}

## Files

| Path | Description |
|------|-------------|
| pdf/{pdf_src.name} | Remediated PDF output |
| audit/ | Audit and validation JSON + XML reports |
| repair/ | Intermediate repair outputs |
| qa/ | Visual QA thumbnails and render comparisons |
| reports/ | Alt text drafts, review HTML, alt maps |
| STATUS.json | Overall remediation status |
| SHA256SUMS.txt | File integrity checksums |
"""
(job_dir / "PACKAGE_CONTENTS.md").write_text(contents)

status_path = job_dir / "STATUS.json"
status = _load_json(status_path) or {}
overall_raw = status.get("overall_result") or status.get("result") or "UNKNOWN"
gates = status.get("gates", {}) if isinstance(status.get("gates", {}), dict) else {}
generated_at = status.get("generated_at", datetime.now(timezone.utc).isoformat())

audit_dir = job_dir / "audit"
outcome_path = audit_dir / "orchestrator_outcome.json"
verdict_input_path = audit_dir / "verdict_input.json"
residual = summarize_residual_analysis(job_dir)
strategy = summarize_strategy_indexing(job_dir)

authoritative_overall = None
routing_source = "none"
if outcome_path.exists():
    try:
        outcome = _load_json(outcome_path) or {}
        authoritative_overall = outcome.get("overall_result")
        routing_source = "orchestrator_outcome.json"
    except Exception:
        pass
if authoritative_overall is None and status:
    authoritative_overall = overall_raw
    routing_source = "STATUS.json"
if authoritative_overall is None and verdict_input_path.exists():
    try:
        raw = _load_json(verdict_input_path) or {}
        residual = raw.get("residual_analysis") or residual
        strategy = raw.get("strategy_indexing") or strategy
        vi = VerdictInput.from_gate_dict(
            raw.get("gates", {}),
            hermes_signals_count=raw.get("hermes_signals_count", 0),
            deviations_count=raw.get("deviations_count", 0),
            total_iterations=raw.get("total_iterations", 0),
            job_hard_cap=raw.get("job_hard_cap", 50),
            has_hard_cap_exceeded=raw.get("has_hard_cap_exceeded", False),
            experimental_profile_failures=raw.get("experimental_profile_failures", []),
            pending_review_rules=raw.get("pending_review_rules", residual.get("pending_review_rules", [])),
            residual_analysis=residual,
            strategy_indexing=strategy,
            targetable_residual_rules=raw.get("targetable_residual_rules", residual.get("targetable_residual_rules", [])),
            non_targetable_residual_rules=raw.get("non_targetable_residual_rules", residual.get("non_targetable_residual_rules", [])),
            introduced_rules=raw.get("introduced_rules", residual.get("introduced_rules", [])),
            partially_resolved_rules=raw.get("partially_resolved_rules", residual.get("partially_resolved_rules", [])),
            transport_blocked=bool(raw.get("transport_blocked", False)),
        )
        authoritative_overall = verdict(vi).overall
        routing_source = "verdict_input.json"
    except Exception:
        pass

overall = authoritative_overall or "UNKNOWN"
effective_skip_pdf = args.skip_pdf or overall in ("FAIL", "ESCALATION")
if overall in ("FAIL", "ESCALATION") and not args.skip_pdf:
    print(json.dumps({
        "result": "WARN",
        "warning": f"overall={overall}; producing report-only output (PDF not copied).",
        "overall_result": overall,
        "job_dir": str(job_dir),
    }, indent=2), file=sys.stderr)

if args.source_pdf:
    basename = Path(args.source_pdf).stem
else:
    basename = pdf_src.stem
basename = re.sub(r"^pass\d+_", "", basename)
basename = basename.replace("_remediated", "").replace("-remediated", "")


def gate_row(name: str, display: str) -> str:
    gate = gates.get(name, {})
    result = gate.get("result", "NOT_RUN") if isinstance(gate, dict) else "NOT_RUN"
    icon = "PASS" if result in ("PASS", "FIXED", "ALREADY_CORRECT", "PASS_WITH_MIXED_PAGES", "SKIPPED") else "WARN" if result in ("REVIEW_REQUIRED", "WARN", "NEEDS_REVIEW") else "FAIL" if result == "FAIL" else "-"
    return f"| {display} | {icon} {result} |\n"


audit_report = f"""# Montefiore PDF/UA Remediation Audit Report

**Source:** {basename}.pdf
**Remediated:** {pdf_src.name}
**Job:** {job_dir.name}
**Generated:** {generated_at}
**Overall Result:** {overall}
**Routing Source:** {routing_source}

---

## Gate Results

| Gate | Result |
|------|--------|
{gate_row('qpdf', 'Structural integrity (qpdf)')}{gate_row('verapdf_pdfua1', 'veraPDF PDF/UA-1 + WCAG 2.2')}{gate_row('metadata_parity', 'Metadata XMP parity')}{gate_row('preservation', 'Native text preservation')}{gate_row('table_semantics', 'Table semantics')}{gate_row('contrast', 'Contrast (WCAG 1.4.3)')}{gate_row('alt_text', 'Figure alt text')}{gate_row('ocr_detection', 'OCR pre-flight')}{gate_row('render_compare', 'Visual render comparison')}{gate_row('visual_qa', 'Visual QA')}
---

## Patch 5 Residual-Aware Verdict Data

- Residual analysis available: {residual.get('available')}
- Targetable residual rules: {len(residual.get('targetable_residual_rules', []))}
- Non-targetable residual rules: {len(residual.get('non_targetable_residual_rules', []))}
- Pending review rules: {len(residual.get('pending_review_rules', []))}
- Strategy indexing available: {strategy.get('available')}
- Proposed rule-map changes referenced only: {strategy.get('proposed_rule_map_changes_count', 0)}

---

## External Validators

axesCheck and PAC 2024 are not run in this container. The receiving party should run these before final sign-off.

---

## Notes

- This document and associated files are provided for review.
- Source files are preserved in the job directory.
- SHA-256 checksums are in SHA256SUMS.txt in the job directory.
- Do not consider this PDF fully compliant until external validators have been run.
"""

out_pdf_name = f"{basename}_remediated.pdf"
out_report_name = f"{basename}_AUDIT_REPORT.md"
out_report = output_dir / out_report_name
out_report.write_text(audit_report)

deliverables = {"audit_report": str(out_report)}
if not effective_skip_pdf:
    out_pdf = output_dir / out_pdf_name
    shutil.copy2(pdf_src, out_pdf)
    deliverables["pdf"] = str(out_pdf)
    out_checksum = f"{sha256(out_pdf)} {out_pdf_name}\n{sha256(out_report)} {out_report_name}\n"
else:
    out_checksum = f"{sha256(out_report)} {out_report_name}\n"

(output_dir / "SHA256SUMS.txt").write_text(out_checksum)
deliverables["checksums"] = str(output_dir / "SHA256SUMS.txt")

print(json.dumps({
    "result": "OK",
    "job_dir": str(job_dir),
    "output_dir": str(output_dir),
    "skip_pdf": args.skip_pdf,
    "effective_skip_pdf": effective_skip_pdf,
    "deliverables": deliverables,
    "internal_package": {
        "pdf": str(dest_pdf_internal),
        "checksums": str(job_dir / "SHA256SUMS.txt"),
        "manifest": str(job_dir / "PACKAGE_CONTENTS.md"),
    },
    "overall_result": overall,
    "routing_source": routing_source,
    "residual_analysis": residual,
    "strategy_indexing": strategy,
}, indent=2, sort_keys=True))
sys.exit(0)
