#!/usr/bin/env python3
"""Evidence-only boundary for WebUI self-extension smoke runs.

H13S adds a narrow wrapper/policy layer for WebUI/Hermes validation of the
bounded self-extension loop. Normal production remediation may still ask an
agent to design and register deterministic repairs after HERMES_REQUIRED. This
module is different: it is only for evidence-only smoke runs where source
mutation, rule-map mutation, adoption, and final-PDF update from failed
generated candidates are prohibited.

The wrapper can launch remediate.py with self-extension configured, then writes
first-class smoke_boundary and target_rule_check summaries into
STATUS.json and audit/orchestrator_outcome.json. The pure helpers are tested
without running the full remediation pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PASS_RESULTS = {"PASS", "SKIPPED", "DISABLED"}
PROHIBITED_SOURCE_PREFIXES = (
    "app/tools/repair/",
    "app/skills/",
    "app/hermes_skills/",
)
PROHIBITED_SOURCE_FILES = {
    "app/tools/audit/rule_repair_map.json",
    "workspace/extract_text.py",
}


def _now() -> str:
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


def normalize_relpath(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def is_prohibited_source_path(path: str | Path) -> bool:
    rel = normalize_relpath(path)
    if rel in PROHIBITED_SOURCE_FILES:
        return True
    return any(rel.startswith(prefix) for prefix in PROHIBITED_SOURCE_PREFIXES)


def blocked_action(action: str, path: str | Path | None = None, reason: str = "evidence_only_smoke_mode") -> dict:
    item = {"action": action, "reason": reason}
    if path is not None:
        item["path"] = normalize_relpath(path)
    return item


def smoke_boundary_summary(blocked_actions: Iterable[dict] | None = None) -> dict:
    actions = [dict(item) for item in (blocked_actions or [])]
    return {
        "evidence_only": True,
        "source_repair_creation_allowed": False,
        "rule_map_mutation_allowed": False,
        "adoption_allowed": False,
        "final_pdf_update_from_failed_candidate_allowed": False,
        "blocked_actions": actions,
        "boundary_result": "BLOCKED" if actions else "PASS",
        "boundary_reason": "prohibited_action_blocked" if actions else "evidence_only_boundary_active",
        "timestamp": _now(),
    }


def rule_ids_from_strategy_gap(strategy_gap: dict) -> list[str]:
    rules = strategy_gap.get("rules")
    if isinstance(rules, list):
        return [str(rule) for rule in rules if rule]
    for key in ("target_rule_id", "rule_id"):
        if strategy_gap.get(key):
            return [str(strategy_gap[key])]
    return []


def target_rule_check(expected_target_rule_id: str | None, actual_rule_ids: Iterable[str]) -> dict:
    expected = (expected_target_rule_id or "").strip() or None
    actual = [str(rule) for rule in actual_rule_ids if rule]
    actual_primary = actual[0] if actual else None
    if not expected:
        result = "NOT_CONFIGURED"
        reason = "expected_self_extension_target_rule_not_configured"
    elif not actual:
        result = "NO_RESIDUAL_GAP"
        reason = "no_actual_residual_rule_selected"
    elif expected == actual_primary:
        result = "MATCH"
        reason = "actual_residual_matches_expected_self_extension_target"
    else:
        result = "MISMATCH"
        reason = "actual_residual_did_not_match_expected_self_extension_target"
    return {
        "expected_target_rule_id": expected,
        "actual_target_rule_id": actual_primary,
        "actual_rule_ids": actual,
        "result": result,
        "reason": reason,
    }


def specific_not_run_reason(*, enabled: bool, expected_target_rule_id: str | None, actual_rule_ids: Iterable[str], policy_blocked: bool = False, transport_unavailable: bool = False) -> str:
    actual = [str(rule) for rule in actual_rule_ids if rule]
    expected = (expected_target_rule_id or "").strip()
    if not enabled:
        return "self_extension_not_enabled"
    if policy_blocked:
        return "self_extension_enabled_but_policy_blocked"
    if transport_unavailable:
        return "self_extension_enabled_but_transport_unavailable"
    if not expected:
        return "self_extension_enabled_but_no_target_rule"
    if not actual:
        return "self_extension_enabled_but_no_residual_gap"
    if expected not in actual:
        return "self_extension_enabled_but_target_rule_mismatch"
    return "self_extension_enabled_but_unexpectedly_not_run"


def normalize_self_extension(existing: dict, *, enabled: bool, expected_target_rule_id: str | None, actual_rule_ids: Iterable[str], policy_blocked: bool = False, transport_unavailable: bool = False) -> dict:
    existing = dict(existing or {})
    result = str(existing.get("result") or "NOT_RUN")
    attempt_count = int(existing.get("attempt_count") or len(existing.get("attempts") or []) or 0)
    if result == "NOT_RUN" and attempt_count == 0:
        existing.update({
            "enabled": bool(enabled),
            "reason": specific_not_run_reason(
                enabled=enabled,
                expected_target_rule_id=expected_target_rule_id,
                actual_rule_ids=actual_rule_ids,
                policy_blocked=policy_blocked,
                transport_unavailable=transport_unavailable,
            ),
            "target_rule_id": existing.get("target_rule_id") or ((expected_target_rule_id or "").strip() or None),
        })
    existing.setdefault("enabled", bool(enabled))
    existing.setdefault("result", result)
    existing.setdefault("attempt_count", attempt_count)
    existing.setdefault("adoption_performed", False)
    existing.setdefault("final_pdf_updated", False)
    existing.setdefault("rule_map_mutation_performed", False)
    existing.setdefault("run_attempts_result", None)
    return existing


def source_snapshot(app_dir: Path, workspace: Path | None = None) -> dict:
    app_dir = Path(app_dir)
    workspace = Path(workspace) if workspace else app_dir.parent / "workspace"
    candidates = [
        app_dir / "tools" / "audit" / "rule_repair_map.json",
        workspace / "extract_text.py",
    ]
    repair_dir = app_dir / "tools" / "repair"
    if repair_dir.exists():
        candidates.extend(sorted(repair_dir.glob("*.py")))
    snapshot = {}
    for path in candidates:
        rel = normalize_relpath(path.relative_to(app_dir.parent) if path.is_absolute() else path)
        if path.exists():
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            snapshot[rel] = None
    return snapshot


def source_mutation_actions(before: dict, app_dir: Path, workspace: Path | None = None) -> list[dict]:
    after = source_snapshot(app_dir, workspace)
    keys = sorted(set(before) | set(after))
    actions = []
    for rel in keys:
        if before.get(rel) != after.get(rel) and is_prohibited_source_path(rel):
            if rel == "app/tools/audit/rule_repair_map.json":
                action = "rule_map_mutation"
            elif rel.startswith("app/tools/repair/"):
                action = "source_repair_creation"
            else:
                action = "source_mutation"
            actions.append(blocked_action(action, rel))
    return actions


def surface_smoke_boundary(job_dir: Path, *, expected_target_rule_id: str | None, self_extension_configured: bool = True, blocked_actions: Iterable[dict] | None = None) -> dict:
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    outcome_path = audit_dir / "orchestrator_outcome.json"
    status_path = job_dir / "STATUS.json"
    strategy_gap = load_json(audit_dir / "strategy_gap.json")
    actual_rules = rule_ids_from_strategy_gap(strategy_gap)
    target_check = target_rule_check(expected_target_rule_id, actual_rules)

    actions = [dict(item) for item in (blocked_actions or [])]
    if target_check["result"] == "MISMATCH":
        actions.append(blocked_action("target_rule_mismatch", reason=target_check["reason"]))

    boundary = smoke_boundary_summary(actions)
    existing_outcome = load_json(outcome_path)
    existing_status = load_json(status_path)
    existing_se = existing_outcome.get("self_extension") or existing_status.get("self_extension") or {}
    self_extension = normalize_self_extension(
        existing_se,
        enabled=self_extension_configured,
        expected_target_rule_id=expected_target_rule_id,
        actual_rule_ids=actual_rules,
        policy_blocked=bool(actions),
    )

    for payload, path in ((existing_outcome, outcome_path), (existing_status, status_path)):
        if not payload:
            continue
        payload["smoke_boundary"] = boundary
        payload["target_rule_check"] = target_check
        payload["self_extension"] = self_extension
        if self_extension_configured and self_extension.get("result") == "NOT_RUN":
            payload["self_extension_not_run_blocker"] = {
                "result": "BLOCKED",
                "reason": self_extension.get("reason"),
                "expected_target_rule_id": expected_target_rule_id,
                "actual_rule_ids": actual_rules,
            }
            if payload.get("overall_result") == "PASS":
                payload["overall_result"] = "ESCALATION"
            if payload.get("result") == "PASS":
                payload["result"] = "ESCALATION"
        if boundary["boundary_result"] != "PASS" and payload.get("overall_result") == "PASS":
            payload["overall_result"] = "ESCALATION"
            payload["result"] = "ESCALATION"
        write_json(path, payload)

    return {
        "smoke_boundary": boundary,
        "target_rule_check": target_check,
        "self_extension": self_extension,
        "status_path": str(status_path),
        "orchestrator_outcome_path": str(outcome_path),
    }


def run_wrapper(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    app_dir = Path(__file__).resolve().parents[2]
    job_name = f"{args.ticket}_{Path(args.basename).stem}"
    job_dir = workspace / "jobs" / job_name
    before = source_snapshot(app_dir, workspace)

    env = os.environ.copy()
    env["HERMES_ENABLE_SELF_EXTENSION"] = "1"
    env["HERMES_SELF_EXTENSION_RULE_ID"] = args.expected_target_rule
    env["HERMES_SELF_EXTENSION_MAX_ATTEMPTS_PER_RULE"] = str(args.max_attempts)
    env["HERMES_SELF_EXTENSION_EVIDENCE_ONLY"] = "1"

    cmd = [
        sys.executable,
        str(Path(__file__).with_name("remediate.py")),
        str(workspace),
        args.ticket,
        args.basename,
        "--title", args.title,
        "--subject", args.subject,
        "--keywords", args.keywords,
    ]
    proc = subprocess.run(cmd, env=env)
    actions = source_mutation_actions(before, app_dir, workspace)
    summary = surface_smoke_boundary(
        job_dir,
        expected_target_rule_id=args.expected_target_rule,
        self_extension_configured=True,
        blocked_actions=actions,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if actions or summary["self_extension"].get("result") == "NOT_RUN":
        return 1
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run remediation in H13S evidence-only self-extension smoke mode")
    parser.add_argument("workspace")
    parser.add_argument("ticket")
    parser.add_argument("basename")
    parser.add_argument("--title", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--expected-target-rule", required=True)
    parser.add_argument("--max-attempts", type=int, default=2)
    return parser


def main() -> None:
    sys.exit(run_wrapper(build_parser().parse_args()))


if __name__ == "__main__":
    main()
