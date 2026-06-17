#!/usr/bin/env python3
"""Production-testing readiness diagnostics for learned strategy replacement trials.

Patch 18A is diagnostic-only. It evaluates whether a changed learned replacement
trial has enough validation evidence for production testing review. It never
adopts a learned output, never softens PASS/FAIL/ESCALATION, never mutates the
canonical rule map, and never installs or promotes repair scripts.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "learned-strategy-production-testing-readiness.v1"
ARTIFACT_NAME = "learned_strategy_production_testing_readiness_report.json"
MODE = "production_testing_readiness_diagnostic"

REQUIRED_CHECKS = (
    "metadata",
    "form_field_preservation",
    "render_compare",
    "verapdf_delta",
)

READINESS_DECISIONS = (
    "production_testing_blocked",
    "production_testing_needs_manual_review",
    "production_testing_evidence_complete",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return data


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "diagnostic_sidecar_only": True,
        "production_testing_readiness_is_not_adoption_approval": True,
        "normal_final_pdf_remains_authoritative": True,
        "candidate_is_adoptable": False,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }


def skipped_check(check_name: str, blocker: str, reason: str = "helper_unavailable") -> Dict[str, Any]:
    return {
        "check_name": check_name,
        "performed": False,
        "result": "SKIPPED",
        "reason": reason,
        "readiness_blocker": blocker,
    }


def _run_json(cmd: List[str], *, timeout_seconds: int) -> Tuple[Optional[Dict[str, Any]], int, str]:
    try:
        cp = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds or 120)),
        )
    except subprocess.TimeoutExpired as exc:
        return None, 124, f"timeout: {exc}"
    except Exception as exc:
        return None, 2, f"{type(exc).__name__}: {exc}"
    text = (cp.stdout or "").strip()
    if not text:
        return None, cp.returncode, (cp.stderr or "").strip()
    try:
        return json.loads(text), cp.returncode, (cp.stderr or "").strip()
    except Exception as exc:
        return None, cp.returncode, f"json_parse_error:{type(exc).__name__}: {exc}; stderr={(cp.stderr or '')[:500]}"


def _app_root_from_job(job_dir: Path) -> Path:
    # Container jobs normally live under /app/workspace/jobs/<job>.  For tests and
    # host runs, fall back to the current checkout's app directory.
    job_dir = Path(job_dir).resolve()
    for parent in [job_dir] + list(job_dir.parents):
        candidate = parent / "tools"
        if candidate.exists():
            return parent
    checkout_app = Path.cwd() / "app"
    if checkout_app.exists():
        return checkout_app
    return Path("/app")


def evaluate_metadata_check(normal_pdf: Path, learned_pdf: Path, job_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    helper = _app_root_from_job(job_dir) / "tools" / "audit" / "metadata_xmp_parity_audit.py"
    if not helper.exists():
        return skipped_check("metadata", "metadata_validation_unavailable")
    normal, normal_rc, normal_err = _run_json(["python3", str(helper), str(normal_pdf)], timeout_seconds=timeout_seconds)
    learned, learned_rc, learned_err = _run_json(["python3", str(helper), str(learned_pdf)], timeout_seconds=timeout_seconds)
    if normal is None or learned is None:
        check = skipped_check("metadata", "metadata_validation_unavailable", reason="metadata_helper_error")
        check["normal_error"] = normal_err
        check["learned_error"] = learned_err
        return check
    normal_info = normal.get("info", {}) if isinstance(normal, dict) else {}
    learned_info = learned.get("info", {}) if isinstance(learned, dict) else {}
    fields = sorted(set(normal_info) | set(learned_info))
    differences = [
        {"field": field, "normal": normal_info.get(field), "learned": learned_info.get(field)}
        for field in fields
        if normal_info.get(field) != learned_info.get(field)
    ]
    hard_fail = normal_rc not in (0, 1) or learned_rc not in (0, 1) or learned.get("result") not in ("PASS", "FAIL")
    result = "FAIL" if hard_fail or differences else "PASS"
    blockers = ["metadata_changed"] if differences else []
    if hard_fail:
        blockers.append("metadata_validation_error")
    return {
        "check_name": "metadata",
        "performed": True,
        "result": result,
        "normal_result": normal.get("result"),
        "learned_result": learned.get("result"),
        "normal_metadata": normal_info,
        "learned_metadata": learned_info,
        "differences": differences,
        "blockers": blockers,
    }


def evaluate_form_field_preservation_check(normal_pdf: Path, learned_pdf: Path, job_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    helper = _app_root_from_job(job_dir) / "tools" / "qa" / "form_field_preservation_audit.py"
    if not helper.exists():
        return skipped_check("form_field_preservation", "form_field_preservation_unavailable")
    payload, rc, err = _run_json(["python3", str(helper), str(normal_pdf), str(learned_pdf)], timeout_seconds=timeout_seconds)
    if payload is None:
        check = skipped_check(
            "form_field_preservation",
            "form_field_preservation_unavailable",
            reason="form_field_helper_error",
        )
        check["error"] = err
        return check
    failures = payload.get("failures") or []
    result = "PASS" if rc == 0 and payload.get("result") == "PASS" else "FAIL"
    return {
        "check_name": "form_field_preservation",
        "performed": True,
        "result": result,
        "normal_field_count": payload.get("source_field_count"),
        "learned_field_count": payload.get("output_field_count"),
        "field_differences": failures,
        "lost_field_names": payload.get("lost_field_names", []),
        "type_mismatches": payload.get("type_mismatches", []),
        "value_mismatches": payload.get("value_mismatches", []),
        "blockers": ["form_field_preservation_failed"] if result == "FAIL" else [],
    }


def evaluate_render_compare_check(normal_pdf: Path, learned_pdf: Path, job_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    helper = _app_root_from_job(job_dir) / "tools" / "qa" / "render_compare.py"
    if not helper.exists():
        return skipped_check("render_compare", "render_compare_unavailable")
    audit_dir = Path(job_dir) / "audit"
    out_dir = audit_dir / "learned_strategy_production_readiness_render_compare"
    out_json = audit_dir / "learned_strategy_production_readiness_render_compare.json"
    payload, rc, err = _run_json(
        ["python3", str(helper), str(normal_pdf), str(learned_pdf), str(out_dir), "--out", str(out_json)],
        timeout_seconds=timeout_seconds,
    )
    if payload is None and out_json.exists():
        try:
            payload = json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            payload = None
    if payload is None:
        check = skipped_check("render_compare", "render_compare_unavailable", reason="render_compare_helper_error")
        check["error"] = err
        check["artifact"] = str(out_json)
        return check
    raw = payload.get("result")
    result = "PASS" if rc == 0 and raw == "PASS" else "FAIL"
    return {
        "check_name": "render_compare",
        "performed": True,
        "result": result,
        "helper_result": raw,
        "artifact": str(out_json),
        "pages_total": payload.get("pages_total"),
        "pages_flagged": payload.get("pages_flagged"),
        "flagged_pages": payload.get("flagged_pages", []),
        "blockers": ["render_compare_failed"] if result == "FAIL" else [],
    }


def evaluate_verapdf_delta_check(normal_pdf: Path, learned_pdf: Path, job_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    from tools.audit.learned_strategy_verapdf_delta import run_verapdf_delta_for_trial

    learned_pdf = Path(learned_pdf)
    normal_pdf = Path(normal_pdf)
    trial_dir = learned_pdf.parent if learned_pdf.parent.exists() else Path(job_dir) / "audit" / "learned_strategy_replacement_trial"
    return run_verapdf_delta_for_trial(
        normal_final_pdf=normal_pdf,
        learned_trial_pdf=learned_pdf,
        trial_dir=trial_dir,
        timeout_seconds=timeout_seconds,
    )

def _records(payload: Dict[str, Any], *names: str) -> List[Dict[str, Any]]:
    for name in names:
        value = payload.get(name)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def _readiness_decision(checks: Iterable[Dict[str, Any]]) -> Tuple[str, List[str]]:
    blockers: List[str] = []
    has_hard_failure = False
    has_manual_review_blocker = False

    for check in checks:
        result = clean_str(check.get("result"))

        check_blockers = [str(b) for b in check.get("blockers", []) if b]
        readiness_blocker = check.get("readiness_blocker")
        if readiness_blocker:
            check_blockers.append(str(readiness_blocker))
        blockers.extend(check_blockers)

        helper_unavailable_or_error = (
            result == "SKIPPED"
            or not check.get("performed")
            or any(
                b in {
                    "metadata_validation_unavailable",
                    "metadata_validation_error",
                    "form_field_preservation_unavailable",
                    "form_field_preservation_error",
                    "render_compare_unavailable",
                    "render_compare_error",
                    "verapdf_delta_unavailable",
                    "verapdf_delta_error",
                "verapdf_output_missing",
                "verapdf_process_failed",
        "verapdf_runner_unavailable",
            "verapdf_delta_timeout",
            "verapdf_delta_parse_failed",
                "verapdf_delta_timeout",
                "verapdf_delta_parse_failed",
                }
                for b in check_blockers
            )
            or str(check.get("reason", "")).endswith("_helper_error")
            or check.get("reason") in {"helper_unavailable", "input_pdf_unavailable"}
        )

        if helper_unavailable_or_error:
            has_manual_review_blocker = True

        if result == "FAIL" and not helper_unavailable_or_error:
            has_hard_failure = True

    blockers = sorted(dict.fromkeys(blockers))

    if has_hard_failure:
        return "production_testing_blocked", blockers
    if has_manual_review_blocker:
        return "production_testing_needs_manual_review", blockers
    return "production_testing_evidence_complete", blockers


def _trial_paths(record: Dict[str, Any]) -> Tuple[Optional[Path], Optional[Path]]:
    normal = record.get("normal_final_pdf") or record.get("normal_pdf")
    learned = record.get("learned_trial_pdf") or record.get("trial_pdf") or record.get("learned_output_pdf")
    return (Path(str(normal)) if normal else None, Path(str(learned)) if learned else None)



def _is_helper_unavailable_or_error_check(check: dict) -> bool:
    """Return True when a check represents missing/unsafe helper evidence, not a hard validation failure."""
    blockers = check.get("blockers") or []
    if isinstance(check.get("readiness_blocker"), str):
        blockers.append(check["readiness_blocker"])

    reason = str(check.get("reason", ""))
    name = str(check.get("check_name", ""))

    helper_blockers = {
        "metadata_validation_unavailable",
        "metadata_validation_error",
        "form_field_preservation_unavailable",
        "form_field_preservation_error",
        "render_compare_unavailable",
        "render_compare_error",
        "verapdf_delta_unavailable",
        "verapdf_delta_error",
                "verapdf_output_missing",
                "verapdf_process_failed",
        "verapdf_runner_unavailable",
    }

    if any(blocker in helper_blockers for blocker in blockers):
        return True
    if reason.endswith("_helper_error") or reason == "helper_unavailable":
        return True
    if check.get("result") == "SKIPPED":
        return True
    return False


def _has_hard_failed_check(checks: list[dict]) -> bool:
    """Only performed non-helper validation failures block production testing."""
    for check in checks:
        if check.get("result") != "FAIL":
            continue
        if _is_helper_unavailable_or_error_check(check):
            continue
        return True
    return False


def _has_manual_review_check(checks: list[dict]) -> bool:
    for check in checks:
        if check.get("result") == "SKIPPED":
            return True
        if _is_helper_unavailable_or_error_check(check):
            return True
    return False


def evaluate_learned_strategy_production_testing_readiness(
    replacement_trial_report_path: Path,
    deeper_validation_report_path: Path,
    job_dir: Path,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Evaluate production-testing readiness evidence for replacement trials."""
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    report_path = audit_dir / ARTIFACT_NAME
    replacement_trial_report_path = Path(replacement_trial_report_path)
    deeper_validation_report_path = Path(deeper_validation_report_path)

    missing = [
        str(path)
        for path in (replacement_trial_report_path, deeper_validation_report_path)
        if not path.exists()
    ]
    if missing:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now_iso(),
            "mode": MODE,
            "result": "SKIPPED",
            "missing_prerequisites": missing,
            "readiness_decision": "production_testing_needs_manual_review",
            "readiness_blockers": ["requires_learned_replacement_trial" if str(replacement_trial_report_path) in missing else "requires_deeper_validation_artifact" for _ in missing],
            "candidate_count": 0,
            "evaluated_count": 0,
            "blocked_count": 0,
            "manual_review_count": 0,
            "evidence_complete_count": 0,
            "results": [],
            "summary": {decision: 0 for decision in READINESS_DECISIONS},
            "policy": no_adoption_policy(),
            "artifact_path": str(report_path),
        }
        write_json_atomic(report_path, payload)
        return payload

    trial_payload = load_json(replacement_trial_report_path)
    deeper_payload = load_json(deeper_validation_report_path)
    trial_results = _records(trial_payload, "results", "decisions")
    results: List[Dict[str, Any]] = []

    for trial in trial_results:
        normal_pdf, learned_pdf = _trial_paths(trial)
        checks: List[Dict[str, Any]] = []
        if not normal_pdf or not learned_pdf or not normal_pdf.exists() or not learned_pdf.exists():
            for check_name in REQUIRED_CHECKS:
                checks.append(skipped_check(check_name, f"{check_name}_input_pdf_unavailable", "input_pdf_unavailable"))
        else:
            checks.append(evaluate_metadata_check(normal_pdf, learned_pdf, job_dir, timeout_seconds))
            checks.append(evaluate_form_field_preservation_check(normal_pdf, learned_pdf, job_dir, timeout_seconds))
            checks.append(evaluate_render_compare_check(normal_pdf, learned_pdf, job_dir, timeout_seconds))
            checks.append(evaluate_verapdf_delta_check(normal_pdf, learned_pdf, job_dir, timeout_seconds))

        decision, blockers = _readiness_decision(checks)
        results.append({
            "rule_id": trial.get("rule_id"),
            "candidate_id": trial.get("candidate_id"),
            "strategy_id": trial.get("strategy_id"),
            "attempt_id": trial.get("attempt_id"),
            "trial_decision": trial.get("trial_decision"),
            "deeper_validation_decision": trial.get("deeper_validation_decision"),
            "readiness_decision": decision,
            "checks": checks,
            "readiness_blockers": blockers,
            "candidate_is_adoptable": False,
            "final_pdf_adoption_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
        })

    summary = {decision: 0 for decision in READINESS_DECISIONS}
    for result in results:
        decision = str(result.get("readiness_decision") or "production_testing_needs_manual_review")
        summary.setdefault(decision, 0)
        summary[decision] += 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "source_replacement_trial_artifact": str(replacement_trial_report_path),
        "source_deeper_validation_artifact": str(deeper_validation_report_path),
        "source_comparison_artifact": str(audit_dir / "learned_strategy_output_comparisons.json"),
        "source_candidate_quality_artifact": str(audit_dir / "learned_strategy_candidate_quality_report.json"),
        "candidate_count": len(trial_results),
        "evaluated_count": len(results),
        "blocked_count": summary.get("production_testing_blocked", 0),
        "manual_review_count": summary.get("production_testing_needs_manual_review", 0),
        "evidence_complete_count": summary.get("production_testing_evidence_complete", 0),
        "results": results,
        "summary": summary,
        "policy": no_adoption_policy(),
        "deeper_validation_summary": deeper_payload.get("summary", {}),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload
