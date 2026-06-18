#!/usr/bin/env python3
"""Isolated learned-strategy apply backup/rollback sandbox.

Patch 23A creates backup-like copies and rollback-like manifests only under an
isolated audit sandbox:

    JOB/audit/learned_strategy_apply_sandbox/

It never performs adoption apply, never creates production backups, never
executes rollback against authoritative files, never mutates package/status
outputs, never mutates app/tools/repair, and never mutates the rule map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "learned-strategy-apply-sandbox.v1"
MODE = "apply_sandbox_only"
SANDBOX_DIR_NAME = "learned_strategy_apply_sandbox"
SANDBOX_MANIFEST_NAME = "sandbox_manifest.json"
BACKUP_MANIFEST_NAME = "backup_manifest.json"
ROLLBACK_MANIFEST_NAME = "rollback_manifest.json"
ROLLBACK_VERIFICATION_NAME = "rollback_verification.json"

EVIDENCE_HASH_ARTIFACT_NAME = "learned_strategy_evidence_hashes.json"
APPLY_DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run.json"
APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run_review.json"

ALLOWED_OUTCOMES = {
    "apply_sandbox_recorded",
    "apply_sandbox_incomplete",
    "apply_sandbox_blocked",
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
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "apply_sandbox_only": True,
    "sandbox_backup_created": True,
    "production_backup_created": False,
    "adoption_apply_performed": False,
    "rollback_execution_performed": False,
    "production_rollback_performed": False,
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

ROLLBACK_VERIFICATION_FLAGS: Dict[str, Any] = {
    "rollback_verification_scope": "sandbox_only",
    "rollback_execution_against_authoritative_files": False,
    "sandbox_rollback_verified": True,
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

REQUIRED_EVIDENCE_KEYS = {
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
}

FORBIDDEN_STATE_KEYS = {
    "state",
    "status",
    "candidate_state",
    "candidate_status",
    "approval_state",
    "adoption_state",
    "readiness_state",
    "review_decision",
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


def sandbox_dir(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / SANDBOX_DIR_NAME


def sandbox_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / SANDBOX_MANIFEST_NAME


def backup_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / BACKUP_MANIFEST_NAME


def rollback_manifest_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / ROLLBACK_MANIFEST_NAME


def rollback_verification_path(job_dir: Path) -> Path:
    return sandbox_dir(job_dir) / ROLLBACK_VERIFICATION_NAME


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
    mutations: List[Dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            mutations.append({"path": path, "before": before.get(path), "after": after.get(path)})
    return mutations


def normalize(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def default_evidence_hashes_path(job_dir: Path) -> Path:
    return job_dir / "audit" / EVIDENCE_HASH_ARTIFACT_NAME


def default_apply_dry_run_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_DRY_RUN_ARTIFACT_NAME


def default_apply_dry_run_review_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME


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


def copy_into_sandbox(source: Path, destination: Path) -> Dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "source_path": str(source),
        "sandbox_copy_path": str(destination),
        "source_sha256": sha256_file(source),
        "sandbox_copy_sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size if destination.exists() else None,
    }


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_sandbox_files_only(sandbox: Path, paths: Iterable[Path]) -> List[str]:
    blockers: List[str] = []
    for path in paths:
        if not path_is_inside(path, sandbox):
            blockers.append(f"sandbox_write_outside_isolated_dir:{path}")
    return blockers


def load_optional_json(path: Path, blockers: List[str], label: str) -> Dict[str, Any]:
    if not path.exists():
        blockers.append(f"missing_{label}_artifact")
        return {}
    try:
        return load_json(path)
    except Exception as exc:
        blockers.append(f"{label}_artifact_unreadable:{exc}")
        return {}


def build_artifacts(
    *,
    job_dir: Path,
    repo_root: Path,
    operator: str,
    candidate_id: str,
    rule_id: str,
    evidence_hashes_path: Path,
    apply_dry_run_path: Path,
    apply_dry_run_review_path: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    sandbox = sandbox_dir(job_dir).resolve()

    before = snapshot_protected(job_dir, repo_root)
    created_at = utc_now()
    blockers: List[str] = []
    incomplete_reasons: List[str] = []

    if not operator.strip():
        blockers.append("missing_operator")
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

    if not blockers and not incomplete_reasons and normal_path and learned_path:
        copied_entries.append(copy_into_sandbox(normal_path, sandbox / "backups" / "normal_final_pdf.pdf"))
        copied_entries.append(copy_into_sandbox(learned_path, sandbox / "backups" / "learned_trial_or_test_pdf.pdf"))
        copied_entries.append(copy_into_sandbox(normal_path, sandbox / "simulated_targets" / "future_normal_final_pdf_target.pdf"))
        copied_entries.append(copy_into_sandbox(learned_path, sandbox / "simulated_targets" / "future_learned_trial_or_test_pdf_target.pdf"))
        for artifact_path in (evidence_hashes_path, apply_dry_run_path, apply_dry_run_review_path):
            copied_entries.append(copy_into_sandbox(artifact_path, sandbox / "evidence" / artifact_path.name))
        copied_files.extend(Path(entry["sandbox_copy_path"]) for entry in copied_entries)

    backup_entries = [
        {
            "label": "normal_final_pdf",
            "future_authoritative_target": str(normal_path) if normal_path else None,
            "sandbox_backup_path": str(sandbox / "backups" / "normal_final_pdf.pdf"),
            "expected_sha256": normal_hash,
            "actual_sandbox_sha256": sha256_file(sandbox / "backups" / "normal_final_pdf.pdf"),
            "production_backup_created": False,
            "sandbox_backup_created": bool((sandbox / "backups" / "normal_final_pdf.pdf").exists()),
        },
        {
            "label": "learned_trial_or_test_pdf",
            "future_reference_target": str(learned_path) if learned_path else None,
            "sandbox_backup_path": str(sandbox / "backups" / "learned_trial_or_test_pdf.pdf"),
            "expected_sha256": learned_hash,
            "actual_sandbox_sha256": sha256_file(sandbox / "backups" / "learned_trial_or_test_pdf.pdf"),
            "production_backup_created": False,
            "sandbox_backup_created": bool((sandbox / "backups" / "learned_trial_or_test_pdf.pdf").exists()),
        },
    ]

    rollback_entries = [
        {
            "label": "normal_final_pdf",
            "authoritative_target_not_mutated": str(normal_path) if normal_path else None,
            "sandbox_backup_path": str(sandbox / "backups" / "normal_final_pdf.pdf"),
            "sandbox_restore_path": str(sandbox / "rollback_verification" / "normal_final_pdf.restored.pdf"),
            "expected_restored_sha256": normal_hash,
            "rollback_execution_against_authoritative_files": False,
        },
        {
            "label": "learned_trial_or_test_pdf",
            "authoritative_target_not_mutated": str(learned_path) if learned_path else None,
            "sandbox_backup_path": str(sandbox / "backups" / "learned_trial_or_test_pdf.pdf"),
            "sandbox_restore_path": str(sandbox / "rollback_verification" / "learned_trial_or_test_pdf.restored.pdf"),
            "expected_restored_sha256": learned_hash,
            "rollback_execution_against_authoritative_files": False,
        },
    ]

    rollback_verified = False
    rollback_checks: List[Dict[str, Any]] = []
    if not blockers and not incomplete_reasons:
        for entry in rollback_entries:
            backup = Path(entry["sandbox_backup_path"])
            restored = Path(entry["sandbox_restore_path"])
            if backup.exists():
                restored.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, restored)
                copied_files.append(restored)
            check = {
                "label": entry["label"],
                "backup_path": str(backup),
                "restored_path": str(restored),
                "backup_sha256": sha256_file(backup),
                "restored_sha256": sha256_file(restored),
                "expected_sha256": entry["expected_restored_sha256"],
                "sandbox_only": True,
                "matches": sha256_file(backup) == sha256_file(restored) == entry["expected_restored_sha256"],
            }
            rollback_checks.append(check)
        rollback_verified = bool(rollback_checks) and all(check["matches"] for check in rollback_checks)
        if not rollback_verified:
            blockers.append("sandbox_rollback_verification_failed")

    manifest_paths = [
        sandbox_manifest_path(job_dir),
        backup_manifest_path(job_dir),
        rollback_manifest_path(job_dir),
        rollback_verification_path(job_dir),
    ]
    blockers.extend(validate_sandbox_files_only(sandbox, [*copied_files, *manifest_paths]))

    outcome = "apply_sandbox_recorded"
    result = "PASS"
    if blockers:
        outcome = "apply_sandbox_blocked"
        result = "BLOCKED"
    elif incomplete_reasons:
        outcome = "apply_sandbox_incomplete"
        result = "INCOMPLETE"

    backup_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "sandbox_backup_manifest",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "sandbox_dir": str(sandbox),
        "operator": operator,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "entries": backup_entries,
        "future_backup_targets": backup_entries,
        "production_backup_created": False,
        "sandbox_backup_created": any(entry["sandbox_backup_created"] for entry in backup_entries),
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
    }

    rollback_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "sandbox_rollback_manifest",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "sandbox_dir": str(sandbox),
        "operator": operator,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "entries": rollback_entries,
        "future_rollback_targets": rollback_entries,
        "rollback_execution_against_authoritative_files": False,
        "production_rollback_performed": False,
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
    }

    rollback_verification = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "sandbox_rollback_verification",
        "created_at": created_at,
        "job_dir": str(job_dir),
        "sandbox_dir": str(sandbox),
        "operator": operator,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "checks": rollback_checks,
        **ROLLBACK_VERIFICATION_FLAGS,
        "sandbox_rollback_verified": rollback_verified if not blockers and not incomplete_reasons else False,
        "production_rollback_performed": False,
    }

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "apply_sandbox_blocked"
        result = "BLOCKED"

    sandbox_manifest = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": created_at,
        "job_dir": str(job_dir),
        "sandbox_dir": str(sandbox),
        "artifact_path": str(sandbox_manifest_path(job_dir)),
        "backup_manifest_path": str(backup_manifest_path(job_dir)),
        "rollback_manifest_path": str(rollback_manifest_path(job_dir)),
        "rollback_verification_path": str(rollback_verification_path(job_dir)),
        "operator": operator,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "apply_sandbox_outcome": outcome,
        "allowed_apply_sandbox_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "incomplete_reasons": incomplete_reasons,
        "source_artifacts": {
            "evidence_hashes": {
                "path": str(evidence_hashes_path),
                "sha256": sha256_file(evidence_hashes_path),
                "result": evidence.get("result") if evidence else None,
            },
            "apply_dry_run": {
                "path": str(apply_dry_run_path),
                "sha256": sha256_file(apply_dry_run_path),
                "result": apply_dry_run.get("result") if apply_dry_run else None,
            },
            "apply_dry_run_review": {
                "path": str(apply_dry_run_review_path),
                "sha256": sha256_file(apply_dry_run_review_path),
                "result": apply_review.get("result") if apply_review else None,
            },
        },
        "source_evidence_hashes": {
            "normal_final_pdf_sha256": normal_hash,
            "learned_trial_or_test_pdf_sha256": learned_hash,
        },
        "copied_files": [str(path) for path in copied_files],
        "sandbox_backup_created": any(entry["sandbox_backup_created"] for entry in backup_entries),
        "production_backup_created": False,
        "rollback_execution_against_authoritative_files": False,
        "production_rollback_performed": False,
        "rollback_verification": rollback_verification,
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        **MANDATORY_SAFETY_FLAGS,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
    }

    return sandbox_manifest, backup_manifest, rollback_manifest, rollback_verification


def write_artifact_bundle(
    *,
    job_dir: Path,
    sandbox_manifest: Dict[str, Any],
    backup_manifest: Dict[str, Any],
    rollback_manifest: Dict[str, Any],
    rollback_verification: Dict[str, Any],
) -> None:
    write_json(sandbox_manifest_path(job_dir), sandbox_manifest)
    write_json(backup_manifest_path(job_dir), backup_manifest)
    write_json(rollback_manifest_path(job_dir), rollback_manifest)
    write_json(rollback_verification_path(job_dir), rollback_verification)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--operator", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--evidence-hashes", type=Path, default=None)
    parser.add_argument("--apply-dry-run", type=Path, default=None)
    parser.add_argument("--apply-dry-run-review", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    evidence_path = (args.evidence_hashes or default_evidence_hashes_path(job_dir)).resolve()
    dry_run_path = (args.apply_dry_run or default_apply_dry_run_path(job_dir)).resolve()
    review_path = (args.apply_dry_run_review or default_apply_dry_run_review_path(job_dir)).resolve()

    sandbox_manifest, backup_manifest, rollback_manifest, rollback_verification = build_artifacts(
        job_dir=job_dir,
        repo_root=repo_root,
        operator=args.operator.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
        evidence_hashes_path=evidence_path,
        apply_dry_run_path=dry_run_path,
        apply_dry_run_review_path=review_path,
    )
    write_artifact_bundle(
        job_dir=job_dir,
        sandbox_manifest=sandbox_manifest,
        backup_manifest=backup_manifest,
        rollback_manifest=rollback_manifest,
        rollback_verification=rollback_verification,
    )
    print(json.dumps(sandbox_manifest, indent=2, sort_keys=True))
    return 0 if sandbox_manifest["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
