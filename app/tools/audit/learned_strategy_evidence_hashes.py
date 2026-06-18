#!/usr/bin/env python3
"""Non-mutating learned-strategy evidence hash normalization.

Patch 22A records sha256 hashes for upstream evidence used by the learned
adoption/apply dry-run chain. It is sidecar-only: no apply, no backup, no
rollback, no rule-map mutation, no repair replacement, and no package/status
mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "learned-strategy-evidence-hashes.v1"
ARTIFACT_NAME = "learned_strategy_evidence_hashes.json"
MODE = "evidence_hashes_only"

ALLOWED_OUTCOMES = {
    "evidence_hashes_recorded",
    "evidence_hashes_incomplete",
    "evidence_hashes_blocked",
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
    "backup_created",
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "evidence_hashes_only": True,
    "adoption_apply_performed": False,
    "backup_created": False,
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
    "future_rollback_not_implemented": True,
}

EVIDENCE_KEYS = (
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
    "adoption_policy_design_report_sha256",
    "adoption_dry_run_plan_sha256",
    "adoption_dry_run_review_sha256",
    "adoption_apply_policy_design_sha256",
    "adoption_apply_dry_run_sha256",
)

REQUIRED_FOR_APPLY_DRY_RUN = {
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
}

DEFAULT_ARTIFACT_FILENAMES = {
    "production_readiness_report_sha256": "learned_strategy_production_readiness.json",
    "production_test_report_sha256": "learned_strategy_production_test.json",
    "production_test_review_report_sha256": "learned_strategy_production_test_review.json",
    "adoption_policy_design_report_sha256": "learned_strategy_adoption_policy_design.json",
    "adoption_dry_run_plan_sha256": "learned_strategy_adoption_dry_run_plan.json",
    "adoption_dry_run_review_sha256": "learned_strategy_adoption_dry_run_review.json",
    "adoption_apply_policy_design_sha256": "learned_strategy_adoption_apply_policy_design.json",
    "adoption_apply_dry_run_sha256": "learned_strategy_adoption_apply_dry_run.json",
}

PDF_PATH_KEYS = {
    "learned_trial_or_test_pdf",
    "learned_test_pdf",
    "learned_trial_pdf",
    "trial_pdf",
    "test_pdf",
    "output_pdf",
    "candidate_pdf",
    "artifact_pdf",
    "pdf",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def artifact_path(job_dir: Path) -> Path:
    return job_dir / "audit" / ARTIFACT_NAME


def snapshot_path(path: Path) -> Dict[str, Any]:
    return {
        "exists": path.exists(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
    }


def snapshot_tree(root: Path) -> Dict[str, Dict[str, Any]]:
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


def resolve_path(raw: Any, *, job_dir: Path, repo_root: Path) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend([job_dir / candidate, repo_root / candidate])
    # Docker artifacts often record /app/... while local tests run from repo root.
    text = raw.strip()
    if text.startswith("/app/"):
        candidates.append(repo_root / text[len("/app/"):])
    for p in candidates:
        if p.exists():
            return p.resolve()
    return candidates[0].resolve()


def recursive_find_path(data: Any, keys: Iterable[str]) -> Optional[str]:
    wanted = set(keys)
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key) in wanted and isinstance(value, str) and value.strip():
                return value
        for value in data.values():
            found = recursive_find_path(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find_path(item, keys)
            if found:
                return found
    return None


def status_final_pdf_path(job_dir: Path, repo_root: Path) -> Tuple[Optional[Path], str]:
    status_path = job_dir / "STATUS.json"
    candidate_paths: List[Path] = []

    if status_path.exists():
        data = load_json(status_path)
        raw = recursive_find_path(data, {"final_pdf", "normal_final_pdf", "authoritative_final_pdf"})
        if raw:
            candidate_paths.append(Path(raw))

    repair_dir = job_dir / "repair"
    if repair_dir.exists():
        candidate_paths.extend(sorted(repair_dir.glob("pass*_fix_cidset.pdf"), reverse=True))
        candidate_paths.extend(sorted(repair_dir.glob("pass*.pdf"), reverse=True))

    for candidate in candidate_paths:
        resolved = candidate if candidate.is_absolute() else (job_dir / candidate)
        if resolved.exists():
            return resolved, "normal_final_pdf_resolved_from_job"

    if not status_path.exists():
        return None, "missing_artifact:STATUS.json"
    return None, "normal_final_pdf_path_not_found"
def learned_trial_or_test_pdf_path(job_dir: Path, repo_root: Path) -> Tuple[Optional[Path], str]:
    audit = job_dir / "audit"
    for name in (
        "learned_strategy_production_test.json",
        "learned_strategy_replacement_trial.json",
        "learned_strategy_output_comparison.json",
    ):
        p = audit / name
        if not p.exists():
            continue
        try:
            data = load_json(p)
        except Exception:
            continue
        raw = recursive_find_path(data, PDF_PATH_KEYS)
        if raw:
            return resolve_path(raw, job_dir=job_dir, repo_root=repo_root), f"from_{name}"
    return None, "learned_trial_or_test_pdf_path_not_found"


def make_entry(
    *,
    key: str,
    path: Optional[Path],
    source_artifact: str,
    verified_at: str,
    missing_reason: Optional[str],
) -> Dict[str, Any]:
    exists = bool(path and path.exists() and path.is_file())
    return {
        "key": key,
        "path": str(path) if path else None,
        "exists": exists,
        "sha256": sha256_file(path) if exists and path else None,
        "source_artifact": source_artifact,
        "verified_at": verified_at,
        "missing_reason": None if exists else missing_reason,
    }


def evidence_targets(job_dir: Path, repo_root: Path) -> Dict[str, Tuple[Optional[Path], str, Optional[str]]]:
    audit = job_dir / "audit"
    targets: Dict[str, Tuple[Optional[Path], str, Optional[str]]] = {}

    normal_pdf, normal_source = status_final_pdf_path(job_dir, repo_root)
    targets["normal_final_pdf_sha256"] = (normal_pdf, normal_source, None if normal_pdf else normal_source)

    learned_pdf, learned_source = learned_trial_or_test_pdf_path(job_dir, repo_root)
    targets["learned_trial_or_test_pdf_sha256"] = (
        learned_pdf,
        learned_source,
        None if learned_pdf else learned_source,
    )

    for key, filename in DEFAULT_ARTIFACT_FILENAMES.items():
        p = audit / filename
        targets[key] = (p, filename, None if p.exists() else f"missing_artifact:{filename}")

    return targets


def validate_no_forbidden_states(candidate_id: str, rule_id: str) -> List[str]:
    blockers: List[str] = []
    for label, value in {"candidate_id": candidate_id, "rule_id": rule_id}.items():
        normalized = str(value).strip().lower()
        if normalized in FORBIDDEN_TERMINAL_STATES:
            blockers.append(f"forbidden_terminal_state_detected:{label}:{value}")
    return blockers


def build_artifact(*, job_dir: Path, repo_root: Path, candidate_id: str, rule_id: str) -> Dict[str, Any]:
    before = snapshot_protected(job_dir, repo_root)
    verified_at = utc_now()
    blockers = validate_no_forbidden_states(candidate_id, rule_id)

    entries: Dict[str, Dict[str, Any]] = {}
    for key, (path, source, missing_reason) in evidence_targets(job_dir, repo_root).items():
        entries[key] = make_entry(
            key=key,
            path=path,
            source_artifact=source,
            verified_at=verified_at,
            missing_reason=missing_reason,
        )

    missing_required = [
        key for key in sorted(REQUIRED_FOR_APPLY_DRY_RUN)
        if not entries.get(key, {}).get("sha256")
    ]

    outcome = "evidence_hashes_recorded"
    result = "PASS"
    if blockers:
        outcome = "evidence_hashes_blocked"
        result = "BLOCKED"
    elif missing_required:
        outcome = "evidence_hashes_incomplete"
        result = "INCOMPLETE"

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "evidence_hashes_blocked"
        result = "BLOCKED"

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": verified_at,
        "job_dir": str(job_dir),
        "artifact_path": str(artifact_path(job_dir)),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "evidence_hashes_outcome": outcome,
        "allowed_evidence_hash_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "missing_required_evidence_hashes": missing_required,
        "evidence_hashes": entries,
        "source_evidence_hashes": {key: entry.get("sha256") for key, entry in entries.items()},
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        **MANDATORY_SAFETY_FLAGS,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
    }
    return artifact


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    artifact = build_artifact(
        job_dir=job_dir,
        repo_root=repo_root,
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
    )
    out = artifact_path(job_dir)
    write_json(out, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
