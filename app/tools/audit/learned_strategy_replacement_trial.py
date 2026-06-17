#!/usr/bin/env python3
"""Isolated learned strategy replacement trial diagnostics.

Patch 17A deliberately evaluates learned outputs only inside a job audit
sidecar directory. It never adopts a learned PDF, never mutates the canonical
rule map, never installs a repair script, and never changes final verdict or
package authority.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "learned-strategy-replacement-trial.v1"
ARTIFACT_NAME = "learned_strategy_replacement_trial_report.json"
MODE = "isolated_replacement_trial"
TRIAL_DIR_NAME = "learned_strategy_replacement_trial"

TRIAL_DECISIONS = (
    "trial_skipped_not_eligible",
    "trial_failed_integrity",
    "trial_failed_regression",
    "trial_needs_manual_review",
    "trial_evidence_passed",
)

BLOCKED_DEEPER_DECISIONS = {
    "skipped_not_eligible",
    "failed_integrity",
    "failed_preservation",
    "failed_render",
    "failed_verapdf_regression",
    "blocked_missing_artifact",
}


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


def sha256_file(path: Path) -> Optional[str]:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "diagnostic_sidecar_only": True,
        "isolated_trial_only": True,
        "normal_final_pdf_remains_authoritative": True,
        "candidate_is_adoptable": False,
        "replacement_trial_is_not_adoption_approval": True,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }


def empty_summary() -> Dict[str, int]:
    return {decision: 0 for decision in TRIAL_DECISIONS}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _key(record: Dict[str, Any]) -> Tuple[str, str, str]:
    return (_clean(record.get("rule_id")), _clean(record.get("candidate_id")), _clean(record.get("attempt_id")))


def _index_by_key(records: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for record in records or []:
        if isinstance(record, dict):
            out[_key(record)] = record
    return out


def _records(payload: Dict[str, Any], *names: str) -> List[Dict[str, Any]]:
    for name in names:
        value = payload.get(name)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def _candidate_id(record: Dict[str, Any]) -> str:
    raw = _clean(record.get("attempt_id")) or _clean(record.get("candidate_id")) or "candidate"
    return raw.replace("/", "-").replace(" ", "_")


def _find_learned_output(comparison: Dict[str, Any]) -> Optional[Path]:
    for field in (
        "output_pdf",
        "learned_output_pdf",
        "candidate_output_pdf",
        "execution_output_pdf",
        "output_path",
    ):
        value = comparison.get(field)
        if value:
            return Path(str(value))
    return None


def _basic_pdf_header_check(path: Path) -> Dict[str, Any]:
    result = {
        "check_name": "basic_pdf_header",
        "performed": True,
        "result": "FAIL",
        "path": str(path),
    }
    try:
        with Path(path).open("rb") as fh:
            header = fh.read(5)
        result["result"] = "PASS" if header == b"%PDF-" else "FAIL"
        result["header_prefix"] = header.decode("latin-1", errors="replace")
    except Exception as exc:
        result["result"] = "FAIL"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _qpdf_check(path: Path, trial_dir: Path, timeout_seconds: int) -> Dict[str, Any]:
    stdout_path = trial_dir / "qpdf.stdout.txt"
    stderr_path = trial_dir / "qpdf.stderr.txt"
    result: Dict[str, Any] = {
        "check_name": "qpdf",
        "performed": False,
        "result": "SKIPPED",
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    qpdf = shutil.which("qpdf")
    if not qpdf:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("qpdf not found on PATH\n", encoding="utf-8")
        result["reason"] = "qpdf_unavailable"
        return result
    try:
        cp = subprocess.run(
            [qpdf, "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds or 60)),
        )
        stdout_path.write_text(cp.stdout or "", encoding="utf-8")
        stderr_path.write_text(cp.stderr or "", encoding="utf-8")
        result.update({
            "performed": True,
            "result": "PASS" if cp.returncode == 0 else "FAIL",
            "exit_code": cp.returncode,
        })
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text((exc.stderr or "") + "\nqpdf timed out\n", encoding="utf-8")
        result.update({"performed": True, "result": "FAIL", "reason": "timeout"})
    except Exception as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        result.update({"performed": True, "result": "FAIL", "reason": "exception"})
    return result


def _eligible_without_force(deeper: Dict[str, Any]) -> bool:
    decision = _clean(deeper.get("deeper_validation_decision"))
    return (
        decision == "deeper_validation_passed"
        and deeper.get("candidate_may_proceed_to_trial") is True
        and deeper.get("candidate_is_adoptable") is False
    )


def _skip_result(
    *,
    deeper: Dict[str, Any],
    comparison: Optional[Dict[str, Any]],
    quality: Optional[Dict[str, Any]],
    reason: str,
) -> Dict[str, Any]:
    return {
        "rule_id": deeper.get("rule_id"),
        "candidate_id": deeper.get("candidate_id"),
        "attempt_id": deeper.get("attempt_id"),
        "comparison_classification": (comparison or {}).get("classification") or (comparison or {}).get("comparison_classification"),
        "quality_decision": (quality or {}).get("quality_decision"),
        "deeper_validation_decision": deeper.get("deeper_validation_decision"),
        "trial_eligible_without_force": False,
        "trial_forced_for_diagnostics": False,
        "trial_decision": "trial_skipped_not_eligible",
        "skip_reason": reason,
        "candidate_is_adoptable": False,
        "final_pdf_adoption_performed": False,
        "production_repair_replacement_performed": False,
        "verdict_softening_performed": False,
    }


def run_learned_strategy_replacement_trial(
    *,
    deeper_validation_report_path: Path,
    comparison_artifact_path: Path,
    quality_report_path: Path,
    job_dir: Path,
    normal_final_pdf: Path,
    allow_manual_review_candidates: bool = False,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """Run an isolated learned-output replacement trial as diagnostics only."""
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    report_path = audit_dir / ARTIFACT_NAME
    comparison_payload = load_json(Path(comparison_artifact_path))
    quality_payload = load_json(Path(quality_report_path))
    deeper_payload = load_json(Path(deeper_validation_report_path))

    comparisons = _index_by_key(_records(comparison_payload, "comparisons", "results"))
    qualities = _index_by_key(_records(quality_payload, "decisions", "results"))
    deeper_results = _records(deeper_payload, "results", "decisions")

    results: List[Dict[str, Any]] = []
    trial_root = audit_dir / TRIAL_DIR_NAME
    normal_final_pdf = Path(normal_final_pdf)

    for deeper in deeper_results:
        key = _key(deeper)
        comparison = comparisons.get(key) or {}
        quality = qualities.get(key) or {}
        deeper_decision = _clean(deeper.get("deeper_validation_decision"))
        eligible_without_force = _eligible_without_force(deeper)
        forced = bool(allow_manual_review_candidates and deeper_decision == "needs_manual_review")

        if deeper_decision in BLOCKED_DEEPER_DECISIONS:
            results.append(_skip_result(deeper=deeper, comparison=comparison, quality=quality, reason=deeper_decision))
            continue
        if not eligible_without_force and not forced:
            results.append(_skip_result(deeper=deeper, comparison=comparison, quality=quality, reason="trial_not_eligible_without_diagnostic_bypass"))
            continue

        learned_output = _find_learned_output(comparison) or _find_learned_output(deeper)
        if not learned_output or not learned_output.exists() or not learned_output.is_file():
            skipped = _skip_result(deeper=deeper, comparison=comparison, quality=quality, reason="learned_output_missing")
            skipped["trial_decision"] = "trial_failed_integrity"
            results.append(skipped)
            continue
        if not normal_final_pdf.exists() or not normal_final_pdf.is_file():
            skipped = _skip_result(deeper=deeper, comparison=comparison, quality=quality, reason="normal_final_pdf_missing")
            skipped["trial_decision"] = "trial_failed_integrity"
            results.append(skipped)
            continue

        attempt_id = _candidate_id(deeper)
        trial_dir = trial_root / attempt_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        trial_normal = trial_dir / "normal_final.pdf"
        trial_learned = trial_dir / "learned_trial.pdf"
        shutil.copy2(normal_final_pdf, trial_normal)
        shutil.copy2(learned_output, trial_learned)

        normal_hash = sha256_file(trial_normal)
        learned_hash = sha256_file(trial_learned)
        header_check = _basic_pdf_header_check(trial_learned)
        qpdf_check = _qpdf_check(trial_learned, trial_dir, timeout_seconds)
        trial_checks = [qpdf_check, header_check]

        if header_check.get("result") != "PASS":
            trial_decision = "trial_failed_integrity"
        elif qpdf_check.get("performed") and qpdf_check.get("result") != "PASS":
            trial_decision = "trial_failed_regression"
        elif forced:
            trial_decision = "trial_needs_manual_review"
        else:
            trial_decision = "trial_evidence_passed"

        results.append({
            "rule_id": deeper.get("rule_id"),
            "candidate_id": deeper.get("candidate_id"),
            "strategy_id": deeper.get("strategy_id"),
            "attempt_id": deeper.get("attempt_id"),
            "comparison_classification": comparison.get("classification") or comparison.get("comparison_classification"),
            "quality_decision": quality.get("quality_decision"),
            "deeper_validation_decision": deeper_decision,
            "trial_eligible_without_force": eligible_without_force,
            "trial_forced_for_diagnostics": forced,
            "trial_directory": str(trial_dir),
            "normal_final_pdf": str(trial_normal),
            "learned_trial_pdf": str(trial_learned),
            "normal_final_sha256": normal_hash,
            "learned_trial_sha256": learned_hash,
            "normal_final_size_bytes": trial_normal.stat().st_size,
            "learned_trial_size_bytes": trial_learned.stat().st_size,
            "learned_differs_from_normal": bool(normal_hash and learned_hash and normal_hash != learned_hash),
            "trial_checks": trial_checks,
            "trial_decision": trial_decision,
            "candidate_is_adoptable": False,
            "final_pdf_adoption_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
        })

    summary = empty_summary()
    for result in results:
        decision = str(result.get("trial_decision") or "trial_skipped_not_eligible")
        summary.setdefault(decision, 0)
        summary[decision] += 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "source_deeper_validation_artifact": str(deeper_validation_report_path),
        "source_comparison_artifact": str(comparison_artifact_path),
        "source_quality_artifact": str(quality_report_path),
        "candidate_count": len(deeper_results),
        "trial_count": sum(1 for r in results if r.get("trial_directory")),
        "skipped_count": sum(1 for r in results if r.get("trial_decision") == "trial_skipped_not_eligible"),
        "failed_count": sum(1 for r in results if str(r.get("trial_decision", "")).startswith("trial_failed")),
        "manual_review_trial_count": sum(1 for r in results if r.get("trial_decision") == "trial_needs_manual_review"),
        "results": results,
        "summary": summary,
        "policy": no_adoption_policy(),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload
