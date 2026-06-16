#!/usr/bin/env python3
"""
residual_analysis.py

Authoritative residual analyzer for the remediation orchestrator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = "1.0.0"

RESOLVABILITY_EFFECTIVE = "effective"
RESOLVABILITY_REPAIRABLE_UNBUILT = "repairable_unbuilt"
RESOLVABILITY_REPAIRABLE_REVIEW = "repairable_review"
RESOLVABILITY_NOT_AUTO_FIXABLE = "not_auto_fixable"
RESOLVABILITY_DETECTOR_MISLABELED = "detector_mislabeled"
RESOLVABILITY_LEGACY_MANUAL = "legacy_manual_review"
RESOLVABILITY_UNKNOWN = "unknown"

OUTCOME_RESOLVED = "resolved"
OUTCOME_RESOLVED_INCIDENTAL = "resolved_incidental"
OUTCOME_PERSISTENT = "persistent"
OUTCOME_ATTEMPTED_NO_EFFECT = "attempted_no_effect"
OUTCOME_INTRODUCED = "introduced"
OUTCOME_NEVER_ATTEMPTED = "never_attempted"
OUTCOME_ESCALATED = "escalated"

REPAIRABLE_RESOLVABILITY = {
    RESOLVABILITY_EFFECTIVE,
    RESOLVABILITY_REPAIRABLE_UNBUILT,
    RESOLVABILITY_REPAIRABLE_REVIEW,
    RESOLVABILITY_UNKNOWN,
}

ESCALATION_RESOLVABILITY = {
    RESOLVABILITY_NOT_AUTO_FIXABLE,
    RESOLVABILITY_DETECTOR_MISLABELED,
    RESOLVABILITY_LEGACY_MANUAL,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path | str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


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


def failure_counts(summary: Optional[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in (summary or {}).get("failures_by_rule", []) or []:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id:
            continue
        try:
            count = int(item.get("failures") or 0)
        except Exception:
            count = 1
        counts[rule_id] = counts.get(rule_id, 0) + count
    return counts


def failures_by_rule(summary: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in (summary or {}).get("failures_by_rule", []) or []:
        if isinstance(item, dict) and item.get("rule_id"):
            out[str(item["rule_id"])] = item
    return out


def rule_map_rules(rule_map: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(rule_map, dict):
        return {}
    rules = rule_map.get("rules", {})
    return rules if isinstance(rules, dict) else {}


def normalize_resolvability(rule_id: str, entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "resolvability": RESOLVABILITY_REPAIRABLE_UNBUILT,
            "source": "missing_map_entry",
            "reason": "rule absent from map; treat as an unbuilt repair gap",
        }

    explicit = str(entry.get("resolvability") or "").strip()
    if explicit:
        return {
            "resolvability": explicit,
            "source": "rule_map.resolvability",
            "reason": f"explicit rule-map resolvability={explicit}",
        }

    status = str(entry.get("status") or entry.get("confidence") or "").strip().upper()
    if status in {"HERMES_REQUIRED", "UNKNOWN", "UNBUILT"}:
        return {
            "resolvability": RESOLVABILITY_REPAIRABLE_UNBUILT,
            "source": "legacy.status",
            "reason": f"legacy status/confidence {status} normalized to repairable_unbuilt",
        }

    strategies = entry.get("strategies", [])
    if not isinstance(strategies, list):
        strategies = []

    if entry.get("manual") and not strategies:
        return {
            "resolvability": RESOLVABILITY_LEGACY_MANUAL,
            "source": "legacy.manual",
            "reason": "legacy manual:true with no strategies; preserve escalation routing",
        }

    if not strategies:
        return {
            "resolvability": RESOLVABILITY_REPAIRABLE_UNBUILT,
            "source": "legacy.empty_strategies",
            "reason": "legacy non-manual rule has no strategies; treat as unbuilt repair gap",
        }

    if any(isinstance(s, dict) and s.get("repair_script") for s in strategies):
        return {
            "resolvability": RESOLVABILITY_EFFECTIVE,
            "source": "legacy.strategy_present",
            "reason": "legacy strategy includes repair_script; treat as an effective known repair",
        }

    return {
        "resolvability": RESOLVABILITY_REPAIRABLE_UNBUILT,
        "source": "legacy.strategy_without_script",
        "reason": "strategies exist but no repair_script; treat as unbuilt repair gap",
    }


def planned_entries_for_rule(repair_plan: Dict[str, Any], rule_id: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for step in repair_plan.get("repair_steps", []) or []:
        if not isinstance(step, dict):
            continue
        rules = step.get("rules_addressed") or step.get("rule_ids") or []
        if isinstance(rules, str):
            rules = [rules]
        if rule_id in rules:
            entries.append(step)
    for key in ("hermes_required", "unknown_rules", "manual_escalations"):
        for item in repair_plan.get(key, []) or []:
            if isinstance(item, dict) and item.get("rule_id") == rule_id:
                merged = dict(item)
                merged["plan_bucket"] = key
                entries.append(merged)
    return entries


def execution_entries_for_rule(execution_log: Dict[str, Any], rule_id: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for entry in execution_log.get("repair_steps", []) or []:
        if not isinstance(entry, dict):
            continue
        rules = entry.get("rule_ids") or entry.get("rules_addressed") or []
        if isinstance(rules, str):
            rules = [rules]
        if rule_id in rules:
            entries.append(entry)
    return entries


def effective_repair_ran(entries: Iterable[Dict[str, Any]]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not entry.get("ran"):
            continue
        if entry.get("result_category") != "ran_success":
            continue
        if entry.get("output_pdf") or entry.get("output_pdf_hash"):
            return True
    return False


def any_attempt_ran(entries: Iterable[Dict[str, Any]]) -> bool:
    return any(bool(e.get("ran")) for e in entries if isinstance(e, dict))


def no_effect_attempt(entries: Iterable[Dict[str, Any]]) -> bool:
    seen = False
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("ran"):
            continue
        seen = True
        if entry.get("output_pdf") or entry.get("output_pdf_hash"):
            return False
    return seen


def targetable_by_self_extension(*, outcome: str, resolvability: str) -> bool:
    if resolvability in ESCALATION_RESOLVABILITY:
        return False
    if resolvability not in REPAIRABLE_RESOLVABILITY:
        return False
    return outcome in {OUTCOME_NEVER_ATTEMPTED, OUTCOME_INTRODUCED}


def classify_rule(
    *,
    rule_id: str,
    baseline_count: int,
    post_count: int,
    repair_plan: Dict[str, Any],
    execution_log: Dict[str, Any],
    rule_map_entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    present_in_baseline = baseline_count > 0
    present_in_post = post_count > 0
    delta = post_count - baseline_count
    partially_resolved = present_in_baseline and present_in_post and post_count < baseline_count

    plan_entries = planned_entries_for_rule(repair_plan, rule_id)
    exec_entries = execution_entries_for_rule(execution_log, rule_id)
    ran_effective = effective_repair_ran(exec_entries)
    ran_any = any_attempt_ran(exec_entries)
    ran_no_effect = no_effect_attempt(exec_entries)
    norm = normalize_resolvability(rule_id, rule_map_entry)
    resolvability = norm["resolvability"]

    review_required = resolvability == RESOLVABILITY_REPAIRABLE_REVIEW
    escalation_required = resolvability in ESCALATION_RESOLVABILITY

    if present_in_baseline and not present_in_post:
        if ran_effective:
            outcome = OUTCOME_RESOLVED
            reason = "baseline failure cleared after an applicable repair produced output"
        else:
            outcome = OUTCOME_RESOLVED_INCIDENTAL
            reason = "baseline failure cleared without an applicable recorded repair output"
    elif not present_in_baseline and present_in_post:
        outcome = OUTCOME_INTRODUCED
        reason = "rule was absent from baseline and present after known repairs"
    elif present_in_baseline and present_in_post and escalation_required:
        outcome = OUTCOME_ESCALATED
        reason = f"unresolved rule is not safely automatable: {resolvability}"
    elif present_in_baseline and present_in_post and ran_no_effect:
        outcome = OUTCOME_ATTEMPTED_NO_EFFECT
        reason = "a mapped step ran but produced no repair output"
    elif present_in_baseline and present_in_post and ran_effective and post_count >= baseline_count:
        outcome = OUTCOME_ATTEMPTED_NO_EFFECT
        reason = "a repair output existed but did not reduce the rule count"
    elif present_in_baseline and present_in_post and ran_effective:
        outcome = OUTCOME_PERSISTENT
        reason = "a repair output existed but the rule remains in post validation"
    elif present_in_baseline and present_in_post and not ran_any and resolvability in REPAIRABLE_RESOLVABILITY:
        outcome = OUTCOME_NEVER_ATTEMPTED
        reason = "rule remains and is repairable/reviewable, but no repair output was recorded"
    elif present_in_baseline and present_in_post and not ran_any:
        outcome = OUTCOME_NEVER_ATTEMPTED
        reason = "rule remains with no recorded repair attempt"
    else:
        outcome = OUTCOME_PERSISTENT
        reason = "rule remains after known repairs"

    targetable = targetable_by_self_extension(outcome=outcome, resolvability=resolvability)
    pending_review = outcome == OUTCOME_RESOLVED and resolvability == RESOLVABILITY_REPAIRABLE_REVIEW

    return {
        "rule_id": rule_id,
        "baseline_count": baseline_count,
        "post_count": post_count,
        "delta": delta,
        "present_in_baseline": present_in_baseline,
        "present_in_post": present_in_post,
        "repair_plan_entries": plan_entries,
        "execution_log_entries": exec_entries,
        "resolvability": resolvability,
        "resolvability_source": norm.get("source"),
        "outcome": outcome,
        "partially_resolved": partially_resolved,
        "targetable_by_self_extension": targetable,
        "review_required": review_required,
        "pending_review": pending_review,
        "escalation_required": escalation_required,
        "reason": reason,
    }


def analyze_residuals(
    *,
    baseline_failures: Dict[str, Any],
    post_failures: Dict[str, Any],
    repair_plan: Dict[str, Any],
    execution_log: Dict[str, Any],
    rule_map: Dict[str, Any],
    job_dir: Optional[Path | str] = None,
    input_paths: Optional[Dict[str, Path | str]] = None,
) -> Dict[str, Any]:
    baseline_counts = failure_counts(baseline_failures)
    post_counts = failure_counts(post_failures)
    baseline_details = failures_by_rule(baseline_failures)
    post_details = failures_by_rule(post_failures)
    rules = rule_map_rules(rule_map)

    all_rule_ids = sorted(set(baseline_counts) | set(post_counts))
    per_rule: Dict[str, Dict[str, Any]] = {}
    for rule_id in all_rule_ids:
        record = classify_rule(
            rule_id=rule_id,
            baseline_count=baseline_counts.get(rule_id, 0),
            post_count=post_counts.get(rule_id, 0),
            repair_plan=repair_plan,
            execution_log=execution_log,
            rule_map_entry=rules.get(rule_id),
        )
        if rule_id in baseline_details:
            record["baseline_failure"] = baseline_details[rule_id]
        if rule_id in post_details:
            record["post_failure"] = post_details[rule_id]
        per_rule[rule_id] = record

    summary_counts = Counter(record["outcome"] for record in per_rule.values())
    targetable = [
        rule_id
        for rule_id, record in per_rule.items()
        if record.get("targetable_by_self_extension")
    ]
    non_targetable = [
        rule_id
        for rule_id, record in per_rule.items()
        if record.get("present_in_post") and not record.get("targetable_by_self_extension")
    ]
    introduced = [
        rule_id
        for rule_id, record in per_rule.items()
        if record.get("outcome") == OUTCOME_INTRODUCED
    ]
    pending_review = [
        rule_id
        for rule_id, record in per_rule.items()
        if record.get("pending_review") or record.get("review_required")
    ]
    escalation = [
        rule_id
        for rule_id, record in per_rule.items()
        if record.get("escalation_required") or record.get("outcome") == OUTCOME_ESCALATED
    ]

    paths: Dict[str, Dict[str, Optional[str]]] = {}
    for key, value in (input_paths or {}).items():
        paths[key] = {"path": str(value), "sha256": sha256_file(value)}

    return {
        "schema": "montefiore.residual_analysis",
        "version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "job_dir": str(job_dir) if job_dir is not None else None,
        "input_artifacts": paths,
        "summary": {
            "total_rules": len(per_rule),
            "counts_by_outcome": dict(sorted(summary_counts.items())),
            "targetable_count": len(targetable),
            "non_targetable_count": len(non_targetable),
            "introduced_count": len(introduced),
            "pending_review_count": len(pending_review),
            "escalation_count": len(escalation),
        },
        "rules": per_rule,
        "targetable_residual_rules": targetable,
        "non_targetable_residual_rules": non_targetable,
        "introduced_rules": introduced,
        "pending_review_rules": pending_review,
        "escalation_rules": escalation,
        "policy": {
            "introduced_rules_targetable": True,
            "partially_resolved_softens_verdict": False,
            "rule_map_mutation_performed": False,
            "repair_script_promotion_performed": False,
        },
    }


def targetable_failures_from_analysis(
    analysis: Dict[str, Any],
    post_failures: Dict[str, Any],
) -> List[Dict[str, Any]]:
    wanted = set(analysis.get("targetable_residual_rules") or [])
    out: List[Dict[str, Any]] = []
    for item in post_failures.get("failures_by_rule", []) or []:
        if isinstance(item, dict) and item.get("rule_id") in wanted:
            enriched = dict(item)
            enriched["residual_analysis"] = analysis.get("rules", {}).get(item.get("rule_id"), {})
            out.append(enriched)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--post", required=True)
    parser.add_argument("--repair-plan", required=True)
    parser.add_argument("--execution-log", required=True)
    parser.add_argument("--rule-map", required=True)
    parser.add_argument("--job-dir", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    paths = {
        "baseline_failures": args.baseline,
        "post_failures": args.post,
        "repair_plan": args.repair_plan,
        "execution_log": args.execution_log,
        "rule_map": args.rule_map,
    }
    analysis = analyze_residuals(
        baseline_failures=read_json(args.baseline),
        post_failures=read_json(args.post),
        repair_plan=read_json(args.repair_plan),
        execution_log=read_json(args.execution_log),
        rule_map=read_json(args.rule_map),
        job_dir=args.job_dir or None,
        input_paths=paths,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis, indent=2, sort_keys=True))
    print(json.dumps({"result": "PASS", "out": str(out), "summary": analysis["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
