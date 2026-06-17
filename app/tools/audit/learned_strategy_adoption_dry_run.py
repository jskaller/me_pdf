#!/usr/bin/env python3
"""Non-mutating learned-strategy adoption dry-run planner.

Patch 20B records a dry-run plan for a possible future adoption workflow. It
never performs adoption apply, never creates backups, never executes rollback,
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

SCHEMA_VERSION = "learned-strategy-adoption-dry-run.v1"
DESIGN_SCHEMA_VERSION = "learned-strategy-adoption-policy-design.v1"
DESIGN_ARTIFACT_NAME = "learned_strategy_adoption_policy_design.json"
DRY_RUN_ARTIFACT_NAME = "learned_strategy_adoption_dry_run_plan.json"
MODE = "adoption_dry_run_planner_only"

ALLOWED_DRY_RUN_OUTCOMES = {
    "adoption_dry_run_plan_recorded",
    "adoption_dry_run_incomplete",
    "adoption_dry_run_blocked",
}

FORBIDDEN_TERMINAL_STATES = {
    "approved",
    "adoptable",
    "production_ready",
    "ready_for_adoption",
    "adoption_unblocked",
    "apply_ready",
    "approved_for_apply",
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
}

DESIGN_ONLY_REQUIRED_TRUE_FLAGS = {
    "adoption_policy_design_only": True,
    "adoption_plan_created": False,
    "adoption_apply_performed": False,
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
    "rollback_execution_performed": False,
}

MANDATORY_SAFETY_FLAGS = {
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

REQUIRED_EVIDENCE_HASHES = [
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
]

REQUIRED_EVIDENCE_ARTIFACTS = [
    "production_testing_readiness_report",
    "production_test_report",
    "production_test_review_report",
    "normal_final_pdf",
    "learned_trial_or_test_pdf",
]

FILES_THAT_MUST_NEVER_CHANGE = [
    "authoritative normal final PDF during dry-run planning",
    "authoritative STATUS.json during dry-run planning",
    "package deliverables during dry-run planning",
    "app/tools/repair/* during dry-run planning",
    "app/tools/audit/rule_repair_map.json during dry-run planning",
]


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


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    return _dedupe_existing_or_named(candidates)


def _package_deliverables(job_dir: Path) -> List[Path]:
    names = {"AUDIT_REPORT.md", "CHECKSUMS.json", "MANIFEST.json", "STATUS.json"}
    paths: List[Path] = []
    for root in [job_dir / "package", job_dir / "deliverables", job_dir / "output"]:
        if root.exists():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    if job_dir.exists():
        paths.extend(p for p in job_dir.iterdir() if p.is_file() and p.name in names)
    return _dedupe_existing_or_named(paths)


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


def _dedupe_existing_or_named(paths: Iterable[Path]) -> List[Path]:
    deduped: Dict[str, Path] = {}
    for path in paths:
        p = Path(path)
        deduped[str(p)] = p
    return [deduped[k] for k in sorted(deduped)]


def _design_artifact_path(job_dir: Path, explicit_path: Optional[Path]) -> Path:
    if explicit_path:
        return Path(explicit_path)
    return Path(job_dir) / "audit" / DESIGN_ARTIFACT_NAME


def _dry_run_artifact_path(job_dir: Path, explicit_path: Optional[Path]) -> Path:
    if explicit_path:
        return Path(explicit_path)
    return Path(job_dir) / "audit" / DRY_RUN_ARTIFACT_NAME


def _policy_flags(design_payload: Dict[str, Any]) -> Dict[str, Any]:
    policy = design_payload.get("policy")
    return policy if isinstance(policy, dict) else {}


def _evidence_hashes(design_payload: Dict[str, Any]) -> Dict[str, Any]:
    hashes = design_payload.get("evidence_hashes")
    return hashes if isinstance(hashes, dict) else {}


def _evidence_artifacts(design_payload: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = design_payload.get("evidence_artifacts")
    return artifacts if isinstance(artifacts, dict) else {}


def _hash_path_entry(value: Any) -> Dict[str, Any]:
    text = clean_str(value)
    if not text:
        return {"path": None, "sha256": None}
    path = Path(text)
    return {"path": text, "sha256": sha256_file(path)}


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


def _validate_design_only(design_payload: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if clean_str(design_payload.get("schema_version")) != DESIGN_SCHEMA_VERSION:
        blockers.append("policy_design_artifact_schema_version_is_not_patch_20a_design")
    if clean_str(design_payload.get("mode")) != "adoption_policy_design_only":
        blockers.append("policy_design_artifact_mode_is_not_design_only")
    policy = _policy_flags(design_payload)
    for name, expected in DESIGN_ONLY_REQUIRED_TRUE_FLAGS.items():
        if policy.get(name) is not expected:
            blockers.append(f"policy_design_flag_not_design_only:{name}")
    if design_payload.get("adoption_plan") not in (None, {}, []):
        blockers.append("policy_design_artifact_already_contains_adoption_plan")
    if clean_str(design_payload.get("policy_design_outcome")) not in {
        "policy_design_recorded",
        "policy_design_incomplete",
        "policy_design_blocked",
    }:
        blockers.append("policy_design_artifact_has_unsupported_design_outcome")
    return blockers


def _blocked_payload(
    *,
    job_dir: Path,
    dry_run_path: Path,
    design_path: Path,
    blockers: Sequence[str],
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "dry_run_outcome": "adoption_dry_run_blocked",
        "blockers": list(blockers),
        "details": details or {},
        "job_dir": str(job_dir),
        "policy_design_artifact": {
            "path": str(design_path),
            "sha256": sha256_file(design_path),
        },
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        "normal_final_pdf_remains_authoritative": True,
        "allowed_dry_run_outcomes": sorted(ALLOWED_DRY_RUN_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blocker_state": "dry_run_only_no_apply_performed",
        "artifact_path": str(dry_run_path),
    }
    write_json_atomic(dry_run_path, payload)
    return payload


def write_learned_strategy_adoption_dry_run_plan(
    *,
    job_dir: Path,
    policy_design_artifact_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    operator: str = "",
    reviewer: str = "",
    candidate_id: str = "",
    rule_id: str = "",
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write a dry-run plan artifact and perform no adoption/apply mutations."""
    job_dir = Path(job_dir)
    design_path = _design_artifact_path(job_dir, policy_design_artifact_path)
    dry_run_path = _dry_run_artifact_path(job_dir, output_path)

    if not design_path.exists() or not design_path.is_file():
        return _blocked_payload(
            job_dir=job_dir,
            dry_run_path=dry_run_path,
            design_path=design_path,
            blockers=["missing_policy_design_artifact"],
        )

    try:
        design_payload = load_json(design_path)
    except Exception as exc:
        return _blocked_payload(
            job_dir=job_dir,
            dry_run_path=dry_run_path,
            design_path=design_path,
            blockers=["invalid_policy_design_artifact_json"],
            details={"error": f"{type(exc).__name__}: {exc}"},
        )

    blockers = _validate_design_only(design_payload)

    operator = clean_str(operator) or clean_str(design_payload.get("operator")) or clean_str(design_payload.get("reviewer"))
    reviewer = clean_str(reviewer) or clean_str(design_payload.get("reviewer"))
    candidate_id = clean_str(candidate_id) or clean_str(design_payload.get("candidate_id"))
    rule_id = clean_str(rule_id) or clean_str(design_payload.get("rule_id"))

    if not operator and not reviewer:
        blockers.append("missing_operator_or_reviewer_identity")
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if not rule_id:
        blockers.append("missing_rule_id")

    forbidden = _contains_forbidden_terminal_state(
        {
            "dry_run_outcome": design_payload.get("dry_run_outcome"),
            "terminal_state": design_payload.get("terminal_state"),
            "adoption_state": design_payload.get("adoption_state"),
            "future_state": design_payload.get("future_state"),
            "policy_design_outcome": design_payload.get("policy_design_outcome"),
        }
    )
    if forbidden:
        blockers.append(f"forbidden_terminal_state_present:{forbidden}")

    evidence_hashes = _evidence_hashes(design_payload)
    evidence_artifacts = _evidence_artifacts(design_payload)
    missing_hashes = [name for name in REQUIRED_EVIDENCE_HASHES if not clean_str(evidence_hashes.get(name))]
    missing_artifacts = [name for name in REQUIRED_EVIDENCE_ARTIFACTS if not clean_str(evidence_artifacts.get(name))]

    status_paths = _status_json_paths(job_dir)
    package_paths = _package_deliverables(job_dir)
    rule_map_path = _rule_map_path(repo_root, job_dir)
    repair_paths = _repair_files(repo_root, job_dir)
    protected_paths = _dedupe_existing_or_named([rule_map_path, *status_paths, *package_paths, *repair_paths])
    before_snapshot = _snapshot(protected_paths)

    if blockers:
        return _blocked_payload(
            job_dir=job_dir,
            dry_run_path=dry_run_path,
            design_path=design_path,
            blockers=sorted(set(blockers)),
            details={
                "candidate_id": candidate_id,
                "rule_id": rule_id,
                "missing_evidence_hashes": missing_hashes,
                "missing_evidence_artifacts": missing_artifacts,
            },
        )

    incomplete_reasons = [f"missing_evidence_hash:{name}" for name in missing_hashes]
    incomplete_reasons.extend(f"missing_evidence_artifact:{name}" for name in missing_artifacts)
    dry_run_outcome = "adoption_dry_run_incomplete" if incomplete_reasons else "adoption_dry_run_plan_recorded"

    files_that_would_need_backups = _dedupe_existing_or_named([
        rule_map_path,
        _repair_root(repo_root, job_dir),
        *status_paths,
        *package_paths,
    ])
    files_allowed_to_change_future_apply = [
        "app/tools/audit/rule_repair_map.json only in a separately implemented future apply patch",
        "one explicitly named learned repair target only in a separately implemented future apply patch",
        "future adoption audit artifact only in a separately implemented future apply patch",
    ]

    plan: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "dry_run_outcome": dry_run_outcome,
        "blockers": ["blocked_pending_explicit_future_apply", "dry_run_only_no_apply_performed"],
        "incomplete_reasons": sorted(incomplete_reasons),
        "job_dir": str(job_dir),
        "operator_identity": operator,
        "reviewer_identity": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "policy_design_artifact": {
            "path": str(design_path),
            "sha256": sha256_file(design_path),
        },
        "production_readiness_report": {
            "path": clean_str(evidence_artifacts.get("production_testing_readiness_report")),
            "sha256": clean_str(evidence_hashes.get("production_readiness_report_sha256")),
        },
        "production_test_report": {
            "path": clean_str(evidence_artifacts.get("production_test_report")),
            "sha256": clean_str(evidence_hashes.get("production_test_report_sha256")),
        },
        "production_test_review_report": {
            "path": clean_str(evidence_artifacts.get("production_test_review_report")),
            "sha256": clean_str(evidence_hashes.get("production_test_review_report_sha256")),
        },
        "normal_final_pdf": {
            "path": clean_str(evidence_artifacts.get("normal_final_pdf")),
            "sha256": clean_str(evidence_hashes.get("normal_final_pdf_sha256")),
            "authoritative": True,
        },
        "learned_trial_or_test_pdf": {
            "path": clean_str(evidence_artifacts.get("learned_trial_or_test_pdf")),
            "sha256": clean_str(evidence_hashes.get("learned_trial_or_test_pdf_sha256")),
        },
        "files_that_would_need_backups_in_future_apply": [str(p) for p in files_that_would_need_backups],
        "files_allowed_to_change_in_future_apply": files_allowed_to_change_future_apply,
        "files_that_must_never_change_in_dry_run": list(FILES_THAT_MUST_NEVER_CHANGE),
        "rollback_steps_required_for_future_apply": [
            "future rollback command must be explicit and separately invoked",
            "future rollback must restore every pre-apply backup by hash",
            "future rollback must verify rule-map, repair files, status, package, and final-PDF authority remain correct",
            "future rollback must write a rollback audit artifact",
        ],
        "manual_evidence_required_before_any_future_apply": [
            "separate approver identity distinct from dry-run operator/reviewer",
            "manual review notes from production-test review",
            "known risks reviewed and accepted in a future patch",
            "normal-vs-learned comparison summary reviewed in a future patch",
            "all required evidence paths and hashes recorded",
        ],
        "explicit_future_apply_requirement": "A future patch must implement and require an explicit --apply flag; Patch 20B does not implement apply.",
        "explicit_future_rollback_command_requirement": "A future patch must implement and require an explicit rollback command; Patch 20B does not implement rollback.",
        "future_apply_not_implemented": True,
        "plan_is_non_executable_without_future_patch": True,
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        "allowed_dry_run_outcomes": sorted(ALLOWED_DRY_RUN_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "protected_snapshot_before": before_snapshot,
        "artifact_path": str(dry_run_path),
    }

    write_json_atomic(dry_run_path, plan)

    after_snapshot = _snapshot(protected_paths)
    protected_mutations = [path for path, before in before_snapshot.items() if after_snapshot.get(path) != before]
    plan["protected_snapshot_after"] = after_snapshot
    plan["protected_mutation_count"] = len(protected_mutations)
    plan["protected_mutations"] = protected_mutations

    if protected_mutations:
        plan["dry_run_outcome"] = "adoption_dry_run_blocked"
        plan["blockers"] = sorted(set(plan["blockers"] + ["protected_artifact_mutation_detected"]))

    write_json_atomic(dry_run_path, plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Write non-mutating learned-strategy adoption dry-run plan")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--policy-design-artifact", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--operator", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--rule-id", default="")
    parser.add_argument("--repo-root", default="/")
    ns = parser.parse_args()

    payload = write_learned_strategy_adoption_dry_run_plan(
        job_dir=Path(ns.job_dir),
        policy_design_artifact_path=Path(ns.policy_design_artifact) if ns.policy_design_artifact else None,
        output_path=Path(ns.output) if ns.output else None,
        operator=ns.operator,
        reviewer=ns.reviewer,
        candidate_id=ns.candidate_id,
        rule_id=ns.rule_id,
        repo_root=Path(ns.repo_root) if ns.repo_root else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("dry_run_outcome") in {
        "adoption_dry_run_plan_recorded",
        "adoption_dry_run_incomplete",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
