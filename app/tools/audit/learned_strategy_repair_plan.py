#!/usr/bin/env python3
"""
learned_strategy_repair_plan.py

Patch 13A discovery-only bridge between the ordinary repair-plan diagnostic
path and already-active learned strategy metadata.

This module deliberately does not import, shell out to, or execute staged
learned strategy scripts. It only calls the discovery policy module, copies the
result into separate diagnostic fields, and optionally lets the caller persist
learned_strategy_discovery.json through that module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from tools.audit.learned_strategy_discovery import discover_active_learned_strategies

SCHEMA_VERSION = "learned-strategy-repair-plan-discovery.v1"
MODE = "discovery_only"


def _clean_rule_id(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def collect_rule_ids_from_repair_plan(plan_data: Dict[str, Any]) -> List[str]:
    """Return unique rule IDs mentioned by the built-in repair plan.

    The returned IDs are diagnostic discovery inputs only. They are not used to
    add or replace executable repair steps.
    """
    seen: Set[str] = set()
    ordered: List[str] = []

    for step in plan_data.get("repair_steps", []) or []:
        if not isinstance(step, dict):
            continue
        for raw_rule_id in step.get("rules_addressed", []) or []:
            rule_id = _clean_rule_id(raw_rule_id)
            if rule_id and rule_id not in seen:
                seen.add(rule_id)
                ordered.append(rule_id)

    for item in (plan_data.get("hermes_required", []) or []) + (plan_data.get("unknown_rules", []) or []):
        if not isinstance(item, dict):
            continue
        rule_id = _clean_rule_id(item.get("rule_id"))
        if rule_id and rule_id not in seen:
            seen.add(rule_id)
            ordered.append(rule_id)

    return ordered


def augment_repair_plan_with_learned_discovery(
    plan_data: Dict[str, Any],
    *,
    rule_map_path: Path,
    repo_root: Optional[Path] = None,
    audit_dir: Optional[Path] = None,
    rule_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return a copy of a repair plan with discovery-only diagnostics added.

    The built-in ``repair_steps`` array is preserved byte-for-byte at the Python
    object level: learned candidates are only attached under
    ``active_learned_strategy_candidates`` and ``learned_strategy_discovery``.
    """
    requested_rule_ids = [
        rule_id for rule_id in (_clean_rule_id(v) for v in (rule_ids or collect_rule_ids_from_repair_plan(plan_data))) if rule_id
    ]

    discovery = discover_active_learned_strategies(
        rule_map_path=Path(rule_map_path),
        rule_ids=requested_rule_ids,
        repo_root=Path(repo_root) if repo_root else None,
        audit_dir=Path(audit_dir) if audit_dir else None,
    )

    augmented = dict(plan_data)
    augmented["active_learned_strategy_candidates"] = list(discovery.get("discovered_strategies", []))
    augmented["learned_strategy_discovery"] = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "artifact": str(Path(audit_dir) / "learned_strategy_discovery.json") if audit_dir else None,
        "rule_ids_requested": discovery.get("rule_ids_requested"),
        "discovered_count": len(discovery.get("discovered_strategies", []) or []),
        "ignored_count": len(discovery.get("ignored_strategies", []) or []),
        "execution_performed": False,
        "final_pdf_adoption_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "orchestrator_execution_integration_performed": False,
        "candidate_handling": "diagnostic_only_not_repair_steps",
    }
    return augmented
