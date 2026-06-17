#!/usr/bin/env python3
"""Diagnostic comparison for learned strategy execution outputs."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

SCHEMA_VERSION = "learned-strategy-output-comparison.v1"
COLLECTION_SCHEMA_VERSION = "learned-strategy-output-comparisons.v1"
ARTIFACT_NAME = "learned_strategy_output_comparisons.json"
CLASSIFICATIONS = (
    "no_effect",
    "changed_valid_pdf",
    "changed_invalid_pdf",
    "missing_output",
    "execution_failed",
    "needs_deeper_validation",
)

QpdfChecker = Callable[[Path, Path, int], Dict[str, Any]]


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


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text())
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


def basic_pdf_header_check(path: Optional[Path]) -> Dict[str, Any]:
    result = {"performed": True, "result": "FAIL"}
    try:
        if path and path.exists() and path.is_file():
            result["result"] = "PASS" if path.read_bytes()[:5] == b"%PDF-" else "FAIL"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def default_qpdf_checker(pdf_path: Path, attempt_dir: Path, timeout_seconds: int = 30) -> Dict[str, Any]:
    stdout_path = attempt_dir / "qpdf_check_stdout.txt"
    stderr_path = attempt_dir / "qpdf_check_stderr.txt"
    qpdf = shutil.which("qpdf")
    if not qpdf:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("qpdf executable not found in PATH\n", encoding="utf-8")
        return {
            "performed": False,
            "result": "SKIPPED",
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "exit_code": None,
            "reason": "qpdf_unavailable",
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
            "performed": True,
            "result": "PASS" if proc.returncode == 0 else "FAIL",
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "exit_code": proc.returncode,
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
            "performed": True,
            "result": "FAIL",
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "exit_code": 124,
            "reason": "qpdf_timeout",
        }
    except Exception as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8", errors="replace")
        return {
            "performed": False,
            "result": "SKIPPED",
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "exit_code": None,
            "reason": "qpdf_exception",
            "error": f"{type(exc).__name__}: {exc}",
        }


def classify_output(*, execution_result: str, output_exists: bool, output_size_bytes: int, header_result: str, qpdf_result: str, input_output_hash_equal: Optional[bool]) -> str:
    if execution_result != "PASS":
        return "execution_failed"
    if not output_exists or output_size_bytes <= 0:
        return "missing_output"
    if header_result == "FAIL" and qpdf_result == "FAIL":
        return "changed_invalid_pdf"
    if input_output_hash_equal is True:
        return "no_effect"
    if qpdf_result == "PASS":
        return "changed_valid_pdf"
    if qpdf_result == "FAIL":
        return "changed_invalid_pdf"
    return "needs_deeper_validation"


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "diagnostic_sidecar_only": True,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }


def compare_learned_execution_output(
    execution_result_path: Path,
    job_dir: Path,
    normal_final_pdf: Path | None = None,
    timeout_seconds: int = 30,
    qpdf_checker: QpdfChecker | None = None,
) -> Dict[str, Any]:
    execution_result_path = Path(execution_result_path)
    job_dir = Path(job_dir)
    execution = load_json(execution_result_path)
    input_pdf = as_path(execution.get("input_pdf"))
    output_pdf = as_path(execution.get("output_pdf"))
    normal_final_pdf = Path(normal_final_pdf) if normal_final_pdf else None
    attempt_dir = execution_result_path.parent

    output_exists = bool(output_pdf and output_pdf.exists() and output_pdf.is_file())
    output_size = output_pdf.stat().st_size if output_exists and output_pdf else 0
    input_hash = sha256_file(input_pdf)
    output_hash = sha256_file(output_pdf)
    normal_hash = sha256_file(normal_final_pdf)
    header = basic_pdf_header_check(output_pdf)

    if output_exists and output_pdf:
        checker = qpdf_checker or default_qpdf_checker
        qpdf = checker(output_pdf, attempt_dir, timeout_seconds)
        qpdf.setdefault("performed", False)
        qpdf.setdefault("result", "SKIPPED")
        qpdf.setdefault("stdout_path", str(attempt_dir / "qpdf_check_stdout.txt"))
        qpdf.setdefault("stderr_path", str(attempt_dir / "qpdf_check_stderr.txt"))
        qpdf.setdefault("exit_code", None)
    else:
        qpdf = {
            "performed": False,
            "result": "SKIPPED",
            "stdout_path": str(attempt_dir / "qpdf_check_stdout.txt"),
            "stderr_path": str(attempt_dir / "qpdf_check_stderr.txt"),
            "exit_code": None,
            "reason": "missing_output",
        }

    input_output_equal = bool(input_hash and output_hash and input_hash == output_hash) if output_hash else None
    normal_output_equal = bool(normal_hash and output_hash and normal_hash == output_hash) if output_hash else None
    classification = classify_output(
        execution_result=str(execution.get("result") or ""),
        output_exists=output_exists,
        output_size_bytes=output_size,
        header_result=str(header.get("result") or "FAIL"),
        qpdf_result=str(qpdf.get("result") or "SKIPPED"),
        input_output_hash_equal=input_output_equal,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "execution_result_path": str(execution_result_path),
        "attempt_id": execution.get("attempt_id"),
        "rule_id": execution.get("rule_id"),
        "candidate_id": execution.get("candidate_id"),
        "strategy_id": execution.get("strategy_id"),
        "input_pdf": str(input_pdf) if input_pdf else None,
        "input_pdf_sha256": input_hash,
        "learned_output_pdf": str(output_pdf) if output_pdf else None,
        "learned_output_pdf_sha256": output_hash,
        "normal_final_pdf": str(normal_final_pdf) if normal_final_pdf else None,
        "normal_final_pdf_sha256": normal_hash,
        "output_exists": output_exists,
        "output_size_bytes": output_size,
        "input_output_hash_equal": input_output_equal,
        "normal_output_hash_equal": normal_output_equal,
        "qpdf_check": qpdf,
        "basic_pdf_header_check": header,
        "classification": classification,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }


def summarize_comparisons(comparisons: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    summary = {name: 0 for name in CLASSIFICATIONS}
    for item in comparisons:
        classification = str(item.get("classification") or "needs_deeper_validation")
        if classification not in summary:
            summary[classification] = 0
        summary[classification] += 1
    return summary


def _error_comparison(summary: Dict[str, Any], result_path: Optional[Path], classification: str, reason: str, error: Optional[str] = None) -> Dict[str, Any]:
    item = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "execution_result_path": str(result_path) if result_path else None,
        "attempt_id": summary.get("attempt_id"),
        "rule_id": summary.get("rule_id"),
        "candidate_id": summary.get("candidate_id"),
        "strategy_id": summary.get("strategy_id"),
        "output_exists": False,
        "output_size_bytes": 0,
        "qpdf_check": {"performed": False, "result": "SKIPPED", "stdout_path": None, "stderr_path": None, "exit_code": None, "reason": reason},
        "basic_pdf_header_check": {"performed": False, "result": "FAIL"},
        "classification": classification,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "production_repair_replacement_performed": False,
    }
    if error:
        item["comparison_error"] = error
    return item


def write_learned_strategy_output_comparisons(
    *,
    execution_summaries: Iterable[Dict[str, Any]],
    job_dir: Path,
    audit_dir: Path,
    normal_final_pdf: Path | None = None,
    timeout_seconds: int = 30,
    qpdf_checker: QpdfChecker | None = None,
) -> Dict[str, Any]:
    audit_dir = Path(audit_dir)
    job_dir = Path(job_dir)
    artifact_path = audit_dir / ARTIFACT_NAME
    comparisons: List[Dict[str, Any]] = []

    for summary in execution_summaries or []:
        result_path = as_path(summary.get("execution_result_path"))
        if not result_path:
            comparisons.append(_error_comparison(summary, None, "execution_failed", "missing_execution_result_path", "missing_execution_result_path"))
            continue
        try:
            comparisons.append(compare_learned_execution_output(
                result_path,
                job_dir=job_dir,
                normal_final_pdf=normal_final_pdf,
                timeout_seconds=timeout_seconds,
                qpdf_checker=qpdf_checker,
            ))
        except Exception as exc:
            comparisons.append(_error_comparison(summary, result_path, "needs_deeper_validation", "comparison_exception", f"{type(exc).__name__}: {exc}"))

    payload = {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": "learned_execution_output_comparison",
        "enabled": True,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "summary": summarize_comparisons(comparisons),
        "policy": no_adoption_policy(),
        "artifact_path": str(artifact_path),
    }
    write_json_atomic(artifact_path, payload)
    return payload
