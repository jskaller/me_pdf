#!/usr/bin/env python3
"""Design-only policy gate definition for any future learned-strategy adoption workflow.

Patch 20A is intentionally non-operative. It records what evidence and gates a
future adoption workflow would need, but it does not create an adoption plan,
does not apply adoption, does not approve candidates, does not mutate package
or status artifacts, and does not make any learned strategy production-ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "learned-strategy-adoption-policy-design.v1"
ARTIFACT_NAME = "learned_strategy_adoption_policy_design.json"
MODE = "adoption_policy_design_only"

ALLOWED_POLICY_DESIGN_OUTCOMES = {
    "policy_design_recorded",
    "policy_design_incomplete",
    "policy_design_blocked",
}

FORBIDDEN_TERMINAL_STATES = {
    "approved",
    "adoptable",
    "production_ready",
    "ready_for_adoption",
    "adoption_unblocked",
    "apply_ready",
}

FORBIDDEN_STATE_TOKENS = {
    "approved",
    "approval",
    "adoptable",
    "adoption_unblocked",
    "apply_ready",
    "production_ready",
    "production-ready",
    "production ready",
    "ready_for_adoption",
    "ready-for-adoption",
    "ready for adoption",
}

MANDATORY_ARTIFACT_NAMES = [
    "production_testing_readiness_report",
    "production_test_report",
    "production_test_review_report",
    "normal_final_pdf",
    "learned_trial_or_test_pdf",
    "normal_vs_learned_comparison_summary",
    "manual_review_notes",
    "known_risks",
]

MANDATORY_HASH_NAMES = [
    "production_readiness_report_sha256",
    "production_test_report_sha256",
    "production_test_review_report_sha256",
    "normal_final_pdf_sha256",
    "learned_trial_or_test_pdf_sha256",
]

MANDATORY_FUTURE_GATES = [
    "reviewer_identity_recorded",
    "separate_approver_identity_required_in_future_patch",
    "candidate_id_recorded",
    "rule_id_recorded",
    "production_readiness_report_hash_recorded",
    "production_test_report_hash_recorded",
    "production_test_review_report_hash_recorded",
    "normal_final_pdf_hash_recorded",
    "learned_trial_or_test_pdf_hash_recorded",
    "normal_vs_learned_comparison_summary_recorded",
    "manual_review_notes_recorded",
    "known_risks_recorded",
    "rollback_requirements_recorded",
    "backup_requirements_recorded",
    "future_apply_requires_explicit_apply_flag",
    "future_rollback_command_requirement_recorded",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return data


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


def _as_path(value: Any) -> Optional[Path]:
    text = clean_str(value)
    return Path(text) if text else None


def _notes(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_str(v) for v in value if clean_str(v)]
    text = clean_str(value)
    return [text] if text else []


def design_only_policy_flags() -> Dict[str, bool]:
    return {
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


def validate_policy_design_outcome(outcome: str) -> str:
    normalized = clean_str(outcome).lower()
    if not normalized:
        raise ValueError("missing_policy_design_outcome")
    if any(token in normalized for token in FORBIDDEN_STATE_TOKENS):
        raise ValueError(f"forbidden_policy_design_outcome:{normalized}")
    if normalized not in ALLOWED_POLICY_DESIGN_OUTCOMES:
        raise ValueError(f"unsupported_policy_design_outcome:{normalized}")
    return normalized


def _status_json_path(job_dir: Path) -> Optional[Path]:
    candidates = [
        job_dir / "STATUS.json",
        job_dir / "package" / "STATUS.json",
        job_dir / "deliverables" / "STATUS.json",
        job_dir / "output" / "STATUS.json",
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    matches = sorted(p for p in job_dir.rglob("STATUS.json") if p.is_file()) if job_dir.exists() else []
    return matches[0] if matches else None


def _package_deliverables(job_dir: Path) -> List[Path]:
    names = {"AUDIT_REPORT.md", "CHECKSUMS.json", "MANIFEST.json", "STATUS.json"}
    paths: List[Path] = []
    for root in [job_dir / "package", job_dir / "deliverables", job_dir / "output"]:
        if root.exists():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    if job_dir.exists():
        paths.extend(p for p in job_dir.iterdir() if p.is_file() and p.name in names)
    deduped = {str(p.resolve()): p for p in paths}
    return [deduped[k] for k in sorted(deduped)]


def _rule_map_path(repo_root: Optional[Path], job_dir: Path) -> Optional[Path]:
    candidates: List[Path] = []
    if repo_root:
        candidates.append(Path(repo_root) / "app" / "tools" / "audit" / "rule_repair_map.json")
    candidates.append(Path("/app/tools/audit/rule_repair_map.json"))
    candidates.append(job_dir.parent.parent / "app" / "tools" / "audit" / "rule_repair_map.json")
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _repair_files(repo_root: Optional[Path], job_dir: Path) -> List[Path]:
    roots: List[Path] = []
    if repo_root:
        roots.append(Path(repo_root) / "app" / "tools" / "repair")
    roots.append(Path("/app/tools/repair"))
    roots.append(job_dir.parent.parent / "app" / "tools" / "repair")
    for root in roots:
        if root.exists() and root.is_dir():
            return sorted(p for p in root.rglob("*") if p.is_file())
    return []


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


def _blocked_payload(job_dir: Path, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    report_path = Path(job_dir) / "audit" / ARTIFACT_NAME
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": "BLOCKED",
        "policy_design_outcome": "policy_design_blocked",
        "policy_design_recorded": False,
        "blockers": [reason],
        "details": details or {},
        "policy": design_only_policy_flags(),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "allowed_policy_design_outcomes": sorted(ALLOWED_POLICY_DESIGN_OUTCOMES),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload


def _default_review_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / "learned_strategy_production_test_review.json"


def _default_readiness_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / "learned_strategy_production_testing_readiness_report.json"


def _extract_evidence(review_payload: Dict[str, Any], review_report_path: Path, job_dir: Path, readiness_report_path: Optional[Path]) -> Dict[str, Any]:
    comparison = review_payload.get("normal_vs_learned_comparison_summary")
    if not isinstance(comparison, dict):
        comparison = {}
    normal_pdf = _as_path(review_payload.get("normal_final_pdf"))
    learned_pdf = _as_path(review_payload.get("learned_trial_pdf")) or _as_path(review_payload.get("production_test_sidecar_pdf"))
    production_test_report = _as_path(review_payload.get("production_test_report_path"))
    readiness_report = readiness_report_path or _default_readiness_path(job_dir)

    evidence_hashes = {
        "production_readiness_report_sha256": sha256_file(readiness_report),
        "production_test_report_sha256": clean_str(review_payload.get("production_test_report_sha256")) or sha256_file(production_test_report),
        "production_test_review_report_sha256": sha256_file(review_report_path),
        "normal_final_pdf_sha256": clean_str(comparison.get("normal_final_sha256")) or sha256_file(normal_pdf),
        "learned_trial_or_test_pdf_sha256": (
            clean_str(comparison.get("learned_trial_sha256"))
            or clean_str(comparison.get("production_test_sidecar_sha256"))
            or sha256_file(learned_pdf)
        ),
    }
    artifacts = {
        "production_testing_readiness_report": str(readiness_report) if readiness_report else None,
        "production_test_report": str(production_test_report) if production_test_report else None,
        "production_test_review_report": str(review_report_path),
        "normal_final_pdf": str(normal_pdf) if normal_pdf else None,
        "learned_trial_or_test_pdf": str(learned_pdf) if learned_pdf else None,
        "normal_vs_learned_comparison_summary": comparison,
        "manual_review_notes": _notes(review_payload.get("manual_review_notes")),
        "known_risks": _notes(review_payload.get("known_risks")),
    }
    return {"evidence_hashes": evidence_hashes, "artifacts": artifacts, "comparison": comparison}


def _missing_required(evidence: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    artifacts = evidence["artifacts"]
    hashes = evidence["evidence_hashes"]
    if not artifacts.get("normal_vs_learned_comparison_summary"):
        missing.append("normal_vs_learned_comparison_summary")
    if not artifacts.get("manual_review_notes"):
        missing.append("manual_review_notes")
    if not artifacts.get("known_risks"):
        missing.append("known_risks")
    for name in [
        "production_testing_readiness_report",
        "production_test_report",
        "production_test_review_report",
        "normal_final_pdf",
        "learned_trial_or_test_pdf",
    ]:
        if not artifacts.get(name):
            missing.append(name)
    for name in MANDATORY_HASH_NAMES:
        if not hashes.get(name):
            missing.append(name)
    return sorted(set(missing))


def write_learned_strategy_adoption_policy_design(
    *,
    job_dir: Path,
    production_test_review_report_path: Optional[Path] = None,
    production_readiness_report_path: Optional[Path] = None,
    reviewer: str,
    candidate_id: str,
    rule_id: str,
    policy_design_outcome: str = "policy_design_recorded",
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write a non-operative policy-design record for future adoption discussion."""
    job_dir = Path(job_dir)
    report_path = job_dir / "audit" / ARTIFACT_NAME
    review_path = Path(production_test_review_report_path) if production_test_review_report_path else _default_review_path(job_dir)

    if not review_path.exists() or not review_path.is_file():
        return _blocked_payload(job_dir, "missing_production_test_review_report", {"path": str(review_path)})

    reviewer = clean_str(reviewer)
    candidate_id = clean_str(candidate_id)
    rule_id = clean_str(rule_id)
    if not reviewer:
        return _blocked_payload(job_dir, "missing_reviewer", {})
    if not candidate_id:
        return _blocked_payload(job_dir, "missing_candidate_id", {})
    if not rule_id:
        return _blocked_payload(job_dir, "missing_rule_id", {})

    try:
        requested_outcome = validate_policy_design_outcome(policy_design_outcome)
    except ValueError as exc:
        return _blocked_payload(job_dir, str(exc), {"policy_design_outcome": policy_design_outcome})

    try:
        review_payload = load_json(review_path)
    except Exception as exc:
        return _blocked_payload(job_dir, "invalid_production_test_review_report_json", {"error": f"{type(exc).__name__}: {exc}"})

    if clean_str(review_payload.get("candidate_id")) != candidate_id:
        return _blocked_payload(job_dir, "candidate_id_mismatch", {"expected": candidate_id, "actual": review_payload.get("candidate_id")})
    if clean_str(review_payload.get("rule_id")) != rule_id:
        return _blocked_payload(job_dir, "rule_id_mismatch", {"expected": rule_id, "actual": review_payload.get("rule_id")})

    status_path = _status_json_path(job_dir)
    package_paths = _package_deliverables(job_dir)
    rule_map_path = _rule_map_path(repo_root, job_dir)
    repair_paths = _repair_files(repo_root, job_dir)
    protected_paths: List[Path] = [p for p in [status_path, rule_map_path] if p]
    protected_paths.extend(package_paths)
    protected_paths.extend(repair_paths)
    before_snapshot = _snapshot(protected_paths)

    evidence = _extract_evidence(review_payload, review_path, job_dir, production_readiness_report_path)
    missing = _missing_required(evidence)
    outcome = "policy_design_incomplete" if missing else requested_outcome
    result = "INCOMPLETE" if missing else "PASS"

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": result,
        "policy_design_outcome": outcome,
        "policy_design_recorded": True,
        "evidence_package_complete_for_policy_discussion": not bool(missing),
        "missing_policy_discussion_prerequisites": missing,
        "reviewer": reviewer,
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "future_separate_approver_identity_required": True,
        "approver_identity_used_for_approval_in_patch_20a": False,
        "policy": design_only_policy_flags(),
        "mandatory_artifacts": MANDATORY_ARTIFACT_NAMES,
        "mandatory_hashes": MANDATORY_HASH_NAMES,
        "evidence_artifacts": evidence["artifacts"],
        "evidence_hashes": evidence["evidence_hashes"],
        "normal_vs_learned_comparison_summary": evidence["comparison"],
        "manual_review_notes": evidence["artifacts"].get("manual_review_notes", []),
        "known_risks": evidence["artifacts"].get("known_risks", []),
        "mandatory_future_gates": MANDATORY_FUTURE_GATES,
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "allowed_policy_design_outcomes": sorted(ALLOWED_POLICY_DESIGN_OUTCOMES),
        "forbidden_mutation_list": [
            "authoritative normal final PDF",
            "authoritative STATUS.json",
            "package deliverables",
            "app/tools/repair/*",
            "app/tools/audit/rule_repair_map.json in Patch 20A",
            "activation metadata in Patch 20A",
        ],
        "allowed_future_mutation_list_policy_text_only": [
            "Patch 20A authorizes no mutations outside this design artifact.",
            "A future adoption patch must define exact backup artifacts before any mutation.",
            "A future adoption patch must define exact apply targets before any mutation.",
            "A future adoption patch must define rollback verification before any mutation.",
        ],
        "backup_requirements_policy_text_only": [
            "Record pre-apply hashes for every future apply target.",
            "Store byte-for-byte backups outside package/status deliverables before future apply.",
            "Record backup paths and hashes in a future audit artifact.",
        ],
        "rollback_requirements_policy_text_only": [
            "A future rollback command must be explicit and separately invoked.",
            "A future rollback must restore every backed-up file by hash.",
            "A future rollback must write a rollback audit artifact.",
        ],
        "future_command_family": "tools/audit/learned_strategy_adoption_* (future, not implemented in Patch 20A)",
        "future_explicit_apply_flag_required": "--apply",
        "future_rollback_command_required": True,
        "adoption_plan": None,
        "artifact_path": str(report_path),
    }

    # Only this design artifact is written. No adoption plan, apply, rollback, package,
    # status, rule-map, repair, or final-PDF mutation is authorized or performed.
    write_json_atomic(report_path, payload)

    after_snapshot = _snapshot(protected_paths)
    protected_mutations = [path for path, before in before_snapshot.items() if after_snapshot.get(path) != before]
    payload["protected_mutation_count"] = len(protected_mutations)
    payload["protected_mutations"] = protected_mutations
    payload["authoritative_status_json"] = str(status_path) if status_path else None
    payload["authoritative_status_json_sha256_before"] = before_snapshot.get(str(status_path), {}).get("sha256") if status_path else None
    payload["authoritative_status_json_sha256_after"] = after_snapshot.get(str(status_path), {}).get("sha256") if status_path else None
    payload["rule_map_sha256_before"] = before_snapshot.get(str(rule_map_path), {}).get("sha256") if rule_map_path else None
    payload["rule_map_sha256_after"] = after_snapshot.get(str(rule_map_path), {}).get("sha256") if rule_map_path else None
    payload["package_deliverable_snapshot_before"] = {str(p): before_snapshot.get(str(p)) for p in package_paths}
    payload["package_deliverable_snapshot_after"] = {str(p): after_snapshot.get(str(p)) for p in package_paths}
    payload["app_tools_repair_snapshot_count"] = len(repair_paths)

    if protected_mutations:
        payload["result"] = "BLOCKED"
        payload["policy_design_outcome"] = "policy_design_blocked"
        payload["policy_design_recorded"] = False
        payload["blockers"] = ["protected_artifact_mutation_detected"]

    write_json_atomic(report_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Write design-only learned strategy adoption policy requirements")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--production-test-review-report", default="")
    parser.add_argument("--production-readiness-report", default="")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--policy-design-outcome", default="policy_design_recorded")
    parser.add_argument("--repo-root", default="/")
    ns = parser.parse_args()

    payload = write_learned_strategy_adoption_policy_design(
        job_dir=Path(ns.job_dir),
        production_test_review_report_path=Path(ns.production_test_review_report) if ns.production_test_review_report else None,
        production_readiness_report_path=Path(ns.production_readiness_report) if ns.production_readiness_report else None,
        reviewer=ns.reviewer,
        candidate_id=ns.candidate_id,
        rule_id=ns.rule_id,
        policy_design_outcome=ns.policy_design_outcome,
        repo_root=Path(ns.repo_root) if ns.repo_root else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("result") in {"PASS", "INCOMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
