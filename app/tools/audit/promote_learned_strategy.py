#!/usr/bin/env python3
"""
promote_learned_strategy.py

Patch 8 reviewed promotion policy for learned strategies.

Default behavior is dry-run review-packet creation only. This tool reads a
job-scoped strategy_indexing_report.json plus its source artifacts and writes a
human-reviewable strategy_promotion_review.json. It does not mutate the canonical
rule map, does not copy generated scripts into tools/repair, and does not adopt
candidate PDFs.

Apply mode is intentionally not implemented in Patch 8; --apply-rule-map fails
closed with a clear message.
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

SCHEMA_VERSION = "strategy-promotion-review.v1"
REVIEW_FILENAME = "strategy_promotion_review.json"
INDEX_REPORT_FILENAME = "strategy_indexing_report.json"
LEARNED_FILENAME = "learned_strategies.json"
RESIDUAL_FILENAME = "residual_analysis.json"
EXECUTION_LOG_FILENAME = "execution_log.json"
DEFAULT_RULE_MAP_CANDIDATES = (
    Path("app/tools/audit/rule_repair_map.json"),
    Path("tools/audit/rule_repair_map.json"),
)


class PromotionError(Exception):
    """Raised for malformed inputs or unsafe promotion conditions."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def read_json(path: Path, label: str, required: bool = True) -> Optional[Dict[str, Any]]:
    if not path.exists():
        if required:
            raise PromotionError(f"missing {label}: {path}")
        return None
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise PromotionError(f"malformed {label}: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PromotionError(f"malformed {label}: expected JSON object at {path}")
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


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def resolve_default_rule_map() -> Path:
    for candidate in DEFAULT_RULE_MAP_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_RULE_MAP_CANDIDATES[0]


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


def artifact_path(job_dir: Path, filename: str) -> Path:
    return Path(job_dir) / "audit" / filename


def source_path_string(path: Path) -> Optional[str]:
    return str(path) if path.exists() else None


def path_from_record(job_dir: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    p = Path(str(value))
    if p.is_absolute():
        return p
    candidate = job_dir / p
    if candidate.exists():
        return candidate
    return p


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def script_location_status(job_dir: Path, script_path_value: Any) -> str:
    p = path_from_record(job_dir, script_path_value)
    if p is None:
        return "missing"
    if is_relative_to(p, job_dir):
        return "quarantine_only"
    return "outside_job_quarantine"


def execution_records_by_attempt(execution_log: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    records = as_list(as_dict(execution_log).get("records"))
    out: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        attempt_id = clean_str(record.get("attempt_id"))
        if attempt_id:
            out[attempt_id] = record
    return out


def load_rule_map(path: Path) -> Dict[str, Any]:
    data = read_json(path, "rule_repair_map.json", required=True)
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise PromotionError(f"malformed rule_repair_map.json: rules must be an object at {path}")
    return data


def load_learned_records(path: Path) -> List[Dict[str, Any]]:
    data = read_json(path, "learned_strategies.json", required=False)
    if not data:
        return []
    records = data.get("records")
    if not isinstance(records, list):
        raise PromotionError(f"malformed learned_strategies.json: records must be a list at {path}")
    return [r for r in records if isinstance(r, dict)]


def base_policy(apply_mode_requested: bool = False) -> Dict[str, Any]:
    return {
        "dry_run_default": True,
        "mode_requested": "apply_rule_map" if apply_mode_requested else "dry_run",
        "apply_mode_implemented": False,
        "canonical_rule_map_mutation_performed": False,
        "generated_script_promotion_performed": False,
        "final_pdf_adoption_performed": False,
        "rule_map_apply_requires_explicit_reviewed_operator_action": True,
        "rule_map_apply_fails_closed_in_patch_8": True,
        "generated_scripts_must_remain_quarantine_only": True,
        "production_runtime_must_not_depend_on_quarantined_scripts": True,
        "existing_effective_primary_strategies_are_preserved": True,
        "repairable_review_semantics_are_preserved": True,
        "dirty_failed_refusal_records_are_review_evidence_not_promotions": True,
    }


def operator_instructions() -> List[str]:
    return [
        "Review each promotion candidate manually before any later apply-capable patch is used.",
        "Confirm execution evidence, stdout/stderr artifacts, residual-analysis hash, and learned-strategy record hash.",
        "Do not copy generated scripts from job quarantine into app/tools/repair as part of Patch 8.",
        "Do not adopt generated PDFs or package outputs based on this packet.",
        "Treat safe_to_apply_rule_map_patch=false as blocking, not advisory.",
        "For repairable_review rules, preserve review-required behavior unless a future reviewed operator action explicitly changes it.",
    ]


def proposal_action(raw_action: Any) -> str:
    action = clean_str(raw_action)
    mapping = {
        "attach_strategy_to_repairable_unbuilt": "attach_strategy",
        "attach_strategy_preserve_existing_semantics": "attach_strategy",
        "attach_strategy_preserve_review": "preserve_review_strategy",
        "add_alternate_strategy": "add_alternate_strategy",
        "add_rule": "add_rule",
    }
    return mapping.get(action, action or "unknown")


def proposed_strategy_from_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(proposal.get("proposed_strategy"), dict):
        return copy.deepcopy(proposal["proposed_strategy"])
    entry = as_dict(proposal.get("proposed_entry"))
    strategies = as_list(entry.get("strategies"))
    if strategies and isinstance(strategies[0], dict):
        return copy.deepcopy(strategies[0])
    return {}


def build_proposed_entry(
    *,
    action: str,
    proposal: Dict[str, Any],
    current_entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if action == "add_rule":
        return copy.deepcopy(as_dict(proposal.get("proposed_entry")))

    current = copy.deepcopy(current_entry or {})
    strategy = proposed_strategy_from_proposal(proposal)
    if not strategy:
        return current

    if action == "add_alternate_strategy":
        current.setdefault("edge_cases", [])
        current["edge_cases"].append(
            {
                "source": "learned_strategy_promotion_review",
                "review_required": True,
                "strategy": strategy,
            }
        )
        return current

    current.setdefault("strategies", [])
    current["strategies"].append(strategy)
    if action == "preserve_review_strategy":
        current["resolvability"] = "repairable_review"
        current["review_required"] = True
    return current


def rule_map_patch(action: str, rule_id: str, proposed_entry: Dict[str, Any]) -> Dict[str, Any]:
    if action == "add_rule":
        return {"op": "add", "path": f"/rules/{rule_id}", "value": proposed_entry}
    if action == "add_alternate_strategy":
        return {"op": "append", "path": f"/rules/{rule_id}/edge_cases", "value": proposed_entry.get("edge_cases", [])[-1:]}
    return {"op": "append", "path": f"/rules/{rule_id}/strategies", "value": proposed_entry.get("strategies", [])[-1:]}


def find_record_for_proposal(
    proposal: Dict[str, Any],
    learned_by_id: Dict[str, Dict[str, Any]],
    learned_records: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    strategy = proposed_strategy_from_proposal(proposal)
    evidence = as_dict(strategy.get("evidence"))
    record_id = clean_str(evidence.get("learned_strategy_record_id"))
    if record_id and record_id in learned_by_id:
        return record_id, learned_by_id[record_id]

    rule_id = clean_str(proposal.get("rule_id"))
    script_path = clean_str(strategy.get("script_path") or strategy.get("repair_script"))
    script_sha = clean_str(strategy.get("script_sha256"))
    for record in learned_records:
        if rule_id and clean_str(record.get("rule_id")) != rule_id:
            continue
        if script_path and clean_str(record.get("script_path")) != script_path:
            continue
        if script_sha and clean_str(record.get("script_sha256")) != script_sha:
            continue
        rid = record_identity(record)
        return rid, record
    return record_id or None, None


def candidate_gate_results(record: Dict[str, Any], strategy: Dict[str, Any]) -> Dict[str, Any]:
    gates = as_dict(record.get("gate_results"))
    if gates:
        return gates
    return as_dict(strategy.get("gate_results"))


def candidate_review_reasons(action: str, current_entry: Optional[Dict[str, Any]]) -> List[str]:
    reasons = ["human_review_required_by_policy"]
    if action == "add_rule":
        reasons.append("new_rule_map_entry_requires_review")
    if action == "add_alternate_strategy":
        reasons.append("existing_effective_primary_preserved_candidate_is_alternate")
    if action == "preserve_review_strategy":
        reasons.append("repairable_review_semantics_preserved")
    if current_entry and as_dict(current_entry).get("resolvability") == "effective":
        reasons.append("rule_already_has_effective_strategy")
    return reasons


def promotion_blockers(
    *,
    job_dir: Path,
    record: Optional[Dict[str, Any]],
    strategy: Dict[str, Any],
    script_status: str,
    execution_log: Optional[Dict[str, Any]],
    execution_by_attempt: Dict[str, Dict[str, Any]],
    residual_path: Path,
    action: str,
) -> List[str]:
    blockers: List[str] = [
        "apply_mode_not_implemented_in_patch_8",
        "script_promotion_required_before_production_rule_map_adoption",
    ]
    if record is None:
        blockers.append("missing_learned_strategy_record")
        return blockers

    if record.get("clean") is not True:
        blockers.append("record_not_clean")
    if record.get("indexing_eligible") is not True:
        blockers.append("record_not_indexing_eligible")
    if as_list(record.get("introduced_rules")):
        blockers.append("introduced_rules_present")
    if as_list(record.get("worsened_rules")):
        blockers.append("worsened_rules_present")

    script_value = record.get("script_path") or strategy.get("script_path") or strategy.get("repair_script")
    script_path = path_from_record(job_dir, script_value)
    expected_sha = clean_str(record.get("script_sha256") or strategy.get("script_sha256"))
    actual_sha = sha256_file(script_path) if script_path else None
    if script_status != "quarantine_only":
        blockers.append("candidate_script_not_quarantine_only")
    if not script_path or not script_path.exists():
        blockers.append("candidate_script_missing")
    if expected_sha and actual_sha and expected_sha != actual_sha:
        blockers.append("candidate_script_hash_mismatch")
    if expected_sha and not actual_sha:
        blockers.append("candidate_script_hash_unverifiable")

    execution_attempt_id = clean_str(record.get("execution_attempt_id"))
    execution_log_path = clean_str(record.get("execution_log_path"))
    stdout_path = clean_str(record.get("stdout_path"))
    stderr_path = clean_str(record.get("stderr_path"))
    if not execution_attempt_id:
        blockers.append("missing_execution_attempt_id")
    if not execution_log_path and execution_log is None:
        blockers.append("missing_execution_log_reference")
    if execution_attempt_id and execution_by_attempt and execution_attempt_id not in execution_by_attempt:
        blockers.append("execution_attempt_id_not_found_in_execution_log")
    if not stdout_path:
        blockers.append("missing_stdout_path")
    if not stderr_path:
        blockers.append("missing_stderr_path")

    if not residual_path.exists():
        blockers.append("missing_residual_analysis")
    if action not in {"add_rule", "attach_strategy", "add_alternate_strategy", "preserve_review_strategy"}:
        blockers.append("unknown_proposal_action")
    return sorted(set(blockers))


def build_candidate(
    *,
    index: int,
    job_dir: Path,
    proposal: Dict[str, Any],
    rule_map: Dict[str, Any],
    learned_by_id: Dict[str, Dict[str, Any]],
    learned_records: List[Dict[str, Any]],
    residual_path: Path,
    execution_log: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    rule_id = clean_str(proposal.get("rule_id"))
    action = proposal_action(proposal.get("action"))
    strategy = proposed_strategy_from_proposal(proposal)
    record_id, record = find_record_for_proposal(proposal, learned_by_id, learned_records)
    current_entry = copy.deepcopy(as_dict(rule_map.get("rules", {}).get(rule_id))) if rule_id else None
    proposed_entry = build_proposed_entry(action=action, proposal=proposal, current_entry=current_entry)
    script_path_value = (record or {}).get("script_path") or strategy.get("script_path") or strategy.get("repair_script")
    script_status = script_location_status(job_dir, script_path_value)
    execution_by_attempt = execution_records_by_attempt(execution_log)
    blockers = promotion_blockers(
        job_dir=job_dir,
        record=record,
        strategy=strategy,
        script_status=script_status,
        execution_log=execution_log,
        execution_by_attempt=execution_by_attempt,
        residual_path=residual_path,
        action=action,
    )
    rid_for_hash = record_id or (record_identity(record) if record else None)
    learned_hash = sha256_text(record) if record else None
    residual_hash = sha256_file(residual_path)
    candidate_id = sha256_text(
        {
            "rule_id": rule_id,
            "action": action,
            "record_id": rid_for_hash,
            "script_path": script_path_value,
            "script_sha256": (record or {}).get("script_sha256") or strategy.get("script_sha256"),
        }
    )[:16]
    return {
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "action": action,
        "source_proposal_index": index,
        "proposed_rule_map_patch": rule_map_patch(action, rule_id, proposed_entry),
        "current_rule_map_entry": current_entry,
        "proposed_rule_map_entry": proposed_entry,
        "script_path": script_path_value,
        "script_sha256": (record or {}).get("script_sha256") or strategy.get("script_sha256"),
        "script_location_status": script_status,
        "execution_attempt_id": (record or {}).get("execution_attempt_id"),
        "execution_log_path": (record or {}).get("execution_log_path") or source_path_string(artifact_path(job_dir, EXECUTION_LOG_FILENAME)),
        "stdout_path": (record or {}).get("stdout_path"),
        "stderr_path": (record or {}).get("stderr_path"),
        "learned_strategy_record_id": rid_for_hash,
        "learned_strategy_record_hash": learned_hash,
        "residual_analysis_path": source_path_string(residual_path),
        "residual_analysis_sha256": residual_hash,
        "validation_artifacts": as_dict((record or {}).get("validation_artifacts")) or as_dict(strategy.get("validation_artifacts")),
        "gate_results": candidate_gate_results(record or {}, strategy),
        "introduced_rules": as_list((record or {}).get("introduced_rules")),
        "worsened_rules": as_list((record or {}).get("worsened_rules")),
        "clean_pass_count": strategy.get("clean_pass_count", 1 if (record or {}).get("clean") is True else 0),
        "fail_count": strategy.get("fail_count", 0),
        "pass_rate": strategy.get("pass_rate", 1.0 if (record or {}).get("clean") is True else 0.0),
        "review_required": True,
        "review_reasons": candidate_review_reasons(action, current_entry),
        "promotion_blockers": blockers,
        "safe_to_apply_rule_map_patch": False,
        "safe_to_apply_explanation": "Patch 8 is dry-run review only; rule-map apply and script promotion are intentionally separate.",
    }


def rejected_from_indexer(rejected: Dict[str, Any], reason_prefix: Optional[str] = None) -> Dict[str, Any]:
    reasons = list(as_list(rejected.get("reasons")))
    if reason_prefix:
        reasons.insert(0, reason_prefix)
    return {
        "record_id": rejected.get("record_id"),
        "rule_id": rejected.get("rule_id"),
        "outcome": rejected.get("outcome"),
        "script_path": rejected.get("script_path"),
        "indexing_eligible": bool(rejected.get("indexing_eligible")),
        "clean": bool(rejected.get("clean")),
        "reasons": reasons or ["not_promotable"],
        "promotion_blockers": sorted(set((reasons or []) + as_list(rejected.get("indexing_blockers")))),
        "failure_summary": rejected.get("failure_summary"),
        "introduced_rules": as_list(rejected.get("introduced_rules")),
        "worsened_rules": as_list(rejected.get("worsened_rules")),
        "gate_results": as_dict(rejected.get("gate_results")),
        "review_required": True,
        "safe_to_apply_rule_map_patch": False,
    }


def empty_packet(
    *,
    job_dir: Path,
    rule_map_path: Path,
    index_report_path: Path,
    learned_path: Path,
    residual_path: Path,
    execution_log_path: Path,
    mode: str,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "job_dir": str(job_dir),
        "source_strategy_indexing_report": source_path_string(index_report_path),
        "source_learned_strategies": source_path_string(learned_path),
        "source_residual_analysis": source_path_string(residual_path),
        "source_execution_log": source_path_string(execution_log_path),
        "rule_map_path": str(rule_map_path),
        "mode": mode,
        "promotion_candidates": [],
        "rejected_candidates": [],
        "review_required": True,
        "policy": base_policy(apply_mode_requested=(mode == "apply_rule_map")),
        "operator_instructions": operator_instructions(),
    }


def create_review_packet(
    *,
    job_dir: Path,
    rule_map_path: Path,
    output_path: Optional[Path] = None,
    candidate_id: Optional[str] = None,
    rule_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    if not dry_run:
        raise PromotionError("apply-rule-map mode is not implemented in Patch 8; rerun with --dry-run")

    job_dir = Path(job_dir)
    rule_map_path = Path(rule_map_path)
    audit_dir = job_dir / "audit"
    index_report_path = audit_dir / INDEX_REPORT_FILENAME
    learned_path = audit_dir / LEARNED_FILENAME
    residual_path = audit_dir / RESIDUAL_FILENAME
    execution_log_path = audit_dir / EXECUTION_LOG_FILENAME
    output_path = Path(output_path) if output_path else audit_dir / REVIEW_FILENAME

    index_report = read_json(index_report_path, INDEX_REPORT_FILENAME, required=True)
    rule_map = load_rule_map(rule_map_path)
    learned_records = load_learned_records(learned_path)
    learned_by_id = {record_identity(record): record for record in learned_records}
    execution_log = read_json(execution_log_path, EXECUTION_LOG_FILENAME, required=False)

    packet = empty_packet(
        job_dir=job_dir,
        rule_map_path=rule_map_path,
        index_report_path=index_report_path,
        learned_path=learned_path,
        residual_path=residual_path,
        execution_log_path=execution_log_path,
        mode="dry_run",
    )

    for idx, proposal in enumerate(as_list(index_report.get("proposed_rule_map_changes"))):
        if not isinstance(proposal, dict):
            continue
        if rule_id and clean_str(proposal.get("rule_id")) != clean_str(rule_id):
            continue
        candidate = build_candidate(
            index=idx,
            job_dir=job_dir,
            proposal=proposal,
            rule_map=rule_map,
            learned_by_id=learned_by_id,
            learned_records=learned_records,
            residual_path=residual_path,
            execution_log=execution_log,
        )
        if candidate_id and candidate.get("candidate_id") != candidate_id:
            continue
        packet["promotion_candidates"].append(candidate)

    for rejected in as_list(index_report.get("rejected_experiments")) or as_list(index_report.get("rejected_records")):
        if not isinstance(rejected, dict):
            continue
        if rule_id and clean_str(rejected.get("rule_id")) != clean_str(rule_id):
            continue
        packet["rejected_candidates"].append(rejected_from_indexer(rejected, "rejected_by_strategy_indexer"))

    if candidate_id and not packet["promotion_candidates"]:
        packet["rejected_candidates"].append(
            {
                "candidate_id": candidate_id,
                "reasons": ["candidate_id_not_found"],
                "promotion_blockers": ["candidate_id_not_found"],
                "review_required": True,
                "safe_to_apply_rule_map_patch": False,
            }
        )

    write_json_atomic(output_path, packet)
    return packet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a reviewed dry-run promotion packet for learned strategies.")
    parser.add_argument("--job-dir", required=True, help="Path to the job directory")
    parser.add_argument("--rule-map", default=None, help="Path to canonical rule_repair_map.json")
    parser.add_argument("--output", default=None, help="Optional output path for strategy_promotion_review.json")
    parser.add_argument("--candidate-id", default=None, help="Optional candidate_id filter")
    parser.add_argument("--rule-id", default=None, help="Optional rule_id filter")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Create review packet only; this is the default")
    parser.add_argument("--apply-rule-map", action="store_true", help="Fails closed in Patch 8; apply mode is not implemented")
    parser.add_argument("--reviewed-by", default=None, help="Required only by future apply-capable patches")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    rule_map = Path(args.rule_map) if args.rule_map else resolve_default_rule_map()

    if args.apply_rule_map:
        print(
            json.dumps(
                {
                    "result": "ERROR",
                    "reason": "apply-rule-map mode is not implemented in Patch 8; rerun with --dry-run",
                    "policy": base_policy(apply_mode_requested=True),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        packet = create_review_packet(
            job_dir=Path(args.job_dir),
            rule_map_path=rule_map,
            output_path=Path(args.output) if args.output else None,
            candidate_id=args.candidate_id,
            rule_id=args.rule_id,
            dry_run=True,
        )
    except PromotionError as exc:
        print(json.dumps({"result": "ERROR", "reason": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    print(json.dumps(packet, indent=2, sort_keys=True, default=json_default))
    return 0


if __name__ == "__main__":
    sys.exit(main())
