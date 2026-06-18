#!/usr/bin/env python3
"""Guarded reviewed learned-strategy apply for one job/candidate/rule.

Patch 25A is the first narrowly scoped real reviewed apply. It may copy the
locked learned trial/test PDF to a job-local adopted output, but only when an
explicit --apply command supplies independent reviewer/approver identities and
locked artifact hashes. It never enables default learned execution, never moves
learned scripts into app/tools/repair, never mutates the global rule map, and
never rewrites package/status outputs.
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

SCHEMA_VERSION = "learned-strategy-reviewed-apply.v1"
MODE = "job_scoped_reviewed_apply"
REVIEWED_APPLY_DIR_NAME = "learned_strategy_reviewed_apply"
APPLY_MANIFEST_NAME = "apply_manifest.json"
BACKUP_MANIFEST_NAME = "backup_manifest.json"
ROLLBACK_MANIFEST_NAME = "rollback_manifest.json"
POST_APPLY_VALIDATION_NAME = "post_apply_validation.json"
APPLY_AUDIT_NAME = "apply_audit.json"
ADOPTED_FINAL_NAME = "adopted_final.pdf"
BACKUP_DIR_NAME = "backups"
NORMAL_BACKUP_NAME = "normal_final_backup.pdf"

EVIDENCE_HASH_ARTIFACT_NAME = "learned_strategy_evidence_hashes.json"
APPLY_DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run.json"
APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run_review.json"
SANDBOX_DIR_NAME = "learned_strategy_apply_sandbox"
SANDBOX_MANIFEST_NAME = "sandbox_manifest.json"
SANDBOX_ROLLBACK_VERIFICATION_NAME = "rollback_verification.json"
SIMULATION_DIR_NAME = "learned_strategy_apply_simulation"
SIMULATION_MANIFEST_NAME = "simulation_manifest.json"
SIMULATED_VALIDATION_REPORT_NAME = "simulated_validation_report.json"
SIMULATED_ROLLBACK_VERIFICATION_NAME = "simulated_rollback_verification.json"

ALLOWED_OUTCOMES = {
    "reviewed_apply_performed",
    "reviewed_apply_blocked",
    "reviewed_apply_incomplete",
    "reviewed_apply_failed_closed",
}
FORBIDDEN_TERMINAL_STATES = {
    "default_learned_execution_enabled",
    "rule_map_mutated",
    "app_tools_repair_mutated",
    "verdict_softened",
    "candidate_globally_approved",
    "candidate_globally_production_ready",
    "apply_without_backup",
    "apply_without_rollback_manifest",
    "apply_without_explicit_approver",
    "apply_without_explicit_reviewer",
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
MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "reviewed_apply_only": True,
    "explicit_apply_requested": True,
    "reviewer_identity_recorded": True,
    "approver_identity_recorded": True,
    "separate_reviewer_and_approver": True,
    "production_backup_created": True,
    "rollback_manifest_created": True,
    "adoption_apply_performed": True,
    "job_scoped_apply_only": True,
    "candidate_is_adoptable": False,
    "candidate_approved": False,
    "candidate_production_ready": False,
    "candidate_apply_ready": False,
    "default_learned_execution_enabled": False,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "production_repair_replacement_performed": False,
    "verdict_softening_performed": False,
    "package_status_mutation_performed": False,
}
POST_APPLY_VALIDATION_FLAGS: Dict[str, Any] = {
    "validation_scope": "job_scoped_reviewed_apply",
    "qpdf_checked": True,
    "hashes_verified": True,
    "adopted_output_exists": True,
    "normal_backup_exists": True,
    "rollback_manifest_exists": True,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "verdict_softening_performed": False,
}
REQUIRED_UPSTREAM_FALSE_FLAGS = {
    "candidate_is_adoptable",
    "candidate_approved",
    "candidate_production_ready",
    "candidate_apply_ready",
    "default_learned_execution_enabled",
    "rule_map_mutation_performed",
    "app_tools_repair_mutation_performed",
    "production_repair_replacement_performed",
    "verdict_softening_performed",
    "package_status_mutation_performed",
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


def reviewed_apply_dir(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / REVIEWED_APPLY_DIR_NAME


def apply_manifest_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / APPLY_MANIFEST_NAME


def backup_manifest_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / BACKUP_MANIFEST_NAME


def rollback_manifest_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ROLLBACK_MANIFEST_NAME


def post_apply_validation_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / POST_APPLY_VALIDATION_NAME


def apply_audit_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / APPLY_AUDIT_NAME


def adopted_final_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ADOPTED_FINAL_NAME


def backup_pdf_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / BACKUP_DIR_NAME / NORMAL_BACKUP_NAME


def default_evidence_hashes_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / EVIDENCE_HASH_ARTIFACT_NAME


def default_apply_dry_run_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / APPLY_DRY_RUN_ARTIFACT_NAME


def default_apply_dry_run_review_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME


def default_sandbox_manifest_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SANDBOX_DIR_NAME / SANDBOX_MANIFEST_NAME


def default_sandbox_rollback_verification_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SANDBOX_DIR_NAME / SANDBOX_ROLLBACK_VERIFICATION_NAME


def default_simulation_manifest_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SIMULATION_DIR_NAME / SIMULATION_MANIFEST_NAME


def default_simulated_validation_report_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SIMULATION_DIR_NAME / SIMULATED_VALIDATION_REPORT_NAME


def default_simulated_rollback_verification_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SIMULATION_DIR_NAME / SIMULATED_ROLLBACK_VERIFICATION_NAME


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


def load_required_json(path: Path, blockers: List[str], label: str) -> Dict[str, Any]:
    if not path.exists():
        blockers.append(f"missing_{label}_artifact")
        return {}
    try:
        return load_json(path)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        blockers.append(f"{label}_artifact_unreadable:{exc}")
        return {}


def artifact_result_is_passish(artifact: Dict[str, Any]) -> bool:
    result = normalize(artifact.get("result"))
    return result in {"pass", "blocked", "escalation"}


def validate_artifact_identity(
    artifact: Dict[str, Any],
    *,
    path: Path,
    label: str,
    expected_candidate_id: str,
    expected_rule_id: str,
) -> List[str]:
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
    return blockers


def validate_safety_false_flags(artifact: Dict[str, Any], *, label: str) -> List[str]:
    blockers: List[str] = []
    safety = artifact.get("safety_flags")
    if not isinstance(safety, dict):
        return blockers
    for key in REQUIRED_UPSTREAM_FALSE_FLAGS:
        if key in safety and safety.get(key) is not False:
            blockers.append(f"{label}_source_flag_not_false:{key}")
    return blockers


def validate_upstream_artifacts(
    *,
    evidence: Dict[str, Any],
    dry_run: Dict[str, Any],
    dry_run_review: Dict[str, Any],
    sandbox_manifest: Dict[str, Any],
    sandbox_rollback: Dict[str, Any],
    simulation_manifest: Dict[str, Any],
    simulated_validation: Dict[str, Any],
    simulated_rollback: Dict[str, Any],
    paths: Dict[str, Path],
    candidate_id: str,
    rule_id: str,
) -> List[str]:
    blockers: List[str] = []
    artifacts = {
        "evidence_hashes": evidence,
        "apply_dry_run": dry_run,
        "apply_dry_run_review": dry_run_review,
        "sandbox_manifest": sandbox_manifest,
        "sandbox_rollback_verification": sandbox_rollback,
        "simulation_manifest": simulation_manifest,
        "simulated_validation": simulated_validation,
        "simulated_rollback_verification": simulated_rollback,
    }
    for label, artifact in artifacts.items():
        if artifact:
            blockers.extend(validate_artifact_identity(
                artifact,
                path=paths[label],
                label=label,
                expected_candidate_id=candidate_id,
                expected_rule_id=rule_id,
            ))
            blockers.extend(validate_safety_false_flags(artifact, label=label))
    if dry_run_review and not artifact_result_is_passish(dry_run_review):
        blockers.append("apply_dry_run_review_result_unusable")
    if sandbox_rollback:
        if sandbox_rollback.get("rollback_verification_scope") != "sandbox_only":
            blockers.append("sandbox_rollback_verification_scope_mismatch")
        if sandbox_rollback.get("sandbox_rollback_verified") is not True:
            blockers.append("sandbox_rollback_verification_not_verified")
        if sandbox_rollback.get("rollback_execution_against_authoritative_files") is not False:
            blockers.append("sandbox_rollback_verification_authoritative_rollback_true")
    if simulation_manifest:
        if simulation_manifest.get("result") != "PASS":
            blockers.append("simulation_manifest_not_pass")
        if simulation_manifest.get("apply_simulation_outcome") != "apply_simulation_recorded":
            blockers.append("simulation_manifest_outcome_not_recorded")
        if simulation_manifest.get("adoption_apply_performed") is not False:
            blockers.append("simulation_manifest_source_adoption_apply_true")
    if simulated_validation:
        if simulated_validation.get("validation_scope") != "simulation_only":
            blockers.append("simulated_validation_scope_mismatch")
        if simulated_validation.get("hashes_verified") is not True:
            blockers.append("simulated_validation_hashes_not_verified")
        details = simulated_validation.get("validation_details")
        if not isinstance(details, dict) or details.get("valid") is not True:
            blockers.append("simulated_validation_pdf_not_valid")
    if simulated_rollback:
        if simulated_rollback.get("rollback_verification_scope") != "simulation_only":
            blockers.append("simulated_rollback_scope_mismatch")
        if simulated_rollback.get("simulation_rollback_verified") is not True:
            blockers.append("simulated_rollback_not_verified")
        if simulated_rollback.get("rollback_execution_against_authoritative_files") is not False:
            blockers.append("simulated_rollback_authoritative_rollback_true")
    return blockers


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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


def write_backup(normal_path: Path, backup_path: Path) -> Dict[str, Any]:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(normal_path, backup_path)
    return {
        "source_path": str(normal_path),
        "backup_path": str(backup_path),
        "source_sha256": sha256_file(normal_path),
        "backup_sha256": sha256_file(backup_path),
        "size_bytes": backup_path.stat().st_size if backup_path.exists() else None,
    }


def copy_adopted_output(learned_path: Path, adopted_path: Path) -> Dict[str, Any]:
    adopted_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(learned_path, adopted_path)
    return {
        "source_path": str(learned_path),
        "adopted_output_path": str(adopted_path),
        "source_sha256": sha256_file(learned_path),
        "adopted_output_sha256": sha256_file(adopted_path),
        "size_bytes": adopted_path.stat().st_size if adopted_path.exists() else None,
    }


def build_artifacts(
    *,
    job_dir: Path,
    repo_root: Path,
    explicit_apply_requested: bool,
    operator: str,
    reviewer: str,
    approver: str,
    candidate_id: str,
    rule_id: str,
    expected_normal_final_pdf_sha256: str,
    expected_learned_trial_or_test_pdf_sha256: str,
    expected_simulation_artifact_sha256: str,
    expected_evidence_hash_artifact_sha256: str,
    evidence_hashes_path: Path,
    apply_dry_run_path: Path,
    apply_dry_run_review_path: Path,
    sandbox_manifest_path: Path,
    sandbox_rollback_verification_path: Path,
    simulation_manifest_path_arg: Path,
    simulated_validation_report_path_arg: Path,
    simulated_rollback_verification_path_arg: Path,
    backup_path_arg: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    apply_dir = reviewed_apply_dir(job_dir).resolve()
    before = snapshot_protected(job_dir, repo_root)
    created_at = utc_now()
    blockers: List[str] = []
    incomplete_reasons: List[str] = []
    write_order: List[str] = []

    if explicit_apply_requested is not True:
        blockers.append("missing_explicit_apply")
    if not operator.strip():
        blockers.append("missing_operator")
    if not reviewer.strip():
        blockers.append("missing_reviewer")
    if not approver.strip():
        blockers.append("missing_approver")
    if reviewer.strip() and approver.strip() and reviewer.strip() == approver.strip():
        blockers.append("reviewer_and_approver_must_be_separate")
    if not candidate_id.strip():
        blockers.append("missing_candidate_id")
    if not rule_id.strip():
        blockers.append("missing_rule_id")
    for label, value in (
        ("expected_normal_final_pdf_sha256", expected_normal_final_pdf_sha256),
        ("expected_learned_trial_or_test_pdf_sha256", expected_learned_trial_or_test_pdf_sha256),
        ("expected_simulation_artifact_sha256", expected_simulation_artifact_sha256),
        ("expected_evidence_hash_artifact_sha256", expected_evidence_hash_artifact_sha256),
    ):
        if not str(value).strip():
            blockers.append(f"missing_{label}")
    if normalize(candidate_id) in FORBIDDEN_TERMINAL_STATES:
        blockers.append(f"forbidden_terminal_state_detected:candidate_id:{candidate_id}")
    if normalize(rule_id) in FORBIDDEN_TERMINAL_STATES:
        blockers.append(f"forbidden_terminal_state_detected:rule_id:{rule_id}")

    evidence = load_required_json(evidence_hashes_path, blockers, "evidence_hashes")
    dry_run = load_required_json(apply_dry_run_path, blockers, "apply_dry_run")
    dry_run_review = load_required_json(apply_dry_run_review_path, blockers, "apply_dry_run_review")
    sandbox_manifest = load_required_json(sandbox_manifest_path, blockers, "sandbox_manifest")
    sandbox_rollback = load_required_json(sandbox_rollback_verification_path, blockers, "sandbox_rollback_verification")
    simulation_manifest = load_required_json(simulation_manifest_path_arg, blockers, "simulation_manifest")
    simulated_validation = load_required_json(simulated_validation_report_path_arg, blockers, "simulated_validation")
    simulated_rollback = load_required_json(simulated_rollback_verification_path_arg, blockers, "simulated_rollback_verification")

    artifact_paths = {
        "evidence_hashes": evidence_hashes_path,
        "apply_dry_run": apply_dry_run_path,
        "apply_dry_run_review": apply_dry_run_review_path,
        "sandbox_manifest": sandbox_manifest_path,
        "sandbox_rollback_verification": sandbox_rollback_verification_path,
        "simulation_manifest": simulation_manifest_path_arg,
        "simulated_validation": simulated_validation_report_path_arg,
        "simulated_rollback_verification": simulated_rollback_verification_path_arg,
    }
    blockers.extend(validate_upstream_artifacts(
        evidence=evidence,
        dry_run=dry_run,
        dry_run_review=dry_run_review,
        sandbox_manifest=sandbox_manifest,
        sandbox_rollback=sandbox_rollback,
        simulation_manifest=simulation_manifest,
        simulated_validation=simulated_validation,
        simulated_rollback=simulated_rollback,
        paths=artifact_paths,
        candidate_id=candidate_id,
        rule_id=rule_id,
    ))

    evidence_artifact_sha = sha256_file(evidence_hashes_path)
    simulation_artifact_sha = sha256_file(simulation_manifest_path_arg)
    if expected_evidence_hash_artifact_sha256 and evidence_artifact_sha != expected_evidence_hash_artifact_sha256:
        blockers.append("expected_evidence_hash_artifact_sha256_mismatch")
    if expected_simulation_artifact_sha256 and simulation_artifact_sha != expected_simulation_artifact_sha256:
        blockers.append("expected_simulation_artifact_sha256_mismatch")

    normal_hash = evidence_entry_hash(evidence, "normal_final_pdf_sha256") if evidence else None
    learned_hash = evidence_entry_hash(evidence, "learned_trial_or_test_pdf_sha256") if evidence else None
    normal_path = evidence_entry_path(evidence, "normal_final_pdf_sha256", job_dir=job_dir, repo_root=repo_root) if evidence else None
    learned_path = evidence_entry_path(evidence, "learned_trial_or_test_pdf_sha256", job_dir=job_dir, repo_root=repo_root) if evidence else None

    if not normal_hash:
        incomplete_reasons.append("missing_normal_final_pdf_hash")
    if not normal_path or not normal_path.exists():
        incomplete_reasons.append("missing_normal_final_pdf_path")
    elif expected_normal_final_pdf_sha256 and sha256_file(normal_path) != expected_normal_final_pdf_sha256:
        blockers.append("expected_normal_final_pdf_hash_mismatch")
    elif normal_hash and sha256_file(normal_path) != normal_hash:
        blockers.append("normal_final_pdf_hash_mismatch")
    if normal_hash and expected_normal_final_pdf_sha256 and normal_hash != expected_normal_final_pdf_sha256:
        blockers.append("expected_normal_final_pdf_hash_not_locked_to_evidence")

    if not learned_hash:
        incomplete_reasons.append("missing_learned_trial_or_test_pdf_hash")
    if not learned_path or not learned_path.exists():
        incomplete_reasons.append("missing_learned_trial_or_test_pdf_path")
    elif expected_learned_trial_or_test_pdf_sha256 and sha256_file(learned_path) != expected_learned_trial_or_test_pdf_sha256:
        blockers.append("expected_learned_trial_or_test_pdf_hash_mismatch")
    elif learned_hash and sha256_file(learned_path) != learned_hash:
        blockers.append("learned_trial_or_test_pdf_hash_mismatch")
    if learned_hash and expected_learned_trial_or_test_pdf_sha256 and learned_hash != expected_learned_trial_or_test_pdf_sha256:
        blockers.append("expected_learned_trial_or_test_pdf_hash_not_locked_to_evidence")

    if simulated_validation and expected_learned_trial_or_test_pdf_sha256:
        if simulated_validation.get("simulated_final_sha256") != expected_learned_trial_or_test_pdf_sha256:
            blockers.append("simulation_final_hash_not_locked_to_expected_learned_hash")

    backup_path = (backup_path_arg or backup_pdf_path(job_dir)).resolve()
    adopted_path = adopted_final_path(job_dir).resolve()
    rollback_path = rollback_manifest_path(job_dir).resolve()
    backup_manifest_out_path = backup_manifest_path(job_dir).resolve()
    validation_path = post_apply_validation_path(job_dir).resolve()
    manifest_path = apply_manifest_path(job_dir).resolve()
    audit_path = apply_audit_path(job_dir).resolve()

    for label, path in (
        ("backup_target", backup_path),
        ("adopted_output", adopted_path),
        ("rollback_manifest", rollback_path),
        ("backup_manifest", backup_manifest_out_path),
        ("post_apply_validation", validation_path),
        ("apply_manifest", manifest_path),
        ("apply_audit", audit_path),
    ):
        if not path_is_inside(path, apply_dir):
            blockers.append(f"{label}_outside_reviewed_apply_dir:{path}")
    if backup_path.exists() and backup_path.is_dir():
        blockers.append("backup_target_is_directory")

    backup_entry: Dict[str, Any] = {}
    adopted_entry: Dict[str, Any] = {}
    validation_details: Dict[str, Any] = {
        "qpdf_checked": True,
        "qpdf_available": bool(shutil.which("qpdf")),
        "qpdf_exit_code": None,
        "valid": False,
        "not_run": True,
    }
    backup_created = False
    rollback_created = False
    adopted_created = False
    apply_failed_closed = False

    if not blockers and not incomplete_reasons and normal_path and learned_path:
        try:
            backup_entry = write_backup(normal_path, backup_path)
            backup_created = backup_entry.get("backup_sha256") == expected_normal_final_pdf_sha256
            write_order.append("backup")
        except Exception as exc:
            blockers.append(f"backup_failed:{exc}")
            apply_failed_closed = True
        if not blockers and not backup_created:
            blockers.append("backup_hash_verification_failed")
            apply_failed_closed = True
        rollback_data = {
            "schema_version": SCHEMA_VERSION,
            "manifest_type": "rollback_manifest",
            "created_at": created_at,
            "job_dir": str(job_dir),
            "operator": operator,
            "reviewer": reviewer,
            "approver": approver,
            "candidate_id": candidate_id,
            "rule_id": rule_id,
            "rollback_instructions": [
                "This Patch 25A apply is job-scoped. Restore by deleting adopted_final.pdf and using the normal final PDF path recorded here as authoritative.",
                "If a future patch adds a job-local final pointer, restore it to original_authoritative_final_pdf_path before re-packaging.",
            ],
            "original_authoritative_final_pdf_path": str(normal_path),
            "normal_backup_path": str(backup_path),
            "normal_backup_sha256": sha256_file(backup_path),
            "adopted_output_path": str(adopted_path),
            "rollback_execution_performed": False,
            "rollback_execution_against_authoritative_files": False,
            "production_rollback_performed": False,
            "rule_map_mutation_performed": False,
            "app_tools_repair_mutation_performed": False,
            "package_status_mutation_performed": False,
        }
        if not blockers:
            try:
                write_json(rollback_path, rollback_data)
                rollback_created = True
                write_order.append("rollback_manifest")
            except Exception as exc:
                blockers.append(f"rollback_manifest_failed:{exc}")
                apply_failed_closed = True
        if not blockers:
            try:
                adopted_entry = copy_adopted_output(learned_path, adopted_path)
                adopted_created = adopted_entry.get("adopted_output_sha256") == expected_learned_trial_or_test_pdf_sha256
                write_order.append("adopted_output")
            except Exception as exc:
                blockers.append(f"adopted_output_failed:{exc}")
                apply_failed_closed = True
        if not blockers and not adopted_created:
            blockers.append("adopted_output_hash_verification_failed")
            apply_failed_closed = True
        if not blockers:
            validation_details = safe_pdf_validation(adopted_path)
            if validation_details.get("valid") is not True:
                blockers.append("post_apply_qpdf_validation_failed")
                apply_failed_closed = True
    elif blockers:
        apply_failed_closed = True

    if backup_created and "backup" not in write_order:
        blockers.append("backup_write_order_not_recorded")
    if rollback_created and "rollback_manifest" not in write_order:
        blockers.append("rollback_write_order_not_recorded")
    if adopted_created and write_order[:2] != ["backup", "rollback_manifest"]:
        blockers.append("apply_without_backup_or_rollback_manifest_order")

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        apply_failed_closed = True

    result = "PASS"
    outcome = "reviewed_apply_performed"
    if blockers:
        result = "FAILED_CLOSED" if apply_failed_closed else "BLOCKED"
        outcome = "reviewed_apply_failed_closed" if apply_failed_closed else "reviewed_apply_blocked"
    elif incomplete_reasons:
        result = "INCOMPLETE"
        outcome = "reviewed_apply_incomplete"

    safety_flags = dict(MANDATORY_SAFETY_FLAGS)
    if result != "PASS":
        safety_flags.update({
            "production_backup_created": backup_created,
            "rollback_manifest_created": rollback_created,
            "adoption_apply_performed": adopted_created,
            "explicit_apply_requested": explicit_apply_requested is True,
            "reviewer_identity_recorded": bool(reviewer.strip()),
            "approver_identity_recorded": bool(approver.strip()),
            "separate_reviewer_and_approver": bool(reviewer.strip() and approver.strip() and reviewer.strip() != approver.strip()),
        })

    backup_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "backup_manifest",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "result": result,
        "production_backup_created": backup_created,
        "entries": [backup_entry] if backup_entry else [],
        "write_order": write_order,
        "safety_flags": safety_flags,
    }
    rollback_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "rollback_manifest",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "result": result,
        "rollback_manifest_created": rollback_created,
        "rollback_execution_performed": False,
        "rollback_execution_against_authoritative_files": False,
        "production_rollback_performed": False,
        "normal_backup_path": str(backup_path),
        "adopted_output_path": str(adopted_path),
        "rollback_instructions": [
            "Delete or ignore adopted_final.pdf to return to the normal pipeline output.",
            "The authoritative normal final PDF was not modified in place by Patch 25A.",
        ],
        "safety_flags": safety_flags,
    }
    if rollback_created and rollback_path.exists():
        try:
            rollback_manifest.update(load_json(rollback_path))
            rollback_manifest["result"] = result
            rollback_manifest["safety_flags"] = safety_flags
        except Exception:
            pass
    post_apply_validation = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "post_apply_validation",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "result": result,
        "adopted_output_path": str(adopted_path),
        "adopted_output_sha256": sha256_file(adopted_path),
        "expected_adopted_output_sha256": expected_learned_trial_or_test_pdf_sha256,
        "normal_backup_path": str(backup_path),
        "normal_backup_sha256": sha256_file(backup_path),
        "expected_normal_backup_sha256": expected_normal_final_pdf_sha256,
        "rollback_manifest_path": str(rollback_path),
        "validation_details": validation_details,
        **POST_APPLY_VALIDATION_FLAGS,
        "hashes_verified": bool(
            result == "PASS"
            and sha256_file(adopted_path) == expected_learned_trial_or_test_pdf_sha256
            and sha256_file(backup_path) == expected_normal_final_pdf_sha256
        ),
        "adopted_output_exists": adopted_path.exists(),
        "normal_backup_exists": backup_path.exists(),
        "rollback_manifest_exists": rollback_path.exists(),
    }
    apply_audit = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "apply_audit",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "result": result,
        "reviewed_apply_outcome": outcome,
        "write_order": write_order,
        "locked_hashes": {
            "expected_normal_final_pdf_sha256": expected_normal_final_pdf_sha256,
            "expected_learned_trial_or_test_pdf_sha256": expected_learned_trial_or_test_pdf_sha256,
            "expected_simulation_artifact_sha256": expected_simulation_artifact_sha256,
            "expected_evidence_hash_artifact_sha256": expected_evidence_hash_artifact_sha256,
        },
        "source_artifacts": {label: {"path": str(path), "sha256": sha256_file(path)} for label, path in artifact_paths.items()},
        "normal_final_pdf_path": str(normal_path) if normal_path else None,
        "learned_trial_or_test_pdf_path": str(learned_path) if learned_path else None,
        "adopted_output_path": str(adopted_path),
        "backup_manifest_path": str(backup_manifest_out_path),
        "rollback_manifest_path": str(rollback_path),
        "post_apply_validation_path": str(validation_path),
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
        "safety_flags": safety_flags,
    }
    apply_manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": created_at,
        "job_dir": str(job_dir),
        "reviewed_apply_dir": str(apply_dir),
        "artifact_path": str(manifest_path),
        "backup_manifest_path": str(backup_manifest_out_path),
        "rollback_manifest_path": str(rollback_path),
        "post_apply_validation_path": str(validation_path),
        "apply_audit_path": str(audit_path),
        "adopted_output_path": str(adopted_path),
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "reviewed_apply_outcome": outcome,
        "allowed_reviewed_apply_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "incomplete_reasons": incomplete_reasons,
        "locked_hashes": apply_audit["locked_hashes"],
        "source_artifacts": apply_audit["source_artifacts"],
        "normal_final_pdf_path": str(normal_path) if normal_path else None,
        "normal_final_pdf_sha256": sha256_file(normal_path) if normal_path else None,
        "learned_trial_or_test_pdf_path": str(learned_path) if learned_path else None,
        "learned_trial_or_test_pdf_sha256": sha256_file(learned_path) if learned_path else None,
        "adopted_output_sha256": sha256_file(adopted_path),
        "backup_manifest": backup_manifest,
        "rollback_manifest": rollback_manifest,
        "post_apply_validation": post_apply_validation,
        "apply_audit": apply_audit,
        "write_order": write_order,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
        "safety_flags": safety_flags,
        **safety_flags,
    }
    return apply_manifest, backup_manifest, rollback_manifest, post_apply_validation, apply_audit


def write_artifact_bundle(
    *,
    job_dir: Path,
    apply_manifest: Dict[str, Any],
    backup_manifest: Dict[str, Any],
    rollback_manifest: Dict[str, Any],
    post_apply_validation: Dict[str, Any],
    apply_audit: Dict[str, Any],
) -> None:
    write_json(backup_manifest_path(job_dir), backup_manifest)
    write_json(rollback_manifest_path(job_dir), rollback_manifest)
    write_json(post_apply_validation_path(job_dir), post_apply_validation)
    write_json(apply_audit_path(job_dir), apply_audit)
    write_json(apply_manifest_path(job_dir), apply_manifest)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true", dest="explicit_apply_requested")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--expected-normal-final-pdf-sha256", required=True)
    parser.add_argument("--expected-learned-trial-or-test-pdf-sha256", required=True)
    parser.add_argument("--expected-simulation-artifact-sha256", required=True)
    parser.add_argument("--expected-evidence-hash-artifact-sha256", required=True)
    parser.add_argument("--evidence-hashes", type=Path, default=None)
    parser.add_argument("--apply-dry-run", type=Path, default=None)
    parser.add_argument("--apply-dry-run-review", type=Path, default=None)
    parser.add_argument("--sandbox-manifest", type=Path, default=None)
    parser.add_argument("--sandbox-rollback-verification", type=Path, default=None)
    parser.add_argument("--simulation-manifest", type=Path, default=None)
    parser.add_argument("--simulated-validation", type=Path, default=None)
    parser.add_argument("--simulated-rollback-verification", type=Path, default=None)
    parser.add_argument("--backup-target", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    manifest, backup, rollback, validation, audit = build_artifacts(
        job_dir=job_dir,
        repo_root=repo_root,
        explicit_apply_requested=args.explicit_apply_requested,
        operator=args.operator.strip(),
        reviewer=args.reviewer.strip(),
        approver=args.approver.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
        expected_normal_final_pdf_sha256=args.expected_normal_final_pdf_sha256.strip(),
        expected_learned_trial_or_test_pdf_sha256=args.expected_learned_trial_or_test_pdf_sha256.strip(),
        expected_simulation_artifact_sha256=args.expected_simulation_artifact_sha256.strip(),
        expected_evidence_hash_artifact_sha256=args.expected_evidence_hash_artifact_sha256.strip(),
        evidence_hashes_path=(args.evidence_hashes or default_evidence_hashes_path(job_dir)).resolve(),
        apply_dry_run_path=(args.apply_dry_run or default_apply_dry_run_path(job_dir)).resolve(),
        apply_dry_run_review_path=(args.apply_dry_run_review or default_apply_dry_run_review_path(job_dir)).resolve(),
        sandbox_manifest_path=(args.sandbox_manifest or default_sandbox_manifest_path(job_dir)).resolve(),
        sandbox_rollback_verification_path=(args.sandbox_rollback_verification or default_sandbox_rollback_verification_path(job_dir)).resolve(),
        simulation_manifest_path_arg=(args.simulation_manifest or default_simulation_manifest_path(job_dir)).resolve(),
        simulated_validation_report_path_arg=(args.simulated_validation or default_simulated_validation_report_path(job_dir)).resolve(),
        simulated_rollback_verification_path_arg=(args.simulated_rollback_verification or default_simulated_rollback_verification_path(job_dir)).resolve(),
        backup_path_arg=args.backup_target.resolve() if args.backup_target else None,
    )
    write_artifact_bundle(
        job_dir=job_dir,
        apply_manifest=manifest,
        backup_manifest=backup,
        rollback_manifest=rollback,
        post_apply_validation=validation,
        apply_audit=audit,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
