#!/usr/bin/env python3
"""
learned_strategy_capture.py

Durable learned-strategy capture for residual self-extension experiments.

This module writes only job-scoped audit artifacts. It does not mutate
rule_repair_map.json, tools/repair canonical scripts, final PDFs, or any
strategy index. Later indexing/ranking patches may consume the artifact.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "learned-strategies.v1"
ARTIFACT_FILENAME = "learned_strategies.json"
ARTIFACT_RELATIVE_PATH = Path("audit") / ARTIFACT_FILENAME

CLEAN_OUTCOME = "clean_success"
DIRTY_OUTCOME = "dirty_success"
PARTIAL_OUTCOME = "partial_improvement"
VALIDATION_FAILED_OUTCOME = "validation_failed"
GENERATION_FAILED_OUTCOME = "generation_failed"
TRANSPORT_BLOCKED_OUTCOME = "transport_blocked"
SEMANTIC_REFUSAL_OUTCOME = "semantic_refusal"
NEEDS_MORE_EVIDENCE_OUTCOME = "needs_more_evidence"
BOUNDARY_VIOLATION_OUTCOME = "boundary_violation"

TERMINAL_GENERATION_OUTCOMES = {
    GENERATION_FAILED_OUTCOME,
    TRANSPORT_BLOCKED_OUTCOME,
    SEMANTIC_REFUSAL_OUTCOME,
    NEEDS_MORE_EVIDENCE_OUTCOME,
    BOUNDARY_VIOLATION_OUTCOME,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def learned_strategies_path(job_dir: Path) -> Path:
    return Path(job_dir) / ARTIFACT_RELATIVE_PATH


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=_json_default))
    tmp.replace(path)


def _load_artifact(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": "learned_strategies",
            "records": [],
        }
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    if isinstance(data, list):
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact": "learned_strategies",
            "records": data,
        }
    if not isinstance(data, dict):
        data = {}
    records = data.get("records")
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": data.get("schema_version") or SCHEMA_VERSION,
        "artifact": data.get("artifact") or "learned_strategies",
        "records": records,
    }


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sha256_file(path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _relative_or_str(path: Any, root: Optional[Path] = None) -> Optional[str]:
    if path in (None, ""):
        return None
    p = Path(str(path))
    if root is not None:
        try:
            return str(p.relative_to(root))
        except Exception:
            pass
    return str(path)


def _run_state_counters(run_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = _safe_dict(run_state)
    return _safe_dict(data.get("self_extension"))


def _record_identity(record: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        _clean_text(record.get("run_id")),
        _clean_text(record.get("rule_id")),
        str(record.get("attempt_number") if record.get("attempt_number") is not None else ""),
        _clean_text(record.get("script_sha256")),
        _clean_text(record.get("outcome")),
    )


def append_or_replace_record(job_dir: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    """Append one record idempotently by run/rule/attempt/script/outcome."""
    path = learned_strategies_path(job_dir)
    artifact = _load_artifact(path)
    records = [r for r in artifact.get("records", []) if isinstance(r, dict)]
    identity = _record_identity(record)
    replaced = False
    for index, existing in enumerate(records):
        if _record_identity(existing) == identity:
            preserved_created_at = existing.get("created_at")
            merged = dict(record)
            if preserved_created_at:
                merged["created_at"] = preserved_created_at
            records[index] = merged
            replaced = True
            break
    if not replaced:
        records.append(record)
    records.sort(key=lambda r: (
        _clean_text(r.get("run_id")),
        _clean_text(r.get("rule_id")),
        _as_int(r.get("attempt_number"), 0),
        _clean_text(r.get("script_sha256")),
        _clean_text(r.get("outcome")),
    ))
    artifact["schema_version"] = SCHEMA_VERSION
    artifact["artifact"] = "learned_strategies"
    artifact["records"] = records
    _write_json_atomic(path, artifact)
    return {"artifact_path": str(path), "record": record, "replaced": replaced}


def _classify_generation_event(failure: Dict[str, Any]) -> str:
    result = _clean_text(failure.get("result")).upper()
    failure_category = _clean_text(failure.get("failure_category"))
    llm_result = _clean_text(failure.get("llm_result")).upper()
    if result == "TRANSPORT_BLOCKED":
        return TRANSPORT_BLOCKED_OUTCOME
    if failure_category == "generation_boundary_violation":
        return BOUNDARY_VIOLATION_OUTCOME
    if failure_category == "llm_semantic_refusal":
        if llm_result == "NEEDS_MORE_EVIDENCE":
            return NEEDS_MORE_EVIDENCE_OUTCOME
        return SEMANTIC_REFUSAL_OUTCOME
    return GENERATION_FAILED_OUTCOME


def _candidate_output_exists(candidate_result: Dict[str, Any]) -> bool:
    path = candidate_result.get("candidate_output_pdf")
    if not path:
        return False
    try:
        p = Path(str(path))
        return p.exists() and p.stat().st_size > 0
    except Exception:
        return False


def _classify_candidate(candidate_result: Dict[str, Any]) -> Tuple[str, bool, List[str]]:
    predicate = _safe_dict(candidate_result.get("success_predicate"))
    execution_contract = _safe_dict(candidate_result.get("execution_contract"))
    validation = _safe_dict(candidate_result.get("validation"))
    target_before = _as_int(predicate.get("target_rule_count_before"), 0)
    target_after = _as_int(predicate.get("target_rule_count_after"), target_before)
    target_decreased = bool(predicate.get("target_rule_strictly_decreased"))
    target_resolved = target_before > 0 and target_after == 0
    introduced = _as_list(predicate.get("new_rule_ids_relative_to_gap_entry"))
    worsened = _as_list(predicate.get("worsened_existing_rules_relative_to_gap_entry"))
    failed_gates = _as_list(predicate.get("failed_gates"))
    blockers: List[str] = []
    if not target_resolved:
        if target_decreased:
            blockers.append("target_rule_not_resolved")
        else:
            blockers.append("target_rule_not_decreased")
    if introduced:
        blockers.append("introduced_rules:" + ",".join(str(x) for x in introduced))
    if worsened:
        blockers.append("worsened_rules:" + ",".join(str(x) for x in worsened))
    if failed_gates:
        blockers.append("failed_gates:" + ",".join(str(x) for x in failed_gates))
    if execution_contract.get("result") and execution_contract.get("result") != "PASS":
        blockers.append("execution_contract_failed")
    checks = _safe_dict(execution_contract.get("checks"))
    if checks.get("input_hash_unchanged") is False:
        blockers.append("input_pdf_hash_changed")
    if checks.get("stdout_json_object") is False:
        blockers.append("stdout_json_missing_or_unparseable")
    # A validated candidate should have a non-empty output. Unit tests that use
    # pure dict fixtures may omit the output path; absence is a blocker, not an
    # exception.
    if candidate_result.get("stage") == "validated_candidate" and not _candidate_output_exists(candidate_result):
        blockers.append("candidate_output_missing_or_empty")
    dirty_blockers = [b for b in blockers if b != "target_rule_not_resolved"]
    clean = target_resolved and not blockers
    if clean:
        return CLEAN_OUTCOME, True, []
    if (target_resolved or target_decreased) and dirty_blockers:
        return DIRTY_OUTCOME, False, blockers
    if target_decreased and target_after > 0:
        return PARTIAL_OUTCOME, False, blockers
    return VALIDATION_FAILED_OUTCOME, False, blockers


def build_candidate_strategy_record(
    *,
    job_dir: Path,
    rule_id: str,
    candidate_result: Dict[str, Any],
    generation_request: Optional[Dict[str, Any]] = None,
    generation_response: Optional[Dict[str, Any]] = None,
    run_state: Optional[Dict[str, Any]] = None,
    attempt_number: Optional[int] = None,
) -> Dict[str, Any]:
    generation_request = _safe_dict(generation_request)
    generation_response = _safe_dict(generation_response)
    candidate_result = _safe_dict(candidate_result)
    predicate = _safe_dict(candidate_result.get("success_predicate"))
    validation = _safe_dict(candidate_result.get("validation"))
    execution_contract = _safe_dict(candidate_result.get("execution_contract"))
    write_result = _safe_dict(candidate_result.get("write_result"))
    counters = _run_state_counters(run_state)
    script_path = candidate_result.get("candidate_script") or write_result.get("candidate_script") or candidate_result.get("candidate_relative_path")
    script_sha = write_result.get("script_sha256") or _sha256_file(Path(str(script_path)))
    outcome, clean, blockers = _classify_candidate(candidate_result)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "run_id": _safe_dict(run_state).get("run_id"),
        "job_dir": str(job_dir),
        "rule_id": rule_id,
        "script_path": _relative_or_str(script_path),
        "script_sha256": script_sha,
        "strategy": generation_response.get("strategy") or _safe_dict(execution_contract.get("stdout_json")).get("strategy"),
        "args_pattern": generation_response.get("expected_args_pattern") or generation_request.get("script_contract", {}).get("cli"),
        "repair_order": None,
        "run_last": True,
        "proposed_resolvability": generation_response.get("proposed_resolvability"),
        "outcome": outcome,
        "clean": clean,
        "review_required": not clean,
        "pre_count": predicate.get("target_rule_count_before"),
        "post_count": predicate.get("target_rule_count_after"),
        "target_rule_strictly_decreased": bool(predicate.get("target_rule_strictly_decreased")),
        "target_rule_resolved": _as_int(predicate.get("target_rule_count_after"), -1) == 0,
        "introduced_rules": _as_list(predicate.get("new_rule_ids_relative_to_gap_entry")),
        "worsened_rules": _as_list(predicate.get("worsened_existing_rules_relative_to_gap_entry")),
        "gate_results": validation.get("gate_results") or {},
        "isolation_snapshot": {
            "attempt_dir": candidate_result.get("attempt_dir"),
            "candidate_output_pdf": candidate_result.get("candidate_output_pdf"),
            "adoption_performed": bool(candidate_result.get("adoption_performed", False)),
        },
        "stdout_json": execution_contract.get("stdout_json"),
        "generation_request": generation_request,
        "generation_response": generation_response,
        "candidate_result": candidate_result,
        "validation_artifacts": validation.get("artifacts") or {},
        "attempt_number": attempt_number if attempt_number is not None else generation_request.get("attempt"),
        "transport_attempts_used": counters.get("transport_retries_used"),
        "repair_attempts_used": counters.get("repair_attempts_used"),
        "semantic_refusal_count": counters.get("semantic_refusal_count"),
        "needs_more_evidence_count": counters.get("needs_more_evidence_count"),
        "failure_summary": _failure_summary(candidate_result, outcome, blockers),
        "indexing_eligible": clean,
        "indexing_blockers": blockers,
    }


def build_generation_event_record(
    *,
    job_dir: Path,
    rule_id: str,
    failure: Dict[str, Any],
    generation_request: Optional[Dict[str, Any]] = None,
    run_state: Optional[Dict[str, Any]] = None,
    attempt_number: Optional[int] = None,
) -> Dict[str, Any]:
    failure = _safe_dict(failure)
    generation_request = _safe_dict(generation_request)
    counters = _run_state_counters(run_state)
    outcome = _classify_generation_event(failure)
    blockers = [outcome]
    if failure.get("failure_category"):
        blockers.append("failure_category:" + str(failure.get("failure_category")))
    if failure.get("llm_result"):
        blockers.append("llm_result:" + str(failure.get("llm_result")))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "run_id": _safe_dict(run_state).get("run_id"),
        "job_dir": str(job_dir),
        "rule_id": rule_id,
        "script_path": None,
        "script_sha256": None,
        "strategy": None,
        "args_pattern": generation_request.get("script_contract", {}).get("cli"),
        "repair_order": None,
        "run_last": True,
        "proposed_resolvability": None,
        "outcome": outcome,
        "clean": False,
        "review_required": True,
        "pre_count": None,
        "post_count": None,
        "target_rule_strictly_decreased": False,
        "target_rule_resolved": False,
        "introduced_rules": [],
        "worsened_rules": [],
        "gate_results": {},
        "isolation_snapshot": {"attempt_dir": None, "adoption_performed": False},
        "stdout_json": None,
        "generation_request": generation_request,
        "generation_response": failure,
        "candidate_result": None,
        "validation_artifacts": {},
        "attempt_number": attempt_number if attempt_number is not None else generation_request.get("attempt"),
        "transport_attempts_used": counters.get("transport_retries_used"),
        "repair_attempts_used": counters.get("repair_attempts_used"),
        "semantic_refusal_count": counters.get("semantic_refusal_count"),
        "needs_more_evidence_count": counters.get("needs_more_evidence_count"),
        "failure_summary": _failure_summary(failure, outcome, blockers),
        "indexing_eligible": False,
        "indexing_blockers": blockers,
    }


def _failure_summary(payload: Dict[str, Any], outcome: str, blockers: List[str]) -> Dict[str, Any]:
    return {
        "outcome": outcome,
        "result": payload.get("result"),
        "stage": payload.get("stage") or payload.get("phase"),
        "reason": payload.get("reason"),
        "failure_category": payload.get("failure_category"),
        "llm_result": payload.get("llm_result"),
        "blockers": blockers,
    }


def capture_candidate_result(
    *,
    job_dir: Path,
    rule_id: str,
    candidate_result: Dict[str, Any],
    generation_request: Optional[Dict[str, Any]] = None,
    generation_response: Optional[Dict[str, Any]] = None,
    run_state: Optional[Dict[str, Any]] = None,
    attempt_number: Optional[int] = None,
) -> Dict[str, Any]:
    record = build_candidate_strategy_record(
        job_dir=Path(job_dir),
        rule_id=rule_id,
        candidate_result=candidate_result,
        generation_request=generation_request,
        generation_response=generation_response,
        run_state=run_state,
        attempt_number=attempt_number,
    )
    return append_or_replace_record(Path(job_dir), record)


def capture_generation_event(
    *,
    job_dir: Path,
    rule_id: str,
    failure: Dict[str, Any],
    generation_request: Optional[Dict[str, Any]] = None,
    run_state: Optional[Dict[str, Any]] = None,
    attempt_number: Optional[int] = None,
) -> Dict[str, Any]:
    record = build_generation_event_record(
        job_dir=Path(job_dir),
        rule_id=rule_id,
        failure=failure,
        generation_request=generation_request,
        run_state=run_state,
        attempt_number=attempt_number,
    )
    return append_or_replace_record(Path(job_dir), record)
