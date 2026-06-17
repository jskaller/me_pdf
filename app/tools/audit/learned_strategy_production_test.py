#!/usr/bin/env python3
"""Controlled production-testing diagnostics for learned strategy candidates.

Patch 19A is diagnostic-only. It creates a production-test sidecar report for
learned replacement-trial outputs only after production-testing readiness evidence
is complete. It never adopts a learned PDF, never changes authoritative STATUS.json,
never mutates package deliverables, never softens verdicts, and never marks a
candidate as adoptable.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "learned-strategy-production-test.v1"
ARTIFACT_NAME = "learned_strategy_production_test_report.json"
MODE = "controlled_production_testing_diagnostic"
SIDE_CAR_DIR_NAME = "learned_strategy_production_test"


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


def no_adoption_policy() -> Dict[str, bool]:
    return {
        "production_test_only": True,
        "normal_final_pdf_remains_authoritative": True,
        "candidate_is_adoptable": False,
        "final_pdf_adoption_performed": False,
        "production_repair_replacement_performed": False,
        "verdict_softening_performed": False,
        "package_status_mutation_performed": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
    }


def _records(payload: Dict[str, Any], *names: str) -> List[Dict[str, Any]]:
    for name in names:
        value = payload.get(name)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def _candidate_key(record: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        clean_str(record.get("rule_id")),
        clean_str(record.get("candidate_id")),
        clean_str(record.get("attempt_id")),
    )


def _safe_name(record: Dict[str, Any], index: int) -> str:
    raw = clean_str(record.get("attempt_id")) or clean_str(record.get("candidate_id")) or f"candidate-{index}"
    return raw.replace("/", "-").replace(" ", "_")


def _path_from_record(record: Dict[str, Any], *fields: str) -> Optional[Path]:
    for field in fields:
        value = record.get(field)
        if value:
            return Path(str(value))
    return None


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
    paths.extend(p for p in job_dir.iterdir() if p.is_file() and p.name in names) if job_dir.exists() else None
    deduped: Dict[str, Path] = {str(p.resolve()): p for p in paths}
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


def _blocked_payload(job_dir: Path, reason: str, missing: Optional[List[str]] = None) -> Dict[str, Any]:
    audit_dir = Path(job_dir) / "audit"
    report_path = audit_dir / ARTIFACT_NAME
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": "BLOCKED",
        "production_test_performed": False,
        "blockers": [reason],
        "missing_prerequisites": missing or [],
        "candidate_count": 0,
        "evaluated_count": 0,
        "results": [],
        "policy": no_adoption_policy(),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload


def _readiness_complete_records(readiness_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        record
        for record in _records(readiness_payload, "results", "decisions")
        if record.get("readiness_decision") == "production_testing_evidence_complete"
    ]


def _index_trials(trial_payload: Dict[str, Any]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    return {_candidate_key(record): record for record in _records(trial_payload, "results", "decisions")}


def evaluate_learned_strategy_production_test(
    *,
    readiness_report_path: Path,
    replacement_trial_report_path: Path,
    job_dir: Path,
    normal_final_pdf: Optional[Path] = None,
) -> Dict[str, Any]:
    """Create a controlled production-test diagnostic report.

    The function only writes under JOB/audit. It copies learned trial PDFs into a
    production-test sidecar area for evaluation evidence and snapshots normal
    package/status artifacts before and after to prove no authoritative mutation.
    """
    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    report_path = audit_dir / ARTIFACT_NAME
    readiness_report_path = Path(readiness_report_path)
    replacement_trial_report_path = Path(replacement_trial_report_path)

    missing = [str(p) for p in (readiness_report_path, replacement_trial_report_path) if not p.exists()]
    if missing:
        return _blocked_payload(job_dir, "missing_production_test_prerequisite_artifact", missing)

    readiness_payload = load_json(readiness_report_path)
    trial_payload = load_json(replacement_trial_report_path)
    complete_records = _readiness_complete_records(readiness_payload)
    if not complete_records:
        return _blocked_payload(job_dir, "production_testing_evidence_not_complete", [])

    trial_index = _index_trials(trial_payload)
    status_path = _status_json_path(job_dir)
    package_paths = _package_deliverables(job_dir)
    protected_paths = [p for p in [status_path] if p] + package_paths
    before_snapshot = _snapshot(protected_paths)

    sidecar_root = audit_dir / SIDE_CAR_DIR_NAME
    results: List[Dict[str, Any]] = []
    copied_count = 0
    missing_trial_output_count = 0

    for index, ready in enumerate(complete_records, start=1):
        trial = trial_index.get(_candidate_key(ready)) or {}
        learned_trial_pdf = _path_from_record(trial, "learned_trial_pdf", "trial_pdf", "learned_output_pdf")
        normal_trial_pdf = _path_from_record(trial, "normal_final_pdf", "normal_pdf") or normal_final_pdf
        result: Dict[str, Any] = {
            "rule_id": ready.get("rule_id"),
            "candidate_id": ready.get("candidate_id"),
            "strategy_id": ready.get("strategy_id"),
            "attempt_id": ready.get("attempt_id"),
            "readiness_decision": ready.get("readiness_decision"),
            "trial_decision": trial.get("trial_decision"),
            "production_test_decision": "production_test_blocked",
            "learned_trial_pdf": str(learned_trial_pdf) if learned_trial_pdf else None,
            "normal_final_pdf": str(normal_trial_pdf) if normal_trial_pdf else None,
            "learned_trial_sha256": sha256_file(learned_trial_pdf),
            "normal_final_sha256": sha256_file(normal_trial_pdf),
            "learned_differs_from_normal": False,
            "candidate_is_adoptable": False,
            "final_pdf_adoption_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
            "package_status_mutation_performed": False,
        }
        if not learned_trial_pdf or not learned_trial_pdf.exists() or not learned_trial_pdf.is_file():
            result["blockers"] = ["missing_learned_trial_output"]
            missing_trial_output_count += 1
            results.append(result)
            continue

        sidecar_dir = sidecar_root / _safe_name(ready, index)
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        sidecar_pdf = sidecar_dir / "learned_production_test.pdf"
        shutil.copy2(learned_trial_pdf, sidecar_pdf)
        copied_count += 1
        learned_hash = sha256_file(sidecar_pdf)
        normal_hash = sha256_file(normal_trial_pdf)
        result.update(
            {
                "production_test_decision": "production_test_diagnostic_complete",
                "production_test_sidecar_pdf": str(sidecar_pdf),
                "production_test_sidecar_sha256": learned_hash,
                "learned_differs_from_normal": bool(learned_hash and normal_hash and learned_hash != normal_hash),
                "simulated_status_verdict_source": "learned_production_test_sidecar_only",
                "authoritative_status_json_used": str(status_path) if status_path else None,
                "authoritative_status_json_mutated": False,
                "package_deliverables_mutated": False,
                "blockers": [],
            }
        )
        results.append(result)

    after_snapshot = _snapshot(protected_paths)
    protected_mutations = [path for path, before in before_snapshot.items() if after_snapshot.get(path) != before]
    result_status = "PASS" if copied_count and not missing_trial_output_count and not protected_mutations else "BLOCKED"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": MODE,
        "result": result_status,
        "production_test_performed": bool(copied_count),
        "source_readiness_artifact": str(readiness_report_path),
        "source_replacement_trial_artifact": str(replacement_trial_report_path),
        "candidate_count": len(complete_records),
        "evaluated_count": len(results),
        "copied_sidecar_count": copied_count,
        "missing_trial_output_count": missing_trial_output_count,
        "protected_mutation_count": len(protected_mutations),
        "protected_mutations": protected_mutations,
        "authoritative_status_json": str(status_path) if status_path else None,
        "authoritative_status_json_sha256_before": before_snapshot.get(str(status_path), {}).get("sha256") if status_path else None,
        "authoritative_status_json_sha256_after": after_snapshot.get(str(status_path), {}).get("sha256") if status_path else None,
        "package_deliverable_snapshot_before": before_snapshot,
        "package_deliverable_snapshot_after": after_snapshot,
        "results": results,
        "summary": {
            "production_test_diagnostic_complete": sum(1 for r in results if r.get("production_test_decision") == "production_test_diagnostic_complete"),
            "production_test_blocked": sum(1 for r in results if r.get("production_test_decision") == "production_test_blocked"),
        },
        "policy": no_adoption_policy(),
        "artifact_path": str(report_path),
    }
    write_json_atomic(report_path, payload)
    return payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run controlled learned production-test diagnostics")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--readiness-report")
    parser.add_argument("--replacement-trial-report")
    parser.add_argument("--normal-final-pdf")
    ns = parser.parse_args()
    job = Path(ns.job_dir)
    audit = job / "audit"
    payload = evaluate_learned_strategy_production_test(
        readiness_report_path=Path(ns.readiness_report) if ns.readiness_report else audit / "learned_strategy_production_testing_readiness_report.json",
        replacement_trial_report_path=Path(ns.replacement_trial_report) if ns.replacement_trial_report else audit / "learned_strategy_replacement_trial_report.json",
        job_dir=job,
        normal_final_pdf=Path(ns.normal_final_pdf) if ns.normal_final_pdf else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
