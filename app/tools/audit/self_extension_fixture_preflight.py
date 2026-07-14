#!/usr/bin/env python3
"""Preflight fixture targeting for WebUI self-extension retry smoke.

H13U answers a narrow question before another WebUI retry-loop smoke runs:
after normal known repairs and validation, which residual rule would be selected
for self-extension, and does it match the configured expected target?

The tool is evidence/reporting only. It does not repair PDFs, write repair
scripts, mutate the rule map, adopt generated candidates, or update final PDFs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def clean_rule_id(value) -> str:
    return str(value or "").strip()


def strategy_gap_rules(strategy_gap: dict) -> list[str]:
    rules = strategy_gap.get("rules")
    if isinstance(rules, list):
        return [clean_rule_id(rule) for rule in rules if clean_rule_id(rule)]
    for key in ("target_rule_id", "rule_id"):
        value = clean_rule_id(strategy_gap.get(key))
        if value:
            return [value]
    return []


def residual_analysis_rules(residual_analysis: dict) -> list[str]:
    for key in (
        "targetable_residual_rules",
        "escalation_rules",
        "introduced_rules",
        "persistent_rules",
        "never_attempted_rules",
    ):
        rules = residual_analysis.get(key)
        if isinstance(rules, list):
            cleaned = [clean_rule_id(rule) for rule in rules if clean_rule_id(rule)]
            if cleaned:
                return cleaned
    return []


def hermes_rules(outcome: dict) -> list[str]:
    reconciliation = outcome.get("hermes_reconciliation") if isinstance(outcome, dict) else {}
    if not isinstance(reconciliation, dict):
        return []
    for key in ("active_actionable_rules", "deduped_rules", "raw_rules"):
        rules = reconciliation.get(key)
        if isinstance(rules, list):
            cleaned = [clean_rule_id(rule) for rule in rules if clean_rule_id(rule)]
            if cleaned:
                return cleaned
    signals = reconciliation.get("active_actionable_signals") or reconciliation.get("deduped_signals") or []
    if isinstance(signals, list):
        cleaned = []
        for signal in signals:
            if isinstance(signal, dict) and clean_rule_id(signal.get("rule_id")):
                cleaned.append(clean_rule_id(signal.get("rule_id")))
        if cleaned:
            return cleaned
    return []


def first_residual_rules(*sources: Iterable[str]) -> list[str]:
    seen = []
    for source in sources:
        for rule in source or []:
            if rule and rule not in seen:
                seen.append(rule)
    return seen


def rule_map_known_repair_available(rule_map: dict, rule_id: str) -> bool:
    rules = rule_map.get("rules") if isinstance(rule_map, dict) else {}
    entry = rules.get(rule_id) if isinstance(rules, dict) else None
    if not isinstance(entry, dict):
        return False
    strategies = entry.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        return False
    if bool(entry.get("manual")):
        return False
    resolvability = str(entry.get("resolvability") or "").lower()
    if resolvability in {"repairable_unbuilt", "manual_only", "unknown", "not_automatable"}:
        return False
    return True


def classify_result(expected_target_rule_id: str | None, residual_rules: list[str]) -> tuple[str, str, str | None, bool]:
    expected = clean_rule_id(expected_target_rule_id) or None
    actual = residual_rules[0] if residual_rules else None
    if not actual:
        return "NO_TARGET", "no_residual_rule_selected", actual, False
    if expected and actual == expected:
        return "MATCH", "actual_residual_matches_expected_target", actual, True
    if expected and actual != expected:
        return "MISMATCH", "actual_residual_did_not_match_expected_self_extension_target", actual, False
    return "MATCH", "no_expected_target_configured_actual_residual_selected", actual, True


def candidate_classification(result: str) -> str:
    if result == "MATCH":
        return "MATCHES_EXPECTED_TARGET"
    if result == "MISMATCH":
        return "MISMATCHES_EXPECTED_TARGET"
    if result == "NO_TARGET":
        return "NO_SELF_EXTENSION_TARGET"
    return "UNUSABLE_FIXTURE"


def build_preflight(*, expected_target_rule_id: str | None, residual_rules: list[str], rule_map: dict | None = None, fixture: str | None = None, evidence_sources: list[str] | None = None) -> dict:
    rule_map = rule_map if isinstance(rule_map, dict) else {}
    result, reason, actual, would_run = classify_result(expected_target_rule_id, residual_rules)
    residual_records = []
    for rule in residual_rules:
        residual_records.append({
            "rule_id": rule,
            "count": None,
            "targetable": True,
            "known_repair_available": rule_map_known_repair_available(rule_map, rule),
        })
    return {
        "result": result,
        "reason": reason,
        "expected_target_rule_id": clean_rule_id(expected_target_rule_id) or None,
        "actual_target_rule_id": actual,
        "residual_rules": residual_records,
        "self_extension_would_run": bool(would_run),
        "retry_loop_smoke_may_proceed": bool(would_run),
        "candidate_classification": candidate_classification(result),
        "fixture": fixture,
        "evidence_sources": evidence_sources or [],
        "timestamp": now(),
        "policy": {
            "evidence_only": True,
            "source_repair_creation_allowed": False,
            "rule_map_mutation_allowed": False,
            "adoption_allowed": False,
            "final_pdf_update_from_failed_candidate_allowed": False,
        },
    }


def build_preflight_from_job(job_dir: Path, *, expected_target_rule_id: str | None, rule_map_path: Path | None = None, fixture: str | None = None) -> dict:
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    strategy_gap = load_json(audit_dir / "strategy_gap.json")
    outcome = load_json(audit_dir / "orchestrator_outcome.json")
    status = load_json(job_dir / "STATUS.json")
    residual_analysis = {}
    for source in (outcome, status):
        if isinstance(source.get("residual_analysis"), dict):
            residual_analysis = source["residual_analysis"]
            break
    rule_map = load_json(rule_map_path) if rule_map_path else {}
    rules = first_residual_rules(
        strategy_gap_rules(strategy_gap),
        residual_analysis_rules(residual_analysis),
        hermes_rules(outcome),
    )
    sources = []
    if strategy_gap:
        sources.append(str(audit_dir / "strategy_gap.json"))
    if residual_analysis:
        sources.append("residual_analysis")
    if outcome:
        sources.append(str(audit_dir / "orchestrator_outcome.json"))
    preflight = build_preflight(
        expected_target_rule_id=expected_target_rule_id,
        residual_rules=rules,
        rule_map=rule_map,
        fixture=fixture or str(job_dir),
        evidence_sources=sources,
    )
    preflight["artifact_path"] = str(audit_dir / "self_extension_fixture_preflight.json")
    return preflight


def preflight_blocks_retry(preflight: dict) -> bool:
    return not bool(preflight.get("self_extension_would_run"))


def surface_preflight(job_dir: Path, preflight: dict) -> dict:
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    artifact = audit_dir / "self_extension_fixture_preflight.json"
    preflight = dict(preflight)
    preflight["artifact_path"] = str(artifact)
    write_json(artifact, preflight)
    for path in (job_dir / "STATUS.json", audit_dir / "orchestrator_outcome.json"):
        payload = load_json(path)
        if not payload:
            continue
        payload["fixture_preflight"] = {
            "result": preflight.get("result"),
            "expected_target_rule_id": preflight.get("expected_target_rule_id"),
            "actual_target_rule_id": preflight.get("actual_target_rule_id"),
            "self_extension_would_run": preflight.get("self_extension_would_run"),
            "reason": preflight.get("reason"),
            "artifact_path": str(artifact),
        }
        if preflight_blocks_retry(preflight) and payload.get("overall_result") == "PASS":
            payload["overall_result"] = "ESCALATION"
            payload["result"] = "ESCALATION"
        write_json(path, payload)
    return preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight a fixture target for self-extension smoke")
    parser.add_argument("job_dir")
    parser.add_argument("--expected-target-rule", required=True)
    parser.add_argument("--rule-map", default="")
    parser.add_argument("--fixture", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--surface", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rule_map_path = Path(args.rule_map) if args.rule_map else None
    job_dir = Path(args.job_dir)
    preflight = build_preflight_from_job(
        job_dir,
        expected_target_rule_id=args.expected_target_rule,
        rule_map_path=rule_map_path,
        fixture=args.fixture or None,
    )
    if args.surface:
        preflight = surface_preflight(job_dir, preflight)
    elif args.out:
        write_json(Path(args.out), preflight)
    print(json.dumps(preflight, indent=2, sort_keys=True))
    sys.exit(0 if preflight.get("self_extension_would_run") else 1)


if __name__ == "__main__":
    main()
