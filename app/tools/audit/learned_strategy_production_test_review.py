#!/usr/bin/env python3
"""Reviewed evidence layer for controlled learned production-test reports.

Patch 19B is diagnostic-only. It records human review metadata for a
Patch 19A production-test report without adopting any learned output,
without mutating authoritative STATUS/package artifacts, without softening
verdicts, and without making any candidate production-ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "learned-strategy-production-test-review.v1"
ARTIFACT_NAME = "learned_strategy_production_test_review.json"
MODE = "production_test_review_diagnostic"

ALLOWED_REVIEW_DECISIONS = {
    "review_recorded",
    "review_requires_followup",
    "review_rejected",
}

FORBIDDEN_DECISION_TOKENS = {
    "approved",
    "approval",
    "adopt",
    "adoptable",
    "adoption",
    "production_ready",
    "ready_for_adoption",
    "ready-for-adoption",
    "ready for adoption",
    "production-ready",
    "production ready",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
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


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _split_notes(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_str(v) for v in value if clean_str(v)]
    text = clean_str(value)
    return [text] if text else []


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "review_is_adoption": False,
        "candidate_is_adoptable": False,
        "final_pdf_adoption_performed": False,
        "production_repair_replacement_performed": False,
        "verdict_softening_performed": False,
        "package_status_mutation_performed": False,
        "normal_final_pdf_remains_authoritative": True,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
        "review_makes_candidate_production_ready": False,
    }


def _records(payload: Dict[str, Any], *names: str) -> List[Dict[str, Any]]:
    for name in names:
        value = payload.get(name)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


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
    matches = sorted(p for p in job_dir.rglob("STATUS.json") if p.is_file())
    return matches[0] if matches else None


def _package_deliverables(job_dir: Path) -> List[Path]:
    names = {"AUDIT_REPORT.md", "CHECKSUMS.json", "MANIFEST.json", "STATUS.json"}
    roots = [job_dir / "package", job_dir / "deliverables", job_dir / "output"]
    paths: List[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    if job_dir.exists():
        paths.extend(p for p in job_dir.iterdir() if p.is_file() and p.name in names)
    deduped: Dict[str, Path] = {str(p.resolve()): p for p in paths}
    return [deduped[k] for k in sorted(deduped)]


def _repair_files(repo_root: Optional[Path], job_dir: Path) -> List[Path]:
    roots: List[Path] = []
    if repo_root:
        roots.append(Path(repo_root) / "app" / "tools" / "repair")
    # Container orchestrator commonly passes repo_root=/, where app/tools/repair is valid.
    roots.append(Path("/app/tools/repair"))
    # Unit-test/local fallback near the job dir.
    roots.append(job_dir.parent.parent / "app" / "tools" / "repair")
    paths: List[Path] = []
    for root in roots:
        if root.exists() and root.is_dir():
            paths.extend(p for p in root.rglob("*") if p.is_file())
            break
    deduped: Dict[str, Path] = {str(p.resolve()): p for p in paths}
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
    audit_dir = Path(job_dir) / "audit"
    report_path = audit_dir / ARTIFACT_NAME
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": "BLOCKED",
        "review_performed": False,
        "blockers": [reason],
        "details": details or {},
        "policy": no_adoption_policy(),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload


def validate_review_decision(decision: str) -> str:
    normalized = clean_str(decision).lower()
    if not normalized:
        raise ValueError("missing_review_decision")
    if normalized not in ALLOWED_REVIEW_DECISIONS:
        raise ValueError(f"unsupported_review_decision:{normalized}")
    if any(token in normalized for token in FORBIDDEN_DECISION_TOKENS):
        raise ValueError(f"forbidden_review_decision:{normalized}")
    return normalized


def _find_production_test_record(payload: Dict[str, Any], *, candidate_id: str, rule_id: str) -> Optional[Dict[str, Any]]:
    for record in _records(payload, "results", "decisions"):
        if clean_str(record.get("candidate_id")) == candidate_id and clean_str(record.get("rule_id")) == rule_id:
            return record
    return None


def _comparison_summary(report_payload: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "production_test_report_result": report_payload.get("result"),
        "production_test_decision": record.get("production_test_decision"),
        "readiness_decision": record.get("readiness_decision"),
        "trial_decision": record.get("trial_decision"),
        "learned_differs_from_normal": record.get("learned_differs_from_normal"),
        "normal_final_sha256": record.get("normal_final_sha256"),
        "learned_trial_sha256": record.get("learned_trial_sha256"),
        "production_test_sidecar_sha256": record.get("production_test_sidecar_sha256"),
        "summary": report_payload.get("summary", {}),
    }


def write_learned_strategy_production_test_review(
    *,
    job_dir: Path,
    production_test_report_path: Path,
    reviewer: str,
    candidate_id: str,
    rule_id: str,
    review_decision: str,
    manual_review_notes: Optional[Any] = None,
    known_risks: Optional[Any] = None,
    report_sha256: Optional[str] = None,
    repo_root: Optional[Path] = None,
    follow_up_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """Write a non-adoptive review artifact for a Patch 19A report."""
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    review_path = audit_dir / ARTIFACT_NAME
    production_test_report_path = Path(production_test_report_path)

    if not production_test_report_path.exists() or not production_test_report_path.is_file():
        return _blocked_payload(job_dir, "missing_production_test_report", {"path": str(production_test_report_path)})

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
        decision = validate_review_decision(review_decision)
    except ValueError as exc:
        return _blocked_payload(job_dir, str(exc), {"review_decision": review_decision})

    notes = _split_notes(manual_review_notes)
    risks = _split_notes(known_risks)
    if not notes and not risks:
        return _blocked_payload(job_dir, "missing_review_notes_or_known_risks", {})

    actual_hash = sha256_file(production_test_report_path)
    supplied_hash = clean_str(report_sha256)
    if supplied_hash and supplied_hash != actual_hash:
        return _blocked_payload(
            job_dir,
            "production_test_report_hash_mismatch",
            {"supplied_hash": supplied_hash, "actual_hash": actual_hash},
        )

    try:
        production_payload = load_json(production_test_report_path)
    except Exception as exc:
        return _blocked_payload(job_dir, "invalid_production_test_report_json", {"error": f"{type(exc).__name__}: {exc}"})

    record = _find_production_test_record(production_payload, candidate_id=candidate_id, rule_id=rule_id)
    if record is None:
        return _blocked_payload(job_dir, "production_test_candidate_record_not_found", {"candidate_id": candidate_id, "rule_id": rule_id})

    status_path = _status_json_path(job_dir)
    package_paths = _package_deliverables(job_dir)
    rule_map_path = _rule_map_path(repo_root, job_dir)
    repair_paths = _repair_files(repo_root, job_dir)
    protected_paths: List[Path] = []
    protected_paths.extend([p for p in [status_path, rule_map_path] if p])
    protected_paths.extend(package_paths)
    protected_paths.extend(repair_paths)
    before_snapshot = _snapshot(protected_paths)

    normal_final_pdf = clean_str(record.get("normal_final_pdf"))
    learned_trial_pdf = clean_str(record.get("learned_trial_pdf")) or clean_str(record.get("production_test_sidecar_pdf"))
    production_test_sidecar_pdf = clean_str(record.get("production_test_sidecar_pdf"))

    follow_up = bool(follow_up_required) if follow_up_required is not None else decision == "review_requires_followup"

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": "PASS",
        "review_performed": True,
        "review_decision": decision,
        "reviewer": reviewer,
        "review_timestamp": utc_now_iso(),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "production_test_report_path": str(production_test_report_path),
        "production_test_report_sha256": actual_hash,
        "production_test_report_result": production_payload.get("result"),
        "normal_final_pdf": normal_final_pdf or None,
        "learned_trial_pdf": learned_trial_pdf or None,
        "production_test_sidecar_pdf": production_test_sidecar_pdf or None,
        "normal_vs_learned_comparison_summary": _comparison_summary(production_payload, record),
        "known_risks": risks,
        "manual_review_notes": notes,
        "follow_up_required": follow_up,
        "review_scope": "evidence_review_only_not_approval",
        "policy": no_adoption_policy(),
        "artifact_path": str(review_path),
    }

    # Only the review artifact is written. It is intentionally outside protected
    # package/status/repair/rule-map paths.
    write_json_atomic(review_path, payload)

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
        payload["blockers"] = ["protected_artifact_mutation_detected"]
        payload["review_performed"] = False

    write_json_atomic(review_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a non-adoptive review for a learned production-test report")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--production-test-report")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--review-decision", required=True, choices=sorted(ALLOWED_REVIEW_DECISIONS))
    parser.add_argument("--review-notes", default="")
    parser.add_argument("--known-risks", default="")
    parser.add_argument("--report-sha256", default="")
    parser.add_argument("--follow-up-required", action="store_true")
    parser.add_argument("--repo-root", default="/")
    ns = parser.parse_args()

    job_dir = Path(ns.job_dir)
    report = Path(ns.production_test_report) if ns.production_test_report else job_dir / "audit" / "learned_strategy_production_test_report.json"
    payload = write_learned_strategy_production_test_review(
        job_dir=job_dir,
        production_test_report_path=report,
        reviewer=ns.reviewer,
        candidate_id=ns.candidate_id,
        rule_id=ns.rule_id,
        review_decision=ns.review_decision,
        manual_review_notes=ns.review_notes,
        known_risks=ns.known_risks,
        report_sha256=ns.report_sha256,
        repo_root=Path(ns.repo_root) if ns.repo_root else None,
        follow_up_required=True if ns.follow_up_required else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
