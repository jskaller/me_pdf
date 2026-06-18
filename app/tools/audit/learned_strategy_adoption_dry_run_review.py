#!/usr/bin/env python3
"""Non-mutating learned-strategy adoption dry-run review/freeze gate.

Patch 20C records a review artifact over a Patch 20B adoption dry-run plan.
It never performs adoption apply, never creates backups, never executes rollback,
and never mutates production repair, rule-map, status, package, or final-PDF
artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA_VERSION = "learned-strategy-adoption-dry-run-review.v1"
DRY_RUN_SCHEMA_VERSION = "learned-strategy-adoption-dry-run.v1"
DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_dry_run_plan.json"
REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_dry_run_review.json"
MODE = "adoption_dry_run_review_only"

ALLOWED_REVIEW_DECISIONS = {
    "dry_run_review_recorded",
    "dry_run_review_requires_followup",
    "dry_run_review_rejected",
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
}

FORBIDDEN_STATE_TOKENS = {
    "approved",
    "adoptable",
    "production_ready",
    "production-ready",
    "production ready",
    "ready_for_adoption",
    "ready-for-adoption",
    "ready for adoption",
    "adoption_unblocked",
    "apply_ready",
    "apply-ready",
    "approved_for_apply",
    "frozen_for_apply",
    "frozen-for-apply",
    "frozen for apply",
}

MANDATORY_SAFETY_FLAGS = {
    "adoption_dry_run_review_only": True,
    "dry_run_plan_reviewed": True,
    "dry_run_plan_hash_recorded": True,
    "candidate_is_adoptable": False,
    "candidate_approved": False,
    "candidate_production_ready": False,
    "candidate_apply_ready": False,
    "adoption_apply_performed": False,
    "backup_created": False,
    "rollback_execution_performed": False,
    "final_pdf_adoption_performed": False,
    "production_repair_replacement_performed": False,
    "verdict_softening_performed": False,
    "package_status_mutation_performed": False,
    "normal_final_pdf_remains_authoritative": True,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "future_apply_not_implemented": True,
}

REQUIRED_PLAN_FLAGS = {
    "adoption_dry_run_only": True,
    "adoption_plan_created": True,
    "adoption_apply_performed": False,
    "backup_created": False,
    "rollback_execution_performed": False,
    "candidate_is_adoptable": False,
    "candidate_approved": False,
    "candidate_production_ready": False,
    "final_pdf_adoption_performed": False,
    "production_repair_replacement_performed": False,
    "verdict_softening_performed": False,
    "package_status_mutation_performed": False,
    "normal_final_pdf_remains_authoritative": True,
    "rule_map_mutation_performed": False,
    "app_tools_repair_mutation_performed": False,
    "plan_is_non_executable_without_future_patch": True,
    "future_apply_not_implemented": True,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")
    tmp.replace(path)


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


def _dedupe(paths: Iterable[Path]) -> List[Path]:
    deduped: Dict[str, Path] = {}
    for path in paths:
        p = Path(path)
        deduped[str(p)] = p
    return [deduped[k] for k in sorted(deduped)]


def _snapshot(paths: Iterable[Path]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        path = Path(path)
        out[str(path)] = {
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
            "sha256": sha256_file(path),
        }
    return out


def _status_json_paths(job_dir: Path) -> List[Path]:
    candidates = [
        job_dir / "STATUS.json",
        job_dir / "package" / "STATUS.json",
        job_dir / "deliverables" / "STATUS.json",
        job_dir / "output" / "STATUS.json",
    ]
    if job_dir.exists():
        candidates.extend(sorted(p for p in job_dir.rglob("STATUS.json") if p.is_file()))
    return _dedupe(candidates)


def _package_deliverables(job_dir: Path) -> List[Path]:
    names = {"AUDIT_REPORT.md", "CHECKSUMS.json", "MANIFEST.json", "STATUS.json"}
    paths: List[Path] = []
    for root in [job_dir / "package", job_dir / "deliverables", job_dir / "output"]:
        if root.exists():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    if job_dir.exists():
        paths.extend(p for p in job_dir.iterdir() if p.is_file() and p.name in names)
    return _dedupe(paths)


def _rule_map_path(repo_root: Optional[Path], job_dir: Path) -> Path:
    if repo_root:
        return Path(repo_root) / "app" / "tools" / "audit" / "rule_repair_map.json"
    return job_dir.parent.parent / "app" / "tools" / "audit" / "rule_repair_map.json"


def _repair_root(repo_root: Optional[Path], job_dir: Path) -> Path:
    if repo_root:
        return Path(repo_root) / "app" / "tools" / "repair"
    return job_dir.parent.parent / "app" / "tools" / "repair"


def _repair_files(repo_root: Optional[Path], job_dir: Path) -> List[Path]:
    root = _repair_root(repo_root, job_dir)
    if root.exists() and root.is_dir():
        return sorted(p for p in root.rglob("*") if p.is_file())
    return [root]


def _protected_paths(job_dir: Path, repo_root: Optional[Path]) -> List[Path]:
    return _dedupe([
        _rule_map_path(repo_root, job_dir),
        *_repair_files(repo_root, job_dir),
        *_status_json_paths(job_dir),
        *_package_deliverables(job_dir),
    ])


def _plan_path(job_dir: Path, explicit_path: Optional[Path]) -> Path:
    if explicit_path:
        return Path(explicit_path)
    return Path(job_dir) / "audit" / DRY_RUN_ARTIFACT_NAME


def _review_path(job_dir: Path, explicit_path: Optional[Path]) -> Path:
    if explicit_path:
        return Path(explicit_path)
    return Path(job_dir) / "audit" / REVIEW_ARTIFACT_NAME


def _policy_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    policy = payload.get("safety_flags")
    return policy if isinstance(policy, dict) else {}


def _contains_forbidden_terminal_state(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if clean_str(key) == "forbidden_terminal_states":
                continue
            found = _contains_forbidden_terminal_state(child)
            if found:
                return found
        return None
    if isinstance(value, list):
        for child in value:
            found = _contains_forbidden_terminal_state(child)
            if found:
                return found
        return None
    text = clean_str(value).lower()
    if not text:
        return None
    for token in FORBIDDEN_STATE_TOKENS:
        if token in text:
            return token
    return None


def _validate_plan_payload(plan_payload: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if clean_str(plan_payload.get("schema_version")) != DRY_RUN_SCHEMA_VERSION:
        blockers.append("dry_run_plan_schema_version_is_not_patch_20b")
    if clean_str(plan_payload.get("mode")) != "adoption_dry_run_planner_only":
        blockers.append("dry_run_plan_mode_is_not_planner_only")
    if clean_str(plan_payload.get("dry_run_outcome")) not in {
        "adoption_dry_run_plan_recorded",
        "adoption_dry_run_incomplete",
        "adoption_dry_run_blocked",
    }:
        blockers.append("dry_run_plan_outcome_is_not_non_adoptive")
    flags = _policy_flags(plan_payload)
    for name, expected in REQUIRED_PLAN_FLAGS.items():
        if flags.get(name) is not expected:
            blockers.append(f"dry_run_plan_flag_not_safe:{name}")
    if plan_payload.get("protected_mutation_count", 0) not in (0, None):
        blockers.append("dry_run_plan_reports_protected_mutations")
    forbidden = _contains_forbidden_terminal_state({
        "review_decision": plan_payload.get("review_decision"),
        "dry_run_outcome": plan_payload.get("dry_run_outcome"),
        "terminal_state": plan_payload.get("terminal_state"),
        "adoption_state": plan_payload.get("adoption_state"),
        "future_state": plan_payload.get("future_state"),
        "freeze_state": plan_payload.get("freeze_state"),
    })
    if forbidden:
        blockers.append(f"forbidden_terminal_state_present:{forbidden}")
    return blockers


def _blocked_payload(
    *,
    job_dir: Path,
    review_path: Path,
    plan_path: Path,
    blockers: Sequence[str],
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": "BLOCKED",
        "review_decision": "dry_run_review_requires_followup",
        "blockers": sorted(set(blockers)),
        "details": details or {},
        "job_dir": str(job_dir),
        "dry_run_plan": {
            "path": str(plan_path),
            "sha256": sha256_file(plan_path),
        },
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        "allowed_review_decisions": sorted(ALLOWED_REVIEW_DECISIONS),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "artifact_path": str(review_path),
        "evidence_freeze_state": "evidence_snapshot_not_frozen_review_blocked",
    }
    write_json_atomic(review_path, payload)
    return payload


def write_learned_strategy_adoption_dry_run_review(
    *,
    job_dir: Path,
    dry_run_plan_path: Optional[Path] = None,
    dry_run_plan_sha256: str = "",
    output_path: Optional[Path] = None,
    reviewer: str = "",
    candidate_id: str = "",
    rule_id: str = "",
    review_decision: str = "",
    review_notes: Optional[Sequence[str]] = None,
    known_risks: Optional[Sequence[str]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write a review artifact over a Patch 20B dry-run plan and mutate nothing else."""
    job_dir = Path(job_dir)
    plan_path = _plan_path(job_dir, dry_run_plan_path)
    review_artifact_path = _review_path(job_dir, output_path)
    reviewer = clean_str(reviewer)
    candidate_id = clean_str(candidate_id)
    rule_id = clean_str(rule_id)
    supplied_plan_hash = clean_str(dry_run_plan_sha256)
    review_decision = clean_str(review_decision)
    notes = [clean_str(note) for note in (review_notes or []) if clean_str(note)]
    risks = [clean_str(risk) for risk in (known_risks or []) if clean_str(risk)]

    protected_paths = _protected_paths(job_dir, repo_root)
    before_snapshot = _snapshot(protected_paths)

    blockers: List[str] = []
    if not plan_path.exists() or not plan_path.is_file():
        blockers.append("missing_dry_run_plan")
    if not reviewer:
        blockers.append("missing_reviewer_identity")
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not rule_id:
        blockers.append("missing_rule_id")
    if not supplied_plan_hash:
        blockers.append("missing_dry_run_plan_hash")
    if not review_decision:
        blockers.append("missing_review_decision")
    elif review_decision not in ALLOWED_REVIEW_DECISIONS:
        if review_decision in FORBIDDEN_TERMINAL_STATES:
            blockers.append(f"forbidden_review_decision:{review_decision}")
        else:
            blockers.append("unsupported_review_decision")
    if not notes:
        blockers.append("missing_review_notes")
    if not risks:
        blockers.append("missing_known_risks")

    plan_payload: Dict[str, Any] = {}
    actual_plan_hash = sha256_file(plan_path)
    if plan_path.exists() and plan_path.is_file():
        try:
            plan_payload = load_json(plan_path)
        except Exception as exc:
            blockers.append("invalid_dry_run_plan_json")
            plan_payload = {"load_error": f"{type(exc).__name__}: {exc}"}
        else:
            blockers.extend(_validate_plan_payload(plan_payload))
            if candidate_id and clean_str(plan_payload.get("candidate_id")) != candidate_id:
                blockers.append("candidate_id_mismatch")
            if rule_id and clean_str(plan_payload.get("rule_id")) != rule_id:
                blockers.append("rule_id_mismatch")
    if supplied_plan_hash and actual_plan_hash and supplied_plan_hash != actual_plan_hash:
        blockers.append("dry_run_plan_hash_mismatch")

    forbidden = _contains_forbidden_terminal_state({
        "review_decision": review_decision,
        "review_notes": notes,
        "known_risks": risks,
    })
    if forbidden:
        blockers.append(f"forbidden_terminal_state_present:{forbidden}")

    if blockers:
        return _blocked_payload(
            job_dir=job_dir,
            review_path=review_artifact_path,
            plan_path=plan_path,
            blockers=blockers,
            details={
                "reviewer": reviewer,
                "candidate_id": candidate_id,
                "rule_id": rule_id,
                "review_decision": review_decision,
                "supplied_dry_run_plan_sha256": supplied_plan_hash,
                "actual_dry_run_plan_sha256": actual_plan_hash,
            },
        )

    review: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "adoption_dry_run_review_only": True,
        "result": "PASS" if review_decision == "dry_run_review_recorded" else "REVIEW_REQUIRED",
        "review_decision": review_decision,
        "review_scope": "dry_run_evidence_review_only_not_approval",
        "job_dir": str(job_dir),
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "dry_run_plan": {
            "path": str(plan_path),
            "sha256": actual_plan_hash,
            "supplied_sha256": supplied_plan_hash,
            "hash_match": supplied_plan_hash == actual_plan_hash,
        },
        "dry_run_plan_reviewed": True,
        "dry_run_plan_hash_recorded": True,
        "review_notes": notes,
        "known_risks": risks,
        "evidence_freeze_state": "evidence_snapshot_frozen_for_future_discussion",
        "freeze_is_apply_ready": False,
        "candidate_is_adoptable": False,
        "candidate_approved": False,
        "candidate_production_ready": False,
        "candidate_apply_ready": False,
        "adoption_apply_performed": False,
        "backup_created": False,
        "rollback_execution_performed": False,
        "final_pdf_adoption_performed": False,
        "production_repair_replacement_performed": False,
        "verdict_softening_performed": False,
        "package_status_mutation_performed": False,
        "normal_final_pdf_remains_authoritative": True,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "future_apply_not_implemented": True,
        "plan_is_non_executable_without_future_patch": True,
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        "allowed_review_decisions": sorted(ALLOWED_REVIEW_DECISIONS),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "source_dry_run_outcome": plan_payload.get("dry_run_outcome"),
        "source_dry_run_blockers": plan_payload.get("blockers", []),
        "source_plan_safety_flags": _policy_flags(plan_payload),
        "artifact_path": str(review_artifact_path),
        "protected_snapshot_before": before_snapshot,
    }
    write_json_atomic(review_artifact_path, review)
    after_snapshot = _snapshot(protected_paths)
    protected_mutations = [path for path, before in before_snapshot.items() if after_snapshot.get(path) != before]
    review["protected_snapshot_after"] = after_snapshot
    review["protected_mutation_count"] = len(protected_mutations)
    review["protected_mutations"] = protected_mutations
    if protected_mutations:
        review["result"] = "BLOCKED"
        review["review_decision"] = "dry_run_review_requires_followup"
        review["blockers"] = ["protected_artifact_mutation_detected"]
    else:
        review["blockers"] = []
    write_json_atomic(review_artifact_path, review)
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Write non-mutating adoption dry-run review/freeze artifact")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--dry-run-plan", required=True)
    parser.add_argument("--dry-run-plan-sha256", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--review-decision", required=True, choices=sorted(ALLOWED_REVIEW_DECISIONS))
    parser.add_argument("--review-notes", action="append", required=True)
    parser.add_argument("--known-risks", action="append", required=True)
    parser.add_argument("--repo-root", default="/")
    ns = parser.parse_args()
    payload = write_learned_strategy_adoption_dry_run_review(
        job_dir=Path(ns.job_dir),
        dry_run_plan_path=Path(ns.dry_run_plan),
        dry_run_plan_sha256=ns.dry_run_plan_sha256,
        output_path=Path(ns.output) if ns.output else None,
        reviewer=ns.reviewer,
        candidate_id=ns.candidate_id,
        rule_id=ns.rule_id,
        review_decision=ns.review_decision,
        review_notes=ns.review_notes,
        known_risks=ns.known_risks,
        repo_root=Path(ns.repo_root) if ns.repo_root else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("result") in {"PASS", "REVIEW_REQUIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
