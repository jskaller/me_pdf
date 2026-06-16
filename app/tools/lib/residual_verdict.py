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
    "zero_count_rules",
)

SUMMARY_BUCKET_KEYS = (
    "targetable_residual_rules",
    "non_targetable_residual_rules",
    "pending_review_rules",
    "introduced_rules",
    "escalation_rules",
    "partially_resolved_rules",
    "never_attempted_rules",
    "attempted_no_effect_rules",
    "persistent_rules",
    "zero_count_rules",
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


def _rule_metadata(record: Mapping[str, Any]) -> Dict[str, Any]:
    outcome = str(record.get("outcome", "") or "").strip().lower()
    resolvability = str(record.get("resolvability", "") or "").strip().lower()
    post_count = _as_int(record.get("post_count", record.get("failures", record.get("post_failures", 0))), 0)
    targetable_flag = _as_bool(record.get("targetable_by_self_extension"))
    if targetable_flag is None:
        targetable_flag = _as_bool(record.get("targetable"))
    pending_review = bool(record.get("pending_review")) or "review" in outcome
    partially_resolved = bool(record.get("partially_resolved")) or outcome == "partially_resolved"
    zero_count = post_count == 0
    resolved = outcome in RESOLVED_OUTCOMES
    explicit_non_targetable = (
        targetable_flag is False
        or outcome in NON_TARGETABLE_OUTCOMES
        or resolvability in NON_TARGETABLE_RESOLVABILITY
    )
    explicit_targetable = (
        targetable_flag is True
        or outcome in TARGETABLE_OUTCOMES
        or resolvability in TARGETABLE_RESOLVABILITY
    )
    return {
        "outcome": outcome,
        "resolvability": resolvability,
        "post_count": post_count,
        "targetable_flag": targetable_flag,
        "pending_review": pending_review,
        "partially_resolved": partially_resolved,
        "zero_count": zero_count,
        "resolved": resolved,
        "explicit_non_targetable": explicit_non_targetable,
        "explicit_targetable": explicit_targetable,
    }


def _empty_residual_summary(path: Path) -> Dict[str, Any]:
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
        "zero_count_rules": [],
        "partially_resolved_softens_verdict": False,
        "repair_script_promotion_performed": False,
        "rule_map_mutation_performed": False,
    }


def summarize_residual_analysis(job_dir: str | Path) -> Dict[str, Any]:
    job = Path(job_dir)
    path = job / "audit" / "residual_analysis.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return _empty_residual_summary(path)

    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    counts = summary.get("counts_by_outcome", {}) if isinstance(summary.get("counts_by_outcome"), dict) else {}
    if not counts and isinstance(data.get("counts_by_outcome"), dict):
        counts = data.get("counts_by_outcome", {})

    buckets: dict[str, list[str]] = {key: [] for key in SUMMARY_BUCKET_KEYS}

    # Current/legacy explicit lists. targetable_remaining_failures is an alias
    # for targetable residuals exposed by the live smoke artifact, but it still
    # must pass the same targetability precedence checks below.
    for key in SUMMARY_LIST_KEYS:
        values = _list_from_containers(data, summary, key)
        if key == "targetable_remaining_failures":
            buckets["targetable_residual_rules"].extend(values)
        elif key in buckets:
            buckets[key].extend(values)

    records: dict[str, Mapping[str, Any]] = {}
    meta_by_rule: dict[str, Dict[str, Any]] = {}
    for rule_id, record in _iter_rule_records(data):
        if not rule_id:
            continue
        records[rule_id] = record
        meta = _rule_metadata(record)
        meta_by_rule[rule_id] = meta

        if meta["zero_count"]:
            buckets["zero_count_rules"].append(rule_id)
        if meta["pending_review"]:
            buckets["pending_review_rules"].append(rule_id)
        if meta["partially_resolved"]:
            buckets["partially_resolved_rules"].append(rule_id)
        if meta["outcome"] == "introduced":
            buckets["introduced_rules"].append(rule_id)
        if meta["outcome"] == "never_attempted":
            buckets["never_attempted_rules"].append(rule_id)
        if meta["outcome"] == "attempted_no_effect":
            buckets["attempted_no_effect_rules"].append(rule_id)

        # Explicit non-targetable classification is authoritative. It wins over
        # attempted_no_effect, escalation, and explicit targetable list entries.
        if meta["explicit_non_targetable"] and not meta["zero_count"] and not meta["resolved"]:
            buckets["non_targetable_residual_rules"].append(rule_id)

        # Targetability requires an unresolved, non-zero post-failure rule that
        # is not pending review and has no explicit non-targetable marker.
        if (
            meta["explicit_targetable"]
            and not meta["explicit_non_targetable"]
            and not meta["zero_count"]
            and not meta["resolved"]
            and not meta["pending_review"]
        ):
            if meta["outcome"] == "introduced":
                buckets["introduced_rules"].append(rule_id)
            else:
                buckets["targetable_residual_rules"].append(rule_id)

        # Persistent is a diagnostic bucket for still-present residuals with a
        # persistent outcome. Pending-review, zero-count, and resolved rules are
        # not persistent blockers.
        if meta["outcome"] == "persistent" and not meta["pending_review"] and not meta["zero_count"] and not meta["resolved"]:
            buckets["persistent_rules"].append(rule_id)

    explicit_non_targetable = set(_sorted_unique(buckets["non_targetable_residual_rules"]))
    zero_count = set(_sorted_unique(buckets["zero_count_rules"]))
    pending = set(_sorted_unique(buckets["pending_review_rules"]))
    resolved = {rid for rid, meta in meta_by_rule.items() if meta["resolved"]}
    targetable_false = {rid for rid, meta in meta_by_rule.items() if meta["targetable_flag"] is False}

    # Clean all buckets with precedence. Explicit non-targetable, zero-count,
    # resolved, pending-review, and targetable:false rules cannot be targetable.
    not_targetable = explicit_non_targetable | zero_count | resolved | pending | targetable_false
    buckets["targetable_residual_rules"] = [
        rid for rid in buckets["targetable_residual_rules"] if rid not in not_targetable
    ]

    # Explicit targetable list entries with metadata targetable:false should be
    # visible as non-targetable residuals when they still have post failures.
    for rid in targetable_false:
        meta = meta_by_rule.get(rid, {})
        if not meta.get("zero_count") and not meta.get("resolved"):
            buckets["non_targetable_residual_rules"].append(rid)

    # Persistent rules must not include pending-review, zero-count, resolved, or
    # explicit non-targetable rules. This preserves Patch 5B expectations while
    # preventing pending-review diagnostics from becoming blockers.
    persistent_exclusions = zero_count | resolved | pending | explicit_non_targetable
    buckets["persistent_rules"] = [
        rid for rid in buckets["persistent_rules"] if rid not in persistent_exclusions
    ]

    # Escalation is at least the actionable targetable/introduced set unless the
    # artifact provided a narrower explicit list. Escalation never promotes a
    # rule into targetable_residual_rules.
    if not buckets["escalation_rules"]:
        buckets["escalation_rules"].extend(buckets["targetable_residual_rules"])
        buckets["escalation_rules"].extend(buckets["introduced_rules"])
    buckets["escalation_rules"] = [
        rid for rid in buckets["escalation_rules"] if rid not in zero_count and rid not in resolved
    ]

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
        "zero_count_rules": _sorted_unique(buckets["zero_count_rules"]),
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


def _signal_rule_ids(signals: Sequence[Mapping[str, Any]]) -> List[str]:
    return _sorted_unique(sig.get("rule_id") for sig in signals if isinstance(sig, Mapping))


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
    zero_count_rules = {str(v) for v in (summary.get("zero_count_rules", []) or [])}
    resolved_rules = {str(v) for v in (summary.get("resolved_rules", []) or [])} | zero_count_rules
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

        # Zero-failure Hermes emissions are audit evidence, not active blockers.
        # This wins over broad targetable/escalation/attempted_no_effect lists.
        if failures == 0:
            classified["reconciliation"] = "suppressed_zero_count"
            classified["active_blocker"] = False
            suppressed_zero.append(classified)
        elif rid in resolved_rules:
            classified["reconciliation"] = "resolved_incidental"
            classified["active_blocker"] = False
            resolved.append(classified)
        elif rid in non_targetable or rid in pending:
            classified["reconciliation"] = "non_targetable_residual" if rid in non_targetable else "review_required"
            classified["active_blocker"] = False
            non_targetable_signals.append(classified)
        elif rid in targetable or rid in introduced:
            classified["reconciliation"] = "active_actionable"
            classified["active_blocker"] = True
            active.append(classified)
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
        "active_actionable_rules": _signal_rule_ids(active),
        "resolved_incidental_rules": _signal_rule_ids(resolved),
        "non_targetable_residual_rules": _signal_rule_ids(non_targetable_signals),
        "suppressed_zero_count_rules": _signal_rule_ids(suppressed_zero),
    }
