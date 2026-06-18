#!/usr/bin/env python3
"""Isolated reviewed learned-strategy apply simulation.

Patch 24A simulates a future reviewed adoption apply transaction under an
isolated audit directory only:

    JOB/audit/learned_strategy_apply_simulation/

It never performs real adoption apply, never creates production backups, never
executes rollback against authoritative files, never mutates package/status
outputs, never mutates app/tools/repair, and never mutates the rule map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "learned-strategy-apply-simulation.v1"
MODE = "apply_simulation_only"
SIMULATION_DIR_NAME = "learned_strategy_apply_simulation"
SIMULATION_MANIFEST_NAME = "simulation_manifest.json"
SIMULATED_APPLY_REPORT_NAME = "simulated_apply_report.json"
SIMULATED_FINAL_NAME = "simulated_final.pdf"
SIMULATED_VALIDATION_REPORT_NAME = "simulated_validation_report.json"
SIMULATED_ROLLBACK_VERIFICATION_NAME = "simulated_rollback_verification.json"

EVIDENCE_HASH_ARTIFACT_NAME = "learned_strategy_evidence_hashes.json"
APPLY_DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run.json"
APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run_review.json"
SANDBOX_DIR_NAME = "learned_strategy_apply_sandbox"
SANDBOX_MANIFEST_NAME = "sandbox_manifest.json"
SANDBOX_BACKUP_MANIFEST_NAME = "backup_manifest.json"
SANDBOX_ROLLBACK_MANIFEST_NAME = "rollback_manifest.json"
SANDBOX_ROLLBACK_VERIFICATION_NAME = "rollback_verification.json"

ALLOWED_OUTCOMES = {
    "apply_simulation_recorded",
    "apply_simulation_incomplete",
    "apply_simulation_blocked",
}
FORBIDDEN_TERMINAL_STATES = {
    "approved",
    "adoptable",
    "production_ready",
    "ready_for_adoption",
    "adoption_unblocked",
    "apply_ready",
    "approved_for_apply",
    "frozen_for_apply",
    "apply_unblocked",
    "rollback_ready",
    "apply_performed",
    "rollback_performed",
    "production_backup_created",
    "production_rollback_performed",
    "final_pdf_adopted",
}
MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "apply_simulation_only": True,
    "simulated_apply_performed": True,
    "adoption_apply_performed": False,
    "production_backup_created": False,
    "production_rollback_performed": False,
    "rollback_execution_against_authoritative_files": False,
    "rollback_execution_performed": False,
    "candidate_is_adoptable": False,
    "candidate_approved": False,
    "candidate_production_ready": False,
    "candidate_apply_ready": False,
    "final_pdf_adoption_performed": False,
    "production_repair_replacement_performed": False,
    "verdict_softening_performed": False,
    "package_status_mutation_performed": False,
    "normal_final_pdf_remains_authoritative": True,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "future_apply_not_implemented": True,
}
SIMULATED_VALIDATION_FLAGS: Dict[str, Any] = {
    "validation_scope": "simulation_only",
    "validated_pdf_is_authoritative_final": False,
    "qpdf_checked": True,
    "hashes_verified": True,
    "package_status_mutation_performed": False,
    "verdict_softening_performed": False,
}
SIMULATED_ROLLBACK_FLAGS: Dict[str, Any] = {
    "rollback_verification_scope": "simulation_only",
    "rollback_execution_against_authoritative_files": False,
    "simulation_rollback_verified": True,
    "production_rollback_performed": False,
}
REQUIRED_FALSE_FLAGS = {
    "adoption_apply_performed",
    "rollback_execution_performed",
    "candidate_is_adoptable",
    "candidate_approved",
    "candidate_production_ready",
    "candidate_apply_ready",
    "final_pdf_adoption_performed",
    "production_repair_replacement_performed",
    "verdict_softening_performed",
    "package_status_mutation_performed",
    "rule_map_mutation_performed",
    "app_tools_repair_mutation_performed",
}
FORBIDDEN_STATE_KEYS = {
    "state",
    "status",
    "candidate_state",
    "candidate_status",
    "approval_state",
    "adoption_state",
    "readiness_state",
    "apply_decision",
    "apply_status",
    "apply_outcome",
    "result_state",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def simulation_dir(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SIMULATION_DIR_NAME


def simulation_manifest_path(job_dir: Path) -> Path:
    return simulation_dir(job_dir) / SIMULATION_MANIFEST_NAME


def simulated_apply_report_path(job_dir: Path) -> Path:
    return simulation_dir(job_dir) / SIMULATED_APPLY_REPORT_NAME


def simulated_final_path(job_dir: Path) -> Path:
    return simulation_dir(job_dir) / SIMULATED_FINAL_NAME


def simulated_validation_report_path(job_dir: Path) -> Path:
    return simulation_dir(job_dir) / SIMULATED_VALIDATION_REPORT_NAME


def simulated_rollback_verification_path(job_dir: Path) -> Path:
    return simulation_dir(job_dir) / SIMULATED_ROLLBACK_VERIFICATION_NAME


def sandbox_dir(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SANDBOX_DIR_NAME


def default_evidence_hashes_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / EVIDENCE_HASH_ARTIFACT_NAME


def default_apply_dry_run_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / APPLY_DRY_RUN_ARTIFACT_NAME


def default_apply_dry_run_review_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME


def default_sandbox_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / SANDBOX_MANIFEST_NAME


def default_sandbox_backup_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / SANDBOX_BACKUP_MANIFEST_NAME


def default_sandbox_rollback_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / SANDBOX_ROLLBACK_MANIFEST_NAME


def default_sandbox_rollback_verification_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / SANDBOX_ROLLBACK_VERIFICATION_NAME


def snapshot_path(path: Path) -> Dict[str, Any]:
    return {
        "exists": path.exists(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
    }


def snapshot_tree(root: Path) -> Dict[str, Dict[str, Any]]:
    root = Path(root)
    if not root.exists():
        return {str(root): {"exists": False, "sha256": None, "size_bytes": None}}
    if root.is_file():
        return {str(root): snapshot_path(root)}
    return {str(child): snapshot_path(child) for child in sorted(p for p in root.rglob("*") if p.is_file())}


def protected_targets(job_dir: Path, repo_root: Path) -> List[Path]:
    return [
        repo_root / "app" / "tools" / "audit" / "rule_repair_map.json",
        repo_root / "app" / "tools" / "repair",
        job_dir / "STATUS.json",
        job_dir / "deliverables" / "STATUS.json",
        job_dir / "output" / "STATUS.json",
        job_dir / "package" / "STATUS.json",
    ]


def snapshot_protected(job_dir: Path, repo_root: Path) -> Dict[str, Dict[str, Any]]:
    snap: Dict[str, Dict[str, Any]] = {}
    for target in protected_targets(job_dir, repo_root):
        snap.update(snapshot_tree(target))
    return snap


def diff_snapshots(before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"path": path, "before": before.get(path), "after": after.get(path)}
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    ]


def normalize(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def resolve_path(raw: Any, *, job_dir: Path, repo_root: Path) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    candidate = Path(text)
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend([job_dir / candidate, repo_root / candidate])
    if text.startswith("/app/"):
        candidates.append(repo_root / text[len("/app/"):])
    for item in candidates:
        if item.exists():
            return item.resolve()
    return candidates[0].resolve()


def evidence_entry_path(evidence: Dict[str, Any], key: str, *, job_dir: Path, repo_root: Path) -> Optional[Path]:
    entries = evidence.get("evidence_hashes")
    if isinstance(entries, dict):
        entry = entries.get(key)
        if isinstance(entry, dict):
            return resolve_path(entry.get("path") or entry.get("artifact_path"), job_dir=job_dir, repo_root=repo_root)
    return None


def evidence_entry_hash(evidence: Dict[str, Any], key: str) -> Optional[str]:
    source = evidence.get("source_evidence_hashes")
    if isinstance(source, dict) and isinstance(source.get(key), str) and source.get(key):
        return source.get(key)
    entries = evidence.get("evidence_hashes")
    if isinstance(entries, dict):
        entry = entries.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("sha256"), str) and entry.get("sha256"):
            return entry.get("sha256")
    return None


def recursive_forbidden_state_hits(data: Any, prefix: str = "") -> List[str]:
    hits: List[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_STATE_KEYS and normalize(value) in FORBIDDEN_TERMINAL_STATES:
                hits.append(f"{path}:{value}")
            if key in FORBIDDEN_TERMINAL_STATES and value is True:
                hits.append(f"{path}:true")
            hits.extend(recursive_forbidden_state_hits(value, path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            hits.extend(recursive_forbidden_state_hits(item, f"{prefix}[{idx}]"))
    return hits


def validate_common_artifact(
    artifact: Dict[str, Any],
    *,
    path: Path,
    expected_candidate_id: str,
    expected_rule_id: str,
    expected_mode: Optional[str],
    label: str,
) -> List[str]:
    blockers: List[str] = []
    if not path.exists():
        blockers.append(f"missing_{label}_artifact")
        return blockers
    if artifact.get("candidate_id") != expected_candidate_id:
        blockers.append(f"{label}_candidate_id_mismatch")
    if artifact.get("rule_id") != expected_rule_id:
        blockers.append(f"{label}_rule_id_mismatch")
    safety = artifact.get("safety_flags")
    if not isinstance(safety, dict):
        blockers.append(f"{label}_missing_safety_flags")
        safety = {}
    if expected_mode:
        mode_matches = artifact.get("mode") == expected_mode
        safety_mode_matches = safety.get(expected_mode) is True
        top_level_mode_matches = artifact.get(expected_mode) is True
        if not (mode_matches or safety_mode_matches or top_level_mode_matches):
            blockers.append(f"{label}_mode_mismatch")
    for key in REQUIRED_FALSE_FLAGS:
        if safety.get(key) is not False:
            blockers.append(f"{label}_source_flag_not_false:{key}")
    if safety.get("normal_final_pdf_remains_authoritative") is not True:
        blockers.append(f"{label}_normal_final_pdf_not_authoritative")
    if safety.get("future_apply_not_implemented") is not True:
        blockers.append(f"{label}_future_apply_not_implemented_missing")
    forbidden = recursive_forbidden_state_hits(artifact)
    if forbidden:
        blockers.append(f"{label}_forbidden_terminal_state_detected:" + ",".join(sorted(set(forbidden))))
    return blockers


def validate_sandbox_artifact(
    artifact: Dict[str, Any],
    *,
    path: Path,
    expected_candidate_id: str,
    expected_rule_id: str,
    label: str,
) -> List[str]:
    if label == "sandbox_rollback_verification":
        blockers: List[str] = []
        if not path.exists():
            blockers.append(f"missing_{label}_artifact")
            return blockers
        if artifact.get("candidate_id") != expected_candidate_id:
            blockers.append(f"{label}_candidate_id_mismatch")
        if artifact.get("rule_id") != expected_rule_id:
            blockers.append(f"{label}_rule_id_mismatch")
        forbidden = recursive_forbidden_state_hits(artifact)
        if forbidden:
            blockers.append(f"{label}_forbidden_terminal_state_detected:" + ",".join(sorted(set(forbidden))))
        if artifact.get("rollback_verification_scope") != "sandbox_only":
            blockers.append("sandbox_rollback_verification_scope_mismatch")
        if artifact.get("rollback_execution_against_authoritative_files") is not False:
            blockers.append("sandbox_rollback_verification_authoritative_rollback_true")
        if artifact.get("sandbox_rollback_verified") is not True:
            blockers.append("sandbox_rollback_verification_not_verified")
        if artifact.get("production_rollback_performed") is not False:
            blockers.append("sandbox_rollback_verification_production_rollback_true")
        return blockers

    blockers = validate_common_artifact(
        artifact,
        path=path,
        expected_candidate_id=expected_candidate_id,
        expected_rule_id=expected_rule_id,
        expected_mode="apply_sandbox_only" if label == "sandbox_manifest" else None,
        label=label,
    )
    if label == "sandbox_manifest" and artifact.get("apply_sandbox_outcome") not in {
        "apply_sandbox_recorded",
        "apply_sandbox_incomplete",
        "apply_sandbox_blocked",
    }:
        blockers.append("sandbox_manifest_outcome_invalid")
    return blockers

def load_optional_json(path: Path, blockers: List[str], label: str) -> Dict[str, Any]:
    if not path.exists():
        blockers.append(f"missing_{label}_artifact")
        return {}
    try:
        return load_json(path)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        blockers.append(f"{label}_artifact_unreadable:{exc}")
        return {}


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def copy_into_simulation(source: Path, destination: Path) -> Dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "source_path": str(source),
        "simulation_copy_path": str(destination),
        "source_sha256": sha256_file(source),
        "simulation_copy_sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size if destination.exists() else None,
    }


def validate_simulation_files_only(sim_dir: Path, paths: Iterable[Path]) -> List[str]:
    blockers: List[str] = []
    for path in paths:
        if not path_is_inside(path, sim_dir):
            blockers.append(f"simulation_write_outside_isolated_dir:{path}")
    return blockers


def safe_pdf_validation(path: Path) -> Dict[str, Any]:
    qpdf = shutil.which("qpdf")
    result: Dict[str, Any] = {
        "qpdf_checked": True,
        "qpdf_available": bool(qpdf),
        "qpdf_command": [qpdf, "--check", str(path)] if qpdf else None,
        "qpdf_exit_code": None,
        "qpdf_stdout": "",
        "qpdf_stderr": "",
        "fallback_pdf_header_checked": False,
        "fallback_pdf_header_valid": None,
        "valid": False,
    }
    if qpdf:
        proc = subprocess.run([qpdf, "--check", str(path)], text=True, capture_output=True, check=False)
        result.update({
            "qpdf_exit_code": proc.returncode,
            "qpdf_stdout": proc.stdout[-4000:],
            "qpdf_stderr": proc.stderr[-4000:],
            "valid": proc.returncode == 0,
        })
        return result
    data = path.read_bytes() if path.exists() else b""
    header_valid = data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]
    result.update({
        "fallback_pdf_header_checked": True,
        "fallback_pdf_header_valid": header_valid,
        "valid": header_valid,
    })
    return result


def build_artifacts(
    *,
    job_dir: Path,
    repo_root: Path,
    operator: str,
    reviewer: str,
    candidate_id: str,
    rule_id: str,
    evidence_hashes_path: Path,
    apply_dry_run_path: Path,
    apply_dry_run_review_path: Path,
    sandbox_manifest_path_arg: Path,
    sandbox_backup_manifest_path: Path,
    sandbox_rollback_manifest_path: Path,
    sandbox_rollback_verification_path: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    sim_dir = simulation_dir(job_dir).resolve()
    before = snapshot_protected(job_dir, repo_root)
    created_at = utc_now()
    blockers: List[str] = []
    incomplete_reasons: List[str] = []

    if not operator.strip():
        blockers.append("missing_operator")
    if not reviewer.strip():
        blockers.append("missing_reviewer")
    if not candidate_id.strip():
        blockers.append("missing_candidate_id")
    if not rule_id.strip():
        blockers.append("missing_rule_id")
    if normalize(candidate_id) in FORBIDDEN_TERMINAL_STATES:
        blockers.append(f"forbidden_terminal_state_detected:candidate_id:{candidate_id}")
    if normalize(rule_id) in FORBIDDEN_TERMINAL_STATES:
        blockers.append(f"forbidden_terminal_state_detected:rule_id:{rule_id}")

    evidence = load_optional_json(evidence_hashes_path, blockers, "evidence_hashes")
    apply_dry_run = load_optional_json(apply_dry_run_path, blockers, "apply_dry_run")
    apply_review = load_optional_json(apply_dry_run_review_path, blockers, "apply_dry_run_review")
    sandbox_manifest = load_optional_json(sandbox_manifest_path_arg, blockers, "sandbox_manifest")
    sandbox_backup_manifest = load_optional_json(sandbox_backup_manifest_path, blockers, "sandbox_backup_manifest")
    sandbox_rollback_manifest = load_optional_json(sandbox_rollback_manifest_path, blockers, "sandbox_rollback_manifest")
    sandbox_rollback = load_optional_json(sandbox_rollback_verification_path, blockers, "sandbox_rollback_verification")

    if evidence:
        blockers.extend(validate_common_artifact(
            evidence,
            path=evidence_hashes_path,
            expected_candidate_id=candidate_id,
            expected_rule_id=rule_id,
            expected_mode="evidence_hashes_only",
            label="evidence_hashes",
        ))
    if apply_dry_run:
        blockers.extend(validate_common_artifact(
            apply_dry_run,
            path=apply_dry_run_path,
            expected_candidate_id=candidate_id,
            expected_rule_id=rule_id,
            expected_mode="adoption_apply_dry_run_only",
            label="apply_dry_run",
        ))
    if apply_review:
        blockers.extend(validate_common_artifact(
            apply_review,
            path=apply_dry_run_review_path,
            expected_candidate_id=candidate_id,
            expected_rule_id=rule_id,
            expected_mode="adoption_apply_dry_run_review_only",
            label="apply_dry_run_review",
        ))
    if sandbox_manifest:
        blockers.extend(validate_sandbox_artifact(
            sandbox_manifest,
            path=sandbox_manifest_path_arg,
            expected_candidate_id=candidate_id,
            expected_rule_id=rule_id,
            label="sandbox_manifest",
        ))
    for label, artifact, path in (
        ("sandbox_backup_manifest", sandbox_backup_manifest, sandbox_backup_manifest_path),
        ("sandbox_rollback_manifest", sandbox_rollback_manifest, sandbox_rollback_manifest_path),
    ):
        if artifact:
            blockers.extend(validate_common_artifact(
                artifact,
                path=path,
                expected_candidate_id=candidate_id,
                expected_rule_id=rule_id,
                expected_mode=None,
                label=label,
            ))
    if sandbox_rollback:
        blockers.extend(validate_sandbox_artifact(
            sandbox_rollback,
            path=sandbox_rollback_verification_path,
            expected_candidate_id=candidate_id,
            expected_rule_id=rule_id,
            label="sandbox_rollback_verification",
        ))

    normal_hash = evidence_entry_hash(evidence, "normal_final_pdf_sha256") if evidence else None
    learned_hash = evidence_entry_hash(evidence, "learned_trial_or_test_pdf_sha256") if evidence else None
    normal_path = evidence_entry_path(evidence, "normal_final_pdf_sha256", job_dir=job_dir, repo_root=repo_root) if evidence else None
    learned_path = evidence_entry_path(evidence, "learned_trial_or_test_pdf_sha256", job_dir=job_dir, repo_root=repo_root) if evidence else None

    if not normal_hash:
        incomplete_reasons.append("missing_normal_final_pdf_hash")
    if not normal_path or not normal_path.exists():
        incomplete_reasons.append("missing_normal_final_pdf_path")
    elif normal_hash and sha256_file(normal_path) != normal_hash:
        blockers.append("normal_final_pdf_hash_mismatch")
    if not learned_hash:
        incomplete_reasons.append("missing_learned_trial_or_test_pdf_hash")
    if not learned_path or not learned_path.exists():
        incomplete_reasons.append("missing_learned_trial_or_test_pdf_path")
    elif learned_hash and sha256_file(learned_path) != learned_hash:
        blockers.append("learned_trial_or_test_pdf_hash_mismatch")

    copied_files: List[Path] = []
    copied_entries: List[Dict[str, Any]] = []
    simulation_pdf = simulated_final_path(job_dir)
    if not blockers and not incomplete_reasons and normal_path and learned_path:
        copy_plan = [
            (normal_path, sim_dir / "source_copies" / "normal_final_pdf.pdf"),
            (learned_path, sim_dir / "source_copies" / "learned_trial_or_test_pdf.pdf"),
            (learned_path, simulation_pdf),
            (evidence_hashes_path, sim_dir / "source_artifacts" / evidence_hashes_path.name),
            (apply_dry_run_path, sim_dir / "source_artifacts" / apply_dry_run_path.name),
            (apply_dry_run_review_path, sim_dir / "source_artifacts" / apply_dry_run_review_path.name),
            (sandbox_manifest_path_arg, sim_dir / "source_artifacts" / SANDBOX_MANIFEST_NAME),
            (sandbox_backup_manifest_path, sim_dir / "source_artifacts" / SANDBOX_BACKUP_MANIFEST_NAME),
            (sandbox_rollback_manifest_path, sim_dir / "source_artifacts" / SANDBOX_ROLLBACK_MANIFEST_NAME),
            (sandbox_rollback_verification_path, sim_dir / "source_artifacts" / SANDBOX_ROLLBACK_VERIFICATION_NAME),
        ]
        for source, destination in copy_plan:
            copied_entries.append(copy_into_simulation(source, destination))
        copied_files.extend(Path(entry["simulation_copy_path"]) for entry in copied_entries)

    manifest_paths = [
        simulation_manifest_path(job_dir),
        simulated_apply_report_path(job_dir),
        simulated_validation_report_path(job_dir),
        simulated_rollback_verification_path(job_dir),
    ]
    if simulation_pdf.exists() or (not blockers and not incomplete_reasons):
        manifest_paths.append(simulation_pdf)
    blockers.extend(validate_simulation_files_only(sim_dir, [*copied_files, *manifest_paths]))

    simulation_final_sha = sha256_file(simulation_pdf)
    learned_hash_verified = bool(learned_hash and simulation_final_sha == learned_hash)
    normal_hash_verified = bool(normal_path and normal_hash and sha256_file(normal_path) == normal_hash)
    hashes_verified = normal_hash_verified and learned_hash_verified

    validation_details = safe_pdf_validation(simulation_pdf) if simulation_pdf.exists() else {
        "qpdf_checked": True,
        "qpdf_available": bool(shutil.which("qpdf")),
        "qpdf_exit_code": None,
        "valid": False,
        "missing_simulated_final_pdf": True,
    }
    if validation_details.get("valid") is not True and not blockers and not incomplete_reasons:
        blockers.append("simulated_final_pdf_validation_failed")
    if not hashes_verified and not blockers and not incomplete_reasons:
        blockers.append("simulated_final_pdf_hash_verification_failed")

    rollback_checks: List[Dict[str, Any]] = []
    rollback_verified = False
    if simulation_pdf.exists() and learned_hash:
        rollback_reference_path = sandbox_rollback_verification_path
        rollback_checks.append({
            "label": "simulated_final_pdf_matches_learned_trial_or_test_pdf",
            "simulated_final_path": str(simulation_pdf),
            "simulated_final_sha256": simulation_final_sha,
            "expected_learned_sha256": learned_hash,
            "matches": simulation_final_sha == learned_hash,
            "sandbox_rollback_verification_path": str(rollback_reference_path),
            "sandbox_rollback_verification_sha256": sha256_file(rollback_reference_path),
            "simulation_only": True,
        })
        rollback_verified = all(check["matches"] for check in rollback_checks) and sandbox_rollback.get("sandbox_rollback_verified") is True
    if not rollback_verified and not blockers and not incomplete_reasons:
        blockers.append("simulation_rollback_verification_failed")

    outcome = "apply_simulation_recorded"
    result = "PASS"
    if blockers:
        outcome = "apply_simulation_blocked"
        result = "BLOCKED"
    elif incomplete_reasons:
        outcome = "apply_simulation_incomplete"
        result = "INCOMPLETE"

    validation_report = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "simulated_validation_report",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "simulation_dir": str(sim_dir),
        "operator": operator,
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": "PASS" if result == "PASS" else result,
        "simulated_final_path": str(simulation_pdf),
        "simulated_final_sha256": simulation_final_sha,
        "normal_final_pdf_sha256": normal_hash,
        "learned_trial_or_test_pdf_sha256": learned_hash,
        "normal_hash_verified": normal_hash_verified,
        "learned_hash_verified": learned_hash_verified,
        "hashes_verified": hashes_verified if result == "PASS" else False,
        "validation_details": validation_details,
        **SIMULATED_VALIDATION_FLAGS,
        "hashes_verified": hashes_verified if result == "PASS" else False,
    }

    simulated_rollback = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "simulated_rollback_verification",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "simulation_dir": str(sim_dir),
        "operator": operator,
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "checks": rollback_checks,
        "sandbox_rollback_verification_reference": {
            "path": str(sandbox_rollback_verification_path),
            "sha256": sha256_file(sandbox_rollback_verification_path),
            "sandbox_rollback_verified": sandbox_rollback.get("sandbox_rollback_verified") if sandbox_rollback else None,
        },
        **SIMULATED_ROLLBACK_FLAGS,
        "simulation_rollback_verified": rollback_verified if result == "PASS" else False,
    }

    apply_report = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "simulated_apply_report",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "simulation_dir": str(sim_dir),
        "operator": operator,
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "apply_simulation_outcome": outcome,
        "simulation_action": "copy_learned_trial_or_test_pdf_to_isolated_simulated_final",
        "authoritative_final_pdf_path": str(normal_path) if normal_path else None,
        "learned_trial_or_test_pdf_path": str(learned_path) if learned_path else None,
        "simulated_final_path": str(simulation_pdf),
        "normal_vs_learned_hash_comparison": {
            "normal_final_pdf_sha256": normal_hash,
            "learned_trial_or_test_pdf_sha256": learned_hash,
            "simulated_final_sha256": simulation_final_sha,
            "normal_matches_learned": bool(normal_hash and learned_hash and normal_hash == learned_hash),
            "simulated_matches_learned": bool(simulation_final_sha and learned_hash and simulation_final_sha == learned_hash),
            "simulated_matches_normal": bool(simulation_final_sha and normal_hash and simulation_final_sha == normal_hash),
        },
        "source_artifact_hashes": {
            "evidence_hashes": sha256_file(evidence_hashes_path),
            "apply_dry_run": sha256_file(apply_dry_run_path),
            "apply_dry_run_review": sha256_file(apply_dry_run_review_path),
            "sandbox_manifest": sha256_file(sandbox_manifest_path_arg),
            "sandbox_backup_manifest": sha256_file(sandbox_backup_manifest_path),
            "sandbox_rollback_manifest": sha256_file(sandbox_rollback_manifest_path),
            "sandbox_rollback_verification": sha256_file(sandbox_rollback_verification_path),
        },
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        **MANDATORY_SAFETY_FLAGS,
    }

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "apply_simulation_blocked"
        result = "BLOCKED"
        apply_report["result"] = result
        apply_report["apply_simulation_outcome"] = outcome

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": created_at,
        "job_dir": str(job_dir),
        "simulation_dir": str(sim_dir),
        "artifact_path": str(simulation_manifest_path(job_dir)),
        "simulated_apply_report_path": str(simulated_apply_report_path(job_dir)),
        "simulated_final_path": str(simulation_pdf),
        "simulated_validation_report_path": str(simulated_validation_report_path(job_dir)),
        "simulated_rollback_verification_path": str(simulated_rollback_verification_path(job_dir)),
        "operator": operator,
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "apply_simulation_outcome": outcome,
        "allowed_apply_simulation_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "incomplete_reasons": incomplete_reasons,
        "source_artifacts": {
            "evidence_hashes": {"path": str(evidence_hashes_path), "sha256": sha256_file(evidence_hashes_path)},
            "apply_dry_run": {"path": str(apply_dry_run_path), "sha256": sha256_file(apply_dry_run_path)},
            "apply_dry_run_review": {"path": str(apply_dry_run_review_path), "sha256": sha256_file(apply_dry_run_review_path)},
            "sandbox_manifest": {"path": str(sandbox_manifest_path_arg), "sha256": sha256_file(sandbox_manifest_path_arg)},
            "sandbox_backup_manifest": {"path": str(sandbox_backup_manifest_path), "sha256": sha256_file(sandbox_backup_manifest_path)},
            "sandbox_rollback_manifest": {"path": str(sandbox_rollback_manifest_path), "sha256": sha256_file(sandbox_rollback_manifest_path)},
            "sandbox_rollback_verification": {"path": str(sandbox_rollback_verification_path), "sha256": sha256_file(sandbox_rollback_verification_path)},
        },
        "source_evidence_hashes": {
            "normal_final_pdf_sha256": normal_hash,
            "learned_trial_or_test_pdf_sha256": learned_hash,
        },
        "copied_files": [str(path) for path in copied_files],
        "normal_vs_learned_hash_comparison": apply_report["normal_vs_learned_hash_comparison"],
        "simulated_validation": validation_report,
        "simulated_rollback_verification": simulated_rollback,
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        **MANDATORY_SAFETY_FLAGS,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
    }
    return manifest, apply_report, validation_report, simulated_rollback


def write_artifact_bundle(
    *,
    job_dir: Path,
    simulation_manifest: Dict[str, Any],
    simulated_apply_report: Dict[str, Any],
    simulated_validation_report: Dict[str, Any],
    simulated_rollback_verification: Dict[str, Any],
) -> None:
    write_json(simulation_manifest_path(job_dir), simulation_manifest)
    write_json(simulated_apply_report_path(job_dir), simulated_apply_report)
    write_json(simulated_validation_report_path(job_dir), simulated_validation_report)
    write_json(simulated_rollback_verification_path(job_dir), simulated_rollback_verification)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--evidence-hashes", type=Path, default=None)
    parser.add_argument("--apply-dry-run", type=Path, default=None)
    parser.add_argument("--apply-dry-run-review", type=Path, default=None)
    parser.add_argument("--sandbox-manifest", type=Path, default=None)
    parser.add_argument("--sandbox-backup-manifest", type=Path, default=None)
    parser.add_argument("--sandbox-rollback-manifest", type=Path, default=None)
    parser.add_argument("--sandbox-rollback-verification", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    manifest, apply_report, validation_report, rollback = build_artifacts(
        job_dir=job_dir,
        repo_root=repo_root,
        operator=args.operator.strip(),
        reviewer=args.reviewer.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
        evidence_hashes_path=(args.evidence_hashes or default_evidence_hashes_path(job_dir)).resolve(),
        apply_dry_run_path=(args.apply_dry_run or default_apply_dry_run_path(job_dir)).resolve(),
        apply_dry_run_review_path=(args.apply_dry_run_review or default_apply_dry_run_review_path(job_dir)).resolve(),
        sandbox_manifest_path_arg=(args.sandbox_manifest or default_sandbox_manifest_path(job_dir)).resolve(),
        sandbox_backup_manifest_path=(args.sandbox_backup_manifest or default_sandbox_backup_manifest_path(job_dir)).resolve(),
        sandbox_rollback_manifest_path=(args.sandbox_rollback_manifest or default_sandbox_rollback_manifest_path(job_dir)).resolve(),
        sandbox_rollback_verification_path=(args.sandbox_rollback_verification or default_sandbox_rollback_verification_path(job_dir)).resolve(),
    )
    write_artifact_bundle(
        job_dir=job_dir,
        simulation_manifest=manifest,
        simulated_apply_report=apply_report,
        simulated_validation_report=validation_report,
        simulated_rollback_verification=rollback,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
