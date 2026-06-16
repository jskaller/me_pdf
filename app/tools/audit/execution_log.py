#!/usr/bin/env python3
"""
execution_log.py

Deterministic execution-log helpers for known-repair orchestration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = "1.0.0"

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


def new_execution_log(
    *,
    job_dir: Path | str,
    source_pdf: Optional[Path | str] = None,
    current_pdf: Optional[Path | str] = None,
) -> Dict[str, Any]:
    now = utc_now()
    return {
        "schema": "montefiore.execution_log",
        "version": SCHEMA_VERSION,
        "created_at": now,
        "updated_at": now,
        "job_dir": str(job_dir),
        "source_pdf": _path(source_pdf),
        "source_pdf_hash": sha256_file(source_pdf),
        "current_pdf": _path(current_pdf),
        "current_pdf_hash": sha256_file(current_pdf),
        "repair_steps": [],
    }


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
) -> Dict[str, Any]:
    if result_category not in VALID_RESULT_CATEGORIES:
        raise ValueError(f"unknown execution-log result category: {result_category}")

    rule_ids = (
        step.get("rules_addressed")
        or step.get("rule_ids")
        or step.get("rule_id")
        or []
    )
    if isinstance(rule_ids, str):
        rule_ids = [rule_ids]

    entry = {
        "index": len(log.setdefault("repair_steps", [])) + 1,
        "iteration": iteration,
        "step": step.get("step"),
        "rule_ids": list(rule_ids),
        "strategy": strategy if strategy is not None else step.get("strategy"),
        "repair_script": repair_script if repair_script is not None else step.get("repair_script"),
        "command": [str(c) for c in command] if command is not None else None,
        "args_pattern": args_pattern if args_pattern is not None else step.get("args_pattern"),
        "started_at": started_at,
        "finished_at": finished_at or utc_now(),
        "exit_code": exit_code,
        "internal_status": internal_status,
        "ran": bool(ran),
        "skipped": bool(skipped),
        "skip_reason": skip_reason,
        "input_pdf": _path(input_pdf),
        "input_pdf_hash": sha256_file(input_pdf),
        "output_pdf": _path(output_pdf),
        "output_pdf_hash": sha256_file(output_pdf),
        "stdout_artifact": _path(stdout_artifact),
        "stderr_artifact": _path(stderr_artifact),
        "result_category": result_category,
        "notes": notes,
    }
    log["repair_steps"].append(entry)
    log["updated_at"] = utc_now()
    return entry


def build_execution_log_from_repair_steps(
    *,
    job_dir: Path | str,
    source_pdf: Optional[Path | str],
    current_pdf: Optional[Path | str],
    repair_steps: list[Dict[str, Any]],
    strategy_attempts: Dict[str, list[Dict[str, Any]]],
) -> Dict[str, Any]:
    log = new_execution_log(
        job_dir=job_dir,
        source_pdf=source_pdf,
        current_pdf=current_pdf,
    )

    for step in repair_steps or []:
        rules = step.get("rules_addressed") or []
        if isinstance(rules, str):
            rules = [rules]
        attempts = []
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
            notes="constructed from strategy_attempts; current orchestrator does not persist per-command stdout/stderr",
        )

    return log


def write_execution_log(log: Dict[str, Any], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    log["updated_at"] = utc_now()
    out.write_text(json.dumps(log, indent=2, sort_keys=True))
    return out


def load_execution_log(path: Path | str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())
