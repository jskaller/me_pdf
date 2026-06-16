#!/usr/bin/env python3
"""Residual-aware verdict/status helpers.

This module summarizes job-local residual and indexing artifacts for verdict,
status, packaging, and Hermes-signal reconciliation. It is intentionally
read-only with respect to canonical remediation policy: it never mutates
rule_repair_map.json, never promotes generated scripts, and never changes final
PDF adoption behavior.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

RESOLVED_OUTCOMES = {"resolved", "resolved_incidental"}
TARGETABLE_OUTCOMES = {
    "targetable_residual",
    "persistent",
    "attempted_no_effect",
    "never_attempted",
    "partially_resolved",
    "introduced",
}
NON_TARGETABLE_OUTCOMES = {
    "manual_review_required",
    "not_auto_fixable",
    "detector_mislabeled",
    "non_targetable_residual",
    "review_required",
    "pending_review",
}
TARGETABLE_RESOLVABILITY = {"targetable", "auto_fixable", "self_extension", "strategy_candidate"}
NON_TARGETABLE_RESOLVABILITY = {"non_targetable", "manual", "manual_review", "not_auto_fixable", "detector_mislabeled"}

SUMMARY_LIST_KEYS = (
    "targetable_residual_rules",
    "targetable_remaining_failures",
    "non_targetable_residual_rules",
    "pending_review_rules",
    "introduced_rules",
    "escalation_rules",
    "partially_resolved_rules",
    "never_attempted_rules",
    "attempted_no_effect_rules",
    "persistent_rules",
)


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


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _extend_rule_list(target: List[str], value: Any) -> None:
    """Append rule IDs from strings, dicts, lists, or keyed objects."""
    if value is None:
        return
    if isinstance(value, str):
        if value.strip():
            target.append(value)
        return
    if isinstance(value, Mapping):
        rid = value.get("rule_id") or value.get("id") or value.get("rule")
        if rid:
            target.append(str(rid))
            return
        # Some artifacts use {"PDF/UA-x": {...}}.
        for key, subvalue in value.items():
            if isinstance(subvalue, Mapping):
                nested_id = subvalue.get("rule_id") or key
                if nested_id:
                    target.append(str(nested_id))
            elif isinstance(subvalue, (str, int, float)):
                target.append(str(subvalue))
        return
    if isinstance(value, Iterable):
        for item in value:
            _extend_rule_list(target, item)


def _list_from_containers(data: Mapping[str, Any], summary: Mapping[str, Any], key: str) -> List[str]:
    values: List[str] = []
    _extend_rule_list(values, summary.get(key))
    _extend_rule_list(values, data.get(key))
    return _sorted_unique(values)


def _iter_rule_records(data: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Yield (rule_id, record) from current and legacy residual schemas."""
    for container_key in ("rules", "by_rule", "rule_results", "residual_rules"):
        container = data.get(container_key)
        if isinstance(container, Mapping):
            for key, value in container.items():
                if isinstance(value, Mapping):
                    rid = value.get("rule_id") or value.get("id") or value.get("rule") or key
                    yield str(rid), value
                else:
                    yield str(key), {"rule_id": key, "outcome": value}
        elif isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
            for item in container:
                if not isinstance(item, Mapping):
                    continue
                rid = item.get("rule_id") or item.get("id") or item.get("rule")
                if rid:
                    yield str(rid), item


def _classify_rule(rule_id: str, record: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """Return primary bucket plus additional diagnostic buckets for a rule."""
    outcome = str(record.get("outcome", "") or "").strip().lower()
    resolvability = str(record.get("resolvability", "") or "").strip().lower()
    post_count = _as_int(record.get("post_count", record.get("failures", record.get("post_failures", 0))), 0)
    targetable_flag = _as_bool(record.get("targetable_by_self_extension"))
    if targetable_flag is None:
        targetable_flag = _as_bool(record.get("targetable"))

    diagnostics: list[str] = []
    if bool(record.get("pending_review")) or "review" in outcome:
        diagnostics.append("pending_review_rules")
    if bool(record.get("partially_resolved")) or outcome == "partially_resolved":
        diagnostics.append("partially_resolved_rules")
    if outcome == "introduced":
        diagnostics.append("introduced_rules")
    if outcome == "never_attempted":
        diagnostics.append("never_attempted_rules")
    if outcome == "attempted_no_effect":
        diagnostics.append("attempted_no_effect_rules")
    if outcome == "persistent":
        diagnostics.append("persistent_rules")

    if not rule_id or outcome in RESOLVED_OUTCOMES or post_count == 0:
        return None, diagnostics
    if outcome == "introduced":
        return "introduced_rules", diagnostics
    if targetable_flag is True or outcome in TARGETABLE_OUTCOMES or resolvability in TARGETABLE_RESOLVABILITY:
        return "targetable_residual_rules", diagnostics
    if targetable_flag is False or outcome in NON_TARGETABLE_OUTCOMES or resolvability in NON_TARGETABLE_RESOLVABILITY:
        return "non_targetable_residual_rules", diagnostics
    if bool(record.get("pending_review")):
        return "pending_review_rules", diagnostics
    return None, diagnostics


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
    counts = summary.get("counts_by_outcome", {}) if isinstance(summary.get("counts_by_outcome"), dict) else {}
    if not counts and isinstance(data.get("counts_by_outcome"), dict):
        counts = data.get("counts_by_outcome", {})

    buckets: dict[str, list[str]] = {
        "targetable_residual_rules": [],
        "non_targetable_residual_rules": [],
        "pending_review_rules": [],
        "introduced_rules": [],
        "escalation_rules": [],
        "partially_resolved_rules": [],
        "never_attempted_rules": [],
        "attempted_no_effect_rules": [],
        "persistent_rules": [],
    }

    # Current/legacy explicit lists. targetable_remaining_failures is an alias
    # for targetable residuals exposed by the live smoke artifact.
    for key in SUMMARY_LIST_KEYS:
        values = _list_from_containers(data, summary, key)
        if key == "targetable_remaining_failures":
            buckets["targetable_residual_rules"].extend(values)
        elif key in buckets:
            buckets[key].extend(values)

    # Per-rule schemas, either dict or list. These are authoritative when list
    # fields are missing or incomplete.
    for rule_id, record in _iter_rule_records(data):
        primary, diagnostics = _classify_rule(rule_id, record)
        if primary:
            buckets[primary].append(rule_id)
        for diagnostic_key in diagnostics:
            if diagnostic_key in buckets:
                buckets[diagnostic_key].append(rule_id)

    # Escalation is at least the actionable targetable/introduced set unless the
    # artifact provided a narrower explicit list.
    if not buckets["escalation_rules"]:
        buckets["escalation_rules"].extend(buckets["targetable_residual_rules"])
        buckets["escalation_rules"].extend(buckets["introduced_rules"])

    policy = data.get("policy", {}) if isinstance(data.get("policy"), dict) else {}
    return {
        "available": True,
        "residual_analysis_path": str(path),
        "residual_analysis_sha256": _sha256(path),
        "counts_by_outcome": dict(counts),
        "targetable_residual_rules": _sorted_unique(buckets["targetable_residual_rules"]),
        "non_targetable_residual_rules": _sorted_unique(buckets["non_targetable_residual_rules"]),
        "pending_review_rules": _sorted_unique(buckets["pending_review_rules"]),
        "introduced_rules": _sorted_unique(buckets["introduced_rules"]),
        "escalation_rules": _sorted_unique(buckets["escalation_rules"]),
        "partially_resolved_rules": _sorted_unique(buckets["partially_resolved_rules"]),
        "never_attempted_rules": _sorted_unique(buckets["never_attempted_rules"]),
        "attempted_no_effect_rules": _sorted_unique(buckets["attempted_no_effect_rules"]),
        "persistent_rules": _sorted_unique(buckets["persistent_rules"]),
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
    targetable = {str(v) for v in (summary.get("targetable_residual_rules", []) or [])}
    non_targetable = {str(v) for v in (summary.get("non_targetable_residual_rules", []) or [])}
    pending = {str(v) for v in (summary.get("pending_review_rules", []) or [])}
    introduced = {str(v) for v in (summary.get("introduced_rules", []) or [])}
    persistent = {str(v) for v in (summary.get("persistent_rules", []) or [])}
    unresolved = targetable | non_targetable | pending | introduced | persistent

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
        failures = _as_int(sig.get("failures"), 0)
        classified = dict(sig)

        # Residual analysis is authoritative for targetable blockers. Even a
        # zero-count raw Hermes signal can remain active when the residual
        # artifact proves the rule is still a targetable residual.
        if rid in targetable or rid in introduced:
            classified["reconciliation"] = "active_actionable"
            classified["active_blocker"] = True
            active.append(classified)
        elif failures == 0:
            classified["reconciliation"] = "suppressed_zero_count"
            classified["active_blocker"] = False
            suppressed_zero.append(classified)
        elif rid in non_targetable or rid in pending:
            classified["reconciliation"] = "non_targetable_residual" if rid in non_targetable else "review_required"
            classified["active_blocker"] = False
            non_targetable_signals.append(classified)
        elif rid and rid not in unresolved:
            classified["reconciliation"] = "resolved_incidental"
            classified["active_blocker"] = False
            resolved.append(classified)
        else:
            classified["reconciliation"] = "active_actionable"
            classified["active_blocker"] = True
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
