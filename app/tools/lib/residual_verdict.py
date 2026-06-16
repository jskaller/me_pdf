#!/usr/bin/env python3
"""Residual-aware verdict/status helpers for Patch 5.

This module is deliberately read-only with respect to canonical repair policy:
it summarizes job-local artifacts only. It never mutates rule_repair_map.json,
never promotes generated scripts, and never changes final PDF adoption.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence

RESOLVED_OUTCOMES = {"resolved", "resolved_incidental"}
NON_TARGETABLE_OUTCOMES = {
    "manual_review_required",
    "not_auto_fixable",
    "detector_mislabeled",
    "non_targetable_residual",
    "review_required",
}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _sorted_unique(values: Iterable[Any]) -> List[str]:
    return sorted({str(v) for v in values if str(v or "").strip()})


def _rules_from_summary(summary: Mapping[str, Any], key: str) -> List[str]:
    value = summary.get(key, [])
    if isinstance(value, list):
        return _sorted_unique(value)
    return []


def summarize_residual_analysis(job_dir: str | Path) -> Dict[str, Any]:
    job = Path(job_dir)
    path = job / "audit" / "residual_analysis.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return {
            "available": False,
            "residual_analysis_path": str(path),
            "residual_analysis_sha256": "",
            "counts_by_outcome": {},
            "targetable_residual_rules": [],
            "non_targetable_residual_rules": [],
            "pending_review_rules": [],
            "introduced_rules": [],
            "escalation_rules": [],
            "partially_resolved_rules": [],
            "never_attempted_rules": [],
            "attempted_no_effect_rules": [],
            "persistent_rules": [],
            "partially_resolved_softens_verdict": False,
            "repair_script_promotion_performed": False,
            "rule_map_mutation_performed": False,
        }

    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    by_rule = data.get("by_rule", {}) if isinstance(data.get("by_rule"), dict) else {}
    counts = summary.get("counts_by_outcome", {}) if isinstance(summary.get("counts_by_outcome"), dict) else {}

    targetable = _rules_from_summary(summary, "targetable_residual_rules")
    non_targetable = _rules_from_summary(summary, "non_targetable_residual_rules")
    pending = _rules_from_summary(summary, "pending_review_rules")
    introduced = _rules_from_summary(summary, "introduced_rules")
    escalation = _rules_from_summary(summary, "escalation_rules")
    partial = _rules_from_summary(summary, "partially_resolved_rules")
    never = _rules_from_summary(summary, "never_attempted_rules")
    no_effect = _rules_from_summary(summary, "attempted_no_effect_rules")
    persistent = _rules_from_summary(summary, "persistent_rules")

    for rule_id, record in by_rule.items():
        if not isinstance(record, dict):
            continue
        outcome = str(record.get("outcome", ""))
        post_count = int(record.get("post_count") or 0)
        if outcome in RESOLVED_OUTCOMES or post_count == 0:
            continue
        if outcome == "introduced":
            introduced.append(rule_id)
        elif outcome == "partially_resolved":
            partial.append(rule_id)
            targetable.append(rule_id)
        elif outcome in {"persistent", "attempted_no_effect", "never_attempted"}:
            targetable.append(rule_id)
            if outcome == "persistent": persistent.append(rule_id)
            if outcome == "attempted_no_effect": no_effect.append(rule_id)
            if outcome == "never_attempted": never.append(rule_id)
        elif outcome in NON_TARGETABLE_OUTCOMES:
            non_targetable.append(rule_id)
        elif "review" in outcome:
            pending.append(rule_id)

    policy = data.get("policy", {}) if isinstance(data.get("policy"), dict) else {}
    return {
        "available": True,
        "residual_analysis_path": str(path),
        "residual_analysis_sha256": _sha256(path),
        "counts_by_outcome": dict(counts),
        "targetable_residual_rules": _sorted_unique(targetable),
        "non_targetable_residual_rules": _sorted_unique(non_targetable),
        "pending_review_rules": _sorted_unique(pending),
        "introduced_rules": _sorted_unique(introduced),
        "escalation_rules": _sorted_unique(escalation),
        "partially_resolved_rules": _sorted_unique(partial),
        "never_attempted_rules": _sorted_unique(never),
        "attempted_no_effect_rules": _sorted_unique(no_effect),
        "persistent_rules": _sorted_unique(persistent),
        "partially_resolved_softens_verdict": bool(policy.get("partially_resolved_softens_verdict", False)),
        "repair_script_promotion_performed": bool(policy.get("repair_script_promotion_performed", False)),
        "rule_map_mutation_performed": bool(policy.get("rule_map_mutation_performed", False)),
    }


def summarize_strategy_indexing(job_dir: str | Path) -> Dict[str, Any]:
    job = Path(job_dir)
    path = job / "audit" / "strategy_indexing_report.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return {
            "available": False,
            "report_path": str(path),
            "report_sha256": "",
            "eligible_count": 0,
            "proposed_rule_map_changes_count": 0,
            "rejected_experiments_count": 0,
            "repair_script_promotion_performed": False,
            "rule_map_mutation_performed": False,
            "final_pdf_adoption_performed": False,
        }
    policy = data.get("policy", {}) if isinstance(data.get("policy"), dict) else {}
    eligible = data.get("eligible_strategies", [])
    proposals = data.get("proposed_rule_map_changes", [])
    rejected = data.get("rejected_experiments", [])
    return {
        "available": True,
        "report_path": str(path),
        "report_sha256": _sha256(path),
        "eligible_count": len(eligible) if isinstance(eligible, list) else int(data.get("eligible_count") or 0),
        "proposed_rule_map_changes_count": len(proposals) if isinstance(proposals, list) else int(data.get("proposed_rule_map_changes_count") or 0),
        "rejected_experiments_count": len(rejected) if isinstance(rejected, list) else int(data.get("rejected_experiments_count") or 0),
        "repair_script_promotion_performed": bool(policy.get("repair_script_promotion_performed", False)),
        "rule_map_mutation_performed": bool(policy.get("rule_map_mutation_performed", False)),
        "final_pdf_adoption_performed": bool(policy.get("final_pdf_adoption_performed", False)),
    }


def reconcile_hermes_signals(
    raw_signals: Sequence[Mapping[str, Any]] | None,
    residual_summary: Mapping[str, Any] | None,
    gate_results: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    summary = residual_summary or {}
    targetable = set(summary.get("targetable_residual_rules", []) or [])
    non_targetable = set(summary.get("non_targetable_residual_rules", []) or [])
    pending = set(summary.get("pending_review_rules", []) or [])
    introduced = set(summary.get("introduced_rules", []) or [])
    unresolved = targetable | non_targetable | pending | introduced | set(summary.get("persistent_rules", []) or [])

    raw = [dict(s) for s in (raw_signals or []) if isinstance(s, Mapping)]
    deduped_map: Dict[tuple, Dict[str, Any]] = {}
    for sig in raw:
        deduped_map[(sig.get("rule_id", ""), sig.get("reason", ""))] = dict(sig)
    deduped = list(deduped_map.values())

    active: List[Dict[str, Any]] = []
    resolved: List[Dict[str, Any]] = []
    non_targetable_signals: List[Dict[str, Any]] = []
    suppressed_zero: List[Dict[str, Any]] = []

    for sig in deduped:
        rid = str(sig.get("rule_id", "") or "")
        try:
            failures = int(sig.get("failures") or 0)
        except Exception:
            failures = 0
        classified = dict(sig)
        if rid in targetable or rid in introduced:
            classified["reconciliation"] = "active_actionable"
            active.append(classified)
        elif rid in non_targetable or rid in pending:
            classified["reconciliation"] = "non_targetable_residual" if rid in non_targetable else "review_required"
            classified["active_blocker"] = False
            non_targetable_signals.append(classified)
        elif failures == 0:
            classified["reconciliation"] = "suppressed_zero_count"
            classified["active_blocker"] = False
            suppressed_zero.append(classified)
        elif rid and rid not in unresolved:
            classified["reconciliation"] = "resolved_incidental"
            classified["active_blocker"] = False
            resolved.append(classified)
        else:
            classified["reconciliation"] = "active_actionable"
            active.append(classified)

    return {
        "raw_emissions": len(raw),
        "deduped_count": len(deduped),
        "active_actionable_count": len(active),
        "resolved_incidental_count": len(resolved),
        "non_targetable_residual_count": len(non_targetable_signals),
        "suppressed_zero_count": len(suppressed_zero),
        "raw_signals": raw,
        "deduped_signals": deduped,
        "active_actionable_signals": active,
        "resolved_incidental_signals": resolved,
        "non_targetable_residual_signals": non_targetable_signals,
        "suppressed_zero_count_signals": suppressed_zero,
    }
