#!/usr/bin/env python3
"""
self_extension_executor.py

Residual self-extension candidate executor for PDF/UA remediation.

Patch 1 scope:
- residual strategy gaps only;
- no adoption or rule-map mutation;
- no remediate.py hook;
- generated candidates stay quarantined under tools/repair/generated/;
- candidate execution uses a job-scoped attempt directory and a strict
  repair-script contract;
- validation success is anchored to the residual failure set at gap entry.

This module is intentionally import-safe: it does not import remediate.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from tools.orchestrate.self_extension import (
        HermesGatewayClient,
        SelfExtensionConfig,
        SelfExtensionThrottle,
        adopted_generated_filename,
        canonical_rule_slug,
        generated_candidate_filename,
    )
except ModuleNotFoundError:
    # Permit direct execution as python3 tools/orchestrate/self_extension_executor.py
    # from /app without requiring callers to set PYTHONPATH explicitly.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.orchestrate.self_extension import (  # type: ignore
        HermesGatewayClient,
        SelfExtensionConfig,
        SelfExtensionThrottle,
        adopted_generated_filename,
        canonical_rule_slug,
        generated_candidate_filename,
    )


PASS_CODES = {
    "PASS",
    "FIXED",
    "ALREADY_CORRECT",
    "PASS_WITH_MIXED_PAGES",
    "PASS_WITH_ONLY_NATIVE_TEXT",
    "SKIPPED",
    "OK",
    "PLAN_READY",
    "NO_FAILURES",
    "NEEDS_REVIEW",
}

DEFAULT_REMEDIATION_PYTHON = os.environ.get("REMEDIATION_PYTHON", "/usr/bin/python3")
DEFAULT_APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
DEFAULT_VERAPDF_BIN = Path("/opt/verapdf-greenfield/verapdf")
DEFAULT_PROFILES = Path(
    os.environ.get(
        "VERAPDF_PROFILE_PATH",
        os.environ.get(
            "VERAPDF_PROFILE_SOURCE",
            "/opt/veraPDF-validation-profiles-integration",
        ),
    )
)


class SelfExtensionExecutorError(RuntimeError):
    """Base exception for residual self-extension executor failures."""


class CandidateRejected(SelfExtensionExecutorError):
    """Raised when a generated candidate violates the execution contract."""


class GenerationRejected(CandidateRejected):
    """Raised when gateway generation fails with diagnostic context."""

    def __init__(self, message: str, failure_record: Dict[str, Any], raw_content: str = ""):
        super().__init__(message)
        self.failure_record = failure_record
        self.raw_content = raw_content


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def is_pass(result: Any) -> bool:
    return str(result or "").upper() in PASS_CODES


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def failure_counts(failures: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for failure in failures or []:
        if not isinstance(failure, dict):
            continue
        rule_id = _clean_text(failure.get("rule_id"))
        if not rule_id:
            continue
        try:
            count = int(failure.get("failures") or failure.get("failed_checks") or 0)
        except Exception:
            count = 0
        counts[rule_id] = counts.get(rule_id, 0) + count
    return counts


def evaluate_residual_success(
    *,
    target_rule_id: str,
    gap_entry_failures: Iterable[Dict[str, Any]],
    candidate_post_failures: Iterable[Dict[str, Any]],
    gate_results: Dict[str, str],
    execution_contract: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a generated candidate against the Patch 1 success predicate.

    The "new failure" comparison anchor is the residual set at the exact moment
    the self-extension gap is entered, not the pre-repair baseline.
    """

    target = _clean_text(target_rule_id)
    before = failure_counts(gap_entry_failures)
    after = failure_counts(candidate_post_failures)

    target_before = before.get(target, 0)
    target_after = after.get(target, 0)
    target_decreased = target_before > 0 and target_after < target_before

    new_rule_ids = sorted(set(after) - set(before))
    worsened_existing_rules = sorted(
        rule_id
        for rule_id, after_count in after.items()
        if rule_id != target and after_count > before.get(rule_id, 0)
    )

    required_gates = ["preservation", "form_fields", "render_compare"]
    failed_gates = [
        gate for gate in required_gates
        if not is_pass(gate_results.get(gate, "FAIL"))
    ]

    contract_pass = bool(execution_contract.get("result") == "PASS")
    result = (
        target_decreased
        and not new_rule_ids
        and not worsened_existing_rules
        and not failed_gates
        and contract_pass
    )

    return {
        "result": "PASS" if result else "FAIL",
        "target_rule_id": target,
        "comparison_anchor": "gap_entry_residual_failures",
        "gap_entry_rule_counts": before,
        "candidate_post_rule_counts": after,
        "target_rule_count_before": target_before,
        "target_rule_count_after": target_after,
        "target_rule_strictly_decreased": target_decreased,
        "new_rule_ids_relative_to_gap_entry": new_rule_ids,
        "worsened_existing_rules_relative_to_gap_entry": worsened_existing_rules,
        "required_gates": required_gates,
        "failed_gates": failed_gates,
        "execution_contract_result": execution_contract.get("result", "UNKNOWN"),
    }


def build_residual_script_generation_request(
    *,
    strategy_request: Dict[str, Any],
    target_rule_id: str,
    attempt: int,
    candidate_relative_path: str,
    prior_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the script-generation request schema for Patch 1.

    This is intentionally distinct from remediate.py's strategy-design schema.
    The response must include complete executable Python source in script_source.
    """

    residual_failures = strategy_request.get("residual_failures", [])
    target_failure = None
    for failure in residual_failures:
        if isinstance(failure, dict) and failure.get("rule_id") == target_rule_id:
            target_failure = failure
            break

    return {
        "request_type": "pdfua_residual_repair_script_generation",
        "patch_scope": "residual_only_no_adoption",
        "target_rule_id": target_rule_id,
        "target_failure": target_failure,
        "attempt": int(attempt),
        "candidate_relative_path": candidate_relative_path,
        "script_contract": {
            "cli": "<input.pdf> <output.pdf> [--out results.json]",
            "stdout": "one JSON object with result, strategy, and reason",
            "success_exit": "exit 0 only when output PDF was written successfully",
            "input_immutability": "must never mutate input PDF",
            "document_specific_values": "must not hardcode object IDs, page counts, font names, or current-file-only constants",
        },
        "validation_success_predicate": {
            "comparison_anchor": "gap_entry_residual_failures",
            "target_rule": "candidate_post_count(target) < gap_entry_count(target)",
            "no_new_rules": "candidate_post_rule_ids subset of gap_entry_rule_ids",
            "no_worsened_existing_rules": "for every non-target rule, candidate_post_count <= gap_entry_count",
            "required_gates": ["preservation", "form_fields", "render_compare"],
            "contract": "script compiles, exits in timeout, leaves input hash unchanged, writes output PDF, emits parseable JSON stdout",
        },
        "evidence": {
            "ticket": strategy_request.get("ticket"),
            "job_name": strategy_request.get("job_name"),
            "doc_tags": strategy_request.get("doc_tags", []),
            "current_pdf": strategy_request.get("current_pdf"),
            "source_pdf": strategy_request.get("source_pdf"),
            "residual_failures": residual_failures,
            "residual_repair_plan": strategy_request.get("residual_repair_plan"),
            "validator_artifacts": strategy_request.get("validator_artifacts"),
            "validator_rule_xml_snippets": strategy_request.get("validator_rule_xml_snippets", []),
            "rule_map_context": strategy_request.get("rule_map_context", {}),
            "existing_repair_scripts": strategy_request.get("existing_repair_scripts", []),
            "strategy_attempts": strategy_request.get("strategy_attempts", {}),
        },
        "prior_feedback": prior_feedback or {},
        "required_response_schema": {
            "result": "SCRIPT_SOURCE | NEEDS_MORE_EVIDENCE | NOT_AUTOMATABLE",
            "rule_id": target_rule_id,
            "strategy": "stable_snake_case_strategy_name",
            "script_source": "complete Python source code as a single string",
            "expected_args_pattern": "<input.pdf> <output.pdf> [--out results.json]",
            "notes": "brief implementation notes",
            "risks": [],
        },
    }


def build_generation_prompt(generation_request: Dict[str, Any]) -> str:
    return (
        "You are writing a deterministic PDF/UA repair script for the "
        "Montefiore remediation pipeline. Return strict JSON only.\n\n"
        "Do not return a plan. Do not return markdown. Do not claim success. "
        "Return complete executable Python source in script_source. The script "
        "must follow the provided script_contract exactly.\n\n"
        "Use only dependencies already present in the repository/runtime. Prefer "
        "pikepdf and PyMuPDF where appropriate. The script must be generalized, "
        "not hardcoded to the current document.\n\n"
        f"GENERATION_REQUEST:\n{json.dumps(generation_request, indent=2)}\n"
    )


def _strip_json_fence(content: str) -> str:
    content = (content or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1].strip()
            if content.startswith("json"):
                content = content[4:].strip()
    return content


def parse_generation_response(raw_content: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(_strip_json_fence(raw_content))
    except Exception as exc:
        raise CandidateRejected(f"generation response was not strict JSON: {type(exc).__name__}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CandidateRejected("generation response JSON was not an object")
    if parsed.get("result") != "SCRIPT_SOURCE":
        raise CandidateRejected(f"generation did not return SCRIPT_SOURCE: {parsed.get('result')}")
    script_source = parsed.get("script_source")
    if not isinstance(script_source, str) or not script_source.strip():
        raise CandidateRejected("generation response missing non-empty script_source")
    return parsed


def build_generation_failure_record(
    *,
    generation_request: Dict[str, Any],
    prompt: str,
    elapsed_seconds: float,
    reason: str,
    error_type: str,
    response: Optional[Dict[str, Any]] = None,
    raw_content: str = "",
    raw_content_path: Optional[str] = None,
) -> Dict[str, Any]:
    response = response or {}
    raw_content = raw_content or ""
    record: Dict[str, Any] = {
        "result": "FAIL",
        "phase": "generation",
        "reason": reason,
        "error_type": error_type,
        "target_rule_id": generation_request.get("target_rule_id"),
        "attempt": generation_request.get("attempt"),
        "candidate_relative_path": generation_request.get("candidate_relative_path"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "reported_usage": response.get("usage", {}),
        "local_prompt_chars": len(prompt),
        "request_packet_chars": len(json.dumps(generation_request)),
        "raw_content_chars": len(raw_content),
        "raw_content_prefix": raw_content[:4000],
        "raw_content_truncated": len(raw_content) > 4000,
        "response_model": response.get("response_model"),
        "gateway_model": response.get("gateway_model"),
        "gateway_base_url": response.get("gateway_base_url"),
    }
    if raw_content_path:
        record["raw_content_path"] = raw_content_path
    return record


def generate_candidate_source(
    *,
    generation_request: Dict[str, Any],
    config: Optional[SelfExtensionConfig] = None,
    job_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    cfg = config or SelfExtensionConfig.from_env()
    throttle = SelfExtensionThrottle(cfg, job_dir=job_dir)
    client = HermesGatewayClient(cfg, throttle=throttle)
    prompt = build_generation_prompt(generation_request)
    start = time.time()
    try:
        response = client.chat_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=cfg.max_tokens,
            timeout_seconds=cfg.gateway_timeout_seconds,
            throttle=True,
        )
    except Exception as exc:
        elapsed = time.time() - start
        reason = f"gateway call failed: {type(exc).__name__}: {exc}"
        failure_record = build_generation_failure_record(
            generation_request=generation_request,
            prompt=prompt,
            elapsed_seconds=elapsed,
            reason=reason,
            error_type=type(exc).__name__,
        )
        raise GenerationRejected(reason, failure_record) from exc

    elapsed = time.time() - start
    raw_content = response.get("content", "")
    try:
        parsed = parse_generation_response(raw_content)
    except CandidateRejected as exc:
        failure_record = build_generation_failure_record(
            generation_request=generation_request,
            prompt=prompt,
            elapsed_seconds=elapsed,
            reason=str(exc),
            error_type=type(exc).__name__,
            response=response,
            raw_content=raw_content,
        )
        raise GenerationRejected(str(exc), failure_record, raw_content=raw_content) from exc

    parsed["_self_extension_gateway"] = {
        "elapsed_seconds": round(elapsed, 3),
        "reported_usage": response.get("usage", {}),
        "local_prompt_chars": len(prompt),
        "request_packet_chars": len(json.dumps(generation_request)),
        "script_source_chars": len(parsed.get("script_source") or ""),
        "response_model": response.get("response_model"),
        "gateway_model": response.get("gateway_model"),
        "gateway_base_url": response.get("gateway_base_url"),
    }
    return parsed


@dataclass(frozen=True)
class CandidatePaths:
    app_dir: Path
    job_dir: Path
    target_rule_id: str
    attempt: int
    generated_dir: Path = field(init=False)
    attempt_dir: Path = field(init=False)
    candidate_script: Path = field(init=False)
    candidate_relative_path: str = field(init=False)
    input_pdf: Path = field(init=False)
    output_pdf: Path = field(init=False)
    stdout_json: Path = field(init=False)
    validation_dir: Path = field(init=False)
    qa_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        generated_dir = self.app_dir / "tools" / "repair" / "generated"
        attempt_dir = (
            self.job_dir
            / "self_extension"
            / canonical_rule_slug(self.target_rule_id)
            / f"attempt_{int(self.attempt):02d}"
        )
        object.__setattr__(self, "generated_dir", generated_dir)
        object.__setattr__(self, "attempt_dir", attempt_dir)
        candidate_name = generated_candidate_filename(self.target_rule_id, self.attempt)
        object.__setattr__(self, "candidate_script", generated_dir / candidate_name)
        object.__setattr__(
            self,
            "candidate_relative_path",
            str(Path("tools") / "repair" / "generated" / candidate_name),
        )
        object.__setattr__(self, "input_pdf", attempt_dir / "input.pdf")
        object.__setattr__(self, "output_pdf", attempt_dir / "output.pdf")
        object.__setattr__(self, "stdout_json", attempt_dir / "candidate_stdout.json")
        object.__setattr__(self, "validation_dir", attempt_dir / "validation")
        object.__setattr__(self, "qa_dir", attempt_dir / "qa")


def prepare_candidate_paths(app_dir: Path, job_dir: Path, target_rule_id: str, attempt: int) -> CandidatePaths:
    paths = CandidatePaths(Path(app_dir), Path(job_dir), target_rule_id, attempt)
    paths.generated_dir.mkdir(parents=True, exist_ok=True)
    paths.attempt_dir.mkdir(parents=True, exist_ok=True)
    paths.validation_dir.mkdir(parents=True, exist_ok=True)
    paths.qa_dir.mkdir(parents=True, exist_ok=True)
    return paths


def write_candidate_script(paths: CandidatePaths, script_source: str) -> Dict[str, Any]:
    paths.generated_dir.mkdir(parents=True, exist_ok=True)
    paths.candidate_script.write_text(script_source)
    try:
        py_compile.compile(str(paths.candidate_script), doraise=True)
    except py_compile.PyCompileError as exc:
        return {
            "result": "FAIL",
            "reason": "py_compile_failed",
            "error": str(exc),
            "candidate_script": str(paths.candidate_script),
        }
    return {
        "result": "PASS",
        "candidate_script": str(paths.candidate_script),
        "candidate_relative_path": paths.candidate_relative_path,
        "script_sha256": hashlib.sha256(script_source.encode("utf-8")).hexdigest(),
    }


def _parse_stdout_json(stdout: str) -> Tuple[Optional[Dict[str, Any]], str]:
    text = (stdout or "").strip()
    if not text:
        return None, "stdout was empty"
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, ""
        return None, "stdout JSON was not an object"
    except Exception as exc:
        return None, f"stdout was not parseable JSON: {type(exc).__name__}: {exc}"


def run_candidate_script(
    *,
    paths: CandidatePaths,
    current_pdf: Path,
    remediation_python: str = DEFAULT_REMEDIATION_PYTHON,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Run a generated candidate against a job-scoped copy of current_pdf."""

    timeout = int(timeout_seconds or os.environ.get("HERMES_SELF_EXTENSION_EXECUTION_TIMEOUT_SECONDS", "120"))
    paths.attempt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_pdf, paths.input_pdf)
    input_hash_before = sha256_file(paths.input_pdf)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(paths.attempt_dir),
            "TMPDIR": str(paths.attempt_dir / "tmp"),
            "PYTHONPATH": str(paths.app_dir),
        }
    )
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    cmd = [
        str(remediation_python),
        str(paths.candidate_script),
        str(paths.input_pdf),
        str(paths.output_pdf),
    ]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(paths.attempt_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired as exc:
        return {
            "result": "FAIL",
            "reason": "candidate_timeout",
            "timeout_seconds": timeout,
            "stdout": (exc.stdout or "")[:4000],
            "stderr": (exc.stderr or "")[:4000],
        }

    input_hash_after = sha256_file(paths.input_pdf) if paths.input_pdf.exists() else "MISSING"
    stdout_data, stdout_error = _parse_stdout_json(proc.stdout)
    if stdout_data is not None:
        _write_json_atomic(paths.stdout_json, stdout_data)

    checks = {
        "exit_code_zero": proc.returncode == 0,
        "stdout_json_object": stdout_data is not None,
        "input_hash_unchanged": input_hash_before == input_hash_after,
        "output_pdf_exists": paths.output_pdf.exists(),
        "output_pdf_nonempty": paths.output_pdf.exists() and paths.output_pdf.stat().st_size > 0,
    }
    result = "PASS" if all(checks.values()) else "FAIL"
    reasons = [name for name, ok in checks.items() if not ok]
    if stdout_error:
        reasons.append(stdout_error)

    return {
        "result": result,
        "reason": "; ".join(reasons) if reasons else "execution_contract_satisfied",
        "command": cmd,
        "elapsed_seconds": round(elapsed, 3),
        "exit_code": proc.returncode,
        "stdout": proc.stdout[:4000],
        "stderr": proc.stderr[:4000],
        "stdout_json": stdout_data,
        "stdout_json_path": str(paths.stdout_json) if stdout_data is not None else None,
        "input_pdf": str(paths.input_pdf),
        "output_pdf": str(paths.output_pdf),
        "input_sha256_before": input_hash_before,
        "input_sha256_after": input_hash_after,
        "checks": checks,
    }


def run_json_command(cmd: List[Any], label: str, timeout_seconds: int = 180) -> Tuple[int, str, str]:
    proc = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_failures_from_verapdf(
    *,
    app_dir: Path,
    validation_dir: Path,
    remediation_python: str,
) -> Tuple[List[Dict[str, Any]], Path, Dict[str, Any]]:
    failures_path = validation_dir / "candidate_failures_post.json"
    rc, out, err = run_json_command(
        [
            remediation_python,
            app_dir / "tools" / "audit" / "parse_verapdf_summary.py",
            validation_dir / "verapdf_candidate_pdfua1.xml",
            validation_dir / "verapdf_candidate_wcag.xml",
        ],
        "parse_candidate_failures",
    )
    try:
        parsed = json.loads(out)
    except Exception:
        parsed = {
            "result": "ERROR",
            "failures_by_rule": [],
            "error": (out + err)[:2000],
            "exit_code": rc,
        }
    _write_json_atomic(failures_path, parsed)
    return parsed.get("failures_by_rule", []), failures_path, parsed


def run_candidate_validation(
    *,
    paths: CandidatePaths,
    source_pdf: Path,
    reference_pdf: Path,
    verapdf_bin: Path = DEFAULT_VERAPDF_BIN,
    profiles: Path = DEFAULT_PROFILES,
    remediation_python: str = DEFAULT_REMEDIATION_PYTHON,
) -> Dict[str, Any]:
    """Run the real validator/gate scripts in an isolated validation dir."""

    gate_results: Dict[str, str] = {}
    artifacts: Dict[str, str] = {}

    run_json_command(
        [
            "bash",
            paths.app_dir / "tools" / "audit" / "run_verapdf_profiles.sh",
            verapdf_bin,
            profiles,
            paths.output_pdf,
            paths.validation_dir,
        ],
        "verapdf_candidate",
        timeout_seconds=300,
    )
    for src, dst in [
        (paths.validation_dir / "verapdf_pdfua_ua1.xml", paths.validation_dir / "verapdf_candidate_pdfua1.xml"),
        (paths.validation_dir / "verapdf_wcag_2_2_machine.xml", paths.validation_dir / "verapdf_candidate_wcag.xml"),
    ]:
        if src.exists():
            shutil.copy2(src, dst)
            artifacts[dst.name] = str(dst)

    candidate_failures, failures_path, parsed = parse_failures_from_verapdf(
        app_dir=paths.app_dir,
        validation_dir=paths.validation_dir,
        remediation_python=remediation_python,
    )
    artifacts["candidate_failures_post"] = str(failures_path)

    preservation_out = paths.validation_dir / "preservation_candidate.json"
    run_json_command(
        [
            remediation_python,
            paths.app_dir / "tools" / "qa" / "preservation_audit.py",
            reference_pdf,
            paths.output_pdf,
            "--out",
            preservation_out,
        ],
        "preservation_candidate",
    )
    preservation_data = _safe_load_dict(preservation_out)
    gate_results["preservation"] = _clean_text(preservation_data.get("result", "ERROR")) or "ERROR"
    artifacts["preservation"] = str(preservation_out)

    form_out = paths.validation_dir / "form_fields_candidate.json"
    run_json_command(
        [
            remediation_python,
            paths.app_dir / "tools" / "qa" / "form_field_preservation_audit.py",
            source_pdf,
            paths.output_pdf,
            "--out",
            form_out,
        ],
        "form_fields_candidate",
    )
    form_data = _safe_load_dict(form_out)
    gate_results["form_fields"] = _clean_text(form_data.get("result", "ERROR")) or "ERROR"
    artifacts["form_fields"] = str(form_out)

    render_out = paths.validation_dir / "render_compare_candidate.json"
    run_json_command(
        [
            remediation_python,
            paths.app_dir / "tools" / "qa" / "render_compare.py",
            reference_pdf,
            paths.output_pdf,
            paths.qa_dir,
            "--out",
            render_out,
        ],
        "render_compare_candidate",
        timeout_seconds=300,
    )
    render_data = _safe_load_dict(render_out)
    gate_results["render_compare"] = _clean_text(render_data.get("result", "ERROR")) or "ERROR"
    artifacts["render_compare"] = str(render_out)

    return {
        "result": "PASS" if all(is_pass(v) for v in gate_results.values()) else "FAIL",
        "gate_results": gate_results,
        "candidate_post_failures": candidate_failures,
        "candidate_failures_artifact": str(failures_path),
        "parse_result": parsed.get("result", "UNKNOWN"),
        "artifacts": artifacts,
    }


def _safe_load_dict(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {"result": "ERROR"}
    except Exception as exc:
        return {"result": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def execute_residual_candidate(
    *,
    app_dir: Path,
    job_dir: Path,
    strategy_request_path: Path,
    target_rule_id: str,
    attempt: int,
    current_pdf: Path,
    source_pdf: Path,
    reference_pdf: Path,
    script_source: str,
    remediation_python: str = DEFAULT_REMEDIATION_PYTHON,
    verapdf_bin: Path = DEFAULT_VERAPDF_BIN,
    profiles: Path = DEFAULT_PROFILES,
) -> Dict[str, Any]:
    """Write, execute, and validate one residual generated candidate."""

    strategy_request = _load_json(strategy_request_path)
    paths = prepare_candidate_paths(app_dir, job_dir, target_rule_id, attempt)
    write_result = write_candidate_script(paths, script_source)
    if write_result.get("result") != "PASS":
        result = {
            "result": "FAIL",
            "stage": "write_candidate",
            "write_result": write_result,
        }
        _write_json_atomic(paths.attempt_dir / "candidate_result.json", result)
        return result

    execution_contract = run_candidate_script(
        paths=paths,
        current_pdf=current_pdf,
        remediation_python=remediation_python,
    )
    if execution_contract.get("result") != "PASS":
        result = {
            "result": "FAIL",
            "stage": "execute_candidate",
            "candidate_relative_path": paths.candidate_relative_path,
            "execution_contract": execution_contract,
        }
        _write_json_atomic(paths.attempt_dir / "candidate_result.json", result)
        return result

    validation = run_candidate_validation(
        paths=paths,
        source_pdf=source_pdf,
        reference_pdf=reference_pdf,
        verapdf_bin=verapdf_bin,
        profiles=profiles,
        remediation_python=remediation_python,
    )
    predicate = evaluate_residual_success(
        target_rule_id=target_rule_id,
        gap_entry_failures=strategy_request.get("residual_failures", []),
        candidate_post_failures=validation.get("candidate_post_failures", []),
        gate_results=validation.get("gate_results", {}),
        execution_contract=execution_contract,
    )

    result = {
        "result": predicate.get("result", "FAIL"),
        "stage": "validated_candidate",
        "adoption_performed": False,
        "candidate_relative_path": paths.candidate_relative_path,
        "candidate_script": str(paths.candidate_script),
        "candidate_output_pdf": str(paths.output_pdf),
        "attempt_dir": str(paths.attempt_dir),
        "write_result": write_result,
        "execution_contract": execution_contract,
        "validation": validation,
        "success_predicate": predicate,
        "adopted_filename_if_later_promoted": adopted_generated_filename(target_rule_id),
    }
    _write_json_atomic(paths.attempt_dir / "candidate_result.json", result)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Residual self-extension candidate executor")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build-request", help="Build a script-generation request from a residual strategy request")
    build.add_argument("strategy_request")
    build.add_argument("--rule-id", required=True)
    build.add_argument("--attempt", type=int, default=1)
    build.add_argument("--job-dir", required=True)
    build.add_argument("--app-dir", default=str(DEFAULT_APP_DIR))
    build.add_argument("--out", required=True)

    gen = sub.add_parser("generate", help="Call Hermes gateway and write generation response JSON")
    gen.add_argument("generation_request")
    gen.add_argument("--job-dir", required=True)
    gen.add_argument("--out", required=True)

    exe = sub.add_parser("execute", help="Execute and validate a script_source JSON response")
    exe.add_argument("generation_response")
    exe.add_argument("--strategy-request", required=True)
    exe.add_argument("--rule-id", required=True)
    exe.add_argument("--attempt", type=int, default=1)
    exe.add_argument("--current-pdf", required=True)
    exe.add_argument("--source-pdf", required=True)
    exe.add_argument("--reference-pdf", required=True)
    exe.add_argument("--job-dir", required=True)
    exe.add_argument("--app-dir", default=str(DEFAULT_APP_DIR))
    exe.add_argument("--remediation-python", default=DEFAULT_REMEDIATION_PYTHON)
    exe.add_argument("--verapdf-bin", default=str(DEFAULT_VERAPDF_BIN))
    exe.add_argument("--profiles", default=str(DEFAULT_PROFILES))
    exe.add_argument("--out", required=True)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    ns = parser.parse_args(argv)

    if ns.command == "build-request":
        app_dir = Path(ns.app_dir)
        job_dir = Path(ns.job_dir)
        paths = prepare_candidate_paths(app_dir, job_dir, ns.rule_id, ns.attempt)
        strategy_request = _load_json(Path(ns.strategy_request))
        generation_request = build_residual_script_generation_request(
            strategy_request=strategy_request,
            target_rule_id=ns.rule_id,
            attempt=ns.attempt,
            candidate_relative_path=paths.candidate_relative_path,
        )
        _write_json_atomic(Path(ns.out), generation_request)
        print(json.dumps({"result": "PASS", "out": ns.out, "candidate_relative_path": paths.candidate_relative_path}, indent=2))
        return 0

    if ns.command == "generate":
        generation_request = _load_json(Path(ns.generation_request))
        try:
            response = generate_candidate_source(
                generation_request=generation_request,
                job_dir=Path(ns.job_dir),
            )
        except GenerationRejected as exc:
            failure = dict(exc.failure_record)
            raw_content = exc.raw_content or failure.get("raw_content_prefix") or ""
            if raw_content:
                raw_path = Path(ns.out).with_suffix(Path(ns.out).suffix + ".raw.txt")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(str(raw_content))
                failure["raw_content_path"] = str(raw_path)
            _write_json_atomic(Path(ns.out), failure)
            print(json.dumps({"result": "FAIL", "out": ns.out, "reason": str(exc)}, indent=2))
            return 2
        _write_json_atomic(Path(ns.out), response)
        print(json.dumps({"result": "PASS", "out": ns.out}, indent=2))
        return 0

    if ns.command == "execute":
        generation_response = _load_json(Path(ns.generation_response))
        script_source = generation_response.get("script_source")
        if not isinstance(script_source, str) or not script_source.strip():
            print(json.dumps({"result": "FAIL", "reason": "generation_response missing script_source"}, indent=2))
            return 2
        result = execute_residual_candidate(
            app_dir=Path(ns.app_dir),
            job_dir=Path(ns.job_dir),
            strategy_request_path=Path(ns.strategy_request),
            target_rule_id=ns.rule_id,
            attempt=ns.attempt,
            current_pdf=Path(ns.current_pdf),
            source_pdf=Path(ns.source_pdf),
            reference_pdf=Path(ns.reference_pdf),
            script_source=script_source,
            remediation_python=ns.remediation_python,
            verapdf_bin=Path(ns.verapdf_bin),
            profiles=Path(ns.profiles),
        )
        _write_json_atomic(Path(ns.out), result)
        print(json.dumps({"result": result.get("result", "UNKNOWN"), "out": ns.out}, indent=2))
        return 0 if result.get("result") == "PASS" else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
