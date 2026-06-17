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
import ast
import copy
import hashlib
import json
import re
import shutil
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



STAGING_SCHEMA_VERSION = "learned-script-staging-result.v1"
STAGING_MANIFEST_SCHEMA_VERSION = "learned-script-staging-manifest.v1"
SCRIPT_PROMOTION_RESULT_FILENAME = "script_promotion_result.json"
STAGING_MANIFEST_FILENAME = "manifest.json"
PATCH8_RULE_MAP_BLOCKERS = {
    "apply_mode_not_implemented_in_patch_8",
    "script_promotion_required_before_production_rule_map_adoption",
}
DANGEROUS_IMPORT_ROOTS = {
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "paramiko",
}
DANGEROUS_CALL_NAMES = {"eval", "exec", "compile", "__import__"}
DANGEROUS_ATTR_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("shutil", "rmtree"),
}


def resolve_default_staging_dir() -> Path:
    """Return a repo-local, non-production staging directory."""
    if Path("app/tools").exists():
        return Path("app/tools/repair_staging/learned")
    return Path("tools/repair_staging/learned")


def safe_filename_component(value: Any) -> str:
    text = clean_str(value).lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or "unknown"


def staged_script_path_for(candidate: Dict[str, Any], staging_dir: Path) -> Path:
    rule_part = safe_filename_component(candidate.get("rule_id"))
    candidate_part = safe_filename_component(candidate.get("candidate_id"))
    return Path(staging_dir) / f"{rule_part}__{candidate_part}.py"


def ast_static_check(script_path: Path) -> Dict[str, Any]:
    checks: Dict[str, Any] = {
        "source_script_exists": script_path.exists(),
        "python_compiles": False,
        "ast_safety_passed": False,
        "blocked_constructs": [],
        "checked_path": str(script_path),
    }
    if not script_path.exists():
        checks["blocked_constructs"].append("source_script_missing")
        return checks
    try:
        source = script_path.read_text()
        tree = ast.parse(source, filename=str(script_path))
        compile(source, str(script_path), "exec")
        checks["python_compiles"] = True
    except SyntaxError as exc:
        checks["blocked_constructs"].append(f"syntax_error:{exc.lineno}:{exc.msg}")
        return checks
    except Exception as exc:
        checks["blocked_constructs"].append(f"compile_error:{type(exc).__name__}:{exc}")
        return checks

    blocked: List[str] = []
    imported_names: Dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                asname = alias.asname or root
                imported_names[asname] = root
                if root in DANGEROUS_IMPORT_ROOTS:
                    blocked.append(f"dangerous_import:{alias.name}")
                if root == "shutil":
                    imported_names[asname] = "shutil"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in DANGEROUS_IMPORT_ROOTS:
                blocked.append(f"dangerous_import_from:{module}")
            for alias in node.names:
                imported_names[alias.asname or alias.name] = root or alias.name
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_CALL_NAMES:
                blocked.append(f"dangerous_call:{func.id}")
            elif isinstance(func, ast.Attribute):
                base_name = None
                if isinstance(func.value, ast.Name):
                    base_name = imported_names.get(func.value.id, func.value.id)
                if (base_name, func.attr) in DANGEROUS_ATTR_CALLS:
                    blocked.append(f"dangerous_call:{base_name}.{func.attr}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "environ":
                blocked.append("environment_access:os.environ")

    checks["blocked_constructs"] = sorted(set(blocked))
    checks["ast_safety_passed"] = checks["python_compiles"] and not checks["blocked_constructs"]
    return checks


def active_stage_blockers(candidate: Dict[str, Any]) -> List[str]:
    blockers = [clean_str(b) for b in as_list(candidate.get("promotion_blockers"))]
    return sorted({b for b in blockers if b and b not in PATCH8_RULE_MAP_BLOCKERS})


def validate_script_staging_candidate(
    *,
    job_dir: Path,
    candidate: Dict[str, Any],
    reviewed_by: Optional[str],
    require_reviewer: bool,
    staging_dir: Path,
) -> Dict[str, Any]:
    blockers: List[str] = active_stage_blockers(candidate)
    candidate_id = clean_str(candidate.get("candidate_id"))
    if not candidate_id:
        blockers.append("missing_candidate_id")
    if require_reviewer and not clean_str(reviewed_by):
        blockers.append("missing_reviewed_by")
    if candidate.get("review_required") is not True:
        blockers.append("candidate_review_required_not_true")
    if clean_str(candidate.get("script_location_status")) != "quarantine_only":
        blockers.append("candidate_script_not_quarantine_only")
    if as_list(candidate.get("introduced_rules")):
        blockers.append("introduced_rules_present")
    if as_list(candidate.get("worsened_rules")):
        blockers.append("worsened_rules_present")
    if not clean_str(candidate.get("execution_attempt_id")):
        blockers.append("missing_execution_attempt_id")
    if not clean_str(candidate.get("execution_log_path")):
        blockers.append("missing_execution_log_reference")
    if not clean_str(candidate.get("stdout_path")):
        blockers.append("missing_stdout_path")
    if not clean_str(candidate.get("stderr_path")):
        blockers.append("missing_stderr_path")

    source_script = path_from_record(job_dir, candidate.get("script_path"))
    if source_script is None:
        blockers.append("candidate_script_missing")
        source_script = Path("__missing__")
    if source_script.exists() and not is_relative_to(source_script, job_dir):
        blockers.append("candidate_script_outside_job_quarantine")
    expected_sha = clean_str(candidate.get("script_sha256"))
    actual_sha = sha256_file(source_script)
    if not actual_sha:
        blockers.append("candidate_script_hash_unverifiable")
    elif expected_sha and expected_sha != actual_sha:
        blockers.append("candidate_script_hash_mismatch")

    static_checks = ast_static_check(source_script)
    if not static_checks.get("source_script_exists"):
        blockers.append("candidate_script_missing")
    if not static_checks.get("python_compiles"):
        blockers.append("script_python_compile_failed")
    if not static_checks.get("ast_safety_passed"):
        blockers.append("script_ast_safety_failed")

    proposed_path = staged_script_path_for(candidate, staging_dir)
    blockers = sorted(set(blockers))
    return {
        "script_staging_ready": not blockers,
        "script_staging_blockers": blockers,
        "staged_script_proposed_path": str(proposed_path),
        "source_script_path": str(source_script),
        "source_script_sha256": actual_sha,
        "expected_source_script_sha256": expected_sha,
        "static_checks": static_checks,
    }


def load_or_create_staging_manifest(path: Path) -> Dict[str, Any]:
    if path.exists():
        data = read_json(path, "staging manifest", required=True)
        if isinstance(data, dict):
            data.setdefault("schema_version", STAGING_MANIFEST_SCHEMA_VERSION)
            data.setdefault("staged_scripts", [])
            return data
    return {
        "schema_version": STAGING_MANIFEST_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "staged_scripts": [],
    }


def update_staging_manifest(manifest_path: Path, entry: Dict[str, Any]) -> None:
    manifest = load_or_create_staging_manifest(manifest_path)
    entries = [e for e in as_list(manifest.get("staged_scripts")) if isinstance(e, dict)]
    key = (entry.get("script_id"), entry.get("staged_script_path"))
    replaced = False
    for idx, existing in enumerate(entries):
        existing_key = (existing.get("script_id"), existing.get("staged_script_path"))
        if existing_key == key:
            entries[idx] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    manifest["staged_scripts"] = entries
    manifest["updated_at"] = utc_now_iso()
    write_json_atomic(manifest_path, manifest)


def build_script_promotion_result(
    *,
    job_dir: Path,
    mode: str,
    candidate: Dict[str, Any],
    reviewed_by: Optional[str],
    review_packet_path: Path,
    validation: Dict[str, Any],
    staged_script_path: Path,
    staged_manifest_path: Path,
    copied: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": STAGING_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": mode,
        "job_dir": str(job_dir),
        "candidate_id": candidate.get("candidate_id"),
        "rule_id": candidate.get("rule_id"),
        "reviewed_by": reviewed_by,
        "source_review_packet": str(review_packet_path),
        "source_script_path": validation.get("source_script_path"),
        "source_script_sha256": validation.get("source_script_sha256"),
        "staged_script_path": str(staged_script_path),
        "staged_script_sha256": sha256_file(staged_script_path) if staged_script_path.exists() else None,
        "staged_manifest_path": str(staged_manifest_path),
        "static_checks": validation.get("static_checks"),
        "promotion_blockers": validation.get("script_staging_blockers", []),
        "script_staging_ready": validation.get("script_staging_ready", False),
        "canonical_rule_map_mutation_performed": False,
        "generated_script_promotion_performed": bool(copied),
        "production_repair_activation_performed": False,
        "final_pdf_adoption_performed": False,
        "rule_map_apply_performed": False,
    }


def stage_script(
    *,
    job_dir: Path,
    rule_map_path: Path,
    candidate_id: str,
    reviewed_by: Optional[str],
    staging_dir: Path,
    dry_run: bool,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not clean_str(candidate_id):
        raise PromotionError("--candidate-id is required for script staging")
    if not dry_run and not clean_str(reviewed_by):
        raise PromotionError("--reviewed-by is required for --stage-script")

    job_dir = Path(job_dir)
    audit_dir = job_dir / "audit"
    review_packet_path = audit_dir / REVIEW_FILENAME
    packet = create_review_packet(
        job_dir=job_dir,
        rule_map_path=Path(rule_map_path),
        output_path=review_packet_path,
        candidate_id=candidate_id,
        dry_run=True,
    )
    matches = [c for c in as_list(packet.get("promotion_candidates")) if isinstance(c, dict) and c.get("candidate_id") == candidate_id]
    if not matches:
        raise PromotionError(f"candidate not found or not promotion-proposed: {candidate_id}")
    candidate = matches[0]

    validation = validate_script_staging_candidate(
        job_dir=job_dir,
        candidate=candidate,
        reviewed_by=reviewed_by,
        require_reviewer=not dry_run,
        staging_dir=Path(staging_dir),
    )
    candidate.update(
        {
            "script_staging_ready": validation["script_staging_ready"],
            "script_staging_blockers": validation["script_staging_blockers"],
            "staged_script_proposed_path": validation["staged_script_proposed_path"],
            "static_checks": validation["static_checks"],
        }
    )
    write_json_atomic(review_packet_path, packet)

    staged_script_path = Path(validation["staged_script_proposed_path"])
    manifest_path = Path(staging_dir) / STAGING_MANIFEST_FILENAME
    copied = False
    if not validation["script_staging_ready"]:
        result = build_script_promotion_result(
            job_dir=job_dir,
            mode="dry_run" if dry_run else "apply_script_staging",
            candidate=candidate,
            reviewed_by=reviewed_by,
            review_packet_path=review_packet_path,
            validation=validation,
            staged_script_path=staged_script_path,
            staged_manifest_path=manifest_path,
            copied=False,
        )
        result_path = Path(output_path) if output_path else audit_dir / SCRIPT_PROMOTION_RESULT_FILENAME
        write_json_atomic(result_path, result)
        raise PromotionError("script staging blocked: " + ", ".join(validation["script_staging_blockers"]))

    if not dry_run:
        source_script_path = Path(validation["source_script_path"])
        source_sha = clean_str(validation.get("source_script_sha256"))
        staged_script_path.parent.mkdir(parents=True, exist_ok=True)
        if staged_script_path.exists():
            existing_sha = sha256_file(staged_script_path)
            if existing_sha != source_sha:
                result = build_script_promotion_result(
                    job_dir=job_dir,
                    mode="apply_script_staging",
                    candidate=candidate,
                    reviewed_by=reviewed_by,
                    review_packet_path=review_packet_path,
                    validation={**validation, "script_staging_blockers": ["staged_script_hash_conflict"], "script_staging_ready": False},
                    staged_script_path=staged_script_path,
                    staged_manifest_path=manifest_path,
                    copied=False,
                )
                result_path = Path(output_path) if output_path else audit_dir / SCRIPT_PROMOTION_RESULT_FILENAME
                write_json_atomic(result_path, result)
                raise PromotionError("script staging blocked: staged_script_hash_conflict")
        else:
            shutil.copy2(source_script_path, staged_script_path)
            copied = True

        manifest_entry = {
            "script_id": f"{safe_filename_component(candidate.get('rule_id'))}__{safe_filename_component(candidate.get('candidate_id'))}",
            "rule_id": candidate.get("rule_id"),
            "candidate_id": candidate.get("candidate_id"),
            "source_job_dir": str(job_dir),
            "source_review_packet": str(review_packet_path),
            "source_script_sha256": source_sha,
            "staged_script_path": str(staged_script_path),
            "staged_script_sha256": sha256_file(staged_script_path),
            "reviewed_by": reviewed_by,
            "reviewed_at": utc_now_iso(),
            "status": "staged_reviewed",
            "production_active": False,
            "rule_map_applied": False,
            "notes": "Reviewed staging artifact only; not imported by production repair runtime.",
        }
        update_staging_manifest(manifest_path, manifest_entry)

    result = build_script_promotion_result(
        job_dir=job_dir,
        mode="dry_run" if dry_run else "apply_script_staging",
        candidate=candidate,
        reviewed_by=reviewed_by,
        review_packet_path=review_packet_path,
        validation=validation,
        staged_script_path=staged_script_path,
        staged_manifest_path=manifest_path,
        copied=copied,
    )
    # Idempotent re-stage should still be reported as staged, even if the file already existed.
    if not dry_run and staged_script_path.exists() and sha256_file(staged_script_path) == result.get("source_script_sha256"):
        result["generated_script_promotion_performed"] = True
        result["staged_script_sha256"] = sha256_file(staged_script_path)
    result_path = Path(output_path) if output_path else audit_dir / SCRIPT_PROMOTION_RESULT_FILENAME
    write_json_atomic(result_path, result)
    return result



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create reviewed promotion packets and non-production staging artifacts for learned strategies.")
    parser.add_argument("--job-dir", required=True, help="Path to the job directory")
    parser.add_argument("--rule-map", default=None, help="Path to canonical rule_repair_map.json")
    parser.add_argument("--output", default=None, help="Optional output path for the result artifact")
    parser.add_argument("--candidate-id", default=None, help="Optional candidate_id filter; required for script staging")
    parser.add_argument("--rule-id", default=None, help="Optional rule_id filter for dry-run review packet creation")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Create review packet only; this is the default")
    parser.add_argument("--apply-rule-map", action="store_true", help="Fails closed; rule-map adoption is a separate reviewed step")
    parser.add_argument("--reviewed-by", default=None, help="Reviewer/operator identity; required by --stage-script")
    parser.add_argument("--stage-script-dry-run", action="store_true", help="Run script staging checks and write readiness artifacts without copying")
    parser.add_argument("--stage-script", action="store_true", help="Copy a reviewed candidate script into non-production staging only")
    parser.add_argument("--staging-dir", default=None, help="Override non-production staging directory")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    rule_map = Path(args.rule_map) if args.rule_map else resolve_default_rule_map()
    staging_dir = Path(args.staging_dir) if args.staging_dir else resolve_default_staging_dir()

    if args.apply_rule_map:
        print(
            json.dumps(
                {
                    "result": "ERROR",
                    "reason": "Rule-map apply is not implemented in this patch. Stage the script first; rule-map adoption is a separate reviewed step.",
                    "policy": base_policy(apply_mode_requested=True),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        if args.stage_script or args.stage_script_dry_run:
            result = stage_script(
                job_dir=Path(args.job_dir),
                rule_map_path=rule_map,
                candidate_id=args.candidate_id or "",
                reviewed_by=args.reviewed_by,
                staging_dir=staging_dir,
                dry_run=bool(args.stage_script_dry_run and not args.stage_script),
                output_path=Path(args.output) if args.output else None,
            )
            print(json.dumps(result, indent=2, sort_keys=True, default=json_default))
            return 0

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
