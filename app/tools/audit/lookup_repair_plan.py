#!/usr/bin/env python3
"""Build a repair plan from parsed veraPDF failures and rule_repair_map.json.

H10G adds an explicit fail-closed guarded-candidate path. Guarded candidates are
ignored by default. They are evaluated only with --enable-guarded-candidates and
may emit a repair step only when --precondition-report proves every required
runtime precondition.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_MAP = Path("/app/tools/audit/rule_repair_map.json")
DEFAULT_TAXONOMY = Path("/app/tools/audit/doc_taxonomy.json")
TARGET_GUARDED_RULE = "PDF/UA-1/7.18.4"
FORM_WIDGET_REPAIR = "tools/repair/repair_form_widget_structure.py"
FORM_WIDGET_STRATEGY_ID = "form_widget_structure_construction_v1"
FORM_WIDGET_REPAIR_VERSION = "1.4.0"
REQUIRED_POST_VALIDATIONS = [
    "qpdf",
    "verapdf_pdfua1",
    "verapdf_pinned_wcag",
    "verapdf_iso_no_regression",
    "profile_accounting",
    "form_widget_structure_inspection",
    "preservation",
]


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(json.dumps({"result": "ERROR", "error": f"Cannot read {label}: {exc}"}))
        sys.exit(2)
    return data if isinstance(data, dict) else {}


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def report_value(report: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in report:
        return report.get(key)
    evidence = report.get("pdf_object_evidence")
    if isinstance(evidence, dict) and key in evidence:
        return evidence.get(key)
    runtime = report.get("guarded_runtime_preconditions")
    if isinstance(runtime, dict) and key in runtime:
        return runtime.get(key)
    return default


def load_precondition_report(path_text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not path_text:
        return None, "missing_precondition_report"
    path = Path(path_text)
    if not path.exists():
        return None, "precondition_report_not_found"
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return None, f"malformed_precondition_report: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "malformed_precondition_report: root_not_object"
    return data, None


def guarded_block(rule_id: str, reasons: list[str]) -> dict[str, Any]:
    reason = reasons[0] if reasons else "guarded_candidate_blocked"
    return {
        "rule_id": rule_id,
        "strategy_id": FORM_WIDGET_STRATEGY_ID,
        "repair_script": FORM_WIDGET_REPAIR,
        "guarded": True,
        "emitted": False,
        "blocked_reason": reason,
        "blocked_reasons": reasons or [reason],
    }


def evaluate_form_widget_guarded_candidate(
    *,
    rule_id: str,
    entry: dict[str, Any],
    failure: dict[str, Any],
    precondition_report: dict[str, Any] | None,
    precondition_error: str | None,
    precondition_path: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (repair step, audit record). Any missing/false gate blocks."""
    blockers: list[str] = []
    candidates = entry.get("guarded_strategy_candidates") or []
    candidate = candidates[0] if candidates else {}

    if rule_id != TARGET_GUARDED_RULE:
        blockers.append("unsupported_guarded_rule")
    if not candidate:
        blockers.append("guarded_candidate_metadata_missing")
    if candidate.get("strategy_id") != FORM_WIDGET_STRATEGY_ID:
        blockers.append("strategy_id_mismatch")
    if candidate.get("repair_script") != FORM_WIDGET_REPAIR:
        blockers.append("repair_script_mismatch")
    if candidate.get("repair_version") != FORM_WIDGET_REPAIR_VERSION:
        blockers.append("repair_version_mismatch")
    if candidate.get("runtime_active") is not False:
        blockers.append("runtime_active_must_remain_false")
    if candidate.get("production_default") is not False:
        blockers.append("production_default_must_remain_false")
    if candidate.get("activation_status") != "guarded_metadata_only":
        blockers.append("activation_status_not_guarded_metadata_only")
    if candidate.get("requires_runtime_gating_implementation") is not True:
        blockers.append("runtime_gating_requirement_missing")
    if candidate.get("requires_explicit_activation_patch") is not True:
        blockers.append("explicit_activation_requirement_missing")
    if precondition_error:
        blockers.append(precondition_error)
    if precondition_report is None:
        return None, guarded_block(rule_id, blockers or ["missing_precondition_report"])

    if precondition_report.get("target_rule") not in (TARGET_GUARDED_RULE, None):
        blockers.append("precondition_target_rule_mismatch")
    if precondition_report.get("schema") not in ("montefiore.form_widget_structure_inspection", None):
        blockers.append("precondition_schema_not_form_widget_inspection")
    if precondition_report.get("result") not in ("INSPECTED", "READY_FOR_GUARDED_RUNTIME", None):
        blockers.append("precondition_report_not_inspected")
    if precondition_report.get("repair_performed") not in (False, None):
        blockers.append("precondition_report_must_be_read_only")
    if precondition_report.get("rule_map_mutation_performed") not in (False, None):
        blockers.append("precondition_report_must_not_mutate_rule_map")
    if not (precondition_report.get("pdf_path") or report_value(precondition_report, "path") or precondition_report.get("job_dir")):
        blockers.append("precondition_report_missing_pdf_or_job_context")

    widget_count = as_int(report_value(precondition_report, "widget_annotation_count"), -1)
    bounded_count = as_int(report_value(precondition_report, "widgets_bounded_count", report_value(precondition_report, "bounded_widget_records_count")), -1)
    missing_struct_parent_count = as_int(report_value(precondition_report, "widgets_missing_struct_parent_count"), 0)
    planned_struct_parent_assignments = as_int(report_value(precondition_report, "planned_struct_parent_assignments"), 0)
    planned_form_struct_elements = as_int(report_value(precondition_report, "planned_form_struct_elements"), 0)

    if report_value(precondition_report, "acroform_present") is not True:
        blockers.append("acroform_not_present")
    if widget_count <= 0:
        blockers.append("no_widget_annotations")
    if report_value(precondition_report, "widget_evidence_complete") is not True:
        blockers.append("widget_evidence_incomplete")
    if report_value(precondition_report, "widgets_truncated") is not False:
        blockers.append("widgets_truncated")
    if widget_count > 0 and bounded_count != widget_count:
        blockers.append("bounded_widget_count_mismatch")
    if missing_struct_parent_count <= 0 and as_int(failure.get("failures"), 0) <= 0:
        blockers.append("no_affected_widget_evidence")
    if report_value(precondition_report, "struct_tree_root_present") is False and report_value(precondition_report, "planned_struct_tree_root_creation") is not True:
        blockers.append("missing_struct_tree_root_creation_plan")
    if report_value(precondition_report, "parent_tree_present") is False and report_value(precondition_report, "planned_parent_tree_creation") is not True:
        blockers.append("missing_parent_tree_creation_plan")
    if planned_struct_parent_assignments <= 0:
        blockers.append("no_planned_struct_parent_assignments")
    if planned_form_struct_elements <= 0:
        blockers.append("no_planned_form_struct_elements")
    if report_value(precondition_report, "field_values_not_dumped") is not True and report_value(precondition_report, "sensitive_field_values_redacted") is not True:
        blockers.append("field_values_not_proven_redacted")
    if report_value(precondition_report, "source_overwrite_allowed") is True:
        blockers.append("source_overwrite_allowed")
    output_policy = report_value(precondition_report, "output_path_policy")
    if output_policy not in ("explicit_safe_intermediate_required", "lookup_does_not_write_outputs") and report_value(precondition_report, "explicit_output_path") is not True:
        blockers.append("explicit_safe_output_path_not_proven")

    if blockers:
        return None, guarded_block(rule_id, blockers)

    step = {
        "repair_script": FORM_WIDGET_REPAIR,
        "repair_order": 8,
        "run_last": False,
        "args_pattern": "<input.pdf> <explicit-safe-output.pdf>",
        "rules_addressed": [rule_id],
        "confidence": "GUARDED_CONFIRMED",
        "strategy": FORM_WIDGET_STRATEGY_ID,
        "strategy_id": FORM_WIDGET_STRATEGY_ID,
        "repair_version": FORM_WIDGET_REPAIR_VERSION,
        "pass_rate": 0.0,
        "pass_count": 0,
        "fail_count": 0,
        "all_strategies": [],
        "guarded": True,
        "runtime_active": False,
        "production_default": False,
        "requires_post_validation": True,
        "required_post_validations": REQUIRED_POST_VALIDATIONS,
        "required_terminal_behavior": "REVIEW_REQUIRED_IF_RESIDUAL_FAILURES_REMAIN",
        "precondition_report": precondition_path,
    }
    audit = {
        "rule_id": rule_id,
        "strategy_id": FORM_WIDGET_STRATEGY_ID,
        "repair_script": FORM_WIDGET_REPAIR,
        "repair_version": FORM_WIDGET_REPAIR_VERSION,
        "guarded": True,
        "emitted": True,
        "blocked_reason": "",
        "blocked_reasons": [],
        "required_post_validations": REQUIRED_POST_VALIDATIONS,
    }
    return step, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_json", help="Output JSON from parse_verapdf_summary.py")
    parser.add_argument("--map", default=str(DEFAULT_MAP), help=f"Path to rule_repair_map.json (default: {DEFAULT_MAP})")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY), help=f"Path to doc_taxonomy.json (default: {DEFAULT_TAXONOMY})")
    parser.add_argument("--doc-tags", default="", help="Comma-separated document tags for strategy ordering")
    parser.add_argument("--enable-guarded-candidates", action="store_true", help="Evaluate guarded_strategy_candidates with explicit fail-closed gates")
    parser.add_argument("--precondition-report", default="", help="JSON report proving guarded-candidate runtime preconditions")
    args = parser.parse_args()

    summary = read_json(Path(args.summary_json), "summary")
    rule_map_data = read_json(Path(args.map), "rule map")
    rule_map = rule_map_data.get("rules", {}) if isinstance(rule_map_data, dict) else {}
    doc_tags = {t.strip() for t in args.doc_tags.split(",") if t.strip()}

    failures = summary.get("failures_by_rule", [])
    if not failures:
        print(json.dumps({
            "result": "NO_FAILURES",
            "repair_steps": [],
            "hermes_required": [],
            "unknown_rules": [],
            "guarded_candidates": [],
            "note": "veraPDF reported no failures - no repairs needed.",
        }, indent=2))
        return 0

    def doc_tag_overlap_score(strategy: dict[str, Any]) -> int:
        if not doc_tags:
            return 0
        confirmed_tags = {
            stat["tag"]
            for stat in strategy.get("doc_type_stats", [])
            if stat.get("pass_count", 0) > 0
        }
        return len(doc_tags & confirmed_tags)

    def sort_strategies(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            strategies,
            key=lambda s: (s.get("pass_rate", 0.0), s.get("pass_count", 0), doc_tag_overlap_score(s)),
            reverse=True,
        )

    script_to_rules: dict[str, list[dict[str, Any]]] = defaultdict(list)
    guarded_steps_raw: list[dict[str, Any]] = []
    guarded_candidates: list[dict[str, Any]] = []
    hermes_required: list[dict[str, Any]] = []
    unknown_rules: list[dict[str, Any]] = []
    precondition_report, precondition_error = (
        load_precondition_report(args.precondition_report)
        if args.enable_guarded_candidates else (None, None)
    )

    for failure in failures:
        rule_id = failure.get("rule_id", "")
        desc = failure.get("description", "")
        count = failure.get("failures", 0)
        entry = rule_map.get(rule_id)

        if entry is None:
            unknown_rules.append({"rule_id": rule_id, "description": desc, "failures": count, "reason": "unknown_rule"})
            hermes_required.append({"rule_id": rule_id, "description": desc, "failures": count, "reason": "unknown_rule", "strategies_attempted": []})
            continue

        if args.enable_guarded_candidates and entry.get("guarded_strategy_candidates"):
            guarded_step, guarded_audit = evaluate_form_widget_guarded_candidate(
                rule_id=rule_id,
                entry=entry,
                failure=failure,
                precondition_report=precondition_report,
                precondition_error=precondition_error,
                precondition_path=str(args.precondition_report),
            )
            guarded_candidates.append(guarded_audit)
            if guarded_step:
                guarded_steps_raw.append(guarded_step)
                continue

        if entry.get("resolvability") == "detector_mislabeled":
            hermes_required.append({
                "rule_id": rule_id,
                "description": entry.get("description", desc),
                "failures": count,
                "reason": "detector_mislabeled_no_repair",
                "resolvability": "detector_mislabeled",
                "detector_scripts": [st.get("repair_script") for st in entry.get("strategies", []) if st.get("repair_script")],
                "strategies_attempted": [],
            })
            continue

        if entry.get("manual", False) and not entry.get("strategies"):
            hermes_required.append({"rule_id": rule_id, "description": entry.get("description", desc), "failures": count, "reason": "manual_no_strategies", "strategies_attempted": []})
            continue

        strategies = sort_strategies(entry.get("strategies", []))
        if not strategies:
            hermes_required.append({"rule_id": rule_id, "description": entry.get("description", desc), "failures": count, "reason": "all_strategies_exhausted", "strategies_attempted": []})
            continue

        best = strategies[0]
        script = best.get("repair_script")
        if not script:
            hermes_required.append({"rule_id": rule_id, "description": entry.get("description", desc), "failures": count, "reason": "manual_no_strategies", "strategies_attempted": []})
            continue

        script_to_rules[script].append({
            "rule_id": rule_id,
            "description": entry.get("description", desc),
            "failures": count,
            "repair_order": best.get("repair_order", 99),
            "run_last": best.get("run_last", False),
            "args_pattern": best.get("args_pattern", ""),
            "confidence": best.get("confidence", "EXPECTED"),
            "strategy": best.get("strategy", ""),
            "pass_rate": best.get("pass_rate", 0.0),
            "pass_count": best.get("pass_count", 0),
            "fail_count": best.get("fail_count", 0),
            "all_strategies": strategies,
        })

    repair_steps_raw: list[dict[str, Any]] = []
    for script, rule_entries in script_to_rules.items():
        best_entry = max(rule_entries, key=lambda r: (r["pass_rate"], r["pass_count"]))
        repair_steps_raw.append({
            "repair_script": script,
            "repair_order": max(r["repair_order"] for r in rule_entries),
            "run_last": any(r["run_last"] for r in rule_entries),
            "args_pattern": best_entry["args_pattern"],
            "rules_addressed": [r["rule_id"] for r in rule_entries],
            "confidence": best_entry["confidence"],
            "strategy": best_entry["strategy"],
            "pass_rate": best_entry["pass_rate"],
            "pass_count": best_entry["pass_count"],
            "fail_count": best_entry["fail_count"],
            "all_strategies": best_entry["all_strategies"],
        })

    repair_steps_raw.extend(guarded_steps_raw)
    repair_steps_raw.sort(key=lambda s: (s.get("run_last", False), s.get("repair_order", 99), s.get("repair_script", "")))

    repair_steps = []
    for index, step in enumerate(repair_steps_raw, start=1):
        out = {
            "step": index,
            "repair_script": step["repair_script"],
            "strategy": step["strategy"],
            "repair_order": step["repair_order"],
            "run_last": step["run_last"],
            "args_pattern": step["args_pattern"],
            "rules_addressed": step["rules_addressed"],
            "confidence": step["confidence"],
            "pass_rate": step["pass_rate"],
            "pass_count": step["pass_count"],
            "fail_count": step["fail_count"],
            "all_strategies": step["all_strategies"],
        }
        for key in (
            "guarded",
            "strategy_id",
            "repair_version",
            "runtime_active",
            "production_default",
            "requires_post_validation",
            "required_post_validations",
            "required_terminal_behavior",
            "precondition_report",
        ):
            if key in step:
                out[key] = step[key]
        repair_steps.append(out)

    result = "PLAN_READY"
    if not repair_steps and hermes_required:
        result = "ALL_MANUAL"

    output = {
        "result": result,
        "failures_total": summary.get("total_failures", 0),
        "rules_failing": len(failures),
        "doc_tags_applied": sorted(doc_tags),
        "repair_steps": repair_steps,
        "hermes_required": hermes_required,
        "unknown_rules": unknown_rules,
        "guarded_candidates": guarded_candidates,
        "agent_instruction": (
            "Execute repair_steps in the order listed (step 1 first). Any step with run_last=true "
            "must execute after all others - no PDF save operations may occur after it. For guarded "
            "repair_steps, execute only in an explicit guarded runtime path with safe intermediate "
            "output paths and all required post-validation gates. For hermes_required entries: emit "
            "HERMES_REQUIRED signal with full rule context so the agent can write or locate a repair script. "
            "For unknown_rules: the rule is not in the map - emit HERMES_REQUIRED with reason=unknown_rule "
            "so the agent researches the rule before writing."
        ),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
