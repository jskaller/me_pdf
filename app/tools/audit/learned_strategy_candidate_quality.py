#!/usr/bin/env python3
"""Diagnostic quality gate for learned strategy output candidates.

Patch 14B deliberately does not approve, adopt, promote, or install learned
outputs. It classifies comparison evidence into conservative governance
states so a later deeper-validation patch can decide what to do next.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "learned-strategy-candidate-quality.v1"
ARTIFACT_NAME = "learned_strategy_candidate_quality_report.json"
MODE = "diagnostic_quality_gate"

QUALITY_DECISIONS = (
    "rejected_no_effect",
    "rejected_invalid",
    "rejected_execution_failed",
    "needs_deeper_validation",
    "candidate_valid_changed",
)

CLASSIFICATION_TO_DECISION = {
    "no_effect": "rejected_no_effect",
    "missing_output": "rejected_invalid",
    "changed_invalid_pdf": "rejected_invalid",
    "execution_failed": "rejected_execution_failed",
    "needs_deeper_validation": "needs_deeper_validation",
    "changed_valid_pdf": "candidate_valid_changed",
}

DECISION_NEXT_STEP = {
    "rejected_no_effect": "no_action",
    "rejected_invalid": "no_action",
    "rejected_execution_failed": "inspect_execution_failure",
    "needs_deeper_validation": "deeper_validation_required",
    "candidate_valid_changed": "deeper_validation_required",
}

DECISION_REASON = {
    "rejected_no_effect": "learned_output_hash_equals_input",
    "rejected_invalid": "learned_output_missing_or_invalid_pdf",
    "rejected_execution_failed": "learned_strategy_execution_failed",
    "needs_deeper_validation": "comparison_inconclusive_requires_deeper_validation",
    "candidate_valid_changed": "learned_output_changed_and_basic_pdf_checks_passed_but_not_approved",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return data


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "diagnostic_sidecar_only": True,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
        "candidate_quality_is_not_adoption_approval": True,
    }


def empty_summary() -> Dict[str, int]:
    return {decision: 0 for decision in QUALITY_DECISIONS}


def _comparison_reason(comparison: Dict[str, Any], decision: str) -> str:
    classification = str(comparison.get("classification") or "needs_deeper_validation")
    if decision == "rejected_no_effect":
        if comparison.get("input_output_hash_equal") is True:
            return "learned_output_hash_equals_input"
        return "learned_output_classified_no_effect"
    if decision == "rejected_invalid":
        if classification == "missing_output":
            return "learned_output_missing"
        return "learned_output_failed_basic_pdf_validation"
    return DECISION_REASON.get(decision, "quality_gate_conservative_default")


def evaluate_comparison_quality(comparison: Dict[str, Any]) -> Dict[str, Any]:
    classification = str(comparison.get("classification") or "needs_deeper_validation")
    decision = CLASSIFICATION_TO_DECISION.get(classification, "needs_deeper_validation")
    return {
        "rule_id": comparison.get("rule_id"),
        "candidate_id": comparison.get("candidate_id"),
        "strategy_id": comparison.get("strategy_id"),
        "attempt_id": comparison.get("attempt_id"),
        "comparison_classification": classification,
        "quality_decision": decision,
        "quality_passed": False,
        "reasons": [_comparison_reason(comparison, decision)],
        "required_next_step": DECISION_NEXT_STEP.get(decision, "deeper_validation_required"),
    }


def summarize_decisions(decisions: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    summary = empty_summary()
    for decision in decisions:
        key = str(decision.get("quality_decision") or "needs_deeper_validation")
        if key not in summary:
            summary[key] = 0
        summary[key] += 1
    return summary


def _diagnostic_blocker_report(
    *,
    comparison_artifact_path: Path,
    job_dir: Optional[Path],
    error: str,
) -> Dict[str, Any]:
    decisions = [
        {
            "rule_id": None,
            "candidate_id": None,
            "strategy_id": None,
            "attempt_id": None,
            "comparison_classification": "needs_deeper_validation",
            "quality_decision": "needs_deeper_validation",
            "quality_passed": False,
            "reasons": ["comparison_artifact_unavailable_or_malformed"],
            "required_next_step": "deeper_validation_required",
        }
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "source_comparison_artifact": str(comparison_artifact_path),
        "job_dir": str(job_dir) if job_dir else None,
        "mode": MODE,
        "candidate_count": 0,
        "decisions": decisions,
        "summary": summarize_decisions(decisions),
        "blockers": ["candidate_quality_comparison_artifact_error"],
        "error": error,
        "policy": no_adoption_policy(),
    }


def evaluate_learned_strategy_candidate_quality(
    comparison_artifact_path: Path,
    job_dir: Path | None = None,
) -> Dict[str, Any]:
    """Evaluate comparison results without approving any learned output."""
    comparison_artifact_path = Path(comparison_artifact_path)
    try:
        comparison_payload = load_json(comparison_artifact_path)
        comparisons = comparison_payload.get("comparisons") or []
        if not isinstance(comparisons, list):
            raise ValueError("comparisons must be a list")
    except Exception as exc:
        return _diagnostic_blocker_report(
            comparison_artifact_path=comparison_artifact_path,
            job_dir=job_dir,
            error=f"{type(exc).__name__}: {exc}",
        )

    decisions: List[Dict[str, Any]] = []
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            decisions.append(
                {
                    "rule_id": None,
                    "candidate_id": None,
                    "strategy_id": None,
                    "attempt_id": None,
                    "comparison_classification": "needs_deeper_validation",
                    "quality_decision": "needs_deeper_validation",
                    "quality_passed": False,
                    "reasons": ["comparison_entry_malformed"],
                    "required_next_step": "deeper_validation_required",
                }
            )
            continue
        decisions.append(evaluate_comparison_quality(comparison))

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "source_comparison_artifact": str(comparison_artifact_path),
        "job_dir": str(job_dir) if job_dir else None,
        "mode": MODE,
        "candidate_count": len(decisions),
        "decisions": decisions,
        "summary": summarize_decisions(decisions),
        "policy": no_adoption_policy(),
    }


def write_learned_strategy_candidate_quality_report(
    *,
    comparison_artifact_path: Path,
    audit_dir: Path,
    job_dir: Path | None = None,
) -> Dict[str, Any]:
    audit_dir = Path(audit_dir)
    artifact_path = audit_dir / ARTIFACT_NAME
    payload = evaluate_learned_strategy_candidate_quality(
        comparison_artifact_path=Path(comparison_artifact_path),
        job_dir=job_dir,
    )
    payload["artifact_path"] = str(artifact_path)
    write_json_atomic(artifact_path, payload)
    return payload
