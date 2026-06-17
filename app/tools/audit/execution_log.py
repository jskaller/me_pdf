#!/usr/bin/env python3
"""
execution_log.py

High-fidelity execution-log helpers for known-repair orchestration.
Patch 6 promotes execution_log.json from an inferred reconstruction to an
appendable audit ledger with subprocess/callable evidence, stdout/stderr
sidecars, hashes, timings, result/exception state, and a backward-compatible
repair_steps view for older residual-analysis consumers.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

SCHEMA_VERSION = "execution-log.v2"
LEGACY_SCHEMA_VERSION = "1.0.0"

RECORD_REPAIR_STEP = "repair_step"
RECORD_VALIDATION_STEP = "validation_step"
RECORD_SELF_EXTENSION_GENERATION = "self_extension_generation"
RECORD_SELF_EXTENSION_CANDIDATE = "self_extension_candidate"
RECORD_TRANSPORT_EVENT = "transport_event"
RECORD_SEMANTIC_REFUSAL = "semantic_refusal"
RECORD_NEEDS_MORE_EVIDENCE = "needs_more_evidence"
RECORD_BOUNDARY_VIOLATION = "boundary_violation"

RAN_SUCCESS = "ran_success"
RAN_FAILED = "ran_failed"
SKIPPED_NO_STRATEGY = "skipped_no_strategy"
SKIPPED_NOT_AUTO_FIXABLE = "skipped_not_auto_fixable"
SKIPPED_REVIEW_REQUIRED = "skipped_review_required"
SKIPPED_GUARD_DISABLED = "skipped_guard_disabled"
NOT_APPLICABLE = "not_applicable"

VALID_RESULT_CATEGORIES = {
    RAN_SUCCESS,
    RAN_FAILED,
    SKIPPED_NO_STRATEGY,
    SKIPPED_NOT_AUTO_FIXABLE,
    SKIPPED_REVIEW_REQUIRED,
    SKIPPED_GUARD_DISABLED,
    NOT_APPLICABLE,
}

RECORD_TYPES = {
    RECORD_REPAIR_STEP,
    RECORD_VALIDATION_STEP,
    RECORD_SELF_EXTENSION_GENERATION,
    RECORD_SELF_EXTENSION_CANDIDATE,
    RECORD_TRANSPORT_EVENT,
    RECORD_SEMANTIC_REFUSAL,
    RECORD_NEEDS_MORE_EVIDENCE,
    RECORD_BOUNDARY_VIOLATION,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Optional[Path | str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _path(path: Optional[Path | str]) -> Optional[str]:
    return str(path) if path is not None else None


def _safe_id(value: Any) -> str:
    raw = str(value or "step").strip().replace(os.sep, "_")
    raw = re_sub_safe(raw)
    return raw.strip("-_") or "step"


def re_sub_safe(raw: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


def _rules_from_step(step: Optional[Dict[str, Any]]) -> list[str]:
    if not isinstance(step, dict):
        return []
    rules = step.get("rules_addressed") or step.get("rule_ids") or step.get("rule_id") or []
    if isinstance(rules, str):
        rules = [rules]
    return [str(r) for r in rules if str(r)]


def _file_size(path: Optional[Path | str]) -> Optional[int]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    return p.stat().st_size


def _attempt_prefix(record_type: str) -> str:
    return {
        RECORD_REPAIR_STEP: "repair",
        RECORD_VALIDATION_STEP: "validation",
        RECORD_SELF_EXTENSION_GENERATION: "selfext-generation",
        RECORD_SELF_EXTENSION_CANDIDATE: "selfext-candidate",
        RECORD_TRANSPORT_EVENT: "transport",
        RECORD_SEMANTIC_REFUSAL: "semantic-refusal",
        RECORD_NEEDS_MORE_EVIDENCE: "needs-more-evidence",
        RECORD_BOUNDARY_VIOLATION: "boundary-violation",
    }.get(record_type, "attempt")


def make_attempt_id(
    *,
    log: Optional[Dict[str, Any]] = None,
    record_type: str = RECORD_REPAIR_STEP,
    step_name: Optional[str] = None,
    iteration: Optional[int] = None,
    rule_id: Optional[str] = None,
    attempt_number: Optional[int] = None,
) -> str:
    stem = _safe_id(step_name or rule_id or record_type)
    prefix = _attempt_prefix(record_type)
    if attempt_number is None:
        existing = len((log or {}).get("records", []) or []) + 1
        attempt_number = existing
    if record_type == RECORD_REPAIR_STEP:
        iter_part = f"iter{iteration}" if iteration is not None else "iter0"
        return f"{prefix}-{iter_part}-{stem}-{attempt_number:03d}"
    if rule_id:
        return f"{prefix}-rule-{_safe_id(rule_id)}-attempt-{attempt_number:03d}"
    return f"{prefix}-{stem}-{attempt_number:03d}"


def _environment_summary(env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source = env if env is not None else os.environ
    safe_keys = [
        "PYTHONPATH",
        "REMEDIATION_PYTHON",
        "VERAPDF_PROFILE_PATH",
        "VERAPDF_PROFILE_SOURCE",
        "PATH",
    ]
    return {key: str(source.get(key, "")) for key in safe_keys if source.get(key)}


def _repair_step_compat(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    rules = record.get("rules_targeted") or record.get("rule_ids") or []
    if isinstance(rules, str):
        rules = [rules]
    result = record.get("result") or "UNKNOWN"
    success = result in {"PASS", "OK", "FIXED", "MODIFIED", "PARTIAL", "SUCCESS"}
    ran = result not in {"SKIPPED", "NOT_APPLICABLE"}
    category = record.get("result_category")
    if not category:
        category = RAN_SUCCESS if success else (RAN_FAILED if ran else NOT_APPLICABLE)
    return {
        "index": index,
        "attempt_id": record.get("attempt_id"),
        "iteration": record.get("iteration"),
        "step": record.get("step") or record.get("step_name"),
        "step_name": record.get("step_name"),
        "rule_ids": list(rules),
        "rules_targeted": list(rules),
        "strategy": record.get("strategy"),
        "repair_script": record.get("script"),
        "script": record.get("script"),
        "callable": record.get("callable"),
        "command": record.get("command"),
        "argv": record.get("argv"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "duration_ms": record.get("duration_ms"),
        "exit_code": record.get("exit_code"),
        "internal_status": result,
        "ran": ran,
        "skipped": not ran,
        "skip_reason": record.get("skip_reason"),
        "input_pdf": record.get("input_pdf"),
        "input_pdf_hash": record.get("input_pdf_sha256") or record.get("input_pdf_hash"),
        "output_pdf": record.get("output_pdf"),
        "output_pdf_hash": record.get("output_pdf_sha256") or record.get("output_pdf_hash"),
        "output_exists": record.get("output_exists"),
        "output_size": record.get("output_size"),
        "stdout_artifact": record.get("stdout_path"),
        "stderr_artifact": record.get("stderr_path"),
        "stdout_path": record.get("stdout_path"),
        "stderr_path": record.get("stderr_path"),
        "stdout_sha256": record.get("stdout_sha256"),
        "stderr_sha256": record.get("stderr_sha256"),
        "exception_type": record.get("exception_type"),
        "exception_message": record.get("exception_message"),
        "result_category": category,
        "notes": record.get("notes"),
    }


def refresh_compat_views(log: Dict[str, Any]) -> Dict[str, Any]:
    records = log.setdefault("records", [])
    repair_records = [r for r in records if isinstance(r, dict) and r.get("record_type") == RECORD_REPAIR_STEP]
    if repair_records:
        log["repair_steps"] = [_repair_step_compat(r, i + 1) for i, r in enumerate(repair_records)]
    else:
        log.setdefault("repair_steps", [])
    return log


def new_execution_log(
    *,
    job_dir: Path | str,
    source_pdf: Optional[Path | str] = None,
    current_pdf: Optional[Path | str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = utc_now()
    log = {
        "schema_version": SCHEMA_VERSION,
        "schema": "montefiore.execution_log",
        "version": LEGACY_SCHEMA_VERSION,
        "artifact": "execution_log",
        "created_at": now,
        "updated_at": now,
        "job_dir": str(job_dir),
        "run_id": run_id,
        "source_pdf": _path(source_pdf),
        "source_pdf_hash": sha256_file(source_pdf),
        "source_pdf_sha256": sha256_file(source_pdf),
        "current_pdf": _path(current_pdf),
        "current_pdf_hash": sha256_file(current_pdf),
        "current_pdf_sha256": sha256_file(current_pdf),
        "records": [],
        "repair_steps": [],
    }
    return log


def append_record(log: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    if record.get("record_type") not in RECORD_TYPES:
        record["record_type"] = record.get("record_type") or RECORD_REPAIR_STEP
    records = log.setdefault("records", [])
    records.append(record)
    log["updated_at"] = utc_now()
    refresh_compat_views(log)
    return record


def _sidecar_paths(job_dir: Path | str, attempt_id: str) -> tuple[Path, Path]:
    base = Path(job_dir) / "audit" / "execution"
    stdout = base / "stdout" / f"{attempt_id}.txt"
    stderr = base / "stderr" / f"{attempt_id}.txt"
    stdout.parent.mkdir(parents=True, exist_ok=True)
    stderr.parent.mkdir(parents=True, exist_ok=True)
    return stdout, stderr


def _write_text_sidecar(path: Path, content: Optional[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8", errors="replace")
    return path


def make_execution_record(
    *,
    log: Optional[Dict[str, Any]] = None,
    job_dir: Optional[Path | str] = None,
    record_type: str = RECORD_REPAIR_STEP,
    attempt_id: Optional[str] = None,
    run_id: Optional[str] = None,
    iteration: Optional[int] = None,
    step_name: Optional[str] = None,
    step: Optional[Dict[str, Any]] = None,
    strategy: Optional[str] = None,
    script: Optional[str] = None,
    callable_name: Optional[str] = None,
    rules_targeted: Optional[Iterable[str]] = None,
    input_pdf: Optional[Path | str] = None,
    output_pdf: Optional[Path | str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
    result: Optional[str] = None,
    result_category: Optional[str] = None,
    exception_type: Optional[str] = None,
    exception_message: Optional[str] = None,
    stdout_path: Optional[Path | str] = None,
    stderr_path: Optional[Path | str] = None,
    command: Optional[Iterable[Any]] = None,
    argv: Optional[Iterable[Any]] = None,
    cwd: Optional[Path | str] = None,
    environment_summary: Optional[Dict[str, Any]] = None,
    validation_artifacts: Optional[Dict[str, Any]] = None,
    pre_rule_counts: Optional[Dict[str, int]] = None,
    post_rule_counts: Optional[Dict[str, int]] = None,
    target_rule_pre_count: Optional[int] = None,
    target_rule_post_count: Optional[int] = None,
    target_rule_strictly_decreased: Optional[bool] = None,
    target_rule_resolved: Optional[bool] = None,
    introduced_rules: Optional[Iterable[str]] = None,
    worsened_rules: Optional[Iterable[str]] = None,
    preservation_result: Optional[str] = None,
    form_fields_result: Optional[str] = None,
    render_compare_result: Optional[str] = None,
    visual_qa_result: Optional[str] = None,
    notes: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    rules = list(rules_targeted or _rules_from_step(step))
    effective_step_name = step_name or (step or {}).get("step_name") or (step or {}).get("strategy") or (Path(str(script)).stem if script else None)
    if not attempt_id:
        attempt_id = make_attempt_id(log=log, record_type=record_type, step_name=effective_step_name, iteration=iteration)
    output_exists = bool(output_pdf and Path(output_pdf).exists())
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": record_type,
        "attempt_id": attempt_id,
        "run_id": run_id or (log or {}).get("run_id"),
        "iteration": iteration,
        "step": (step or {}).get("step"),
        "step_name": effective_step_name,
        "strategy": strategy if strategy is not None else (step or {}).get("strategy"),
        "script": script if script is not None else (step or {}).get("repair_script"),
        "callable": callable_name,
        "rules_targeted": rules,
        "rule_ids": rules,
        "input_pdf": _path(input_pdf),
        "input_pdf_sha256": sha256_file(input_pdf),
        "input_pdf_hash": sha256_file(input_pdf),
        "output_pdf": _path(output_pdf),
        "output_pdf_sha256": sha256_file(output_pdf),
        "output_pdf_hash": sha256_file(output_pdf),
        "output_exists": output_exists,
        "output_size": _file_size(output_pdf),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "result": result,
        "result_category": result_category,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "stdout_path": _path(stdout_path),
        "stderr_path": _path(stderr_path),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
        "command": [str(c) for c in command] if command is not None else None,
        "argv": [str(c) for c in argv] if argv is not None else None,
        "cwd": str(cwd) if cwd is not None else None,
        "environment_summary": environment_summary,
        "validation_artifacts": validation_artifacts or {},
        "pre_rule_counts": pre_rule_counts,
        "post_rule_counts": post_rule_counts,
        "target_rule_pre_count": target_rule_pre_count,
        "target_rule_post_count": target_rule_post_count,
        "target_rule_strictly_decreased": target_rule_strictly_decreased,
        "target_rule_resolved": target_rule_resolved,
        "introduced_rules": list(introduced_rules or []),
        "worsened_rules": list(worsened_rules or []),
        "preservation_result": preservation_result,
        "form_fields_result": form_fields_result,
        "render_compare_result": render_compare_result,
        "visual_qa_result": visual_qa_result,
        "notes": notes,
    }
    for key, value in extra.items():
        if value is not None:
            record[key] = value
    if not record.get("result_category"):
        if result in {"PASS", "OK", "FIXED", "MODIFIED", "PARTIAL", "SUCCESS"} or exit_code == 0:
            record["result_category"] = RAN_SUCCESS
        elif result in {"SKIPPED", "NOT_APPLICABLE"}:
            record["result_category"] = NOT_APPLICABLE
        else:
            record["result_category"] = RAN_FAILED
    return record


def record_execution_step(
    log: Dict[str, Any],
    *,
    step: Dict[str, Any],
    iteration: Optional[int] = None,
    strategy: Optional[str] = None,
    repair_script: Optional[str] = None,
    command: Optional[Iterable[Any]] = None,
    args_pattern: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    exit_code: Optional[int] = None,
    internal_status: Optional[str] = None,
    ran: bool = False,
    skipped: bool = False,
    skip_reason: Optional[str] = None,
    input_pdf: Optional[Path | str] = None,
    output_pdf: Optional[Path | str] = None,
    stdout_artifact: Optional[Path | str] = None,
    stderr_artifact: Optional[Path | str] = None,
    result_category: str = NOT_APPLICABLE,
    notes: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    if result_category not in VALID_RESULT_CATEGORIES:
        raise ValueError(f"unknown execution-log result category: {result_category}")
    record = make_execution_record(
        log=log,
        job_dir=log.get("job_dir"),
        record_type=RECORD_REPAIR_STEP,
        iteration=iteration,
        step_name=str(step.get("step") or step.get("strategy") or step.get("repair_script") or "repair_step"),
        step=step,
        strategy=strategy,
        script=repair_script,
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        started_at=started_at,
        finished_at=finished_at or utc_now(),
        exit_code=exit_code,
        result=internal_status,
        result_category=result_category,
        stdout_path=stdout_artifact,
        stderr_path=stderr_artifact,
        command=command,
        argv=command,
        notes=notes,
        skip_reason=skip_reason,
        args_pattern=args_pattern if args_pattern is not None else step.get("args_pattern"),
        ran=bool(ran),
        skipped=bool(skipped),
        **extra,
    )
    return append_record(log, record)


def record_subprocess_execution(
    log: Dict[str, Any],
    *,
    argv: Sequence[Any],
    record_type: str = RECORD_REPAIR_STEP,
    job_dir: Optional[Path | str] = None,
    attempt_id: Optional[str] = None,
    iteration: Optional[int] = None,
    step_name: Optional[str] = None,
    step: Optional[Dict[str, Any]] = None,
    strategy: Optional[str] = None,
    script: Optional[str] = None,
    rules_targeted: Optional[Iterable[str]] = None,
    input_pdf: Optional[Path | str] = None,
    output_pdf: Optional[Path | str] = None,
    cwd: Optional[Path | str] = None,
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = True,
    text: bool = True,
    notes: Optional[str] = None,
) -> tuple[subprocess.CompletedProcess[str], Dict[str, Any]]:
    job_dir = job_dir or log.get("job_dir") or "."
    if not attempt_id:
        attempt_id = make_attempt_id(log=log, record_type=record_type, step_name=step_name or script, iteration=iteration)
    stdout_path, stderr_path = _sidecar_paths(job_dir, attempt_id)
    started_at = utc_now()
    start = time.monotonic()
    exc_type = None
    exc_msg = None
    try:
        proc = subprocess.run(
            [str(a) for a in argv],
            capture_output=capture_output,
            text=text,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
        )
        stdout_text = proc.stdout if capture_output else ""
        stderr_text = proc.stderr if capture_output else ""
    except Exception as exc:
        proc = subprocess.CompletedProcess([str(a) for a in argv], 2, "", f"{type(exc).__name__}: {exc}")
        stdout_text = ""
        stderr_text = proc.stderr
        exc_type = type(exc).__name__
        exc_msg = str(exc)
    finished_at = utc_now()
    duration_ms = int((time.monotonic() - start) * 1000)
    _write_text_sidecar(stdout_path, stdout_text)
    _write_text_sidecar(stderr_path, stderr_text)
    result = "PASS" if proc.returncode == 0 else "FAIL"
    record = make_execution_record(
        log=log,
        job_dir=job_dir,
        record_type=record_type,
        attempt_id=attempt_id,
        iteration=iteration,
        step_name=step_name,
        step=step,
        strategy=strategy,
        script=script,
        rules_targeted=rules_targeted,
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        exit_code=proc.returncode,
        result=result,
        result_category=RAN_SUCCESS if proc.returncode == 0 else RAN_FAILED,
        exception_type=exc_type,
        exception_message=exc_msg,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=argv,
        argv=argv,
        cwd=cwd,
        environment_summary=_environment_summary(env),
        notes=notes,
    )
    append_record(log, record)
    return proc, record


def record_callable_execution(
    log: Dict[str, Any],
    *,
    func: Callable[..., Any],
    args: Optional[Sequence[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    record_type: str = RECORD_REPAIR_STEP,
    attempt_id: Optional[str] = None,
    iteration: Optional[int] = None,
    step_name: Optional[str] = None,
    step: Optional[Dict[str, Any]] = None,
    strategy: Optional[str] = None,
    script: Optional[str] = None,
    rules_targeted: Optional[Iterable[str]] = None,
    input_pdf: Optional[Path | str] = None,
    output_pdf: Optional[Path | str] = None,
    notes: Optional[str] = None,
) -> tuple[Any, Dict[str, Any]]:
    args = list(args or [])
    kwargs = dict(kwargs or {})
    started_at = utc_now()
    start = time.monotonic()
    result_obj = None
    exc_type = None
    exc_msg = None
    result = "PASS"
    try:
        result_obj = func(*args, **kwargs)
    except Exception as exc:
        result = "FAIL"
        exc_type = type(exc).__name__
        exc_msg = str(exc)
    finished_at = utc_now()
    duration_ms = int((time.monotonic() - start) * 1000)
    record = make_execution_record(
        log=log,
        job_dir=log.get("job_dir"),
        record_type=record_type,
        attempt_id=attempt_id,
        iteration=iteration,
        step_name=step_name or getattr(func, "__name__", "callable"),
        step=step,
        strategy=strategy,
        script=script,
        callable_name=f"{getattr(func, '__module__', '')}.{getattr(func, '__name__', 'callable')}",
        rules_targeted=rules_targeted,
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        exit_code=None,
        result=result,
        result_category=RAN_SUCCESS if result == "PASS" else RAN_FAILED,
        exception_type=exc_type,
        exception_message=exc_msg,
        notes=notes,
    )
    append_record(log, record)
    if exc_type:
        raise RuntimeError(exc_msg or exc_type)
    return result_obj, record


def build_execution_log_from_repair_steps(
    *,
    job_dir: Path | str,
    source_pdf: Optional[Path | str],
    current_pdf: Optional[Path | str],
    repair_steps: list[Dict[str, Any]],
    strategy_attempts: Dict[str, list[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Compatibility builder for older orchestrator paths.

    Patch 6 callers should append real records as work executes. This fallback
    still exists so older tests and consumers get a v2 top-level shape, but the
    resulting records are explicitly marked inferred.
    """
    log = new_execution_log(job_dir=job_dir, source_pdf=source_pdf, current_pdf=current_pdf)
    for step in repair_steps or []:
        rules = _rules_from_step(step)
        attempts: list[Dict[str, Any]] = []
        for rule_id in rules:
            attempts.extend(strategy_attempts.get(rule_id, []) or [])
        ran = bool(attempts)
        any_pass = any((a.get("result") or "").upper() == "PASS" for a in attempts if isinstance(a, dict))
        any_fail = any((a.get("result") or "").upper() == "FAIL" for a in attempts if isinstance(a, dict))
        if not ran:
            category = NOT_APPLICABLE
            skipped = True
            skip_reason = "no_attempt_recorded"
            status = "NOT_APPLICABLE"
        elif any_pass:
            category = RAN_SUCCESS
            skipped = False
            skip_reason = None
            status = "PASS"
        elif any_fail:
            category = RAN_FAILED
            skipped = False
            skip_reason = None
            status = "FAIL"
        else:
            category = RAN_FAILED
            skipped = False
            skip_reason = None
            status = "UNKNOWN"
        execution_refs = [a.get("execution_attempt_id") for a in attempts if isinstance(a, dict) and a.get("execution_attempt_id")]
        record_execution_step(
            log,
            step=step,
            iteration=None,
            strategy=step.get("strategy"),
            repair_script=step.get("repair_script"),
            command=[step.get("repair_script") or "unknown"],
            args_pattern=step.get("args_pattern"),
            ran=ran,
            skipped=skipped,
            skip_reason=skip_reason,
            input_pdf=source_pdf,
            output_pdf=current_pdf if any_pass else None,
            internal_status=status,
            result_category=category,
            notes="inferred from strategy_attempts; no direct subprocess evidence was available",
            inferred=True,
            inferred_from_strategy_attempts=True,
            referenced_execution_attempt_ids=execution_refs,
        )
    return refresh_compat_views(log)


def write_execution_log(log: Dict[str, Any], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    log["schema_version"] = log.get("schema_version") or SCHEMA_VERSION
    log["artifact"] = log.get("artifact") or "execution_log"
    log["updated_at"] = utc_now()
    refresh_compat_views(log)
    out.write_text(json.dumps(log, indent=2, sort_keys=True))
    return out


def load_execution_log(path: Path | str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text())
    return refresh_compat_views(data)
