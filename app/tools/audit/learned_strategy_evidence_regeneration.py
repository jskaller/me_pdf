#!/usr/bin/env python3
"""Non-mutating learned-strategy evidence regeneration/resolution helper.

Patch 22B records whether the learned trial/test PDF, production-testing
readiness report, and production-test report can be resolved and hashed. It is a
sidecar-only diagnostic: no apply, no backup, no rollback, no rule-map mutation,
no repair replacement, no package/status mutation, and no final PDF adoption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "learned-strategy-evidence-regeneration.v1"
ARTIFACT_NAME = "learned_strategy_evidence_regeneration.json"
MODE = "evidence_regeneration_only"

ALLOWED_OUTCOMES = {
    "evidence_regeneration_recorded",
    "evidence_regeneration_incomplete",
    "evidence_regeneration_blocked",
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
    "evidence_regeneration_only": True,
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

PDF_PATH_KEYS = {
    "learned_trial_or_test_pdf",
    "learned_test_pdf",
    "learned_trial_pdf",
    "learned_output_pdf",
    "trial_pdf",
    "test_pdf",
    "output_pdf",
    "candidate_pdf",
    "artifact_pdf",
    "production_test_sidecar_pdf",
    "pdf",
}

REPORT_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "production_readiness_report": (
        "learned_strategy_production_testing_readiness_report.json",
        "learned_strategy_production_readiness.json",
    ),
    "production_test_report": (
        "learned_strategy_production_test_report.json",
        "learned_strategy_production_test.json",
    ),
}

LEARNED_PDF_SOURCE_REPORTS = (
    "learned_strategy_production_test_report.json",
    "learned_strategy_production_test.json",
    "learned_strategy_replacement_trial_report.json",
    "learned_strategy_replacement_trial.json",
    "learned_strategy_output_comparisons.json",
    "learned_strategy_output_comparison.json",
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
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def artifact_path(job_dir: Path) -> Path:
    return Path(job_dir) / "audit" / ARTIFACT_NAME


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


def resolve_path(raw: Any, *, job_dir: Path, repo_root: Path) -> Optional[Path]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    candidate = Path(text)
    candidates: List[Path] = [candidate]
    if not candidate.is_absolute():
        candidates.extend([job_dir / candidate, repo_root / candidate])
    if text.startswith("/app/"):
        candidates.append(repo_root / text[len("/app/"):])
    for item in candidates:
        if item.exists():
            return item.resolve()
    return candidates[0].resolve()


def recursive_find_path(data: Any, keys: Iterable[str]) -> Optional[str]:
    wanted = set(keys)
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key) in wanted and isinstance(value, str) and value.strip():
                return value
        for value in data.values():
            found = recursive_find_path(value, wanted)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find_path(item, wanted)
            if found:
                return found
    return None


def first_existing_report(audit_dir: Path, names: Iterable[str]) -> Optional[Path]:
    for name in names:
        path = audit_dir / name
        if path.exists() and path.is_file():
            return path.resolve()
    return None


def locate_report_artifact(job_dir: Path, target: str) -> Tuple[Optional[Path], str]:
    audit_dir = Path(job_dir) / "audit"
    names = REPORT_CANDIDATES[target]
    path = first_existing_report(audit_dir, names)
    if path:
        return path, f"artifact_reused_existing:{path.name}"
    return None, "missing_artifact:" + ",".join(names)


def locate_learned_pdf(job_dir: Path, repo_root: Path) -> Tuple[Optional[Path], str, Optional[str]]:
    audit_dir = Path(job_dir) / "audit"
    for report_name in LEARNED_PDF_SOURCE_REPORTS:
        report_path = audit_dir / report_name
        if not report_path.exists():
            continue
        try:
            payload = load_json(report_path)
        except Exception as exc:
            return None, f"artifact_unverifiable:{report_name}", f"source_report_unreadable:{exc}"
        raw_path = recursive_find_path(payload, PDF_PATH_KEYS)
        if not raw_path:
            continue
        resolved = resolve_path(raw_path, job_dir=job_dir, repo_root=repo_root)
        if resolved and resolved.exists() and resolved.is_file():
            return resolved, f"artifact_reused_existing:{report_name}", None
        return resolved, f"artifact_unverifiable:{report_name}", f"path_not_found:{raw_path}"
    return None, "artifact_missing", "learned_trial_or_test_pdf_path_not_found"


def make_record(
    *,
    target: str,
    path: Optional[Path],
    status: str,
    source_command: Optional[str],
    source_artifact: Optional[str],
    verified_at: str,
    missing_reason: Optional[str] = None,
    unverifiable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    exists = bool(path and path.exists() and path.is_file())
    digest = sha256_file(path) if exists else None
    if exists and status.startswith("artifact_"):
        final_status = status.split(":", 1)[0]
    elif status.startswith("artifact_unverifiable"):
        final_status = "artifact_unverifiable"
    else:
        final_status = "artifact_missing"
    return {
        "target": target,
        "status": final_status,
        "artifact_path": str(path) if path else None,
        "path": str(path) if path else None,
        "sha256": digest,
        "source_command": source_command,
        "source_artifact": source_artifact,
        "verified_at": verified_at,
        "missing_reason": None if digest else missing_reason,
        "unverifiable_reason": unverifiable_reason,
    }


def validate_no_forbidden_states(candidate_id: str, rule_id: str) -> List[str]:
    blockers: List[str] = []
    for label, value in {"candidate_id": candidate_id, "rule_id": rule_id}.items():
        normalized = str(value).strip().lower()
        if normalized in FORBIDDEN_TERMINAL_STATES:
            blockers.append(f"forbidden_terminal_state_detected:{label}:{value}")
    return blockers


def build_artifact(*, job_dir: Path, repo_root: Path, candidate_id: str, rule_id: str) -> Dict[str, Any]:
    job_dir = Path(job_dir).resolve()
    repo_root = Path(repo_root).resolve()
    before = snapshot_protected(job_dir, repo_root)
    verified_at = utc_now()
    blockers = validate_no_forbidden_states(candidate_id, rule_id)

    records: Dict[str, Dict[str, Any]] = {}

    learned_pdf, learned_status, learned_problem = locate_learned_pdf(job_dir, repo_root)
    records["learned_trial_or_test_pdf"] = make_record(
        target="learned_trial_or_test_pdf",
        path=learned_pdf,
        status=learned_status,
        source_command=(
            "python3 app/tools/audit/learned_strategy_replacement_trial.py ... "
            "or python3 app/tools/audit/learned_strategy_production_test.py ..."
        ),
        source_artifact=learned_status.split(":", 1)[1] if ":" in learned_status else None,
        verified_at=verified_at,
        missing_reason=learned_problem if learned_status == "artifact_missing" else None,
        unverifiable_reason=learned_problem if learned_status.startswith("artifact_unverifiable") else None,
    )

    for target in ("production_readiness_report", "production_test_report"):
        path, status = locate_report_artifact(job_dir, target)
        records[target] = make_record(
            target=target,
            path=path,
            status=status,
            source_command=(
                "python3 app/tools/audit/learned_strategy_production_readiness.py ..."
                if target == "production_readiness_report"
                else "python3 app/tools/audit/learned_strategy_production_test.py ..."
            ),
            source_artifact=status.split(":", 1)[1] if ":" in status else None,
            verified_at=verified_at,
            missing_reason=None if path else status,
        )

    missing_targets = [
        key for key, record in records.items()
        if record["status"] == "artifact_missing" or not record.get("sha256")
    ]
    unverifiable_targets = [
        key for key, record in records.items()
        if record["status"] == "artifact_unverifiable"
    ]

    outcome = "evidence_regeneration_recorded"
    result = "PASS"
    if blockers:
        outcome = "evidence_regeneration_blocked"
        result = "BLOCKED"
    elif missing_targets or unverifiable_targets:
        outcome = "evidence_regeneration_incomplete"
        result = "INCOMPLETE"

    after = snapshot_protected(job_dir, repo_root)
    protected_mutations = diff_snapshots(before, after)
    if protected_mutations:
        blockers.append("protected_mutation_detected")
        outcome = "evidence_regeneration_blocked"
        result = "BLOCKED"

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "created_at": verified_at,
        "job_dir": str(job_dir),
        "artifact_path": str(artifact_path(job_dir)),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "result": result,
        "evidence_regeneration_outcome": outcome,
        "allowed_evidence_regeneration_outcomes": sorted(ALLOWED_OUTCOMES),
        "forbidden_terminal_states": sorted(FORBIDDEN_TERMINAL_STATES),
        "blockers": blockers,
        "missing_targets": missing_targets,
        "unverifiable_targets": unverifiable_targets,
        "artifacts": records,
        "source_evidence_hashes": {
            "learned_trial_or_test_pdf_sha256": records["learned_trial_or_test_pdf"].get("sha256"),
            "production_readiness_report_sha256": records["production_readiness_report"].get("sha256"),
            "production_test_report_sha256": records["production_test_report"].get("sha256"),
        },
        "safety_flags": dict(MANDATORY_SAFETY_FLAGS),
        **MANDATORY_SAFETY_FLAGS,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--rule-id", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    artifact = build_artifact(
        job_dir=args.job_dir,
        repo_root=args.repo_root,
        candidate_id=args.candidate_id.strip(),
        rule_id=args.rule_id.strip(),
    )
    out = artifact_path(Path(args.job_dir).resolve())
    write_json_atomic(out, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["result"] in {"PASS", "INCOMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
