#!/usr/bin/env python3
"""Non-mutating learned-strategy adoption apply dry-run simulation.

Patch 21B records a simulation of a possible future adoption apply
transaction over the Patch 21A apply-policy-design artifact. It never creates
an apply plan, never performs adoption apply, never creates backups, never
executes rollback, and never mutates production repair, rule-map, status,
package, or final-PDF artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCHEMA_VERSION = "learned-strategy-adoption-apply-dry-run.v1"
APPLY_POLICY_DESIGN_SCHEMA_VERSION = "learned-strategy-adoption-apply-policy-design.v1"
APPLY_POLICY_DESIGN_ARTIFACT_NAME = "learned_strategy_adoption_apply_policy_design.json"
APPLY_DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_apply_dry_run.json"
MODE = "adoption_apply_dry_run_only"

ALLOWED_OUTCOMES = {
    "apply_dry_run_simulation_recorded",
    "apply_dry_run_simulation_incomplete",
    "apply_dry_run_simulation_blocked",
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
    "apply_performed",
    "rollback_performed",
    "backup_created",
}

MANDATORY_SAFETY_FLAGS: Dict[str, Any] = {
    "adoption_apply_dry_run_only": True,
    "apply_dry_run_simulation_recorded": True,
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

REQUIRED_DESIGN_FALSE_FLAGS = {
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

REQUIRED_DESIGN_HASH_KEYS = {
    "dry_run_review_artifact_sha256",
    "dry_run_plan_artifact_sha256",
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
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


def default_design_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_POLICY_DESIGN_ARTIFACT_NAME


def artifact_path(job_dir: Path) -> Path:
    return job_dir / "audit" / APPLY_DRY_RUN_ARTIFACT_NAME


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


def forbidden_terminal_state_violations(data: Dict[str, Any]) -> List[str]:
    hits: List[str] = []
    for key, value in data.items():
        if key in FORBIDDEN_STATE_KEYS and _normalize(value) in FORBIDDEN_TERMINAL_STATES:
            hits.append(f"{key}:{value}")
    safety = data.get("safety_flags")
    if isinstance(safety, dict):
        for key in REQUIRED_DESIGN_FALSE_FLAGS:
            if safety.get(key) is True:
                hits.append(f"safety_flags.{key}:true")
    return sorted(set(hits))


def extract_design_hashes(design: Dict[str, Any], design_path: Path) -> Dict[str, Optional[str]]:
    hashes: Dict[str, Optional[str]] = {key: None for key in REQUIRED_DESIGN_HASH_KEYS}
    source = design.get("future_apply_requirements", {}).get("source_hashes_recorded_for_policy_discussion")
    if isinstance(source, dict):
        for key in hashes:
            hashes[key] = source.get(key)
    for key in hashes:
        hashes[key] = hashes[key] or design.get(key)
    hashes["apply_policy_design_artifact_sha256"] = sha256_file(design_path)
    return hashes


def validate_design_source(design: Dict[str, Any], design_path: Path, candidate_id: str, rule_id: str) -> List[str]:
    blockers: List[str] = []
    if design.get("schema_version") != APPLY_POLICY_DESIGN_SCHEMA_VERSION:
        blockers.append("apply_policy_design_schema_version_mismatch")
    if design.get("mode") != "adoption_apply_policy_design_only":
        blockers.append("apply_policy_design_not_design_only")
    if design.get("apply_policy_design_outcome") not in {
        "apply_policy_design_recorded",
        "apply_policy_design_incomplete",
    }:
        blockers.append("apply_policy_design_outcome_not_usable")
    if design.get("candidate_id") != candidate_id:
        blockers.append("candidate_id_mismatch")
    if design.get("rule_id") != rule_id:
        blockers.append("rule_id_mismatch")
    safety = design.get("safety_flags")
    if not isinstance(safety, dict):
        blockers.append("missing_apply_policy_design_safety_flags")
        safety = {}
    if safety.get("adoption_apply_policy_design_only") is not True:
        blockers.append("apply_policy_design_not_design_only")
    if safety.get("apply_policy_design_recorded") is not True:
        blockers.append("apply_policy_design_not_recorded")
    for key in REQUIRED_DESIGN_FALSE_FLAGS:
        if safety.get(key) is not False:
            blockers.append(f"source_flag_not_false:{key}")
    if safety.get("normal_final_pdf_remains_authoritative") is not True:
        blockers.append("normal_final_pdf_not_authoritative")
    if safety.get("future_apply_not_implemented") is not True:
        blockers.append("future_apply_appears_implemented")
    if safety.get("future_rollback_not_implemented") is not True:
        blockers.append("future_rollback_appears_implemented")
    forbidden = forbidden_terminal_state_violations(design)
    if forbidden:
        blockers.append("forbidden_terminal_state_detected:" + ",".join(forbidden))
    if sha256_file(design_path) is None:
        blockers.append("apply_policy_design_hash_missing")
    return blockers


def simulated_apply_transaction_steps() -> Dict[str, Any]:
    return {
        "future_apply_transaction_steps_policy_text_only": [
            "verify explicit future apply command and separate approver identity",
            "recompute immutable evidence hashes before any mutation",
            "create and verify byte-for-byte backups before any mutation",
            "apply one explicitly reviewed rule-map mutation only in a future patch",
            "apply one explicitly reviewed repair-file mutation only in a future patch",
            "run post-apply protected mutation and evidence validation checks",
            "write future apply audit artifact only after all future checks pass",
        ],
        "future_backup_manifest_entries_policy_text_only": [
            "rule_repair_map.json pre-apply hash and backup path",
            "each explicitly named repair target pre-apply hash and backup path",
            "future apply audit directory pre-apply listing",
            "operator, approver, timestamp, and evidence hash bundle",
        ],
        "future_rollback_manifest_entries_policy_text_only": [
            "every future mutation target mapped to its backup artifact",
            "pre-rollback and post-rollback sha256 for each restored target",
            "rollback operator and timestamp",
            "post-rollback protected mutation check results",
        ],
        "future_allowed_file_mutations_policy_text_only": [
            "one explicitly named rule-map entry in a future apply patch",
            "one explicitly named learned repair script target in a future apply patch",
            "future adoption apply audit artifact in JOB/audit",
        ],
        "future_forbidden_file_mutations_policy_text_only": [
            "authoritative normal final PDF",
            "authoritative STATUS.json or package deliverables",
            "broad app/tools/repair mutation",
            "unreviewed rule-map entries",
            "verdict or package/status softening outputs",
        ],
        "future_post_apply_validation_checks_policy_text_only": [
            "protected mutation diff check",
            "rule-map hash and exact-entry check",
            "repair target hash and import check",
            "canonical normal smoke remains authoritative",
            "no final PDF adoption or verdict softening occurred",
        ],
        "future_post_rollback_validation_checks_policy_text_only": [
            "all backed-up hashes restored",
            "rule-map and repair protected targets restored",
            "normal final PDF authority unchanged",
            "STATUS.json and package deliverables unchanged unless explicitly allowed by a future patch",
        ],
        "future_abort_conditions_policy_text_only": [
            "missing or mismatched immutable evidence hash",
            "missing separate approver identity",
            "missing backup manifest before mutation",
            "unexpected protected mutation",
            "candidate marked approved, adoptable, production-ready, or apply-ready",
            "any attempt to mutate authoritative normal final PDF or verdict/package state",
        ],
        "future_operator_prompts_policy_text_only": [
            "confirm explicit future apply command",
            "confirm separate approver identity",
            "confirm exact candidate id and rule id",
            "confirm immutable evidence hashes match the reviewed dry-run snapshot",
        ],
        "future_required_approver_identity_policy_text_only": "A future apply patch must require a separate named approver distinct from the dry-run reviewer/operator.",
        "future_immutable_evidence_hash_checks_policy_text_only": [
            "apply policy design artifact hash",
            "dry-run review artifact hash",
            "production readiness/report/review hashes",
            "normal final PDF hash",
            "learned trial or test PDF hash",
        ],
    }


def build_artifact(
    *,
    job_dir: Path,
    repo_root: Path,
    design_path: Path,
    operator: str,
    candidate_id: str,
    rule_id: str,
) -> Dict[str, Any]:
    before = snapshot_protected(job_dir, repo_root)
    blockers: List[str] = []
    incomplete_reasons: List[str] = []
    design: Dict[str, Any] = {}

    if not design_path.exists():
        blockers.append("missing_apply_policy_design")
    else:
        try:
            design = load_json(design_path)
        except Exception as exc:  # pragma: no cover - defensive artifact handling
            blockers.append(f"apply_policy_design_unreadable:{exc}")
    if not operator:
        blockers.append("missing_operator")
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not rule_id:
        blockers.append("missing_rule_id")
    if design and candidate_id and rule_id:
        blockers.extend(validate_design_source(design, design_path, candidate_id, rule_id))

    hashes = extract_design_hashes(design, design_path) if design else {key: None for key in REQUIRED_DESIGN_HASH_KEYS}
    if design:
        hashes.setdefault("apply_policy_design_artifact_sha256", sha256_file(design_path))
    for key in sorted(REQUIRED_DESIGN_HASH_KEYS):
        if not hashes.get(key):
            incomplete_reasons.append(f"missing_required_artifact_hash:{key}")

    outcome = "apply_dry_run_simulation_recorded"
    result = "PASS"
    if blockers:
        outcome = "apply_dry_run_simulation_blocked"
        result = "BLOCKED"
    elif incomplete_reasons:
        outcome = "apply_dry_run_simulation_incomplete"
        result = "INCOMPLETE"

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "apply_dry_run_simulation_blocked"
        result = "BLOCKED"

    simulation = simulated_apply_transaction_steps()
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": utc_now(),
        "job_dir": str(job_dir),
        "artifact_path": str(artifact_path(job_dir)),
        "apply_policy_design_artifact": {
            "path": str(design_path),
            "sha256": hashes.get("apply_policy_design_artifact_sha256"),
        },
        "operator": operator,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "apply_dry_run_simulation_outcome": outcome,
        "allowed_apply_dry_run_simulation_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "incomplete_reasons": incomplete_reasons,
        "required_future_explicit_apply": True,
        "apply_plan": None,
        "apply_ready": False,
        "rollback_ready": False,
        "backup_manifest_created": False,
        "rollback_manifest_created": False,
        "simulation_text_only": True,
        "source_design_result": design.get("result") if design else None,
        "source_design_outcome": design.get("apply_policy_design_outcome") if design else None,
        "source_design_safety_flags": design.get("safety_flags") if design else {},
        "source_evidence_hashes": hashes,
        **simulation,
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
    parser.add_argument("--apply-policy-design", type=Path, default=None)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    job_dir = args.job_dir.resolve()
    repo_root = args.repo_root.resolve()
    design_path = (args.apply_policy_design or default_design_path(job_dir)).resolve()
    artifact = build_artifact(
        job_dir=job_dir,
        repo_root=repo_root,
        design_path=design_path,
        operator=args.operator.strip(),
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
    )
    out = artifact_path(job_dir)
    write_json(out, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
