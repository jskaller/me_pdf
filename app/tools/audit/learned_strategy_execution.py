#!/usr/bin/env python3
"""
learned_strategy_execution.py

Patch 12B isolated execution harness for already-discovered active learned
strategies. This module is intentionally not imported by the orchestrator and
never adopts final PDFs, mutates the rule map, or moves scripts into
app/tools/repair/*.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from tools.audit.learned_strategy_discovery import (
        APPROVED_STAGING_DIR,
        clean_str,
        is_relative_to,
        resolve_staged_path,
        sha256_file,
        static_check_script,
    )
except Exception:  # pragma: no cover - direct script fallback
    from learned_strategy_discovery import (  # type: ignore
        APPROVED_STAGING_DIR,
        clean_str,
        is_relative_to,
        resolve_staged_path,
        sha256_file,
        static_check_script,
    )

SCHEMA_VERSION = "learned-strategy-execution-harness.v1"
ARTIFACT_NAME = "execution_result.json"
RECORD_TYPE = "learned_strategy_execution"
RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_BLOCKED = "BLOCKED"


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


def safe_attempt_id(value: Optional[str]) -> str:
    raw = clean_str(value) if value else ""
    if not raw:
        raw = "learned-exec-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    chars = []
    for ch in raw:
        chars.append(ch if ch.isalnum() or ch in {"-", "_", "."} else "-")
    cleaned = "".join(chars).strip("-_.")
    return cleaned or "learned-exec"


def ensure_text_sidecars(stdout_path: Path, stderr_path: Path, stdout: str = "", stderr: str = "") -> None:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")


def new_execution_log(job_dir: Path) -> Dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": "execution-log.v2",
        "schema": "montefiore.execution_log",
        "version": "1.0.0",
        "artifact": "execution_log",
        "created_at": now,
        "updated_at": now,
        "job_dir": str(job_dir),
        "run_id": None,
        "records": [],
        "repair_steps": [],
    }


def append_execution_log_record(job_dir: Path, record: Dict[str, Any]) -> Path:
    log_path = job_dir / "audit" / "execution_log.json"
    if log_path.exists():
        try:
            log = load_json(log_path)
        except Exception:
            log = new_execution_log(job_dir)
    else:
        log = new_execution_log(job_dir)
    log.setdefault("records", [])
    log.setdefault("repair_steps", [])
    log["updated_at"] = utc_now_iso()
    if not record.get("run_id"):
        record["run_id"] = log.get("run_id")
    log["records"].append(record)
    write_json_atomic(log_path, log)
    return log_path


def selected_discovered_strategy(discovery: Dict[str, Any], candidate_id: str) -> Optional[Dict[str, Any]]:
    for strategy in discovery.get("discovered_strategies", []) or []:
        if isinstance(strategy, dict) and clean_str(strategy.get("candidate_id")) == candidate_id:
            return strategy
    return None


def result_template(
    discovered_strategy: Dict[str, Any],
    *,
    input_pdf: Path,
    job_dir: Path,
    repo_root: Path,
    attempt_id: str,
    dry_run: bool,
) -> Dict[str, Any]:
    attempt_dir = job_dir / "audit" / "learned_strategy_execution" / attempt_id
    stdout_path = attempt_dir / "stdout.txt"
    stderr_path = attempt_dir / "stderr.txt"
    output_pdf = attempt_dir / "output.pdf"
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": "dry_run" if dry_run else "execute",
        "job_dir": str(job_dir),
        "attempt_id": attempt_id,
        "rule_id": clean_str(discovered_strategy.get("rule_id")),
        "candidate_id": clean_str(discovered_strategy.get("candidate_id")),
        "strategy_id": clean_str(discovered_strategy.get("strategy_id")),
        "staged_script_path": clean_str(discovered_strategy.get("staged_script_path")),
        "staged_script_sha256": clean_str(discovered_strategy.get("staged_script_sha256")).lower(),
        "input_pdf": str(input_pdf),
        "input_pdf_sha256": sha256_file(input_pdf),
        "output_pdf": str(output_pdf),
        "output_pdf_sha256": None,
        "attempt_dir": str(attempt_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_sha256": None,
        "stderr_sha256": None,
        "exit_code": None,
        "duration_ms": 0,
        "result": RESULT_BLOCKED,
        "execution_blockers": [],
        "static_checks": {"passed": False, "reasons": [], "checks": []},
        "hash_verified": False,
        "path_verified": False,
        "execution_performed": False,
        "final_pdf_adoption_performed": False,
        "orchestrator_integration_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "validation_performed": False,
        "validation_artifacts": {},
        "repo_root": str(repo_root),
    }


def check_discovered_strategy(
    discovered_strategy: Dict[str, Any],
    *,
    input_pdf: Path,
    job_dir: Path,
    repo_root: Path,
    attempt_id: str,
    dry_run: bool,
) -> Tuple[Dict[str, Any], Optional[Path]]:
    result = result_template(
        discovered_strategy,
        input_pdf=input_pdf,
        job_dir=job_dir,
        repo_root=repo_root,
        attempt_id=attempt_id,
        dry_run=dry_run,
    )
    blockers: List[str] = []

    if discovered_strategy.get("runtime_eligible") is not True:
        blockers.append("not_runtime_eligible")
    if discovered_strategy.get("production_active") is not True:
        blockers.append("not_production_active")
    if clean_str(discovered_strategy.get("activation_status")) != "active":
        blockers.append("activation_status_not_active")
    if clean_str(discovered_strategy.get("source")) != "learned_strategy_staged":
        blockers.append("source_not_learned_strategy_staged")

    raw_script_path = clean_str(discovered_strategy.get("staged_script_path"))
    staged_script_path, path_reasons = resolve_staged_path(raw_script_path, repo_root)
    blockers.extend(path_reasons)
    if staged_script_path is None:
        blockers.append("missing_staged_script_path")
    elif not staged_script_path.exists() or not staged_script_path.is_file():
        blockers.append("staged_script_missing")

    approved_root = repo_root / APPROVED_STAGING_DIR
    if staged_script_path is not None and is_relative_to(staged_script_path, approved_root):
        result["path_verified"] = True
    else:
        result["path_verified"] = False

    expected_sha = clean_str(discovered_strategy.get("staged_script_sha256")).lower()
    actual_sha = sha256_file(staged_script_path) if staged_script_path else None
    if not expected_sha:
        blockers.append("missing_staged_script_sha256")
    elif actual_sha != expected_sha:
        blockers.append("staged_script_hash_mismatch")
    else:
        result["hash_verified"] = True

    static_checks = static_check_script(staged_script_path)
    result["static_checks"] = static_checks
    if not static_checks.get("passed"):
        blockers.append("static_checks_failed")
        blockers.extend([str(r) for r in static_checks.get("reasons", []) or []])

    if not input_pdf.exists() or not input_pdf.is_file():
        blockers.append("input_pdf_missing")
    else:
        result["input_pdf_sha256"] = sha256_file(input_pdf)

    attempt_dir = Path(result["attempt_dir"])
    output_pdf = Path(result["output_pdf"])
    if not is_relative_to(output_pdf, attempt_dir):
        blockers.append("output_pdf_not_under_attempt_dir")

    result["execution_blockers"] = sorted(set(blockers))
    if blockers:
        result["result"] = RESULT_BLOCKED
    elif dry_run:
        result["result"] = RESULT_PASS
    return result, staged_script_path


def make_log_record(result: Dict[str, Any], *, started_at: str, finished_at: str, script_path: Optional[Path]) -> Dict[str, Any]:
    return {
        "schema_version": "execution-log.v2",
        "record_type": RECORD_TYPE,
        "attempt_id": result.get("attempt_id"),
        "run_id": result.get("run_id"),
        "rule_id": result.get("rule_id"),
        "candidate_id": result.get("candidate_id"),
        "strategy_id": result.get("strategy_id"),
        "script_path": str(script_path) if script_path else result.get("staged_script_path"),
        "script_sha256": result.get("staged_script_sha256"),
        "input_pdf": result.get("input_pdf"),
        "input_pdf_sha256": result.get("input_pdf_sha256"),
        "output_pdf": result.get("output_pdf"),
        "output_pdf_sha256": result.get("output_pdf_sha256"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": result.get("duration_ms"),
        "exit_code": result.get("exit_code"),
        "stdout_path": result.get("stdout_path"),
        "stderr_path": result.get("stderr_path"),
        "stdout_sha256": result.get("stdout_sha256"),
        "stderr_sha256": result.get("stderr_sha256"),
        "result": result.get("result"),
        "execution_blockers": result.get("execution_blockers") or [],
        "static_checks": result.get("static_checks") or {},
        "hash_verified": result.get("hash_verified"),
        "path_verified": result.get("path_verified"),
        "execution_performed": result.get("execution_performed"),
        "validation_performed": result.get("validation_performed"),
        "validation_artifacts": result.get("validation_artifacts") or {},
        "final_pdf_adoption_performed": False,
        "orchestrator_integration_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
    }


def persist_result_and_log(result: Dict[str, Any], *, started_at: str, finished_at: str, script_path: Optional[Path]) -> Dict[str, Any]:
    attempt_dir = Path(result["attempt_dir"])
    write_json_atomic(attempt_dir / ARTIFACT_NAME, result)
    append_execution_log_record(Path(result["job_dir"]), make_log_record(result, started_at=started_at, finished_at=finished_at, script_path=script_path))
    return result


def execute_discovered_learned_strategy(
    discovered_strategy: Dict[str, Any],
    input_pdf: Path,
    job_dir: Path,
    repo_root: Path | None = None,
    attempt_id: str | None = None,
    timeout_seconds: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Validate and optionally execute one discovered active learned strategy.

    Execution is isolated to JOB/audit/learned_strategy_execution/<attempt_id>/.
    The only output PDF considered by the harness is the controlled output path
    passed as argv[2]. The function never adopts the output as a final PDF.
    """
    input_pdf = Path(input_pdf)
    job_dir = Path(job_dir)
    repo_root = Path(repo_root) if repo_root else Path.cwd()
    attempt_id = safe_attempt_id(attempt_id)
    started_at = utc_now_iso()
    start = time.monotonic()

    result, staged_script_path = check_discovered_strategy(
        discovered_strategy,
        input_pdf=input_pdf,
        job_dir=job_dir,
        repo_root=repo_root,
        attempt_id=attempt_id,
        dry_run=dry_run,
    )
    attempt_dir = Path(result["attempt_dir"])
    stdout_path = Path(result["stdout_path"])
    stderr_path = Path(result["stderr_path"])
    attempt_dir.mkdir(parents=True, exist_ok=True)

    if result["execution_blockers"] or dry_run:
        if not dry_run:
            ensure_text_sidecars(stdout_path, stderr_path)
            result["stdout_sha256"] = sha256_file(stdout_path)
            result["stderr_sha256"] = sha256_file(stderr_path)
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        finished_at = utc_now_iso()
        return persist_result_and_log(result, started_at=started_at, finished_at=finished_at, script_path=staged_script_path)

    controlled_input = attempt_dir / "input.pdf"
    output_pdf = attempt_dir / "output.pdf"
    shutil.copyfile(input_pdf, controlled_input)
    result["input_pdf"] = str(controlled_input)
    result["input_pdf_sha256"] = sha256_file(controlled_input)
    argv = [sys.executable, str(staged_script_path), str(controlled_input), str(output_pdf)]

    try:
        proc = subprocess.run(
            argv,
            cwd=str(attempt_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={"PYTHONPATH": str(repo_root / "app")},
        )
        exit_code = proc.returncode
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
        result["result"] = RESULT_PASS if exit_code == 0 and output_pdf.exists() else RESULT_FAIL
        if exit_code == 0 and not output_pdf.exists():
            result["execution_blockers"] = ["script_completed_without_output_pdf"]
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout_text = exc.stdout or ""
        stderr_text = exc.stderr or ""
        if isinstance(stdout_text, bytes):
            stdout_text = stdout_text.decode("utf-8", errors="replace")
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode("utf-8", errors="replace")
        stderr_text = (stderr_text + "\n" if stderr_text else "") + f"timeout_after_seconds={timeout_seconds}"
        result["result"] = RESULT_FAIL
        result["execution_blockers"] = ["script_timeout"]

    ensure_text_sidecars(stdout_path, stderr_path, stdout_text, stderr_text)
    result["exit_code"] = exit_code
    result["execution_performed"] = True
    result["output_pdf_sha256"] = sha256_file(output_pdf)
    result["stdout_sha256"] = sha256_file(stdout_path)
    result["stderr_sha256"] = sha256_file(stderr_path)
    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    finished_at = utc_now_iso()
    return persist_result_and_log(result, started_at=started_at, finished_at=finished_at, script_path=staged_script_path)


def load_selected_strategy(discovery_json: Path, candidate_id: str) -> Dict[str, Any]:
    discovery = load_json(discovery_json)
    strategy = selected_discovered_strategy(discovery, candidate_id)
    if strategy is None:
        return {
            "rule_id": "",
            "candidate_id": candidate_id,
            "strategy_id": "",
            "source": "",
            "production_active": False,
            "activation_status": "missing",
            "runtime_eligible": False,
            "staged_script_path": "",
            "staged_script_sha256": "",
            "selection_blocker": "candidate_id_not_found_in_discovery_json",
        }
    return strategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one discovered active learned strategy in an isolated harness.")
    parser.add_argument("--discovery-json", required=True, help="Path to learned_strategy_discovery.json")
    parser.add_argument("--candidate-id", required=True, help="Candidate ID to execute from discovered_strategies")
    parser.add_argument("--input-pdf", required=True, help="Caller-controlled input PDF path")
    parser.add_argument("--job-dir", required=True, help="Job directory that owns audit artifacts")
    parser.add_argument("--repo-root", default=None, help="Repository root; defaults to current working directory")
    parser.add_argument("--attempt-id", default=None, help="Optional deterministic attempt ID")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Subprocess timeout")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate only; do not execute")
    mode.add_argument("--execute", action="store_true", help="Run the selected active strategy")
    parser.add_argument("--allow-fail-exit-zero", action="store_true", help="Return 0 even when result is BLOCKED or FAIL")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    strategy = load_selected_strategy(Path(args.discovery_json), args.candidate_id)
    result = execute_discovered_learned_strategy(
        strategy,
        input_pdf=Path(args.input_pdf),
        job_dir=Path(args.job_dir),
        repo_root=Path(args.repo_root) if args.repo_root else Path.cwd(),
        attempt_id=args.attempt_id,
        timeout_seconds=args.timeout_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=json_default))
    if args.allow_fail_exit_zero:
        return 0
    return 0 if result.get("result") == RESULT_PASS else 1


if __name__ == "__main__":
    sys.exit(main())
