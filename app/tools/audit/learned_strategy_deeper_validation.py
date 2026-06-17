#!/usr/bin/env python3
"""Diagnostic deeper validation gate for changed learned strategy outputs.

Patch 16A is intentionally governance-only. It evaluates learned output
artifacts that already passed the candidate-quality gate far enough to deserve
stronger validation evidence, but it never adopts an output PDF, softens a
verdict, mutates the rule map, or installs a production repair script.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

SCHEMA_VERSION = "learned-strategy-deeper-validation.v1"
ARTIFACT_NAME = "learned_strategy_deeper_validation_report.json"
MODE = "diagnostic_deeper_validation"

ELIGIBLE_QUALITY_DECISIONS = {
    "candidate_valid_changed",
    "needs_deeper_validation",
}
SKIPPED_QUALITY_DECISIONS = {
    "rejected_no_effect",
    "rejected_invalid",
    "rejected_execution_failed",
}
DECISIONS = (
    "skipped_not_eligible",
    "blocked_missing_artifact",
    "failed_integrity",
    "failed_preservation",
    "failed_render",
    "failed_verapdf_regression",
    "needs_manual_review",
    "deeper_validation_passed",
)

CheckProvider = Callable[[Dict[str, Any], Dict[str, Any], Path, int], List[Dict[str, Any]]]


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
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return data


def sha256_file(path: Optional[Path]) -> Optional[str]:
    if not path or not Path(path).exists() or not Path(path).is_file():
        return None
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def as_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text)


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "diagnostic_sidecar_only": True,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
        "candidate_is_adoptable": False,
        "deeper_validation_is_not_adoption_approval": True,
    }


def empty_summary() -> Dict[str, int]:
    return {decision: 0 for decision in DECISIONS}


def summarize_results(results: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    summary = empty_summary()
    for item in results:
        decision = str(item.get("deeper_validation_decision") or "needs_manual_review")
        if decision not in summary:
            summary[decision] = 0
        summary[decision] += 1
    return summary


def _check_result(checks: Iterable[Dict[str, Any]], name: str) -> Optional[str]:
    for check in checks:
        if str(check.get("check_name") or "") == name:
            return str(check.get("result") or "UNKNOWN")
    return None


def _any_check_result(checks: Iterable[Dict[str, Any]], name: str, result: str) -> bool:
    return any(str(c.get("check_name") or "") == name and str(c.get("result") or "") == result for c in checks)


def decide_deeper_validation(checks: List[Dict[str, Any]]) -> tuple[str, List[str]]:
    """Map validation evidence to a conservative diagnostic decision."""
    reasons: List[str] = []

    if _any_check_result(checks, "basic_pdf_header", "FAIL") or _any_check_result(checks, "qpdf", "FAIL"):
        return "failed_integrity", ["integrity_check_failed"]
    if _any_check_result(checks, "form_field_preservation", "FAIL") or _any_check_result(checks, "preservation", "FAIL"):
        return "failed_preservation", ["preservation_check_failed"]
    if _any_check_result(checks, "render_compare", "FAIL"):
        return "failed_render", ["render_check_failed"]
    if _any_check_result(checks, "verapdf_delta", "FAIL"):
        return "failed_verapdf_regression", ["verapdf_regression_detected"]

    incomplete = [
        str(c.get("check_name") or "unknown")
        for c in checks
        if str(c.get("result") or "") in {"SKIPPED", "UNKNOWN"}
        or c.get("performed") is False
    ]
    if incomplete:
        return "needs_manual_review", ["validation_checks_incomplete", *[f"incomplete:{name}" for name in incomplete]]

    failing = [
        str(c.get("check_name") or "unknown")
        for c in checks
        if str(c.get("result") or "") != "PASS"
    ]
    if failing:
        return "needs_manual_review", ["validation_check_non_pass", *[f"non_pass:{name}" for name in failing]]

    header = _check_result(checks, "basic_pdf_header")
    qpdf = _check_result(checks, "qpdf")
    if header == "PASS" and qpdf == "PASS":
        return "deeper_validation_passed", ["all_performed_validation_checks_passed"]

    reasons.append("required_integrity_checks_missing")
    return "needs_manual_review", reasons


def basic_pdf_header_check(pdf_path: Optional[Path]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "check_name": "basic_pdf_header",
        "performed": True,
        "result": "FAIL",
    }
    try:
        if pdf_path and pdf_path.exists() and pdf_path.is_file() and pdf_path.read_bytes()[:5] == b"%PDF-":
            result["result"] = "PASS"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def default_qpdf_check(pdf_path: Path, attempt_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    stdout_path = attempt_dir / "deeper_validation_qpdf_stdout.txt"
    stderr_path = attempt_dir / "deeper_validation_qpdf_stderr.txt"
    qpdf = shutil.which("qpdf")
    if not qpdf:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("qpdf executable not found in PATH\n", encoding="utf-8")
        return {
            "check_name": "qpdf",
            "performed": False,
            "result": "SKIPPED",
            "reason": "helper_unavailable",
            "exit_code": None,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    try:
        proc = subprocess.run(
            [qpdf, "--check", str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout_path.write_text(proc.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8", errors="replace")
        return {
            "check_name": "qpdf",
            "performed": True,
            "result": "PASS" if proc.returncode == 0 else "FAIL",
            "exit_code": proc.returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text((stderr + "\n" if stderr else "") + f"timeout_after_seconds={timeout_seconds}\n", encoding="utf-8", errors="replace")
        return {
            "check_name": "qpdf",
            "performed": True,
            "result": "FAIL",
            "reason": "timeout",
            "exit_code": 124,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except Exception as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8", errors="replace")
        return {
            "check_name": "qpdf",
            "performed": False,
            "result": "SKIPPED",
            "reason": "helper_unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "exit_code": None,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _hash_and_size_checks(comparison: Dict[str, Any], output_pdf: Optional[Path]) -> List[Dict[str, Any]]:
    input_hash = comparison.get("input_pdf_sha256")
    output_hash = comparison.get("learned_output_pdf_sha256") or sha256_file(output_pdf)
    normal_hash = comparison.get("normal_final_pdf_sha256")
    output_size = output_pdf.stat().st_size if output_pdf and output_pdf.exists() and output_pdf.is_file() else 0
    return [
        {
            "check_name": "input_output_hash_comparison",
            "performed": True,
            "result": "PASS" if input_hash and output_hash and input_hash != output_hash else "FAIL",
            "input_output_hash_equal": bool(input_hash and output_hash and input_hash == output_hash) if output_hash else None,
            "input_pdf_sha256": input_hash,
            "learned_output_pdf_sha256": output_hash,
        },
        {
            "check_name": "normal_final_output_hash_comparison",
            "performed": bool(normal_hash and output_hash),
            "result": "PASS" if normal_hash and output_hash and normal_hash != output_hash else ("SKIPPED" if not normal_hash or not output_hash else "FAIL"),
            "reason": None if normal_hash and output_hash else "helper_unavailable",
            "normal_output_hash_equal": bool(normal_hash and output_hash and normal_hash == output_hash) if output_hash else None,
            "normal_final_pdf_sha256": normal_hash,
            "learned_output_pdf_sha256": output_hash,
        },
        {
            "check_name": "file_size_comparison",
            "performed": True,
            "result": "PASS" if output_size > 0 else "FAIL",
            "output_size_bytes": output_size,
            "comparison_output_size_bytes": comparison.get("output_size_bytes"),
        },
    ]


def _skipped_optional_checks() -> List[Dict[str, Any]]:
    return [
        {"check_name": "metadata_extraction", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
        {"check_name": "form_field_preservation", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
        {"check_name": "render_compare", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
        {"check_name": "verapdf_delta", "performed": False, "result": "SKIPPED", "reason": "helper_unavailable"},
    ]


def default_check_provider(comparison: Dict[str, Any], candidate: Dict[str, Any], attempt_dir: Path, timeout_seconds: int) -> List[Dict[str, Any]]:
    del candidate
    output_pdf = as_path(comparison.get("learned_output_pdf"))
    checks: List[Dict[str, Any]] = []
    checks.append(basic_pdf_header_check(output_pdf))
    if output_pdf and output_pdf.exists() and output_pdf.is_file():
        checks.append(default_qpdf_check(output_pdf, attempt_dir, timeout_seconds))
    else:
        checks.append({
            "check_name": "qpdf",
            "performed": False,
            "result": "SKIPPED",
            "reason": "missing_artifact",
            "exit_code": None,
            "stdout_path": str(attempt_dir / "deeper_validation_qpdf_stdout.txt"),
            "stderr_path": str(attempt_dir / "deeper_validation_qpdf_stderr.txt"),
        })
    checks.extend(_hash_and_size_checks(comparison, output_pdf))
    checks.extend(_skipped_optional_checks())
    return checks


def _candidate_key(item: Dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        item.get("rule_id"),
        item.get("candidate_id"),
        item.get("strategy_id"),
        item.get("attempt_id"),
    )


def _index_comparisons(comparisons: Iterable[Dict[str, Any]]) -> Dict[tuple[Any, Any, Any, Any], Dict[str, Any]]:
    indexed: Dict[tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
    fallback: Dict[tuple[Any, Any, Any, Any], Dict[str, Any]] = {}
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        indexed[_candidate_key(comparison)] = comparison
        fallback[(comparison.get("rule_id"), comparison.get("candidate_id"), comparison.get("strategy_id"), None)] = comparison
    indexed.update({k: v for k, v in fallback.items() if k not in indexed})
    return indexed


def _match_comparison(candidate: Dict[str, Any], index: Dict[tuple[Any, Any, Any, Any], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    keys = [
        _candidate_key(candidate),
        (candidate.get("rule_id"), candidate.get("candidate_id"), candidate.get("strategy_id"), None),
        (candidate.get("rule_id"), candidate.get("candidate_id"), None, None),
    ]
    for key in keys:
        if key in index:
            return index[key]
    for comparison in index.values():
        if comparison.get("rule_id") == candidate.get("rule_id") and comparison.get("candidate_id") == candidate.get("candidate_id"):
            return comparison
    return None


def _result_base(candidate: Dict[str, Any], comparison: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    comparison = comparison or {}
    return {
        "rule_id": candidate.get("rule_id") or comparison.get("rule_id"),
        "candidate_id": candidate.get("candidate_id") or comparison.get("candidate_id"),
        "strategy_id": candidate.get("strategy_id") or comparison.get("strategy_id"),
        "attempt_id": candidate.get("attempt_id") or comparison.get("attempt_id"),
        "comparison_classification": comparison.get("classification") or candidate.get("comparison_classification"),
        "quality_decision": candidate.get("quality_decision"),
        "checks": [],
        "candidate_may_proceed_to_trial": False,
        "candidate_is_adoptable": False,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }


def evaluate_candidate_deeper_validation(
    candidate: Dict[str, Any],
    comparison: Optional[Dict[str, Any]],
    attempt_dir: Path,
    timeout_seconds: int = 60,
    check_provider: CheckProvider | None = None,
) -> Dict[str, Any]:
    quality_decision = str(candidate.get("quality_decision") or "")
    result = _result_base(candidate, comparison)

    if quality_decision not in ELIGIBLE_QUALITY_DECISIONS:
        result.update({
            "deeper_validation_decision": "skipped_not_eligible",
            "reasons": ["quality_decision_not_deeper_validation_eligible"],
            "checks": [],
        })
        return result

    if not comparison:
        result.update({
            "deeper_validation_decision": "blocked_missing_artifact",
            "reasons": ["comparison_artifact_missing_for_candidate"],
            "checks": [],
        })
        return result

    output_pdf = as_path(comparison.get("learned_output_pdf"))
    if not output_pdf or not output_pdf.exists() or not output_pdf.is_file():
        result.update({
            "deeper_validation_decision": "blocked_missing_artifact",
            "reasons": ["learned_output_artifact_missing"],
            "checks": [],
        })
        return result

    provider = check_provider or default_check_provider
    try:
        checks = provider(comparison, candidate, attempt_dir, timeout_seconds)
    except Exception as exc:
        checks = [{
            "check_name": "deeper_validation_check_provider",
            "performed": False,
            "result": "SKIPPED",
            "reason": "helper_unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }]
    if not isinstance(checks, list):
        checks = [{
            "check_name": "deeper_validation_check_provider",
            "performed": False,
            "result": "SKIPPED",
            "reason": "helper_unavailable",
            "error": "check_provider_returned_non_list",
        }]
    decision, reasons = decide_deeper_validation(checks)
    result.update({
        "deeper_validation_decision": decision,
        "deeper_validation_passed": decision == "deeper_validation_passed",
        "candidate_may_proceed_to_trial": decision == "deeper_validation_passed",
        "candidate_is_adoptable": False,
        "checks": checks,
        "reasons": reasons,
    })
    return result


def evaluate_learned_strategy_deeper_validation(
    *,
    quality_report_path: Path,
    comparison_artifact_path: Path,
    job_dir: Path,
    timeout_seconds: int = 60,
    check_provider: CheckProvider | None = None,
) -> Dict[str, Any]:
    quality_report_path = Path(quality_report_path)
    comparison_artifact_path = Path(comparison_artifact_path)
    job_dir = Path(job_dir)
    quality = load_json(quality_report_path)
    comparison_payload = load_json(comparison_artifact_path)
    candidates = quality.get("decisions") or []
    comparisons = comparison_payload.get("comparisons") or []
    if not isinstance(candidates, list):
        raise ValueError("quality report decisions must be a list")
    if not isinstance(comparisons, list):
        raise ValueError("comparison artifact comparisons must be a list")

    attempt_dir = job_dir / "audit" / "learned_strategy_deeper_validation"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    comparison_index = _index_comparisons(comparisons)
    results: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        comparison = _match_comparison(candidate, comparison_index)
        results.append(evaluate_candidate_deeper_validation(
            candidate,
            comparison,
            attempt_dir=attempt_dir,
            timeout_seconds=timeout_seconds,
            check_provider=check_provider,
        ))

    summary = summarize_results(results)
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "source_quality_artifact": str(quality_report_path),
        "source_comparison_artifact": str(comparison_artifact_path),
        "job_dir": str(job_dir),
        "candidate_count": len(results),
        "validated_count": sum(1 for r in results if r.get("deeper_validation_decision") in {"needs_manual_review", "deeper_validation_passed", "failed_integrity", "failed_preservation", "failed_render", "failed_verapdf_regression"}),
        "skipped_count": summary.get("skipped_not_eligible", 0),
        "failed_count": sum(summary.get(k, 0) for k in ("failed_integrity", "failed_preservation", "failed_render", "failed_verapdf_regression")),
        "manual_review_count": summary.get("needs_manual_review", 0),
        "passed_count": summary.get("deeper_validation_passed", 0),
        "results": results,
        "summary": summary,
        "policy": no_adoption_policy(),
    }


def run_learned_strategy_deeper_validation(
    quality_report_path: Path,
    comparison_artifact_path: Path,
    job_dir: Path,
    timeout_seconds: int = 60,
    check_provider: CheckProvider | None = None,
) -> Dict[str, Any]:
    """Write JOB/audit/learned_strategy_deeper_validation_report.json."""
    job_dir = Path(job_dir)
    artifact_path = job_dir / "audit" / ARTIFACT_NAME
    payload = evaluate_learned_strategy_deeper_validation(
        quality_report_path=Path(quality_report_path),
        comparison_artifact_path=Path(comparison_artifact_path),
        job_dir=job_dir,
        timeout_seconds=timeout_seconds,
        check_provider=check_provider,
    )
    payload["artifact_path"] = str(artifact_path)
    write_json_atomic(artifact_path, payload)
    return payload
