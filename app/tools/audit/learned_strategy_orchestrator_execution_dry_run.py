#!/usr/bin/env python3
"""
learned_strategy_orchestrator_execution_dry_run.py

Patch 13B orchestrator-side diagnostic runner for active learned strategies.

This module is intentionally a thin integration layer. It discovers active
learned candidates, delegates all execution to the Patch 12B isolated harness,
and writes a diagnostic comparison artifact. It never adopts learned output PDFs,
never mutates the canonical rule map, never mutates app/tools/repair/*, and never
changes orchestrator verdict/status/package behavior.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tools.audit.learned_strategy_discovery import discover_active_learned_strategies, sha256_file
from tools.audit.learned_strategy_execution import execute_discovered_learned_strategy

from tools.audit.learned_strategy_output_comparison import write_learned_strategy_output_comparisons
from tools.audit.learned_strategy_candidate_quality import write_learned_strategy_candidate_quality_report
SCHEMA_VERSION = "learned-strategy-orchestrator-execution-dry-run.v1"
ARTIFACT_NAME = "learned_strategy_execution_diagnostics.json"
MODE = "learned_execution_dry_run"
NO_CANDIDATES_REASON = "no_active_learned_strategy_candidates"
LIMIT_REASON = "learned_execution_limit_reached"
INPUT_UNAVAILABLE_REASON = "learned_execution_input_pdf_unavailable"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default))
    tmp.replace(path)


def policy() -> Dict[str, Any]:
    return {
        "learned_execution_default_enabled": False,
        "requires_explicit_flag": True,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
        "uses_patch_12b_isolated_execution_harness": True,
        "diagnostic_sidecar_only": True,
    }


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def rule_ids_from_failures(failures: Optional[Iterable[Dict[str, Any]]]) -> List[str]:
    ids: List[str] = []
    for failure in failures or []:
        if not isinstance(failure, dict):
            continue
        rule_id = clean_str(failure.get("rule_id"))
        if rule_id and rule_id not in ids:
            ids.append(rule_id)
    return ids


def deterministic_candidates(discovery: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = [c for c in discovery.get("discovered_strategies", []) or [] if isinstance(c, dict)]
    return sorted(candidates, key=lambda c: (clean_str(c.get("rule_id")), clean_str(c.get("candidate_id")), clean_str(c.get("strategy_id"))))


def empty_diagnostics(*, audit_dir: Path, input_pdf: Optional[Path], enabled: bool = True) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "enabled": enabled,
        "input_pdf": str(input_pdf) if input_pdf else None,
        "input_pdf_sha256": sha256_file(input_pdf) if input_pdf and input_pdf.exists() else None,
        "candidate_count": 0,
        "executed_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
        "executions": [],
        "skipped_candidates": [],
        "blockers": [],
        "policy": policy(),
        "artifact_path": str(audit_dir / ARTIFACT_NAME),
    }


def execution_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rule_id": result.get("rule_id"),
        "candidate_id": result.get("candidate_id"),
        "strategy_id": result.get("strategy_id"),
        "attempt_id": result.get("attempt_id"),
        "execution_result_path": str(Path(result.get("attempt_dir", "")) / "execution_result.json") if result.get("attempt_dir") else None,
        "execution_log_record_type": "learned_strategy_execution",
        "result": result.get("result"),
        "exit_code": result.get("exit_code"),
        "output_pdf": result.get("output_pdf"),
        "output_pdf_sha256": result.get("output_pdf_sha256"),
        "execution_performed": bool(result.get("execution_performed")),
        "execution_blockers": result.get("execution_blockers") or [],
        "final_pdf_adoption_performed": False,
        "orchestrator_diagnostic_execution_performed": bool(result.get("execution_performed")),
        "orchestrator_final_adoption_performed": False,
        "orchestrator_integration_performed": False,
    }


def _patch14a_original_run_orchestrator_learned_execution_dry_run(
    *,
    rule_map_path: Path,
    audit_dir: Path,
    job_dir: Path,
    repo_root: Path,
    input_pdf: Path,
    residual_failures: Optional[Iterable[Dict[str, Any]]] = None,
    limit: int = 1,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Discover and execute active learned candidates as diagnostics only.

    The caller must invoke this only when an explicit opt-in flag is present.
    Normal remediation output, final PDF adoption, STATUS.json, and verdicts are
    intentionally outside this function's control.
    """
    audit_dir = Path(audit_dir)
    job_dir = Path(job_dir)
    repo_root = Path(repo_root)
    input_pdf = Path(input_pdf) if input_pdf else Path("")
    artifact_path = audit_dir / ARTIFACT_NAME
    limit = max(0, int(limit or 0))

    diagnostics = empty_diagnostics(audit_dir=audit_dir, input_pdf=input_pdf, enabled=True)

    if not input_pdf or not input_pdf.exists() or not input_pdf.is_file():
        diagnostics["blockers"].append(INPUT_UNAVAILABLE_REASON)
        diagnostics["skipped_candidates"].append({"reason": INPUT_UNAVAILABLE_REASON})
        diagnostics["skipped_count"] = 1
        write_json_atomic(artifact_path, diagnostics)
        return diagnostics

    requested_rule_ids = rule_ids_from_failures(residual_failures)
    discovery = discover_active_learned_strategies(
        rule_map_path=Path(rule_map_path),
        rule_ids=requested_rule_ids or None,
        repo_root=repo_root,
        audit_dir=audit_dir,
    )
    candidates = deterministic_candidates(discovery)
    diagnostics["input_pdf"] = str(input_pdf)
    diagnostics["input_pdf_sha256"] = sha256_file(input_pdf)
    diagnostics["candidate_count"] = len(candidates)
    diagnostics["discovery_artifact"] = str(audit_dir / "learned_strategy_discovery.json")
    diagnostics["rule_ids_requested"] = requested_rule_ids or None

    if not candidates:
        diagnostics["skipped_candidates"].append({"reason": NO_CANDIDATES_REASON})
        diagnostics["skipped_count"] = 1
        write_json_atomic(artifact_path, diagnostics)
        return diagnostics

    to_run = candidates[:limit]
    skipped = candidates[limit:]
    for candidate in skipped:
        diagnostics["skipped_candidates"].append({
            "rule_id": candidate.get("rule_id"),
            "candidate_id": candidate.get("candidate_id"),
            "strategy_id": candidate.get("strategy_id"),
            "reason": LIMIT_REASON,
        })

    for index, candidate in enumerate(to_run, start=1):
        attempt_id = "orchestrator-dry-run-%03d-%s-%s" % (
            index,
            clean_str(candidate.get("rule_id")).replace("/", "-") or "rule",
            clean_str(candidate.get("candidate_id")) or "candidate",
        )
        try:
            result = execute_discovered_learned_strategy(
                candidate,
                input_pdf=input_pdf,
                job_dir=job_dir,
                repo_root=repo_root,
                attempt_id=attempt_id,
                timeout_seconds=timeout_seconds,
                dry_run=False,
            )
        except Exception as exc:
            result = {
                "rule_id": candidate.get("rule_id"),
                "candidate_id": candidate.get("candidate_id"),
                "strategy_id": candidate.get("strategy_id"),
                "attempt_id": attempt_id,
                "result": "FAIL",
                "exit_code": None,
                "output_pdf": None,
                "output_pdf_sha256": None,
                "execution_performed": False,
                "execution_blockers": [f"orchestrator_learned_execution_exception:{type(exc).__name__}:{exc}"],
                "attempt_dir": str(job_dir / "audit" / "learned_strategy_execution" / attempt_id),
            }
        summary = execution_summary(result)
        diagnostics["executions"].append(summary)

    diagnostics["executed_count"] = sum(1 for e in diagnostics["executions"] if e.get("execution_performed"))
    diagnostics["failed_count"] = sum(1 for e in diagnostics["executions"] if e.get("result") == "FAIL")
    diagnostics["blocked_count"] = sum(1 for e in diagnostics["executions"] if e.get("result") == "BLOCKED")
    diagnostics["skipped_count"] = len(diagnostics["skipped_candidates"])

    if diagnostics.get("executions"):
        try:
            comparison_payload = write_learned_strategy_output_comparisons(
                execution_summaries=diagnostics.get("executions") or [],
                job_dir=job_dir,
                audit_dir=audit_dir,
                normal_final_pdf=input_pdf,
                timeout_seconds=timeout_seconds,
            )
            diagnostics["output_comparison_performed"] = True
            diagnostics["output_comparison_artifact"] = str(audit_dir / "learned_strategy_output_comparisons.json")
            diagnostics["output_comparison_count"] = comparison_payload.get("comparison_count", 0)
            diagnostics["output_comparison_summary"] = comparison_payload.get("summary", {})
        except Exception as exc:
            comparison_payload = None
            diagnostics["output_comparison_performed"] = False
            diagnostics["candidate_quality_performed"] = False
            diagnostics.setdefault("blockers", []).append("learned_output_comparison_diagnostic_error")
            diagnostics["output_comparison_error"] = f"{type(exc).__name__}: {exc}"
        else:
            try:
                quality_payload = write_learned_strategy_candidate_quality_report(
                    comparison_artifact_path=audit_dir / "learned_strategy_output_comparisons.json",
                    audit_dir=audit_dir,
                    job_dir=job_dir,
                )
                diagnostics["candidate_quality_performed"] = True
                diagnostics["candidate_quality_artifact"] = str(audit_dir / "learned_strategy_candidate_quality_report.json")
                diagnostics["candidate_quality_summary"] = quality_payload.get("summary", {})
                diagnostics["candidate_quality_policy"] = quality_payload.get("policy", {})
            except Exception as exc:
                diagnostics["candidate_quality_performed"] = False
                diagnostics.setdefault("blockers", []).append("learned_candidate_quality_diagnostic_error")
                diagnostics["candidate_quality_error"] = f"{type(exc).__name__}: {exc}"
    else:
        diagnostics["output_comparison_performed"] = False
        diagnostics["candidate_quality_performed"] = False
    write_json_atomic(artifact_path, diagnostics)
    return diagnostics
# Patch 14A wrapper: learned output comparison remains diagnostic-only.
def run_orchestrator_learned_execution_dry_run(
    *,
    rule_map_path: Path,
    audit_dir: Path,
    job_dir: Path,
    repo_root: Path,
    input_pdf: Path,
    residual_failures: Optional[Iterable[Dict[str, Any]]] = None,
    limit: int = 1,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Run the original learned execution dry-run, then add comparison sidecar evidence.

    The comparison is diagnostic-only. It does not adopt learned PDFs, soften
    verdicts, mutate the rule map, mutate app/tools/repair/*, or replace any
    production repair output.
    """
    diagnostics = _patch14a_original_run_orchestrator_learned_execution_dry_run(
        rule_map_path=rule_map_path,
        audit_dir=audit_dir,
        job_dir=job_dir,
        repo_root=repo_root,
        input_pdf=input_pdf,
        residual_failures=residual_failures,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )

    audit_dir = Path(audit_dir)
    job_dir = Path(job_dir)
    input_pdf = Path(input_pdf) if input_pdf else None
    artifact_path = audit_dir / ARTIFACT_NAME

    if not diagnostics.get("executions"):
        diagnostics.setdefault("output_comparison_performed", False)
        diagnostics.setdefault("output_comparison_count", 0)
        diagnostics.setdefault("output_comparison_summary", {})
        write_json_atomic(artifact_path, diagnostics)
        return diagnostics

    try:
        from tools.audit.learned_strategy_output_comparison import write_learned_strategy_output_comparisons

        comparison_payload = write_learned_strategy_output_comparisons(
            execution_summaries=diagnostics.get("executions", []),
            job_dir=job_dir,
            audit_dir=audit_dir,
            normal_final_pdf=input_pdf,
            timeout_seconds=timeout_seconds,
        )
        diagnostics["output_comparison_performed"] = True
        diagnostics["output_comparison_artifact"] = comparison_payload.get("artifact_path")
        diagnostics["output_comparison_count"] = comparison_payload.get("comparison_count", 0)
        diagnostics["output_comparison_summary"] = comparison_payload.get("summary", {})
    except Exception as exc:
        diagnostics["output_comparison_performed"] = False
        diagnostics["output_comparison_error"] = f"{type(exc).__name__}: {exc}"
        diagnostics.setdefault("blockers", []).append("learned_output_comparison_diagnostic_error")

    write_json_atomic(artifact_path, diagnostics)
    return diagnostics

# PATCH16A_DEEPER_VALIDATION_WRAPPER
# Patch 16A wrapper: after opt-in learned execution dry-run writes output
# comparisons, add candidate quality and deeper-validation sidecars. This wrapper
# is diagnostic-only and does not alter final PDF adoption, verdicts, rule-map
# state, or app/tools/repair/*.
_patch16a_previous_run_orchestrator_learned_execution_dry_run = run_orchestrator_learned_execution_dry_run


def run_orchestrator_learned_execution_dry_run(
    *,
    rule_map_path: Path,
    audit_dir: Path,
    job_dir: Path,
    repo_root: Path,
    input_pdf: Path,
    residual_failures: Optional[Iterable[Dict[str, Any]]] = None,
    limit: int = 1,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    diagnostics = _patch16a_previous_run_orchestrator_learned_execution_dry_run(
        rule_map_path=rule_map_path,
        audit_dir=audit_dir,
        job_dir=job_dir,
        repo_root=repo_root,
        input_pdf=input_pdf,
        residual_failures=residual_failures,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )
    audit_dir = Path(audit_dir)
    job_dir = Path(job_dir)
    artifact_path = audit_dir / ARTIFACT_NAME
    comparison_path = audit_dir / "learned_strategy_output_comparisons.json"

    if not comparison_path.exists():
        diagnostics.setdefault("candidate_quality_performed", False)
        diagnostics.setdefault("deeper_validation_performed", False)
        write_json_atomic(artifact_path, diagnostics)
        return diagnostics

    try:
        from tools.audit.learned_strategy_candidate_quality import write_learned_strategy_candidate_quality_report

        quality_payload = write_learned_strategy_candidate_quality_report(
            comparison_artifact_path=comparison_path,
            audit_dir=audit_dir,
            job_dir=job_dir,
        )
        diagnostics["candidate_quality_performed"] = True
        diagnostics["candidate_quality_artifact"] = quality_payload.get("artifact_path")
        diagnostics["candidate_quality_summary"] = quality_payload.get("summary", {})
    except Exception as exc:
        diagnostics["candidate_quality_performed"] = False
        diagnostics["candidate_quality_error"] = f"{type(exc).__name__}: {exc}"
        diagnostics.setdefault("blockers", []).append("learned_candidate_quality_diagnostic_error")
        write_json_atomic(artifact_path, diagnostics)
        return diagnostics

    try:
        from tools.audit.learned_strategy_deeper_validation import run_learned_strategy_deeper_validation

        quality_path = audit_dir / "learned_strategy_candidate_quality_report.json"
        deeper_payload = run_learned_strategy_deeper_validation(
            quality_report_path=quality_path,
            comparison_artifact_path=comparison_path,
            job_dir=job_dir,
            timeout_seconds=timeout_seconds,
        )
        diagnostics["deeper_validation_performed"] = True
        diagnostics["deeper_validation_artifact"] = deeper_payload.get("artifact_path")
        diagnostics["deeper_validation_summary"] = deeper_payload.get("summary", {})
        diagnostics["deeper_validation_candidate_count"] = deeper_payload.get("candidate_count", 0)
        diagnostics["deeper_validation_policy"] = deeper_payload.get("policy", {})
    except Exception as exc:
        diagnostics["deeper_validation_performed"] = False
        diagnostics["deeper_validation_error"] = f"{type(exc).__name__}: {exc}"
        diagnostics.setdefault("blockers", []).append("learned_deeper_validation_diagnostic_error")

    diagnostics["final_pdf_adoption_performed"] = False
    diagnostics["verdict_softening_performed"] = False
    diagnostics["rule_map_mutation_performed"] = False
    diagnostics["app_tools_repair_mutation_performed"] = False
    diagnostics["production_repair_replacement_performed"] = False
    write_json_atomic(artifact_path, diagnostics)
    return diagnostics
