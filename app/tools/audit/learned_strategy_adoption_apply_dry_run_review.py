#!/usr/bin/env python3
"""Review/freeze artifact for a learned-strategy adoption apply dry-run.

Patch 21B records review evidence over the apply dry-run simulation. Any freeze
language means only an evidence snapshot frozen for future discussion; it never
means approval, adoptability, production readiness, apply readiness, or rollback
readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCHEMA_VERSION = "learned-strategy-adoption-apply-dry-run-review.v1"
APPLY_DRY_RUN_SCHEMA_VERSION = "learned-strategy-adoption-apply-dry-run.v1"
APPLY_DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run.json"
APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run_review.json"
MODE = "adoption_apply_dry_run_review_only"

ALLOWED_REVIEW_DECISIONS = {
    "apply_dry_run_review_recorded",
    "apply_dry_run_review_requires_followup",
    "apply_dry_run_review_rejected",
}

FORBIDDEN_REVIEW_STATES = {
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
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "adoption_apply_dry_run_review_only": True,
    "apply_dry_run_review_recorded": True,
    "apply_dry_run_hash_recorded": True,
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
    "future_rollback_not_implemented": True,
}

REQUIRED_SIMULATION_FALSE_FLAGS = {
    "apply_plan_created",
    "adoption_apply_performed",
    "backup_created",
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
    "review_decision",
    "apply_decision",
    "apply_status",
    "apply_outcome",
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


def default_apply_dry_run_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_DRY_RUN_ARTIFACT_NAME


def artifact_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_DRY_RUN_REVIEW_ARTIFACT_NAME


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


def _normalize(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def forbidden_review_state_violations(data: Dict[str, Any]) -> List[str]:
    hits: List[str] = []
    for key, value in data.items():
        if key in FORBIDDEN_STATE_KEYS and _normalize(value) in FORBIDDEN_REVIEW_STATES:
            hits.append(f"{key}:{value}")
    safety = data.get("safety_flags")
    if isinstance(safety, dict):
        for key in REQUIRED_SIMULATION_FALSE_FLAGS:
            if safety.get(key) is True:
                hits.append(f"safety_flags.{key}:true")
    return sorted(set(hits))


def validate_simulation_source(
    simulation: Dict[str, Any],
    simulation_path: Path,
    candidate_id: str,
    rule_id: str,
    expected_sha256: Optional[str],
) -> List[str]:
    blockers: List[str] = []
    computed_hash = sha256_file(simulation_path)
    if simulation.get("schema_version") != APPLY_DRY_RUN_SCHEMA_VERSION:
        blockers.append("apply_dry_run_schema_version_mismatch")
    if simulation.get("mode") != "adoption_apply_dry_run_only":
        blockers.append("apply_dry_run_not_dry_run_only")
    if simulation.get("apply_dry_run_simulation_outcome") not in {
        "apply_dry_run_simulation_recorded",
        "apply_dry_run_simulation_incomplete",
    }:
        blockers.append("apply_dry_run_simulation_outcome_not_usable")
    if simulation.get("candidate_id") != candidate_id:
        blockers.append("candidate_id_mismatch")
    if simulation.get("rule_id") != rule_id:
        blockers.append("rule_id_mismatch")
    if expected_sha256 and computed_hash != expected_sha256:
        blockers.append("apply_dry_run_simulation_hash_mismatch")
    if computed_hash is None:
        blockers.append("apply_dry_run_simulation_hash_missing")
    safety = simulation.get("safety_flags")
    if not isinstance(safety, dict):
        blockers.append("missing_apply_dry_run_safety_flags")
        safety = {}
    if safety.get("adoption_apply_dry_run_only") is not True:
        blockers.append("apply_dry_run_not_dry_run_only")
    if safety.get("apply_dry_run_simulation_recorded") is not True:
        blockers.append("apply_dry_run_simulation_not_recorded")
    for key in REQUIRED_SIMULATION_FALSE_FLAGS:
        if safety.get(key) is not False:
            blockers.append(f"source_flag_not_false:{key}")
    if safety.get("normal_final_pdf_remains_authoritative") is not True:
        blockers.append("normal_final_pdf_not_authoritative")
    if safety.get("future_apply_not_implemented") is not True:
        blockers.append("future_apply_appears_implemented")
    if safety.get("future_rollback_not_implemented") is not True:
        blockers.append("future_rollback_appears_implemented")
    forbidden = forbidden_review_state_violations(simulation)
    if forbidden:
        blockers.append("forbidden_review_state_detected:" + ",".join(forbidden))
    return blockers


def _list_from_text(raw: str) -> List[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def build_artifact(
    *,
    job_dir: Path,
    repo_root: Path,
    apply_dry_run_path: Path,
    reviewer: str,
    candidate_id: str,
    rule_id: str,
    review_notes: List[str],
    known_risks: List[str],
    review_decision: str,
    expected_apply_dry_run_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    before = snapshot_protected(job_dir, repo_root)
    blockers: List[str] = []
    simulation: Dict[str, Any] = {}

    if not apply_dry_run_path.exists():
        blockers.append("missing_apply_dry_run_simulation")
    else:
        try:
            simulation = load_json(apply_dry_run_path)
        except Exception as exc:  # pragma: no cover - defensive artifact handling
            blockers.append(f"apply_dry_run_simulation_unreadable:{exc}")
    if not reviewer:
        blockers.append("missing_reviewer")
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not rule_id:
        blockers.append("missing_rule_id")
    if not review_notes:
        blockers.append("missing_review_notes")
    if not known_risks:
        blockers.append("missing_known_risks")
    if review_decision not in ALLOWED_REVIEW_DECISIONS:
        blockers.append("review_decision_not_allowed")
    if review_decision in FORBIDDEN_REVIEW_STATES:
        blockers.append("forbidden_review_state_detected:review_decision")
    if simulation and candidate_id and rule_id:
        blockers.extend(
            validate_simulation_source(
                simulation,
                apply_dry_run_path,
                candidate_id,
                rule_id,
                expected_apply_dry_run_sha256,
            )
        )

    apply_dry_run_sha256 = sha256_file(apply_dry_run_path)
    outcome = review_decision if review_decision in ALLOWED_REVIEW_DECISIONS else "apply_dry_run_review_rejected"
    result = "PASS"
    if blockers:
        outcome = "apply_dry_run_review_rejected"
        result = "BLOCKED"
    elif review_decision == "apply_dry_run_review_requires_followup":
        result = "REVIEW_REQUIRED"
    elif review_decision == "apply_dry_run_review_rejected":
        result = "REJECTED"

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "apply_dry_run_review_rejected"
        result = "BLOCKED"

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": utc_now(),
        "job_dir": str(job_dir),
        "artifact_path": str(artifact_path(job_dir)),
        "apply_dry_run_simulation": {
            "path": str(apply_dry_run_path),
            "sha256": apply_dry_run_sha256,
            "expected_sha256": expected_apply_dry_run_sha256,
        },
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "review_notes": review_notes,
        "known_risks": known_risks,
        "review_decision": outcome,
        "allowed_review_decisions": sorted(ALLOWED_REVIEW_DECISIONS),
        "forbidden_review_states": sorted(FORBIDDEN_REVIEW_STATES),
        "freeze_concept": "apply_dry_run_evidence_snapshot_frozen_for_future_discussion",
        "freeze_is_apply_ready": False,
        "result": result,
        "blockers": blockers,
        "source_apply_dry_run_result": simulation.get("result") if simulation else None,
        "source_apply_dry_run_outcome": simulation.get("apply_dry_run_simulation_outcome") if simulation else None,
        "source_apply_dry_run_safety_flags": simulation.get("safety_flags") if simulation else {},
        "source_apply_dry_run_simulation_text_only": simulation.get("simulation_text_only") if simulation else None,
        "apply_ready": False,
        "rollback_ready": False,
        "backup_manifest_created": False,
        "rollback_manifest_created": False,
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
    parser.add_argument("--apply-dry-run", type=Path, default=None)
    parser.add_argument("--expected-apply-dry-run-sha256", default=None)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--known-risks", required=True)
    parser.add_argument("--review-decision", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    apply_dry_run_path = (args.apply_dry_run or default_apply_dry_run_path(job_dir)).resolve()
    artifact = build_artifact(
        job_dir=job_dir,
        repo_root=repo_root,
        apply_dry_run_path=apply_dry_run_path,
        reviewer=args.reviewer.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
        review_notes=_list_from_text(args.review_notes),
        known_risks=_list_from_text(args.known_risks),
        review_decision=args.review_decision.strip(),
        expected_apply_dry_run_sha256=args.expected_apply_dry_run_sha256,
    )
    out = artifact_path(job_dir)
    write_json(out, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["result"] in {"PASS", "REVIEW_REQUIRED", "REJECTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
