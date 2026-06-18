#!/usr/bin/env python3
"""Design-only learned-strategy adoption apply policy contract.

Patch 21A records a policy-design artifact over a Patch 20C adoption dry-run
review artifact. It never creates an apply plan, never performs adoption apply,
never creates backups, never executes rollback, and never mutates production
repair, rule-map, status, package, or final-PDF artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA_VERSION = "learned-strategy-adoption-apply-policy-design.v1"
DRY_RUN_REVIEW_SCHEMA_VERSION = "learned-strategy-adoption-dry-run-review.v1"
DRY_RUN_REVIEW_ARTIFACT_NAME = "learned_strategy_adoption_dry_run_review.json"
APPLY_POLICY_DESIGN_ARTIFACT_NAME = "learned_strategy_adoption_apply_policy_design.json"
MODE = "adoption_apply_policy_design_only"

ALLOWED_OUTCOMES = {
    "apply_policy_design_recorded",
    "apply_policy_design_incomplete",
    "apply_policy_design_blocked",
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
    "apply_plan_created",
    "apply_unblocked",
    "rollback_ready",
}

FORBIDDEN_VALUE_TOKENS = {
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
    "apply_plan_created",
    "apply_unblocked",
    "rollback_ready",
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "adoption_apply_policy_design_only": True,
    "apply_policy_design_recorded": True,
    "apply_plan_created": False,
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

REQUIRED_SOURCE_FALSE_FLAGS = {
    "candidate_is_adoptable",
    "candidate_approved",
    "candidate_production_ready",
    "candidate_apply_ready",
    "adoption_apply_performed",
    "backup_created",
    "rollback_execution_performed",
    "final_pdf_adoption_performed",
    "production_repair_replacement_performed",
    "verdict_softening_performed",
    "package_status_mutation_performed",
    "rule_map_mutation_performed",
    "app_tools_repair_mutation_performed",
}

REQUIRED_HASH_KEYS = {
    "dry_run_review_artifact_sha256",
    "dry_run_plan_artifact_sha256",
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
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


def default_review_path(job_dir: Path) -> Path:
    return job_dir / "audit" / DRY_RUN_REVIEW_ARTIFACT_NAME


def artifact_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_POLICY_DESIGN_ARTIFACT_NAME


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


def iter_value_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_value_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_value_strings(child)


def forbidden_values(data: Any) -> List[str]:
    hits: List[str] = []
    for raw in iter_value_strings(data):
        normalized = raw.strip().lower()
        if normalized in FORBIDDEN_VALUE_TOKENS:
            hits.append(raw)
    return sorted(set(hits))


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def extract_plan_from_review(review: Dict[str, Any]) -> Dict[str, Any]:
    plan = review.get("dry_run_plan")
    if isinstance(plan, dict):
        return plan
    return {}


def extract_source_hashes(review: Dict[str, Any], review_path: Path) -> Dict[str, Optional[str]]:
    plan = extract_plan_from_review(review)
    source_plan_safety = review.get("source_plan_safety_flags")
    _ = source_plan_safety if isinstance(source_plan_safety, dict) else {}
    hashes: Dict[str, Optional[str]] = {
        "dry_run_review_artifact_sha256": sha256_file(review_path),
        "dry_run_plan_artifact_sha256": plan.get("sha256") if isinstance(plan, dict) else None,
        "production_readiness_report_sha256": None,
        "production_test_report_sha256": None,
        "production_test_review_report_sha256": None,
        "normal_final_pdf_sha256": None,
        "learned_trial_or_test_pdf_sha256": None,
    }

    # Patch 20C review artifacts usually carry the source plan summaries and may
    # also carry flattened evidence objects. Support both to keep the design tool
    # tolerant of historical dry-run review variants.
    for key, source_key in [
        ("production_readiness_report_sha256", "production_readiness_report"),
        ("production_test_report_sha256", "production_test_report"),
        ("production_test_review_report_sha256", "production_test_review_report"),
        ("normal_final_pdf_sha256", "normal_final_pdf"),
        ("learned_trial_or_test_pdf_sha256", "learned_trial_or_test_pdf"),
    ]:
        obj = review.get(source_key)
        if isinstance(obj, dict):
            hashes[key] = obj.get("sha256") or obj.get("hash")

    source_hashes = review.get("source_plan_evidence_hashes")
    if isinstance(source_hashes, dict):
        for key in list(hashes):
            hashes[key] = hashes[key] or source_hashes.get(key)

    source_plan_artifacts = review.get("source_plan_artifacts")
    if isinstance(source_plan_artifacts, dict):
        for key, artifact_key in [
            ("production_readiness_report_sha256", "production_readiness_report"),
            ("production_test_report_sha256", "production_test_report"),
            ("production_test_review_report_sha256", "production_test_review_report"),
            ("normal_final_pdf_sha256", "normal_final_pdf"),
            ("learned_trial_or_test_pdf_sha256", "learned_trial_or_test_pdf"),
        ]:
            obj = source_plan_artifacts.get(artifact_key)
            if isinstance(obj, dict):
                hashes[key] = hashes[key] or obj.get("sha256")

    # Many Patch 20B plans are summarized directly on Patch 20C under these keys.
    for key, artifact_key in [
        ("production_readiness_report_sha256", "source_production_readiness_report"),
        ("production_test_report_sha256", "source_production_test_report"),
        ("production_test_review_report_sha256", "source_production_test_review_report"),
        ("normal_final_pdf_sha256", "source_normal_final_pdf"),
        ("learned_trial_or_test_pdf_sha256", "source_learned_trial_or_test_pdf"),
    ]:
        obj = review.get(artifact_key)
        if isinstance(obj, dict):
            hashes[key] = hashes[key] or obj.get("sha256")

    return hashes


def validate_review_source(
    review: Dict[str, Any],
    review_path: Path,
    candidate_id: str,
    rule_id: str,
) -> List[str]:
    blockers: List[str] = []
    if review.get("schema_version") != DRY_RUN_REVIEW_SCHEMA_VERSION:
        blockers.append("dry_run_review_schema_version_mismatch")
    if review.get("mode") != "adoption_dry_run_review_only":
        blockers.append("dry_run_review_not_review_only")
    safety = review.get("safety_flags")
    if not isinstance(safety, dict):
        blockers.append("missing_dry_run_review_safety_flags")
        safety = {}
    if safety.get("adoption_dry_run_review_only") is not True:
        blockers.append("dry_run_review_not_review_only")
    if safety.get("dry_run_plan_reviewed") is not True:
        blockers.append("dry_run_plan_not_reviewed")
    if safety.get("dry_run_plan_hash_recorded") is not True:
        blockers.append("dry_run_plan_hash_not_recorded")
    for key in REQUIRED_SOURCE_FALSE_FLAGS:
        if safety.get(key) is not False:
            blockers.append(f"source_flag_not_false:{key}")
    if review.get("candidate_id") != candidate_id:
        blockers.append("candidate_id_mismatch")
    if review.get("rule_id") != rule_id:
        blockers.append("rule_id_mismatch")
    if review.get("reviewer") in (None, ""):
        blockers.append("source_reviewer_missing")
    review_decision = review.get("review_decision")
    if review_decision not in {"dry_run_review_recorded", "dry_run_review_requires_followup", "dry_run_review_rejected"}:
        blockers.append("source_review_decision_not_allowed")
    forbidden = forbidden_values(review)
    if forbidden:
        blockers.append("forbidden_terminal_state_detected:" + ",".join(forbidden))
    if sha256_file(review_path) is None:
        blockers.append("dry_run_review_hash_missing")
    return blockers


def future_apply_requirements(hashes: Dict[str, Optional[str]]) -> Dict[str, Any]:
    return {
        "required_reviewer_identity": "reviewer identity must be recorded from dry-run review evidence",
        "required_separate_approver_identity_for_future_patch": True,
        "candidate_id_required": True,
        "rule_id_required": True,
        "dry_run_review_artifact_hash_required": True,
        "dry_run_plan_artifact_hash_required": True,
        "policy_design_artifact_hash_required_in_future_patch": True,
        "production_readiness_report_hash_required": True,
        "production_test_report_hash_required": True,
        "production_test_review_report_hash_required": True,
        "normal_final_pdf_hash_required": True,
        "learned_trial_or_test_pdf_hash_required": True,
        "source_hashes_recorded_for_policy_discussion": hashes,
        "future_backup_manifest_requirements_policy_text_only": [
            "future apply must write a backup manifest before any mutation",
            "backup manifest must include byte-for-byte backup paths and pre-apply sha256 hashes",
            "backup manifest must include every allowed mutation target before apply",
            "backup manifest must be verified before apply proceeds",
        ],
        "future_rollback_manifest_requirements_policy_text_only": [
            "future rollback must have an explicit manifest separate from apply execution",
            "rollback manifest must map every mutation target to its backup by hash",
            "rollback manifest must record rollback command, operator, and verification hashes",
        ],
        "future_rollback_verification_requirements_policy_text_only": [
            "verify rule map hash restored",
            "verify repair files restored or unchanged",
            "verify authoritative STATUS.json and package deliverables unchanged unless explicitly allowed in future patch",
            "verify normal final PDF authority remains correct",
        ],
        "future_allowed_mutation_list_policy_text_only": [
            "one explicitly named rule-map entry only in a future apply patch",
            "one explicitly named learned repair target only in a future apply patch",
            "future apply audit artifact only in a future apply patch",
        ],
        "future_forbidden_mutation_list_policy_text_only": [
            "authoritative normal final PDF without explicit future approval",
            "broad app/tools/repair/* mutation",
            "broad package/status rewrite",
            "verdict softening",
            "default learned execution",
            "unreviewed activation mutation",
        ],
        "future_apply_command_family": "tools/audit/learned_strategy_adoption_apply_* (future only; not implemented in Patch 21A)",
        "future_explicit_apply_requirement": "future apply must require an explicit --apply flag",
        "future_explicit_rollback_requirement": "future rollback must require an explicit --rollback command or equivalent explicit rollback subcommand",
        "future_post_apply_validation_requirements_policy_text_only": [
            "post-apply protected mutation audit",
            "post-apply rule-map hash audit",
            "post-apply package/status authority audit",
            "post-apply normal-vs-learned evidence audit",
        ],
        "future_post_rollback_validation_requirements_policy_text_only": [
            "post-rollback protected mutation audit",
            "post-rollback backup hash restoration audit",
            "post-rollback package/status authority audit",
            "post-rollback final PDF authority audit",
        ],
    }


def build_artifact(
    *,
    job_dir: Path,
    repo_root: Path,
    review_path: Path,
    reviewer: str,
    candidate_id: str,
    rule_id: str,
) -> Dict[str, Any]:
    created_at = utc_now()
    before = snapshot_protected(job_dir, repo_root)
    blockers: List[str] = []
    incomplete_reasons: List[str] = []
    review: Dict[str, Any] = {}

    if not review_path.exists():
        blockers.append("missing_dry_run_review")
    else:
        try:
            review = load_json(review_path)
        except Exception as exc:  # pragma: no cover - defensive artifact path handling
            blockers.append(f"dry_run_review_unreadable:{exc}")

    if not reviewer:
        blockers.append("missing_reviewer")
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not rule_id:
        blockers.append("missing_rule_id")

    if review and candidate_id and rule_id:
        blockers.extend(validate_review_source(review, review_path, candidate_id, rule_id))

    hashes = extract_source_hashes(review, review_path) if review else {key: None for key in REQUIRED_HASH_KEYS}
    for key in sorted(REQUIRED_HASH_KEYS):
        if not hashes.get(key):
            incomplete_reasons.append(f"missing_required_hash:{key}")

    outcome = "apply_policy_design_recorded"
    result = "PASS"
    if blockers:
        outcome = "apply_policy_design_blocked"
        result = "BLOCKED"
    elif incomplete_reasons:
        outcome = "apply_policy_design_incomplete"
        result = "INCOMPLETE"

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "apply_policy_design_blocked"
        result = "BLOCKED"

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": created_at,
        "job_dir": str(job_dir),
        "artifact_path": str(artifact_path(job_dir)),
        "dry_run_review_artifact": {
            "path": str(review_path),
            "sha256": hashes.get("dry_run_review_artifact_sha256"),
        },
        "dry_run_plan_artifact": {
            "path": extract_plan_from_review(review).get("path") if review else None,
            "sha256": hashes.get("dry_run_plan_artifact_sha256"),
        },
        "reviewer": reviewer,
        "source_reviewer": review.get("reviewer") if review else None,
        "required_separate_approver_identity_for_future_patch": True,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "apply_policy_design_outcome": outcome,
        "allowed_apply_policy_design_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "incomplete_reasons": incomplete_reasons,
        "apply_plan": None,
        "apply_ready": False,
        "rollback_ready": False,
        "future_apply_requirements": future_apply_requirements(hashes),
        "future_apply_requirements_policy_text_only": True,
        "future_backup_requirements_policy_text_only": True,
        "future_rollback_requirements_policy_text_only": True,
        "future_post_apply_validation_requirements_policy_text_only": True,
        "future_post_rollback_validation_requirements_policy_text_only": True,
        "source_review_result": review.get("result") if review else None,
        "source_review_decision": review.get("review_decision") if review else None,
        "source_review_scope": review.get("review_scope") if review else None,
        "source_dry_run_outcome": review.get("source_dry_run_outcome") if review else None,
        "source_dry_run_blockers": review.get("source_dry_run_blockers") if review else [],
        "source_review_safety_flags": review.get("safety_flags") if review else {},
        "source_plan_safety_flags": review.get("source_plan_safety_flags") if review else {},
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        "adoption_apply_policy_design_only": True,
        "apply_policy_design_recorded": True,
        "apply_plan_created": False,
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
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
    }
    return artifact


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--dry-run-review", type=Path, default=None)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    review_path = (args.dry_run_review or default_review_path(job_dir)).resolve()
    artifact = build_artifact(
        job_dir=job_dir,
        repo_root=repo_root,
        review_path=review_path,
        reviewer=args.reviewer.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
    )
    out = artifact_path(job_dir)
    write_json(out, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
