#!/usr/bin/env python3
"""
post_job_indexer.py

Patch 4 learned-strategy indexing.

Default behavior is dry-run only. The indexer consumes:

- JOB/audit/learned_strategies.json
- JOB/audit/residual_analysis.json, when present
- app/tools/audit/rule_repair_map.json

It emits:

- JOB/audit/strategy_indexing_report.json

It does not mutate rule_repair_map.json by default.
It does not promote generated scripts into canonical repair folders.
It does not adopt generated candidate PDFs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = "strategy-indexing-report.v1"
LEARNED_SCHEMA_VERSION = "learned-strategies.v1"
REPORT_FILENAME = "strategy_indexing_report.json"

DEFAULT_RULE_MAP_CANDIDATES = (
    Path("app/tools/audit/rule_repair_map.json"),
    Path("tools/audit/rule_repair_map.json"),
)


class IndexingError(Exception):
    """Raised for malformed inputs or unsafe indexing conditions."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def read_json(path: Path, label: str, required: bool = True) -> Optional[Dict[str, Any]]:
    if not path.exists():
        if required:
            raise IndexingError(f"missing {label}: {path}")
        return None
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise IndexingError(f"malformed {label}: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IndexingError(f"malformed {label}: expected JSON object at {path}")
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default))
    tmp.replace(path)


def sha256_text(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=json_default).encode("utf-8")).hexdigest()


def sha256_file(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_default_rule_map() -> Path:
    for candidate in DEFAULT_RULE_MAP_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_RULE_MAP_CANDIDATES[0]


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def gate_failed(value: Any) -> bool:
    if isinstance(value, str):
        return value.upper() not in ("", "PASS", "SKIPPED", "NOT_RUN", "NA", "N/A")
    if isinstance(value, bool):
        return value is False
    if isinstance(value, dict):
        result = value.get("result")
        if result is not None:
            return gate_failed(result)
    return False


def any_gate_failed(gate_results: Any) -> bool:
    gates = as_dict(gate_results)
    return any(gate_failed(value) for value in gates.values())


def record_identity(record: Dict[str, Any]) -> str:
    basis = {
        "run_id": record.get("run_id"),
        "job_dir": record.get("job_dir"),
        "rule_id": record.get("rule_id"),
        "script_path": record.get("script_path"),
        "script_sha256": record.get("script_sha256"),
        "attempt_number": record.get("attempt_number"),
        "outcome": record.get("outcome"),
    }
    return sha256_text(basis)[:16]


def residual_hash_and_path(path: Path) -> Tuple[Optional[str], Optional[str]]:
    if not path.exists():
        return None, None
    return sha256_file(path), str(path)


def load_learned_strategies(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    data = read_json(path, "learned_strategies.json", required=True)
    records = data.get("records")
    if not isinstance(records, list):
        raise IndexingError(f"malformed learned_strategies.json: records must be a list at {path}")
    schema = data.get("schema_version")
    if schema and schema != LEARNED_SCHEMA_VERSION:
        raise IndexingError(
            f"malformed learned_strategies.json: unsupported schema_version {schema!r} at {path}"
        )
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            raise IndexingError(f"malformed learned_strategies.json: record {idx} is not an object")
    return data


def load_rule_map(path: Path) -> Dict[str, Any]:
    data = read_json(path, "rule_repair_map.json", required=True)
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise IndexingError(f"malformed rule_repair_map.json: rules must be an object at {path}")
    return data


def validate_residual(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return read_json(path, "residual_analysis.json", required=True)


def rejection(record: Dict[str, Any], reasons: Iterable[str]) -> Dict[str, Any]:
    reason_list = [r for r in reasons if r]
    return {
        "record_id": record_identity(record),
        "rule_id": record.get("rule_id"),
        "outcome": record.get("outcome"),
        "script_path": record.get("script_path"),
        "indexing_eligible": bool(record.get("indexing_eligible")),
        "clean": bool(record.get("clean")),
        "reasons": reason_list or ["not_indexing_eligible"],
        "indexing_blockers": as_list(record.get("indexing_blockers")),
        "failure_summary": record.get("failure_summary"),
        "introduced_rules": as_list(record.get("introduced_rules")),
        "worsened_rules": as_list(record.get("worsened_rules")),
        "gate_results": as_dict(record.get("gate_results")),
        "evidence": {
            "job_dir": record.get("job_dir"),
            "attempt_number": record.get("attempt_number"),
            "run_id": record.get("run_id"),
        },
    }


def eligibility_errors(record: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if record.get("clean") is not True:
        errors.append("record_not_clean")
    if record.get("indexing_eligible") is not True:
        errors.append("record_not_indexing_eligible")
    if as_list(record.get("indexing_blockers")):
        errors.append("indexing_blockers_present")
    if not clean_str(record.get("rule_id")):
        errors.append("missing_rule_id")
    if not clean_str(record.get("script_path")):
        errors.append("missing_script_path")
    if record.get("target_rule_resolved") is not True:
        errors.append("target_rule_not_resolved")
    if as_list(record.get("introduced_rules")):
        errors.append("introduced_rules_present")
    if as_list(record.get("worsened_rules")):
        errors.append("worsened_rules_present")
    if any_gate_failed(record.get("gate_results")):
        errors.append("failed_gate_results_present")
    if record.get("outcome") != "clean_success":
        errors.append(f"unsupported_outcome:{record.get('outcome')}")

    return errors


def build_strategy_entry(
    record: Dict[str, Any],
    residual_path: Path,
    residual_hash: Optional[str],
) -> Dict[str, Any]:
    validation_artifacts = as_dict(record.get("validation_artifacts"))
    generation_response = as_dict(record.get("generation_response"))

    repair_order = record.get("repair_order")
    run_last = bool(record.get("run_last", False))

    return {
        "source": "learned_strategy_capture",
        "repair_script": record.get("script_path"),
        "script_path": record.get("script_path"),
        "script_sha256": record.get("script_sha256"),
        "strategy": record.get("strategy") or "generated_clean_strategy",
        "args_pattern": record.get("args_pattern") or "",
        "repair_order": repair_order,
        "run_last": run_last,
        "repair_order_validated_by_isolated_evidence": False,
        "run_last_validated_by_isolated_evidence": False,
        "clean_pass_count": 1,
        "pass_count": 1,
        "fail_count": 0,
        "pass_rate": 1.0,
        "doc_type_stats": [],
        "introduced_rules": [],
        "worsened_rules": [],
        "gate_results": as_dict(record.get("gate_results")),
        "known_failure_modes": [],
        "review_required": bool(record.get("review_required", False)),
        "last_observed_at": record.get("created_at") or utc_now_iso(),
        "proposed_resolvability": record.get("proposed_resolvability")
        or generation_response.get("proposed_resolvability"),
        "evidence": {
            "learned_strategy_record_id": record_identity(record),
            "learned_strategy_record_hash": sha256_text(record),
            "job_dir": record.get("job_dir"),
            "residual_analysis_path": str(residual_path) if residual_path.exists() else None,
            "residual_analysis_sha256": residual_hash,
            "validation_artifacts": validation_artifacts,
            "attempt_number": record.get("attempt_number"),
            "run_id": record.get("run_id"),
            "target_rule_pre_count": record.get("pre_count"),
            "target_rule_post_count": record.get("post_count"),
        },
    }


def propose_change(
    record: Dict[str, Any],
    rule_map: Dict[str, Any],
    residual_path: Path,
    residual_hash: Optional[str],
) -> Dict[str, Any]:
    rules = as_dict(rule_map.get("rules"))
    rule_id = clean_str(record.get("rule_id"))
    existing = rules.get(rule_id)
    strategy = build_strategy_entry(record, residual_path, residual_hash)

    if existing is None:
        return {
            "action": "add_rule",
            "rule_id": rule_id,
            "reason": "rule_absent_from_map",
            "proposed_entry": {
                "clause": record.get("clause") or "",
                "description": record.get("description") or "",
                "manual": False,
                "resolvability": record.get("proposed_resolvability") or "repairable_review",
                "emits_review_artifact": False,
                "review_required": True,
                "strategies": [strategy],
                "evidence_counters": {
                    "clean_pass_count": 1,
                    "fail_count": 0,
                    "pass_rate": 1.0,
                },
                "review_state": "new_learned_strategy_review_required",
            },
        }

    existing_resolvability = existing.get("resolvability")
    existing_strategies = as_list(existing.get("strategies"))
    has_effective_primary = bool(existing_strategies) and existing_resolvability == "effective"

    if existing_resolvability == "repairable_unbuilt":
        return {
            "action": "attach_strategy_to_repairable_unbuilt",
            "rule_id": rule_id,
            "reason": "clean_strategy_for_repairable_unbuilt_rule",
            "preserve_existing_primary": True,
            "proposed_resolvability": "effective_if_policy_allows",
            "proposed_strategy": strategy,
        }

    if existing_resolvability == "repairable_review":
        return {
            "action": "attach_strategy_preserve_review",
            "rule_id": rule_id,
            "reason": "clean_strategy_for_review_rule",
            "preserve_review_semantics": True,
            "proposed_resolvability": "repairable_review",
            "proposed_strategy": strategy,
        }

    if has_effective_primary:
        return {
            "action": "add_alternate_strategy",
            "rule_id": rule_id,
            "reason": "existing_effective_primary_preserved",
            "preserve_existing_primary": True,
            "proposed_container": "edge_cases_or_lower_ranked_strategy",
            "proposed_strategy": strategy,
        }

    return {
        "action": "attach_strategy_preserve_existing_semantics",
        "rule_id": rule_id,
        "reason": "known_rule_without_effective_primary",
        "existing_resolvability": existing_resolvability,
        "preserve_existing_primary": True,
        "proposed_strategy": strategy,
    }


def base_policy() -> Dict[str, Any]:
    return {
        "canonical_rule_map_mutation_performed": False,
        "generated_script_promotion_performed": False,
        "final_pdf_adoption_performed": False,
        "only_clean_indexing_eligible_learned_strategies_can_produce_proposed_rule_map_changes": True,
        "dirty_failed_refusal_transport_records_retained_as_rejected_experiments": True,
        "dry_run_default": True,
        "apply_mode_implemented": False,
    }


def empty_report(
    job_dir: Path,
    rule_map_path: Path,
    learned_path: Path,
    residual_path: Path,
    mode: str,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "job_dir": str(job_dir),
        "rule_map_path": str(rule_map_path),
        "learned_strategies_path": str(learned_path),
        "residual_analysis_path": str(residual_path),
        "mode": mode,
        "eligible_records": [],
        "indexed_records": [],
        "rejected_records": [],
        "proposed_rule_map_changes": [],
        "rejected_experiments": [],
        "warnings": [],
        "policy": base_policy(),
    }


def run_indexing(
    *,
    job_dir: Path,
    rule_map_path: Path,
    dry_run: bool = True,
    report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not dry_run:
        raise IndexingError("apply/write-rule-map mode is not implemented in Patch 4; rerun with --dry-run")

    job_dir = Path(job_dir)
    rule_map_path = Path(rule_map_path)
    audit_dir = job_dir / "audit"
    learned_path = audit_dir / "learned_strategies.json"
    residual_path = audit_dir / "residual_analysis.json"
    report_path = Path(report_path) if report_path else audit_dir / REPORT_FILENAME

    report = empty_report(
        job_dir=job_dir,
        rule_map_path=rule_map_path,
        learned_path=learned_path,
        residual_path=residual_path,
        mode="dry_run",
    )

    rule_map = load_rule_map(rule_map_path)
    residual = validate_residual(residual_path)
    residual_hash, _ = residual_hash_and_path(residual_path)

    if residual is None:
        report["warnings"].append("residual_analysis.json missing; proposals retain learned-strategy evidence only")

    learned = load_learned_strategies(learned_path)
    if learned is None:
        report["warnings"].append("learned_strategies.json missing; safe no-op")
        write_json_atomic(report_path, report)
        return report

    records = learned.get("records", [])
    if not records:
        report["warnings"].append("learned_strategies.json contains no records; safe no-op")

    original_rule_map = copy.deepcopy(rule_map)

    for record in records:
        errors = eligibility_errors(record)
        if errors:
            rejected = rejection(record, errors)
            report["rejected_records"].append(rejected)
            report["rejected_experiments"].append(rejected)
            continue

        eligible = {
            "record_id": record_identity(record),
            "rule_id": record.get("rule_id"),
            "script_path": record.get("script_path"),
            "script_sha256": record.get("script_sha256"),
            "outcome": record.get("outcome"),
            "evidence_hash": sha256_text(record),
        }
        report["eligible_records"].append(eligible)

        proposal = propose_change(record, rule_map, residual_path, residual_hash)
        report["proposed_rule_map_changes"].append(proposal)
        report["indexed_records"].append(
            {
                "record_id": eligible["record_id"],
                "rule_id": eligible["rule_id"],
                "action": proposal.get("action"),
                "dry_run": True,
                "canonical_mutation_performed": False,
            }
        )

    if rule_map != original_rule_map:
        raise IndexingError("internal safety failure: dry-run mutated in-memory rule map")

    write_json_atomic(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a dry-run learned-strategy indexing report.")
    parser.add_argument("job_dir", nargs="?", help="Path to the job directory")
    parser.add_argument("--job-dir", dest="job_dir_flag", help="Path to the job directory")
    parser.add_argument(
        "--rule-map",
        "--map",
        dest="rule_map",
        default=None,
        help="Path to rule_repair_map.json",
    )
    parser.add_argument("--report", default=None, help="Optional report output path")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry-run only; this is the default")
    parser.add_argument(
        "--apply",
        "--write-rule-map",
        dest="apply",
        action="store_true",
        help="Rejected in Patch 4; apply mode is intentionally not implemented",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    job_dir_arg = args.job_dir_flag or args.job_dir
    if not job_dir_arg:
        parser.error("job_dir is required, either positional or --job-dir")

    rule_map_path = Path(args.rule_map) if args.rule_map else resolve_default_rule_map()

    try:
        report = run_indexing(
            job_dir=Path(job_dir_arg),
            rule_map_path=rule_map_path,
            dry_run=not args.apply,
            report_path=Path(args.report) if args.report else None,
        )
    except IndexingError as exc:
        print(json.dumps({"result": "ERROR", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True, default=json_default))
    return 0


if __name__ == "__main__":
    sys.exit(main())
