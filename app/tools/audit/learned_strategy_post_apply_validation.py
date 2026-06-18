#!/usr/bin/env python3
"""Post-apply validation, rollback proof, and sidecar readiness gate.

Patch 26A validates the Patch 25A reviewed sidecar apply result without
promoting learned execution into the normal remediation pipeline. It never
mutates the rule map, never moves learned scripts into app/tools/repair, never
rewrites package/status authority, and never performs rollback against
authoritative files.
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

SCHEMA_VERSION = "learned-strategy-post-apply-validation.v1"
MODE = "post_apply_validation_only"
REVIEWED_APPLY_DIR_NAME = "learned_strategy_reviewed_apply"
APPLY_MANIFEST_NAME = "apply_manifest.json"
APPLY_AUDIT_NAME = "apply_audit.json"
BACKUP_MANIFEST_NAME = "backup_manifest.json"
ROLLBACK_MANIFEST_NAME = "rollback_manifest.json"
POST_APPLY_VALIDATION_NAME = "post_apply_validation.json"
ADOPTED_FINAL_NAME = "adopted_final.pdf"
BACKUP_DIR_NAME = "backups"
NORMAL_BACKUP_NAME = "normal_final_backup.pdf"
POST_APPLY_SOAK_REPORT_NAME = "post_apply_soak_report.json"
ROLLBACK_PROOF_REPORT_NAME = "rollback_proof_report.json"
PRODUCTION_READINESS_GATE_NAME = "production_readiness_gate.json"
ROLLBACK_PROOF_DIR_NAME = "rollback_proof_isolated"

ALLOWED_VALIDATION_OUTCOMES = {
    "post_apply_validation_passed",
    "post_apply_validation_blocked",
    "post_apply_validation_failed_closed",
    "production_readiness_sidecar_gate_recorded",
    "production_readiness_sidecar_gate_blocked",
}

READINESS_TERMINAL_STATES = {
    "sidecar_reviewed_adoption_production_ready",
    "sidecar_reviewed_adoption_blocked",
}

FORBIDDEN_TERMINAL_STATES = {
    "default_learned_execution_enabled",
    "global_candidate_approved",
    "global_candidate_production_ready",
    "global_apply_ready",
    "rule_map_mutated",
    "app_tools_repair_mutated",
    "verdict_softened",
    "package_status_mutated_silently",
    "package_integrated_adoption_enabled",
    "authoritative_rollback_performed",
    "package_integrated_adoption_ready",
    "global_learned_execution_ready",
    "candidate_globally_approved",
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
    "terminal_state",
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "post_apply_validation_only": True,
    "reviewed_sidecar_adoption_validated": True,
    "package_integrated_adoption_enabled": False,
    "default_learned_execution_enabled": False,
    "global_candidate_approved": False,
    "global_candidate_production_ready": False,
    "global_apply_ready": False,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "production_repair_replacement_performed": False,
    "verdict_softening_performed": False,
    "package_status_mutation_performed": False,
    "rollback_execution_against_authoritative_files": False,
    "authoritative_rollback_performed": False,
    "normal_pipeline_final_pdf_remains_authoritative": True,
}

ROLLBACK_PROOF_FLAGS: Dict[str, Any] = {
    "rollback_proof_scope": "isolated_validation_directory_only",
    "rollback_execution_against_authoritative_files": False,
    "authoritative_rollback_performed": False,
    "rollback_restored_hash_matches_backup": True,
}

REQUIRED_APPLY_FALSE_FLAGS = {
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

STATUS_RELATIVE_PATHS = (
    "STATUS.json",
    "deliverables/STATUS.json",
    "output/STATUS.json",
    "package/STATUS.json",
)


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


def apply_audit_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / APPLY_AUDIT_NAME


def backup_manifest_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / BACKUP_MANIFEST_NAME


def rollback_manifest_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ROLLBACK_MANIFEST_NAME


def source_post_apply_validation_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / POST_APPLY_VALIDATION_NAME


def adopted_final_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ADOPTED_FINAL_NAME


def normal_backup_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / BACKUP_DIR_NAME / NORMAL_BACKUP_NAME


def post_apply_soak_report_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / POST_APPLY_SOAK_REPORT_NAME


def rollback_proof_report_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ROLLBACK_PROOF_REPORT_NAME


def production_readiness_gate_path(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / PRODUCTION_READINESS_GATE_NAME


def rollback_proof_dir(job_dir: Path) -> Path:
    return reviewed_apply_dir(job_dir) / ROLLBACK_PROOF_DIR_NAME


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
    out: Dict[str, Dict[str, Any]] = {}
    for child in sorted(p for p in root.rglob("*") if p.is_file()):
        out[str(child)] = snapshot_path(child)
    return out


def protected_targets(job_dir: Path, repo_root: Path) -> List[Path]:
    targets = [
        repo_root / "app" / "tools" / "audit" / "rule_repair_map.json",
        repo_root / "app" / "tools" / "repair",
    ]
    targets.extend(Path(job_dir) / rel for rel in STATUS_RELATIVE_PATHS)
    return targets


def snapshot_protected(job_dir: Path, repo_root: Path) -> Dict[str, Dict[str, Any]]:
    snap: Dict[str, Dict[str, Any]] = {}
    for target in protected_targets(job_dir, repo_root):
        snap.update(snapshot_tree(target))
    return snap


def diff_snapshots(before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    mutations: List[Dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            mutations.append({"path": path, "before": before.get(path), "after": after.get(path)})
    return mutations


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def normalize(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


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
        blockers.append(f"missing_{label}")
        return {}
    try:
        return load_json(path)
    except Exception as exc:
        blockers.append(f"{label}_unreadable:{exc}")
        return {}


def artifact_hash_mismatch(path: Path, expected_hash: str, blockers: List[str], label: str) -> None:
    actual_hash = sha256_file(path)
    if not expected_hash.strip():
        blockers.append(f"missing_expected_{label}_hash")
    elif actual_hash != expected_hash.strip():
        blockers.append(f"{label}_hash_mismatch")


def validate_pdf(path: Path, qpdf_command: Optional[str] = None) -> Dict[str, Any]:
    command = qpdf_command or shutil.which("qpdf")
    result: Dict[str, Any] = {
        "qpdf_checked": True,
        "qpdf_available": bool(command),
        "qpdf_command": [command, "--check", str(path)] if command else None,
        "qpdf_exit_code": None,
        "qpdf_stdout": "",
        "qpdf_stderr": "",
        "valid": False,
    }
    if not command:
        result["qpdf_stderr"] = "qpdf unavailable; Patch 26A fails closed for adopted output validation"
        return result
    proc = subprocess.run([command, "--check", str(path)], text=True, capture_output=True, check=False)
    result.update({
        "qpdf_exit_code": proc.returncode,
        "qpdf_stdout": proc.stdout[-4000:],
        "qpdf_stderr": proc.stderr[-4000:],
        "valid": proc.returncode == 0,
    })
    return result


def check_identity_and_scope(
    *,
    apply_manifest: Dict[str, Any],
    apply_audit: Dict[str, Any],
    operator: str,
    reviewer: str,
    approver: str,
    candidate_id: str,
    rule_id: str,
    blockers: List[str],
) -> None:
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

    for label, artifact in (("apply_manifest", apply_manifest), ("apply_audit", apply_audit)):
        if not artifact:
            continue
        if artifact.get("operator") != operator:
            blockers.append(f"{label}_operator_mismatch")
        if artifact.get("reviewer") != reviewer:
            blockers.append(f"{label}_reviewer_mismatch")
        if artifact.get("approver") != approver:
            blockers.append(f"{label}_approver_mismatch")
        if artifact.get("candidate_id") != candidate_id:
            blockers.append(f"{label}_candidate_id_mismatch")
        if artifact.get("rule_id") != rule_id:
            blockers.append(f"{label}_rule_id_mismatch")

    safety = apply_manifest.get("safety_flags") if isinstance(apply_manifest.get("safety_flags"), dict) else {}
    if safety.get("reviewer_identity_recorded") is not True:
        blockers.append("reviewer_identity_not_recorded")
    if safety.get("approver_identity_recorded") is not True:
        blockers.append("approver_identity_not_recorded")
    if safety.get("separate_reviewer_and_approver") is not True:
        blockers.append("reviewer_approver_separation_not_recorded")
    for key in REQUIRED_APPLY_FALSE_FLAGS:
        if safety.get(key) is not False:
            blockers.append(f"apply_manifest_source_flag_not_false:{key}")


def validate_source_artifacts(
    *,
    apply_manifest: Dict[str, Any],
    apply_audit: Dict[str, Any],
    backup_manifest: Dict[str, Any],
    rollback_manifest: Dict[str, Any],
    post_apply_validation: Dict[str, Any],
    adopted_pdf: Path,
    backup_pdf: Path,
    expected_adopted_output_hash: str,
    expected_normal_backup_hash: str,
    blockers: List[str],
) -> Dict[str, Any]:
    if not adopted_pdf.exists():
        blockers.append("missing_adopted_final_pdf")
    else:
        artifact_hash_mismatch(adopted_pdf, expected_adopted_output_hash, blockers, "adopted_output")

    if not backup_pdf.exists():
        blockers.append("missing_normal_backup")
    else:
        artifact_hash_mismatch(backup_pdf, expected_normal_backup_hash, blockers, "normal_backup")

    if apply_manifest and apply_manifest.get("reviewed_apply_outcome") != "reviewed_apply_performed":
        blockers.append("apply_manifest_not_performed")
    if apply_manifest and apply_manifest.get("result") != "PASS":
        blockers.append("apply_manifest_not_pass")
    if apply_manifest and apply_manifest.get("adopted_output_sha256") != expected_adopted_output_hash:
        blockers.append("apply_manifest_adopted_output_hash_mismatch")

    if apply_audit:
        locked = apply_audit.get("locked_hashes") if isinstance(apply_audit.get("locked_hashes"), dict) else {}
        if locked.get("expected_learned_trial_or_test_pdf_sha256") != expected_adopted_output_hash:
            blockers.append("apply_audit_locked_adopted_hash_mismatch")
        if locked.get("expected_normal_final_pdf_sha256") != expected_normal_backup_hash:
            blockers.append("apply_audit_locked_backup_hash_mismatch")
        if apply_audit.get("package_status_mutation_performed") is True:
            blockers.append("apply_audit_package_status_mutation_true")

    if backup_manifest:
        entries = backup_manifest.get("entries")
        serialized = json.dumps(backup_manifest, sort_keys=True)
        if expected_normal_backup_hash not in serialized:
            blockers.append("backup_manifest_missing_expected_backup_hash")
        if not entries:
            blockers.append("backup_manifest_missing_entries")

    if rollback_manifest:
        serialized = json.dumps(rollback_manifest, sort_keys=True)
        if str(backup_pdf) not in serialized and NORMAL_BACKUP_NAME not in serialized:
            blockers.append("rollback_manifest_missing_normal_backup_reference")
        if rollback_manifest.get("rollback_execution_against_authoritative_files") is True:
            blockers.append("rollback_manifest_authoritative_rollback_true")

    validation_details = post_apply_validation.get("validation_details") if isinstance(post_apply_validation.get("validation_details"), dict) else {}
    validation_passed = (
        post_apply_validation.get("post_apply_validation_passed") is True
        or post_apply_validation.get("result") == "PASS"
        or validation_details.get("valid") is True
    )
    if not validation_passed:
        blockers.append("post_apply_validation_not_passed")

    return {"post_apply_validation_passed": validation_passed}


def build_post_apply_report(
    *,
    job_dir: Path,
    repo_root: Path,
    operator: str,
    reviewer: str,
    approver: str,
    candidate_id: str,
    rule_id: str,
    expected_adopted_output_hash: str,
    expected_normal_backup_hash: str,
    expected_apply_manifest_hash: str,
    expected_post_apply_validation_hash: str,
    qpdf_command: Optional[str] = None,
) -> Dict[str, Any]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    apply_dir = reviewed_apply_dir(job_dir).resolve()
    created_at = utc_now()
    before = snapshot_protected(job_dir, repo_root)
    blockers: List[str] = []
    failed_closed_reasons: List[str] = []

    manifest_path = apply_manifest_path(job_dir).resolve()
    audit_path = apply_audit_path(job_dir).resolve()
    backup_manifest_file = backup_manifest_path(job_dir).resolve()
    rollback_manifest_file = rollback_manifest_path(job_dir).resolve()
    validation_path = source_post_apply_validation_path(job_dir).resolve()
    adopted_pdf = adopted_final_path(job_dir).resolve()
    backup_pdf = normal_backup_path(job_dir).resolve()

    apply_manifest = load_required_json(manifest_path, blockers, "reviewed_apply_manifest")
    apply_audit = load_required_json(audit_path, blockers, "apply_audit")
    backup_manifest = load_required_json(backup_manifest_file, blockers, "backup_manifest")
    rollback_manifest = load_required_json(rollback_manifest_file, blockers, "rollback_manifest")
    post_apply_validation = load_required_json(validation_path, blockers, "post_apply_validation")

    if manifest_path.exists():
        artifact_hash_mismatch(manifest_path, expected_apply_manifest_hash, blockers, "apply_manifest")
    if validation_path.exists():
        artifact_hash_mismatch(validation_path, expected_post_apply_validation_hash, blockers, "post_apply_validation")

    check_identity_and_scope(
        apply_manifest=apply_manifest,
        apply_audit=apply_audit,
        operator=operator,
        reviewer=reviewer,
        approver=approver,
        candidate_id=candidate_id,
        rule_id=rule_id,
        blockers=blockers,
    )

    source_summary = validate_source_artifacts(
        apply_manifest=apply_manifest,
        apply_audit=apply_audit,
        backup_manifest=backup_manifest,
        rollback_manifest=rollback_manifest,
        post_apply_validation=post_apply_validation,
        adopted_pdf=adopted_pdf,
        backup_pdf=backup_pdf,
        expected_adopted_output_hash=expected_adopted_output_hash,
        expected_normal_backup_hash=expected_normal_backup_hash,
        blockers=blockers,
    )

    qpdf_validation = validate_pdf(adopted_pdf, qpdf_command=qpdf_command) if adopted_pdf.exists() else {"valid": False, "qpdf_checked": False}
    if adopted_pdf.exists() and qpdf_validation.get("valid") is not True:
        failed_closed_reasons.append("qpdf_validation_failed")

    for label, artifact in (
        ("apply_manifest", apply_manifest),
        ("apply_audit", apply_audit),
        ("backup_manifest", backup_manifest),
        ("rollback_manifest", rollback_manifest),
        ("post_apply_validation", post_apply_validation),
    ):
        hits = recursive_forbidden_state_hits(artifact)
        if hits:
            blockers.append(f"{label}_forbidden_terminal_state_detected:" + ",".join(sorted(set(hits))))

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")

    result = "PASS"
    outcome = "post_apply_validation_passed"
    if failed_closed_reasons:
        result = "FAILED_CLOSED"
        outcome = "post_apply_validation_failed_closed"
    if blockers:
        result = "BLOCKED" if not failed_closed_reasons else "FAILED_CLOSED"
        outcome = "post_apply_validation_blocked" if not failed_closed_reasons else "post_apply_validation_failed_closed"

    safety_flags = dict(MANDATORY_SAFETY_FLAGS)
    if result != "PASS":
        safety_flags["reviewed_sidecar_adoption_validated"] = False

    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": created_at,
        "job_dir": str(job_dir),
        "reviewed_apply_dir": str(apply_dir),
        "artifact_path": str(post_apply_soak_report_path(job_dir)),
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "post_apply_validation_outcome": outcome,
        "allowed_outcomes": sorted(ALLOWED_VALIDATION_OUTCOMES),
        "blockers": blockers,
        "failed_closed_reasons": failed_closed_reasons,
        "source_summary": source_summary,
        "source_artifacts": {
            "apply_manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "apply_audit": {"path": str(audit_path), "sha256": sha256_file(audit_path)},
            "backup_manifest": {"path": str(backup_manifest_file), "sha256": sha256_file(backup_manifest_file)},
            "rollback_manifest": {"path": str(rollback_manifest_file), "sha256": sha256_file(rollback_manifest_file)},
            "post_apply_validation": {"path": str(validation_path), "sha256": sha256_file(validation_path)},
            "adopted_final_pdf": {"path": str(adopted_pdf), "sha256": sha256_file(adopted_pdf)},
            "normal_final_backup_pdf": {"path": str(backup_pdf), "sha256": sha256_file(backup_pdf)},
        },
        "locked_hashes": {
            "expected_adopted_output_hash": expected_adopted_output_hash,
            "expected_normal_backup_hash": expected_normal_backup_hash,
            "expected_apply_manifest_hash": expected_apply_manifest_hash,
            "expected_post_apply_validation_hash": expected_post_apply_validation_hash,
        },
        "qpdf_validation": qpdf_validation,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
        "safety_flags": safety_flags,
        **safety_flags,
    }
    return report


def build_rollback_proof_report(
    *,
    job_dir: Path,
    repo_root: Path,
    operator: str,
    reviewer: str,
    approver: str,
    candidate_id: str,
    rule_id: str,
    expected_normal_backup_hash: str,
) -> Dict[str, Any]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    proof_dir = rollback_proof_dir(job_dir).resolve()
    created_at = utc_now()
    before = snapshot_protected(job_dir, repo_root)
    blockers: List[str] = []

    apply_dir = reviewed_apply_dir(job_dir).resolve()
    adopted_pdf = adopted_final_path(job_dir).resolve()
    backup_pdf = normal_backup_path(job_dir).resolve()
    if not adopted_pdf.exists():
        blockers.append("missing_adopted_final_pdf")
    if not backup_pdf.exists():
        blockers.append("missing_normal_backup")
    elif sha256_file(backup_pdf) != expected_normal_backup_hash:
        blockers.append("normal_backup_hash_mismatch")

    proof_adopted = proof_dir / "adopted_final.before_rollback.pdf"
    proof_backup = proof_dir / "normal_final_backup.source.pdf"
    proof_target = proof_dir / "normal_final.restored.pdf"
    write_targets = [proof_adopted, proof_backup, proof_target]
    for target in write_targets:
        if not path_is_inside(target, proof_dir):
            blockers.append(f"rollback_proof_write_outside_isolated_dir:{target}")

    restored_matches = False
    if not blockers:
        proof_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(adopted_pdf, proof_adopted)
        shutil.copy2(backup_pdf, proof_backup)
        shutil.copy2(proof_adopted, proof_target)
        proof_target.unlink()
        shutil.copy2(proof_backup, proof_target)
        restored_matches = sha256_file(proof_target) == sha256_file(backup_pdf) == expected_normal_backup_hash
        if not restored_matches:
            blockers.append("rollback_restored_hash_mismatch")

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")

    flags = dict(ROLLBACK_PROOF_FLAGS)
    flags["rollback_restored_hash_matches_backup"] = restored_matches and not blockers
    result = "PASS" if not blockers else "BLOCKED"

    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "rollback_proof_only",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "reviewed_apply_dir": str(apply_dir),
        "artifact_path": str(rollback_proof_report_path(job_dir)),
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "blockers": blockers,
        "proof_dir": str(proof_dir),
        "source_artifacts": {
            "real_adopted_final_pdf": {"path": str(adopted_pdf), "sha256": sha256_file(adopted_pdf)},
            "real_normal_backup_pdf": {"path": str(backup_pdf), "sha256": sha256_file(backup_pdf)},
            "proof_adopted_copy": {"path": str(proof_adopted), "sha256": sha256_file(proof_adopted)},
            "proof_backup_copy": {"path": str(proof_backup), "sha256": sha256_file(proof_backup)},
            "proof_restored_pdf": {"path": str(proof_target), "sha256": sha256_file(proof_target)},
        },
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
        "safety_flags": flags,
        **flags,
    }
    return report


def build_readiness_gate_report(
    *,
    job_dir: Path,
    repo_root: Path,
    operator: str,
    reviewer: str,
    approver: str,
    candidate_id: str,
    rule_id: str,
) -> Dict[str, Any]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    validation_report = load_required_json(post_apply_soak_report_path(job_dir), [], "post_apply_soak_report") if post_apply_soak_report_path(job_dir).exists() else {}
    rollback_report = load_required_json(rollback_proof_report_path(job_dir), [], "rollback_proof_report") if rollback_proof_report_path(job_dir).exists() else {}
    blockers: List[str] = []
    if not validation_report:
        blockers.append("missing_post_apply_soak_report")
    elif validation_report.get("result") != "PASS":
        blockers.append("post_apply_validation_not_pass")
    if not rollback_report:
        blockers.append("missing_rollback_proof_report")
    elif rollback_report.get("rollback_restored_hash_matches_backup") is not True:
        blockers.append("rollback_proof_not_verified")

    for label, artifact in (("validation_report", validation_report), ("rollback_report", rollback_report)):
        hits = recursive_forbidden_state_hits(artifact)
        if hits:
            blockers.append(f"{label}_forbidden_terminal_state_detected:" + ",".join(sorted(set(hits))))

    terminal_state = "sidecar_reviewed_adoption_production_ready" if not blockers else "sidecar_reviewed_adoption_blocked"
    result = "PASS" if not blockers else "BLOCKED"
    safety_flags = dict(MANDATORY_SAFETY_FLAGS)
    safety_flags["reviewed_sidecar_adoption_validated"] = result == "PASS"

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "sidecar_production_readiness_gate_only",
        "created_at": utc_now(),
        "job_dir": str(job_dir),
        "artifact_path": str(production_readiness_gate_path(job_dir)),
        "operator": operator,
        "reviewer": reviewer,
        "approver": approver,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "production_readiness_terminal_state": terminal_state,
        "allowed_terminal_states": sorted(READINESS_TERMINAL_STATES),
        "post_apply_validation_outcome": "production_readiness_sidecar_gate_recorded" if not blockers else "production_readiness_sidecar_gate_blocked",
        "blockers": blockers,
        "forbidden_states_not_emitted": sorted(FORBIDDEN_TERMINAL_STATES),
        "package_integrated_adoption_ready": False,
        "global_learned_execution_ready": False,
        "candidate_globally_approved": False,
        "safety_flags": safety_flags,
        **safety_flags,
    }


def write_selected_reports(job_dir: Path, reports: Iterable[Dict[str, Any]]) -> None:
    for report in reports:
        path = Path(report["artifact_path"])
        write_json(path, report)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--mode", choices=("validate", "rollback-proof", "readiness-gate", "all"), default="validate")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--expected-adopted-output-hash", required=True)
    parser.add_argument("--expected-normal-backup-hash", required=True)
    parser.add_argument("--expected-apply-manifest-hash", required=True)
    parser.add_argument("--expected-post-apply-validation-hash", required=True)
    parser.add_argument("--qpdf-command", default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    reports: List[Dict[str, Any]] = []
    if args.mode in {"validate", "all"}:
        reports.append(build_post_apply_report(
            job_dir=args.job_dir,
            repo_root=args.repo_root,
            operator=args.operator.strip(),
            reviewer=args.reviewer.strip(),
            approver=args.approver.strip(),
            candidate_id=args.candidate_id.strip(),
            rule_id=args.rule_id.strip(),
            expected_adopted_output_hash=args.expected_adopted_output_hash.strip(),
            expected_normal_backup_hash=args.expected_normal_backup_hash.strip(),
            expected_apply_manifest_hash=args.expected_apply_manifest_hash.strip(),
            expected_post_apply_validation_hash=args.expected_post_apply_validation_hash.strip(),
            qpdf_command=args.qpdf_command,
        ))
    if args.mode in {"rollback-proof", "all"}:
        reports.append(build_rollback_proof_report(
            job_dir=args.job_dir,
            repo_root=args.repo_root,
            operator=args.operator.strip(),
            reviewer=args.reviewer.strip(),
            approver=args.approver.strip(),
            candidate_id=args.candidate_id.strip(),
            rule_id=args.rule_id.strip(),
            expected_normal_backup_hash=args.expected_normal_backup_hash.strip(),
        ))
    write_selected_reports(args.job_dir, reports)
    if args.mode in {"readiness-gate", "all"}:
        gate = build_readiness_gate_report(
            job_dir=args.job_dir,
            repo_root=args.repo_root,
            operator=args.operator.strip(),
            reviewer=args.reviewer.strip(),
            approver=args.approver.strip(),
            candidate_id=args.candidate_id.strip(),
            rule_id=args.rule_id.strip(),
        )
        write_selected_reports(args.job_dir, [gate])
        reports.append(gate)
    summary = reports[-1] if reports else {}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("result") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
