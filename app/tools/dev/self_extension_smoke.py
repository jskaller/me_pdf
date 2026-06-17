#!/usr/bin/env python3
"""
Deterministic self-extension candidate-path smoke harness.

Patch 7 scope:
- fake/stub gateway only by default;
- generated candidates stay in job-scoped quarantine;
- candidate PDFs are not adopted as final outputs;
- canonical rule map and app/tools/repair are never mutated;
- dry-run indexer may propose changes but never applies them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from tools.audit.post_job_indexer import run_indexing, resolve_default_rule_map
except ModuleNotFoundError:  # direct execution from /app without PYTHONPATH
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.audit.post_job_indexer import run_indexing, resolve_default_rule_map  # type: ignore

SCHEMA_VERSION = "self-extension-smoke.v1"
EXECUTION_LOG_SCHEMA_VERSION = "execution-log.v2"
LEARNED_SCHEMA_VERSION = "learned-strategies.v1"
DEFAULT_RULE_ID = "PDF/UA-1/7.21.7"
MODES = ("fake-clean", "fake-dirty", "fake-failed", "fake-refusal")


class SmokeHarnessError(RuntimeError):
    """Raised when the deterministic smoke harness cannot proceed safely."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default))
    tmp.replace(path)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def sha256_file(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relative_or_str(path: Optional[Path], root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def require_under(path: Path, root: Path, label: str) -> Path:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SmokeHarnessError(f"unsafe {label}: {resolved_path} is outside {resolved_root}") from exc
    return resolved_path


def assert_no_canonical_writes(path: Path) -> None:
    parts = set(path.resolve().parts)
    if "app" in parts and "tools" in parts and "repair" in parts:
        raise SmokeHarnessError(f"generated candidate path is not allowed under app/tools/repair: {path}")


def make_minimal_pdf(path: Path) -> None:
    # A tiny syntactically valid one-page PDF fixture. It is intentionally not a
    # Montefiore document and is used only to exercise plumbing.
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>endobj\n"
    )
    xref_offset = len(body)
    pdf = body + (
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    path.write_bytes(pdf)


def fake_gateway_response(mode: str, rule_id: str) -> Dict[str, Any]:
    if mode == "fake-refusal":
        return {
            "result": "NEEDS_MORE_EVIDENCE",
            "rule_id": rule_id,
            "strategy": "smoke_needs_more_evidence",
            "notes": "Deterministic refusal mode used to prove non-script capture.",
            "risks": [],
        }

    if mode == "fake-failed":
        script_source = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

def main() -> int:
    payload = {"result": "FAIL", "strategy": "smoke_forced_failure", "reason": "deterministic fake failure"}
    print(json.dumps(payload, sort_keys=True))
    return 17

if __name__ == "__main__":
    raise SystemExit(main())
"""
    else:
        script_source = """#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    src = Path(args.input_pdf)
    dst = Path(args.output_pdf)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    payload = {
        "result": "PASS",
        "strategy": "smoke_copy_pdf_candidate",
        "reason": "deterministic quarantine smoke candidate copied input to output",
        "output_pdf": str(dst),
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"""

    return {
        "result": "SCRIPT_SOURCE",
        "rule_id": rule_id,
        "strategy": "smoke_copy_pdf_candidate" if mode != "fake-failed" else "smoke_forced_failure",
        "script_source": script_source,
        "expected_args_pattern": "input_pdf output_pdf [--out results.json]",
        "notes": f"Deterministic {mode} SCRIPT_SOURCE payload.",
        "risks": [],
    }


def parse_script_source(response: Dict[str, Any], mode: str) -> Tuple[Optional[str], Optional[str]]:
    result = str(response.get("result") or "").strip().upper()
    if result != "SCRIPT_SOURCE":
        if mode == "fake-refusal" and result in {"NEEDS_MORE_EVIDENCE", "NOT_AUTOMATABLE"}:
            return None, result
        raise SmokeHarnessError(f"fake provider response did not contain SCRIPT_SOURCE: {result}")
    source = response.get("script_source")
    if not isinstance(source, str) or not source.strip():
        raise SmokeHarnessError("SCRIPT_SOURCE response missing non-empty script_source")
    return source, None


def execution_log_path(job_dir: Path) -> Path:
    return job_dir / "audit" / "execution_log.json"


def load_execution_log(job_dir: Path) -> Dict[str, Any]:
    path = execution_log_path(job_dir)
    if not path.exists():
        return {
            "schema_version": EXECUTION_LOG_SCHEMA_VERSION,
            "artifact": "execution_log",
            "records": [],
        }
    data = read_json(path)
    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": data.get("schema_version") or EXECUTION_LOG_SCHEMA_VERSION,
        "artifact": data.get("artifact") or "execution_log",
        "records": records,
    }


def append_execution_record(job_dir: Path, record: Dict[str, Any]) -> None:
    log = load_execution_log(job_dir)
    log["schema_version"] = EXECUTION_LOG_SCHEMA_VERSION
    log["artifact"] = "execution_log"
    log.setdefault("records", []).append(record)
    write_json_atomic(execution_log_path(job_dir), log)


def sidecar_hash(path: Path) -> Optional[str]:
    return sha256_file(path) if path.exists() else None


def execute_candidate(
    *,
    job_dir: Path,
    mode: str,
    rule_id: str,
    run_id: str,
    attempt_id: str,
    script_path: Path,
    input_pdf: Path,
    output_pdf: Path,
    timeout_seconds: int,
) -> Dict[str, Any]:
    require_under(script_path, job_dir, "script_path")
    require_under(output_pdf, job_dir, "output_pdf")
    assert_no_canonical_writes(script_path)
    assert_no_canonical_writes(output_pdf)

    py_compile.compile(str(script_path), doraise=True)

    stdout_path = job_dir / "audit" / "execution" / "stdout" / f"{attempt_id}.out"
    stderr_path = job_dir / "audit" / "execution" / "stderr" / f"{attempt_id}.err"
    result_json_path = job_dir / "audit" / "self_extension" / "quarantine" / mode / f"{attempt_id}.result.json"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    input_before = sha256_file(input_pdf)
    started_monotonic = time.monotonic()
    started_at = utc_now_iso()
    exception_fields: Dict[str, Any] = {}
    exit_code: Optional[int] = None
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                str(input_pdf),
                str(output_pdf),
                "--out",
                str(result_json_path),
            ],
            cwd=str(job_dir),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            },
        )
        exit_code = int(proc.returncode)
        stdout_path.write_text(proc.stdout or "")
        stderr_path.write_text(proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout_path.write_text(exc.stdout or "")
        stderr_path.write_text((exc.stderr or "") + "\nTIMEOUT\n")
        exception_fields = {"exception_type": "TimeoutExpired", "exception_message": str(exc)}
    except Exception as exc:  # failure is captured, not swallowed
        exit_code = 1
        stdout_path.write_text("")
        stderr_path.write_text(str(exc))
        exception_fields = {"exception_type": type(exc).__name__, "exception_message": str(exc)}

    finished_at = utc_now_iso()
    duration_ms = int((time.monotonic() - started_monotonic) * 1000)
    input_after = sha256_file(input_pdf)
    output_hash = sha256_file(output_pdf)
    stdout_hash = sidecar_hash(stdout_path)
    stderr_hash = sidecar_hash(stderr_path)
    script_hash = sha256_file(script_path)

    contract_result = "PASS" if exit_code == 0 and output_pdf.exists() and input_before == input_after else "FAIL"
    record = {
        "record_type": "self_extension_candidate",
        "attempt_id": attempt_id,
        "run_id": run_id,
        "mode": mode,
        "rule_id": rule_id,
        "rules_targeted": [rule_id],
        "script_path": relative_or_str(script_path, job_dir),
        "script_sha256": script_hash,
        "input_pdf": relative_or_str(input_pdf, job_dir),
        "input_pdf_sha256": input_before,
        "input_pdf_sha256_after": input_after,
        "output_pdf": relative_or_str(output_pdf, job_dir),
        "output_pdf_sha256": output_hash,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "stdout_path": relative_or_str(stdout_path, job_dir),
        "stdout_sha256": stdout_hash,
        "stderr_path": relative_or_str(stderr_path, job_dir),
        "stderr_sha256": stderr_hash,
        "result_json_path": relative_or_str(result_json_path, job_dir) if result_json_path.exists() else None,
        "result": contract_result,
        "status": "completed" if exit_code == 0 else "failed",
        "policy": {
            "quarantine_only": True,
            "canonical_rule_map_mutation_performed": False,
            "generated_script_promotion_performed": False,
            "final_pdf_adoption_performed": False,
            "environment_secrets_logged": False,
        },
    }
    record.update(exception_fields)
    append_execution_record(job_dir, record)
    return record


def write_residual_analysis(job_dir: Path, mode: str, rule_id: str) -> Path:
    if mode == "fake-clean":
        residuals_after: List[Dict[str, Any]] = []
        result = "PASS"
    elif mode == "fake-dirty":
        residuals_after = [
            {"rule_id": "PDF/UA-1/7.18.4", "failures": 1, "status": "introduced_by_fake_dirty"}
        ]
        result = "FAIL"
    elif mode == "fake-failed":
        residuals_after = [{"rule_id": rule_id, "failures": 1, "status": "candidate_failed"}]
        result = "FAIL"
    else:
        residuals_after = [{"rule_id": rule_id, "failures": 1, "status": "needs_more_evidence"}]
        result = "ESCALATION"
    payload = {
        "schema_version": "residual-analysis.v1",
        "artifact": "residual_analysis",
        "created_at": utc_now_iso(),
        "job_dir": str(job_dir),
        "mode": mode,
        "overall_result": result,
        "active_actionable_residuals": residuals_after,
        "target_rule_id": rule_id,
        "smoke_harness": True,
    }
    path = job_dir / "audit" / "residual_analysis.json"
    write_json_atomic(path, payload)
    return path


def learned_record(
    *,
    job_dir: Path,
    mode: str,
    rule_id: str,
    run_id: str,
    response: Dict[str, Any],
    execution_record: Optional[Dict[str, Any]],
    script_path: Optional[Path],
) -> Dict[str, Any]:
    base = {
        "created_at": utc_now_iso(),
        "schema_version": LEARNED_SCHEMA_VERSION,
        "run_id": run_id,
        "job_dir": str(job_dir),
        "rule_id": rule_id,
        "clause": rule_id,
        "description": "Patch 7 deterministic self-extension smoke target",
        "attempt_number": 1,
        "mode": mode,
        "generation_response": {k: v for k, v in response.items() if k != "script_source"},
        "proposed_resolvability": "repairable_review",
        "review_required": True,
        "run_last": False,
        "repair_order": None,
        "args_pattern": "input_pdf output_pdf [--out results.json]",
        "validation_artifacts": {
            "residual_analysis": "audit/residual_analysis.json",
            "execution_log": "audit/execution_log.json",
        },
    }

    if execution_record:
        base.update(
            {
                "execution_attempt_id": execution_record.get("attempt_id"),
                "execution_log_path": "audit/execution_log.json",
                "stdout_path": execution_record.get("stdout_path"),
                "stdout_sha256": execution_record.get("stdout_sha256"),
                "stderr_path": execution_record.get("stderr_path"),
                "stderr_sha256": execution_record.get("stderr_sha256"),
                "script_path": execution_record.get("script_path"),
                "script_sha256": execution_record.get("script_sha256"),
                "candidate_output_pdf": execution_record.get("output_pdf"),
                "candidate_output_pdf_sha256": execution_record.get("output_pdf_sha256"),
            }
        )
    elif script_path is not None:
        base.update({"script_path": relative_or_str(script_path, job_dir), "script_sha256": sha256_file(script_path)})
    else:
        base.update({"script_path": None, "script_sha256": None})

    if mode == "fake-clean":
        base.update(
            {
                "outcome": "clean_success",
                "clean": True,
                "indexing_eligible": True,
                "target_rule_resolved": True,
                "pre_count": 1,
                "post_count": 0,
                "introduced_rules": [],
                "worsened_rules": [],
                "indexing_blockers": [],
                "gate_results": {"preservation": "PASS", "form_fields": "PASS", "render_compare": "PASS"},
                "failure_summary": None,
            }
        )
    elif mode == "fake-dirty":
        base.update(
            {
                "outcome": "dirty_success",
                "clean": False,
                "indexing_eligible": False,
                "target_rule_resolved": True,
                "pre_count": 1,
                "post_count": 0,
                "introduced_rules": ["PDF/UA-1/7.18.4"],
                "worsened_rules": [],
                "indexing_blockers": ["introduced_rules:PDF/UA-1/7.18.4"],
                "gate_results": {"preservation": "PASS", "form_fields": "PASS", "render_compare": "PASS"},
                "failure_summary": "candidate resolved target but introduced/worsened controlled validation evidence",
            }
        )
    elif mode == "fake-failed":
        base.update(
            {
                "outcome": "validation_failed",
                "clean": False,
                "indexing_eligible": False,
                "target_rule_resolved": False,
                "pre_count": 1,
                "post_count": 1,
                "introduced_rules": [],
                "worsened_rules": [],
                "indexing_blockers": ["candidate_execution_failed"],
                "gate_results": {"preservation": "NOT_RUN", "form_fields": "NOT_RUN", "render_compare": "NOT_RUN"},
                "failure_summary": "candidate script exited nonzero in deterministic fake-failed mode",
            }
        )
    else:
        base.update(
            {
                "outcome": "needs_more_evidence",
                "clean": False,
                "indexing_eligible": False,
                "target_rule_resolved": False,
                "pre_count": 1,
                "post_count": 1,
                "introduced_rules": [],
                "worsened_rules": [],
                "indexing_blockers": ["no_script_source_generated", "semantic_refusal_or_needs_more_evidence"],
                "gate_results": {"preservation": "NOT_RUN", "form_fields": "NOT_RUN", "render_compare": "NOT_RUN"},
                "failure_summary": "fake provider returned NEEDS_MORE_EVIDENCE; no candidate script was executed",
                "execution_attempt_id": None,
                "execution_log_path": None,
            }
        )
    return base


def write_learned_strategy(job_dir: Path, record: Dict[str, Any]) -> Path:
    path = job_dir / "audit" / "learned_strategies.json"
    artifact = {
        "schema_version": LEARNED_SCHEMA_VERSION,
        "artifact": "learned_strategies",
        "records": [record],
    }
    write_json_atomic(path, artifact)
    return path


def write_run_state_event(job_dir: Path, mode: str, rule_id: str, run_id: str, response: Dict[str, Any]) -> Path:
    path = job_dir / "audit" / "self_extension" / "run_state.json"
    event = {
        "schema_version": "self-extension-run-state-smoke.v1",
        "run_id": run_id,
        "mode": mode,
        "rule_id": rule_id,
        "created_at": utc_now_iso(),
        "generation_events": [
            {
                "result": response.get("result"),
                "strategy": response.get("strategy"),
                "script_source_sha256": sha256_text(response.get("script_source", "")) if response.get("script_source") else None,
                "durable": True,
            }
        ],
        "policy": {
            "fake_gateway": True,
            "live_gateway_used": False,
            "no_adoption": True,
        },
    }
    write_json_atomic(path, event)
    return path


def run_smoke(
    *,
    job_dir: Path,
    mode: str,
    rule_id: str = DEFAULT_RULE_ID,
    rule_map_path: Optional[Path] = None,
    run_indexer: bool = True,
    timeout_seconds: int = 10,
) -> Dict[str, Any]:
    if mode not in MODES:
        raise SmokeHarnessError(f"unsupported mode {mode!r}; expected one of {', '.join(MODES)}")

    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    require_under(job_dir / "audit", job_dir, "audit_dir")
    run_id = f"selfext-smoke-{uuid.uuid4().hex[:12]}"
    attempt_id = f"{run_id}-attempt-1"

    input_pdf = job_dir / "input" / "smoke_input.pdf"
    output_pdf = job_dir / "repair" / "self_extension_candidates" / mode / "candidate_output.pdf"
    make_minimal_pdf(input_pdf)

    response = fake_gateway_response(mode, rule_id)
    write_run_state_event(job_dir, mode, rule_id, run_id, response)
    script_source, terminal_generation_result = parse_script_source(response, mode)

    execution_record: Optional[Dict[str, Any]] = None
    script_path: Optional[Path] = None

    if script_source is not None:
        script_dir = job_dir / "audit" / "self_extension" / "quarantine" / mode
        script_path = script_dir / "candidate.py"
        require_under(script_path, job_dir, "script_path")
        assert_no_canonical_writes(script_path)
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script_source)
        execution_record = execute_candidate(
            job_dir=job_dir,
            mode=mode,
            rule_id=rule_id,
            run_id=run_id,
            attempt_id=attempt_id,
            script_path=script_path,
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            timeout_seconds=timeout_seconds,
        )

    residual_path = write_residual_analysis(job_dir, mode, rule_id)
    learned = learned_record(
        job_dir=job_dir,
        mode=mode,
        rule_id=rule_id,
        run_id=run_id,
        response=response,
        execution_record=execution_record,
        script_path=script_path,
    )
    learned_path = write_learned_strategy(job_dir, learned)

    index_report: Optional[Dict[str, Any]] = None
    report_path: Optional[Path] = None
    if run_indexer:
        resolved_rule_map = Path(rule_map_path) if rule_map_path else resolve_default_rule_map()
        report_path = job_dir / "audit" / "strategy_indexing_report.json"
        index_report = run_indexing(
            job_dir=job_dir,
            rule_map_path=resolved_rule_map,
            dry_run=True,
            report_path=report_path,
        )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "result": "PASS",
        "mode": mode,
        "job_dir": str(job_dir),
        "rule_id": rule_id,
        "run_id": run_id,
        "terminal_generation_result": terminal_generation_result,
        "execution_attempt_id": execution_record.get("attempt_id") if execution_record else None,
        "execution_log_path": str(execution_log_path(job_dir)) if execution_record else None,
        "learned_strategies_path": str(learned_path),
        "residual_analysis_path": str(residual_path),
        "strategy_indexing_report_path": str(report_path) if report_path else None,
        "outcome": learned.get("outcome"),
        "clean": learned.get("clean"),
        "indexing_eligible": learned.get("indexing_eligible"),
        "proposed_rule_map_change_count": len(index_report.get("proposed_rule_map_changes", [])) if index_report else 0,
        "rejected_experiment_count": len(index_report.get("rejected_experiments", [])) if index_report else 0,
        "policy": {
            "canonical_rule_map_mutation_performed": False,
            "generated_script_promotion_performed": False,
            "final_pdf_adoption_performed": False,
            "generated_scripts_stayed_in_quarantine": script_path is None or "audit/self_extension/quarantine" in relative_or_str(script_path, job_dir).replace(os.sep, "/"),
        },
    }
    write_json_atomic(job_dir / "audit" / "self_extension_smoke_summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic self-extension candidate-path smoke harness.")
    parser.add_argument("--job-dir", required=True, help="Controlled smoke job directory")
    parser.add_argument("--mode", choices=MODES, required=True, help="Deterministic fake provider mode")
    parser.add_argument("--rule-id", default=DEFAULT_RULE_ID, help="Target PDF/UA rule id")
    parser.add_argument("--rule-map", default=None, help="Optional rule_repair_map.json path for dry-run indexer")
    parser.add_argument("--no-indexer", action="store_true", help="Skip dry-run strategy indexer")
    parser.add_argument("--timeout-seconds", type=int, default=10, help="Candidate execution timeout")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_smoke(
            job_dir=Path(args.job_dir),
            mode=args.mode,
            rule_id=args.rule_id,
            rule_map_path=Path(args.rule_map) if args.rule_map else None,
            run_indexer=not args.no_indexer,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(json.dumps({"result": "ERROR", "reason": str(exc), "type": type(exc).__name__}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
