#!/usr/bin/env python3
"""
Run-scoped state and retry/attempt accounting for PDF/UA self-extension.

Patch scope:
- authoritative current-run artifact: audit/self_extension_run_state.json
- stale copied budget/artifact evidence is preserved, never silently deleted
- generation calls, transport retries, semantic refusals, and repair candidate
  attempts are counted separately
- 429/timeouts are retryable transport failures and never consume repair
  candidate attempt budget
- no candidate adoption, rule-map mutation, or learned-strategy indexing
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

RUN_STATE_RELATIVE_PATH = Path("audit") / "self_extension_run_state.json"
PREVIOUS_RUNS_RELATIVE_PATH = Path("audit") / "self_extension_previous_runs"
LEGACY_BUDGET_NAME = "self_extension_call_budget.json"
TRANSPORT_FAILURE_DIR = Path("audit") / "self_extension_transport_failures"

TRANSPORT_BLOCKED = "TRANSPORT_BLOCKED"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _load_json_object(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def _sha256_file(path: Optional[Path]) -> Optional[str]:
    if path is None or not Path(path).exists() or not Path(path).is_file():
        return None
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_copy(src: Path, dst: Path) -> Optional[str]:
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _failure_category(record: Dict[str, Any]) -> str:
    return str(record.get("failure_category") or "").lower()


def is_retryable_transport_failure(record: Dict[str, Any]) -> bool:
    """Return True for generation failures caused by gateway transport.

    Current executor classification already marks HTTP 429 and timeout-like
    failures as retryable. This helper also accepts the stable categories so
    tests can exercise it without constructing a full gateway exception.
    """
    category = _failure_category(record)
    if category in {"gateway_rate_limited", "gateway_timeout"}:
        return True
    if record.get("retryable") is True:
        if category.startswith("gateway_") or "transport" in category:
            return True
    text = json.dumps(record, sort_keys=True).lower()
    return (
        "http 429" in text
        or "too many requests" in text
        or "timed out" in text
        or "timeout" in text
    )


def is_semantic_refusal(record: Dict[str, Any]) -> bool:
    category = _failure_category(record)
    result = str(record.get("llm_result") or record.get("result") or "").upper()
    return category == "llm_semantic_refusal" or result in {
        "NOT_AUTOMATABLE",
        "NEEDS_MORE_EVIDENCE",
    }


def transport_retry_delay_seconds(
    retry_index: int,
    *,
    retry_after: Optional[Any] = None,
    base_seconds: float = 1.0,
    max_seconds: float = 30.0,
) -> float:
    """Deterministic retry delay calculator.

    Tests can assert this value and pass sleep_fn=lambda _: None so no test
    performs a real long sleep. Retry-After is honored when it is already
    exposed in the failure record; otherwise exponential backoff is used.
    """
    if retry_after not in (None, ""):
        try:
            return max(0.0, min(float(retry_after), max_seconds))
        except (TypeError, ValueError):
            pass
    exponent = max(0, int(retry_index) - 1)
    return min(max_seconds, max(0.0, float(base_seconds)) * (2**exponent))


@dataclass
class SelfExtensionRunState:
    job_dir: Path
    run_id: str
    path: Path
    data: Dict[str, Any]

    @classmethod
    def start(
        cls,
        *,
        job_dir: Path,
        target_rule_id: Optional[str] = None,
        source_pdf: Optional[Path] = None,
        current_pdf: Optional[Path] = None,
        residual_gap_entry_anchor: Optional[str] = None,
        repair_attempt_budget: int = 3,
        transport_retry_budget: int = 3,
        generation_call_budget: int = 10,
    ) -> "SelfExtensionRunState":
        job_dir = Path(job_dir)
        run_id = uuid.uuid4().hex
        path = job_dir / RUN_STATE_RELATIVE_PATH
        previous_state = _load_json_object(path)
        previous_budget = _load_json_object(job_dir / LEGACY_BUDGET_NAME)
        previous_meta = preserve_stale_self_extension_artifacts(
            job_dir=job_dir,
            new_run_id=run_id,
            previous_state=previous_state,
            previous_budget=previous_budget,
        )
        data = {
            "run_id": run_id,
            "started_at": _utc_now(),
            "job_dir": str(job_dir),
            "source_pdf": str(source_pdf) if source_pdf else None,
            "source_pdf_hash": _sha256_file(source_pdf),
            "current_pdf": str(current_pdf) if current_pdf else None,
            "current_pdf_hash": _sha256_file(current_pdf),
            "residual_gap_entry_anchor": residual_gap_entry_anchor,
            "self_extension": {
                "target_rule_id": target_rule_id,
                "repair_attempt_budget": int(repair_attempt_budget),
                "repair_attempts_used": 0,
                "transport_retry_budget": int(transport_retry_budget),
                "transport_retries_used": 0,
                "transport_failure_count": 0,
                "generation_call_budget": int(generation_call_budget),
                "generation_call_count": 0,
                "candidate_attempt_count": 0,
                "semantic_refusal_count": 0,
                "needs_more_evidence_count": 0,
                "boundary_violation_count": 0,
                "validation_failure_count": 0,
                "last_outcome": "STARTED",
            },
            "stale_artifacts": previous_meta,
            "events": [],
        }
        _write_json_atomic(path, data)
        return cls(job_dir=job_dir, run_id=run_id, path=path, data=data)

    @classmethod
    def load(cls, job_dir: Path) -> "SelfExtensionRunState":
        job_dir = Path(job_dir)
        path = job_dir / RUN_STATE_RELATIVE_PATH
        data = _load_json_object(path)
        if not data:
            raise FileNotFoundError(f"self-extension run state does not exist: {path}")
        return cls(job_dir=job_dir, run_id=str(data["run_id"]), path=path, data=data)

    def save(self) -> None:
        _write_json_atomic(self.path, self.data)

    @property
    def counters(self) -> Dict[str, Any]:
        return self.data.setdefault("self_extension", {})

    def event(self, kind: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = {"at": _utc_now(), "kind": kind}
        if payload:
            record.update(payload)
        self.data.setdefault("events", []).append(record)
        return record

    def reserve_generation_call(self) -> Dict[str, Any]:
        counters = self.counters
        used = int(counters.get("generation_call_count") or 0)
        budget = int(counters.get("generation_call_budget") or 0)
        if budget >= 0 and used >= budget:
            counters["last_outcome"] = "GENERATION_BUDGET_EXHAUSTED"
            self.event("generation_budget_exhausted", {"used": used, "budget": budget})
            self.save()
            return {"result": "GENERATION_BUDGET_EXHAUSTED", "used": used, "budget": budget}
        counters["generation_call_count"] = used + 1
        self.event("generation_call_reserved", {"generation_call_count": used + 1})
        self.save()
        return {"result": "RESERVED", "generation_call_count": used + 1, "budget": budget}

    def record_transport_failure(self, failure: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        counters["transport_failure_count"] = int(counters.get("transport_failure_count") or 0) + 1
        counters["last_outcome"] = failure.get("failure_category") or "TRANSPORT_FAILURE"
        artifact = write_transport_failure_artifact(self.job_dir, self.run_id, counters["transport_failure_count"], failure)
        self.event(
            "transport_failure",
            {
                "failure_category": failure.get("failure_category"),
                "transport_failure_count": counters["transport_failure_count"],
                "artifact": str(artifact),
            },
        )
        self.save()
        return {"result": "RECORDED", "artifact": str(artifact)}

    def reserve_transport_retry(self, failure: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        used = int(counters.get("transport_retries_used") or 0)
        budget = int(counters.get("transport_retry_budget") or 0)
        if used >= budget:
            counters["last_outcome"] = TRANSPORT_BLOCKED
            self.event("transport_retry_budget_exhausted", {"used": used, "budget": budget})
            self.save()
            return {"result": TRANSPORT_BLOCKED, "used": used, "budget": budget}
        counters["transport_retries_used"] = used + 1
        delay = transport_retry_delay_seconds(
            used + 1,
            retry_after=failure.get("retry_after") or failure.get("retry_after_seconds"),
        )
        self.event(
            "transport_retry_reserved",
            {"transport_retries_used": used + 1, "budget": budget, "delay_seconds": delay},
        )
        self.save()
        return {"result": "RETRY_RESERVED", "used": used + 1, "budget": budget, "delay_seconds": delay}

    def record_semantic_refusal(self, failure: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        counters["semantic_refusal_count"] = int(counters.get("semantic_refusal_count") or 0) + 1
        if str(failure.get("llm_result") or failure.get("result") or "").upper() == "NEEDS_MORE_EVIDENCE":
            counters["needs_more_evidence_count"] = int(counters.get("needs_more_evidence_count") or 0) + 1
        counters["last_outcome"] = "SEMANTIC_REFUSAL_RECORDED"
        self.event(
            "semantic_refusal",
            {"llm_result": failure.get("llm_result") or failure.get("result"), "reason": failure.get("reason")},
        )
        self.save()
        return {"result": "RECORDED"}

    def record_boundary_violation(self, failure: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        counters["boundary_violation_count"] = int(counters.get("boundary_violation_count") or 0) + 1
        counters["last_outcome"] = "BOUNDARY_VIOLATION_RECORDED"
        self.event("boundary_violation", {"reason": failure.get("reason")})
        self.save()
        return {"result": "RECORDED"}

    def record_candidate_attempt(self, candidate_result: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        counters["repair_attempts_used"] = int(counters.get("repair_attempts_used") or 0) + 1
        counters["candidate_attempt_count"] = int(counters.get("candidate_attempt_count") or 0) + 1
        if candidate_result.get("result") != "PASS":
            counters["validation_failure_count"] = int(counters.get("validation_failure_count") or 0) + 1
        counters["last_outcome"] = "CANDIDATE_VALIDATED" if candidate_result.get("result") == "PASS" else "CANDIDATE_VALIDATION_FAILED"
        self.event(
            "candidate_attempt",
            {
                "result": candidate_result.get("result"),
                "stage": candidate_result.get("stage"),
                "candidate_relative_path": candidate_result.get("candidate_relative_path"),
                "repair_attempts_used": counters["repair_attempts_used"],
            },
        )
        self.save()
        return {"result": "RECORDED", "repair_attempts_used": counters["repair_attempts_used"]}

    def transport_blocked_result(self, failure: Dict[str, Any]) -> Dict[str, Any]:
        counters = self.counters
        counters["last_outcome"] = TRANSPORT_BLOCKED
        self.event("transport_blocked", {"failure_category": failure.get("failure_category"), "reason": failure.get("reason")})
        self.save()
        return {
            "result": TRANSPORT_BLOCKED,
            "stage": "generate_candidate",
            "failure_category": failure.get("failure_category"),
            "retryable": False,
            "transport_retries_used": counters.get("transport_retries_used", 0),
            "transport_retry_budget": counters.get("transport_retry_budget", 0),
            "repair_attempts_used": counters.get("repair_attempts_used", 0),
            "candidate_attempt_count": counters.get("candidate_attempt_count", 0),
            "last_transport_failure": failure,
            "run_state_path": str(self.path),
        }


def preserve_stale_self_extension_artifacts(
    *,
    job_dir: Path,
    new_run_id: str,
    previous_state: Optional[Dict[str, Any]],
    previous_budget: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Preserve evidence from copied/stale job dirs without using it.

    The current run always gets fresh counters. Any existing run-state or legacy
    budget artifact is copied under audit/self_extension_previous_runs/ and
    marked as superseded by the new run id.
    """
    job_dir = Path(job_dir)
    archive_dir = job_dir / PREVIOUS_RUNS_RELATIVE_PATH
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{_epoch_ms()}_{new_run_id[:12]}"
    meta: Dict[str, Any] = {
        "previous_run_state_existed": previous_state is not None,
        "previous_legacy_budget_existed": previous_budget is not None,
        "action": "fresh_run_started_stale_artifacts_superseded",
        "superseded_by_run_id": new_run_id,
        "archived_artifacts": {},
        "ignored_for_budget_accounting": True,
    }
    state_src = job_dir / RUN_STATE_RELATIVE_PATH
    budget_src = job_dir / LEGACY_BUDGET_NAME
    state_dst = archive_dir / f"{stamp}_self_extension_run_state.json"
    budget_dst = archive_dir / f"{stamp}_{LEGACY_BUDGET_NAME}"
    state_copy = _safe_copy(state_src, state_dst)
    budget_copy = _safe_copy(budget_src, budget_dst)
    if state_copy:
        meta["archived_artifacts"]["previous_run_state"] = state_copy
    if budget_copy:
        meta["archived_artifacts"]["legacy_budget"] = budget_copy
    return meta


def write_transport_failure_artifact(job_dir: Path, run_id: str, ordinal: int, failure: Dict[str, Any]) -> Path:
    path = Path(job_dir) / TRANSPORT_FAILURE_DIR / f"{run_id}_transport_failure_{int(ordinal):03d}.json"
    record = dict(failure)
    record.setdefault("result", "FAIL")
    record["run_id"] = run_id
    record["recorded_at"] = _utc_now()
    _write_json_atomic(path, record)
    return path


def generation_call_with_run_state(
    *,
    run_state: SelfExtensionRunState,
    generation_request: Dict[str, Any],
    generate_fn: Callable[..., Dict[str, Any]],
    sleep_fn: Callable[[float], None] = time.sleep,
    config: Optional[Any] = None,
    job_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Call a candidate-generation function with run-scoped accounting.

    This wrapper is intentionally dependency-injected so tests can simulate
    429s/timeouts without live gateway behavior. The supplied generate_fn may
    raise an object with ``failure_record`` (the existing GenerationRejected
    shape) or return a parsed SCRIPT_SOURCE record.
    """
    while True:
        reservation = run_state.reserve_generation_call()
        if reservation.get("result") != "RESERVED":
            return {"result": reservation["result"], "run_state_path": str(run_state.path)}
        try:
            try:
                result = generate_fn(
                    generation_request=generation_request,
                    config=config,
                    job_dir=job_dir or run_state.job_dir,
                )
            except TypeError as exc:
                if "config" not in str(exc):
                    raise
                result = generate_fn(
                    generation_request=generation_request,
                    job_dir=job_dir or run_state.job_dir,
                )
            run_state.counters["last_outcome"] = "GENERATION_SUCCEEDED"
            run_state.event("generation_succeeded", {"strategy": result.get("strategy")})
            run_state.save()
            return result
        except Exception as exc:  # noqa: BLE001 - preserves existing GenerationRejected shape without import cycle.
            failure = getattr(exc, "failure_record", None) or {
                "result": "FAIL",
                "reason": f"{type(exc).__name__}: {exc}",
                "error_type": type(exc).__name__,
            }
            if is_retryable_transport_failure(failure):
                run_state.record_transport_failure(failure)
                retry = run_state.reserve_transport_retry(failure)
                if retry.get("result") == TRANSPORT_BLOCKED:
                    return run_state.transport_blocked_result(failure)
                sleep_fn(float(retry.get("delay_seconds") or 0.0))
                continue
            if is_semantic_refusal(failure):
                run_state.record_semantic_refusal(failure)
            elif _failure_category(failure) == "generation_boundary_violation":
                run_state.record_boundary_violation(failure)
            else:
                run_state.counters["last_outcome"] = failure.get("failure_category") or "GENERATION_REJECTED"
                run_state.event("generation_rejected", {"failure_category": failure.get("failure_category"), "reason": failure.get("reason")})
                run_state.save()
            return dict(failure, run_state_path=str(run_state.path))


def summarize_no_adoption_guard(*, rule_map_before_hash: str, rule_map_after_hash: str, final_pdf_before: Any, final_pdf_after: Any) -> Dict[str, Any]:
    """Small assertion helper used by tests and future integration code."""
    return {
        "rule_map_mutated": rule_map_before_hash != rule_map_after_hash,
        "final_pdf_path_changed": str(final_pdf_before) != str(final_pdf_after),
        "adoption_performed": False,
        "result": "PASS" if rule_map_before_hash == rule_map_after_hash and str(final_pdf_before) == str(final_pdf_after) else "FAIL",
    }
