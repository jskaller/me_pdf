#!/usr/bin/env python3
"""Build durable unsupported-rule iteration stress evidence for H11.

This tool is intentionally read-only. It summarizes the artifacts a production
orchestrator run already produced for rules without a working deterministic
repair and writes one compact, durable report that can be attached to
STATUS/orchestrator evidence or used by the outer Hermes agent.
"""
from __future__ import annotations

import argparse
import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "montefiore.unsupported_rule_iteration_stress"
VERSION = "1.0.0"
DEFAULT_CAPS = {
    "PER_RULE_CAP": 15,
    "JOB_WARN_AT": 20,
    "JOB_HARD_CAP": 50,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def parse_iteration_caps(remediate_path: Path) -> dict[str, Any]:
    caps = dict(DEFAULT_CAPS)
    source = str(remediate_path)
    parsed_from_source: list[str] = []
    try:
        tree = ast.parse(remediate_path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            if name not in caps:
                continue
            value = ast.literal_eval(node.value)
            caps[name] = int(value)
            parsed_from_source.append(name)
    except Exception:
        source = f"{remediate_path} (fallback defaults used)"
    return {
        "per_rule_cap": caps["PER_RULE_CAP"],
        "job_warn_at": caps["JOB_WARN_AT"],
        "job_hard_cap": caps["JOB_HARD_CAP"],
        "source_file": source,
        "parsed_settings": sorted(parsed_from_source),
    }


def rule_failure_count(rule_id: str, failures: list[Any]) -> int:
    for failure in failures:
        item = as_dict(failure)
        if item.get("rule_id") == rule_id:
            try:
                return int(item.get("failures") or item.get("failed_checks") or 0)
            except Exception:
                return 0
    return 0


def collect_hermes_items(*plans: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for plan in plans:
        for item in as_list(as_dict(plan).get("hermes_required")) + as_list(as_dict(plan).get("hermes_required_effective")):
            data = as_dict(item)
            rule_id = clean_text(data.get("rule_id"))
            if not rule_id:
                continue
            existing = items.setdefault(rule_id, {})
            existing.update({k: v for k, v in data.items() if v not in (None, "", [])})
    return items


def collect_unknown_rules(*plans: Mapping[str, Any]) -> set[str]:
    unknown: set[str] = set()
    for plan in plans:
        for item in as_list(as_dict(plan).get("unknown_rules")):
            rule_id = clean_text(as_dict(item).get("rule_id"))
            if rule_id:
                unknown.add(rule_id)
    return unknown


def collect_request_rules(request: Mapping[str, Any]) -> set[str]:
    rules: set[str] = set()
    for failure in as_list(request.get("residual_failures")):
        rule_id = clean_text(as_dict(failure).get("rule_id"))
        if rule_id:
            rules.add(rule_id)
    for rule_id in as_list(request.get("rules")):
        if clean_text(rule_id):
            rules.add(clean_text(rule_id))
    return rules


def normalize_attempts(rule_id: str, attempts_by_rule: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen_fingerprints: set[tuple[Any, ...]] = set()
    for index, raw in enumerate(as_list(attempts_by_rule.get(rule_id)), start=1):
        item = as_dict(raw)
        strategy = clean_text(item.get("strategy") or item.get("strategy_id") or item.get("repair_script") or item.get("script"))
        stop_reason = clean_text(
            item.get("stop_reason")
            or item.get("reason")
            or item.get("result")
            or item.get("terminal_state")
            or "attempt_recorded"
        )
        fingerprint = (
            strategy,
            clean_text(item.get("repair_script") or item.get("script")),
            clean_text(item.get("input_pdf")),
            clean_text(item.get("output_pdf")),
            clean_text(item.get("result") or item.get("terminal_state")),
        )
        repeat = fingerprint in seen_fingerprints
        seen_fingerprints.add(fingerprint)
        attempts.append({
            "attempt": int(item.get("attempt") or item.get("iteration") or index),
            "strategy": strategy or "unknown_strategy",
            "input_evidence": clean_text(item.get("input_pdf") or item.get("current_pdf") or item.get("source_pdf")),
            "validation_result": clean_text(item.get("validation_result") or item.get("result") or item.get("terminal_state") or "UNKNOWN"),
            "new_evidence": bool(item.get("validation_artifacts") or item.get("output_pdf") or item.get("output_pdf_sha256") or item.get("artifacts")),
            "repeat_of_prior_attempt": repeat,
            "stop_reason": stop_reason,
            "raw": item,
        })
    return attempts


def build_rule_record(
    *,
    rule_id: str,
    caps: Mapping[str, Any],
    hermes_item: Mapping[str, Any],
    attempts_by_rule: Mapping[str, Any],
    request: Mapping[str, Any],
    gap: Mapping[str, Any],
    strategy_request_path: Path,
    unknown_rules: set[str],
) -> dict[str, Any]:
    attempts = normalize_attempts(rule_id, attempts_by_rule)
    request_exists = strategy_request_path.exists()
    failure_count = int(hermes_item.get("failures") or rule_failure_count(rule_id, as_list(request.get("residual_failures"))) or 0)
    reason = clean_text(hermes_item.get("reason")) or ("unknown_rule" if rule_id in unknown_rules else "unsupported_rule")

    repeated_attempts_flagged = any(attempt.get("repeat_of_prior_attempt") for attempt in attempts)
    if not attempts:
        stop_reason = "no_working_script_available" if reason in {"unknown_rule", "all_strategies_exhausted", "manual_no_strategies"} else reason
    elif len(attempts) >= int(caps.get("per_rule_cap", DEFAULT_CAPS["PER_RULE_CAP"])):
        stop_reason = "per_rule_attempt_cap_exhausted"
    elif repeated_attempts_flagged:
        stop_reason = "repeated_identical_attempt_detected"
    else:
        stop_reason = reason or "needs_human_review"

    self_extension = as_dict(gap.get("self_extension"))
    candidate_generated = bool(self_extension and self_extension.get("result") not in (None, "SKIPPED"))

    if request_exists and failure_count > 0:
        terminal_state = "ATTEMPTS_EXHAUSTED_REVIEW_REQUIRED" if attempts else "UNSUPPORTED_REVIEW_REQUIRED"
    else:
        terminal_state = "UNSUPPORTED_RULE_NOT_ACTIONABLE"

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "rule_id": rule_id,
        "workflow": "unsupported_rule_strategy_generation",
        "description": clean_text(hermes_item.get("description")),
        "reason": reason,
        "failure_count": failure_count,
        "configured_max_attempts": int(caps.get("per_rule_cap", DEFAULT_CAPS["PER_RULE_CAP"])),
        "configured_job_warn_at": int(caps.get("job_warn_at", DEFAULT_CAPS["JOB_WARN_AT"])),
        "configured_job_hard_cap": int(caps.get("job_hard_cap", DEFAULT_CAPS["JOB_HARD_CAP"])),
        "attempts_used": len(attempts),
        "attempts": attempts,
        "strategy_request_created": request_exists,
        "strategy_request_path": str(strategy_request_path) if request_exists else "",
        "reusable_repair_candidate_generated": candidate_generated,
        "validation_ran_after_candidate": bool(self_extension.get("candidate_result") or self_extension.get("candidate_output_pdf") or self_extension.get("success_predicate")),
        "repeated_identical_attempts_detected": repeated_attempts_flagged,
        "final_stop_reason": stop_reason,
        "terminal_state": terminal_state,
        "next_action": (
            "Outer Hermes agent must use hermes_strategy_request.json to design or reject a reusable deterministic repair; do not claim PASS."
            if request_exists else
            "Fix unsupported-rule pipeline actionability: no strategy request artifact was found."
        ),
    }


def build_report(job_dir: Path, *, app_dir: Path) -> dict[str, Any]:
    audit_dir = job_dir / "audit"
    repair_plan = as_dict(read_json(audit_dir / "repair_plan.json"))
    repair_plan_post = as_dict(read_json(audit_dir / "repair_plan_post.json"))
    strategy_attempts_payload = as_dict(read_json(audit_dir / "strategy_attempts.json"))
    strategy_attempts = as_dict(strategy_attempts_payload.get("attempts"))
    request_path = audit_dir / "hermes_strategy_request.json"
    request = as_dict(read_json(request_path))
    gap = as_dict(read_json(audit_dir / "strategy_gap.json"))
    outcome = as_dict(read_json(audit_dir / "orchestrator_outcome.json"))
    status = as_dict(read_json(job_dir / "STATUS.json"))

    caps = parse_iteration_caps(app_dir / "tools" / "orchestrate" / "remediate.py")
    hermes_items = collect_hermes_items(repair_plan, repair_plan_post)
    unknown_rules = collect_unknown_rules(repair_plan, repair_plan_post)
    rule_ids = set(hermes_items) | collect_request_rules(request)

    records = [
        build_rule_record(
            rule_id=rule_id,
            caps=caps,
            hermes_item=hermes_items.get(rule_id, {}),
            attempts_by_rule=strategy_attempts,
            request=request,
            gap=gap,
            strategy_request_path=request_path,
            unknown_rules=unknown_rules,
        )
        for rule_id in sorted(rule_ids)
    ]

    actionable = bool(records) and all(record.get("strategy_request_created") for record in records)
    has_unactionable = any(record.get("terminal_state") == "UNSUPPORTED_RULE_NOT_ACTIONABLE" for record in records)
    result = "UNSUPPORTED_RULE_PIPELINE_ACTIONABLE" if actionable and not has_unactionable else "UNSUPPORTED_RULE_PIPELINE_NOT_ACTIONABLE"

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": now(),
        "result": result,
        "job_dir": str(job_dir),
        "audit_dir": str(audit_dir),
        "configured_caps": caps,
        "overall_status_result": status.get("overall_result") or status.get("result") or "UNKNOWN",
        "orchestrator_outcome_result": outcome.get("overall_result", "UNKNOWN"),
        "rules": records,
        "strategy_request_path": str(request_path) if request_path.exists() else "",
        "strategy_gap_path": str(audit_dir / "strategy_gap.json") if (audit_dir / "strategy_gap.json").exists() else "",
        "repair_plan_post_path": str(audit_dir / "repair_plan_post.json") if (audit_dir / "repair_plan_post.json").exists() else "",
        "safe_to_claim_pass": False,
        "safe_to_claim_production_ready": False,
        "policy": {
            "read_only": True,
            "repair_performed": False,
            "rule_map_mutation_performed": False,
            "final_pdf_adoption_performed": False,
            "package_mutation_performed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write H11 unsupported-rule iteration stress evidence")
    parser.add_argument("job_dir", help="Workspace job directory containing audit artifacts")
    parser.add_argument("--app-dir", default="/app", help="Application root containing tools/orchestrate/remediate.py")
    parser.add_argument("--out", default="", help="Output JSON path; defaults to job audit directory")
    args = parser.parse_args(argv)

    job_dir = Path(args.job_dir)
    out = Path(args.out) if args.out else job_dir / "audit" / "unsupported_rule_iteration_stress.json"
    report = build_report(job_dir, app_dir=Path(args.app_dir))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "UNSUPPORTED_RULE_PIPELINE_ACTIONABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
