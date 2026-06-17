#!/usr/bin/env python3
"""Reviewed learned-strategy promotion, script staging, and rule-map adoption.

Patch 10 keeps the promotion pipeline intentionally conservative:

clean learned strategy -> promotion review packet -> reviewed script staging ->
reviewed rule-map dry-run/apply metadata referencing the staged script.

This tool never copies learned scripts into app/tools/repair, never adopts final PDFs,
never runs remediation, and marks learned rule-map entries as staged-review only.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "strategy-promotion-review.v2"
RULE_MAP_REVIEW_SCHEMA_VERSION = "learned-rule-map-adoption-review.v1"
RULE_MAP_APPLY_SCHEMA_VERSION = "learned-rule-map-apply-result.v1"
REVIEW_FILENAME = "strategy_promotion_review.json"
INDEX_REPORT_FILENAME = "strategy_indexing_report.json"
LEARNED_FILENAME = "learned_strategies.json"
RESIDUAL_FILENAME = "residual_analysis.json"
EXECUTION_LOG_FILENAME = "execution_log.json"
SCRIPT_PROMOTION_FILENAME = "script_promotion_result.json"
RULE_MAP_REVIEW_FILENAME = "rule_map_adoption_review.json"
RULE_MAP_APPLY_FILENAME = "rule_map_apply_result.json"
STAGING_REL_DIR = Path("tools/repair_staging/learned")
BACKUP_REL_DIR = Path("tools/audit/backups")
DEFAULT_RULE_MAP_CANDIDATES = (
    Path("app/tools/audit/rule_repair_map.json"),
    Path("tools/audit/rule_repair_map.json"),
)
IGNORABLE_PATCH8_BLOCKERS = {
    "apply_mode_not_implemented_in_patch_8",
    "script_promotion_required_before_production_rule_map_adoption",
}


class PromotionError(Exception):
    """Raised for malformed inputs or unsafe promotion conditions."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def safe_name(value: Any) -> str:
    raw = clean_str(value) or "candidate"
    out = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip("._") or "candidate"
    return name[:120]


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
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default) + "\n")
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


def repo_root_from_rule_map(rule_map_path: Path) -> Path:
    resolved = rule_map_path.resolve()
    parts = resolved.parts
    tail = ("app", "tools", "audit", "rule_repair_map.json")
    if len(parts) >= 4 and tuple(parts[-4:]) == tail:
        return Path(*parts[:-4])
    tail2 = ("tools", "audit", "rule_repair_map.json")
    if len(parts) >= 3 and tuple(parts[-3:]) == tail2:
        return Path(*parts[:-3]).parent
    return Path.cwd()


def app_root_from_rule_map(rule_map_path: Path) -> Path:
    resolved = rule_map_path.resolve()
    if resolved.name == "rule_repair_map.json" and resolved.parent.name == "audit" and resolved.parent.parent.name == "tools":
        return resolved.parent.parent.parent
    return Path.cwd() / "app"


def resolve_default_rule_map() -> Path:
    for candidate in DEFAULT_RULE_MAP_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_RULE_MAP_CANDIDATES[0]


def artifact_path(job_dir: Path, filename: str) -> Path:
    return Path(job_dir) / "audit" / filename


def source_path_string(path: Path) -> Optional[str]:
    return str(path) if path.exists() else None


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


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


def repo_path_for_runtime(app_root: Path, value: Any) -> Path:
    p = Path(str(value))
    if p.is_absolute():
        if str(p).startswith("/app/"):
            return app_root / p.relative_to("/app")
        return p
    if str(p).startswith("app/"):
        return app_root.parent / p
    return app_root / p


def repo_relative_to_app(app_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(app_root.resolve()))
    except Exception:
        try:
            return str(resolved.relative_to(app_root.parent.resolve() / "app"))
        except Exception:
            return str(path)


def script_location_status(job_dir: Path, script_path_value: Any) -> str:
    p = path_from_record(job_dir, script_path_value)
    if p is None:
        return "missing"
    if is_relative_to(p, job_dir):
        return "quarantine_only"
    return "outside_job_quarantine"


def load_rule_map(path: Path) -> Dict[str, Any]:
    data = read_json(path, "rule_repair_map.json", required=True)
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise PromotionError(f"malformed rule_repair_map.json: rules must be an object at {path}")
    return data


def load_learned_records(path: Path) -> List[Dict[str, Any]]:
    data = read_json(path, LEARNED_FILENAME, required=False)
    if not data:
        return []
    records = data.get("records")
    if not isinstance(records, list):
        raise PromotionError(f"malformed {LEARNED_FILENAME}: records must be a list at {path}")
    return [r for r in records if isinstance(r, dict)]


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


def base_policy(mode: str = "dry_run") -> Dict[str, Any]:
    return {
        "dry_run_default": True,
        "mode_requested": mode,
        "apply_mode_implemented": mode == "apply_rule_map",
        "canonical_rule_map_mutation_performed": False,
        "generated_script_promotion_performed": False,
        "final_pdf_adoption_performed": False,
        "production_repair_activation_performed": False,
        "rule_map_apply_requires_explicit_reviewed_operator_action": True,
        "generated_scripts_must_remain_staged_only": True,
        "production_runtime_must_not_depend_on_quarantined_scripts": True,
        "existing_effective_primary_strategies_are_preserved": True,
        "repairable_review_semantics_are_preserved": True,
        "dirty_failed_refusal_records_are_blocked": True,
    }


def operator_instructions() -> List[str]:
    return [
        "Review each promotion candidate manually before stage or rule-map apply.",
        "Rule-map adoption requires a staged script, matching staged hash, and --reviewed-by.",
        "Do not copy generated scripts into app/tools/repair as part of this workflow.",
        "Do not adopt generated PDFs or package outputs based on these artifacts.",
        "Treat safe_to_apply_rule_map_patch=false as blocking, not advisory.",
        "Rollback an apply by copying the recorded backup over rule_repair_map.json.",
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


def build_proposed_entry(action: str, proposal: Dict[str, Any], current_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if action == "add_rule":
        return copy.deepcopy(as_dict(proposal.get("proposed_entry")))
    current = copy.deepcopy(current_entry or {})
    strategy = proposed_strategy_from_proposal(proposal)
    if not strategy:
        return current
    if action == "add_alternate_strategy":
        current.setdefault("edge_cases", [])
        current["edge_cases"].append({"source": "learned_strategy_promotion_review", "review_required": True, "strategy": strategy})
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


def find_record_for_proposal(proposal: Dict[str, Any], learned_by_id: Dict[str, Dict[str, Any]], learned_records: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
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


def promotion_blockers(job_dir: Path, record: Optional[Dict[str, Any]], strategy: Dict[str, Any], script_status: str, residual_path: Path, action: str) -> List[str]:
    blockers: List[str] = ["script_promotion_required_before_production_rule_map_adoption"]
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
    outcome = clean_str(record.get("outcome")).upper()
    if outcome and outcome not in {"PASS", "CLEAN", "SUCCESS"}:
        blockers.append("record_outcome_not_pass")
    if clean_str(record.get("semantic_status")).lower() in {"refusal", "failed", "dirty"}:
        blockers.append("record_refusal_or_dirty_status")
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
    if not clean_str(record.get("execution_attempt_id")):
        blockers.append("missing_execution_attempt_id")
    if not residual_path.exists():
        blockers.append("missing_residual_analysis")
    if action not in {"add_rule", "attach_strategy", "add_alternate_strategy", "preserve_review_strategy"}:
        blockers.append("unknown_proposal_action")
    return sorted(set(blockers))


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


def build_candidate(index: int, job_dir: Path, proposal: Dict[str, Any], rule_map: Dict[str, Any], learned_by_id: Dict[str, Dict[str, Any]], learned_records: List[Dict[str, Any]], residual_path: Path) -> Dict[str, Any]:
    rule_id = clean_str(proposal.get("rule_id"))
    action = proposal_action(proposal.get("action"))
    strategy = proposed_strategy_from_proposal(proposal)
    record_id, record = find_record_for_proposal(proposal, learned_by_id, learned_records)
    current_entry = copy.deepcopy(as_dict(rule_map.get("rules", {}).get(rule_id))) if rule_id else None
    proposed_entry = build_proposed_entry(action, proposal, current_entry)
    script_path_value = (record or {}).get("script_path") or strategy.get("script_path") or strategy.get("repair_script")
    script_status = script_location_status(job_dir, script_path_value)
    blockers = promotion_blockers(job_dir, record, strategy, script_status, residual_path, action)
    rid_for_hash = record_id or (record_identity(record) if record else None)
    candidate_id = sha256_text({"rule_id": rule_id, "action": action, "record_id": rid_for_hash, "script_path": script_path_value, "script_sha256": (record or {}).get("script_sha256") or strategy.get("script_sha256")})[:16]
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
        "learned_strategy_record_hash": sha256_text(record) if record else None,
        "residual_analysis_path": source_path_string(residual_path),
        "residual_analysis_sha256": sha256_file(residual_path),
        "validation_artifacts": as_dict((record or {}).get("validation_artifacts")) or as_dict(strategy.get("validation_artifacts")),
        "gate_results": as_dict((record or {}).get("gate_results")) or as_dict(strategy.get("gate_results")),
        "introduced_rules": as_list((record or {}).get("introduced_rules")),
        "worsened_rules": as_list((record or {}).get("worsened_rules")),
        "clean_pass_count": strategy.get("clean_pass_count", 1 if (record or {}).get("clean") is True else 0),
        "fail_count": strategy.get("fail_count", 0),
        "pass_rate": strategy.get("pass_rate", 1.0 if (record or {}).get("clean") is True else 0.0),
        "review_required": True,
        "review_reasons": candidate_review_reasons(action, current_entry),
        "promotion_blockers": blockers,
        "safe_to_apply_rule_map_patch": False,
        "safe_to_apply_explanation": "Requires separate reviewed script staging and Patch 10 rule-map dry-run/apply.",
    }


def create_review_packet(job_dir: Path, rule_map_path: Path, output_path: Optional[Path] = None, candidate_id: Optional[str] = None, rule_id: Optional[str] = None, dry_run: bool = True) -> Dict[str, Any]:
    if not dry_run:
        raise PromotionError("rule-map apply must use --apply-rule-map; strategy review packet creation is dry-run only")
    job_dir = Path(job_dir)
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
    packet: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "job_dir": str(job_dir),
        "source_strategy_indexing_report": source_path_string(index_report_path),
        "source_learned_strategies": source_path_string(learned_path),
        "source_residual_analysis": source_path_string(residual_path),
        "source_execution_log": source_path_string(execution_log_path),
        "rule_map_path": str(rule_map_path),
        "mode": "dry_run",
        "promotion_candidates": [],
        "rejected_candidates": [],
        "review_required": True,
        "policy": base_policy("dry_run"),
        "operator_instructions": operator_instructions(),
    }
    for idx, proposal in enumerate(as_list(index_report.get("proposed_rule_map_changes"))):
        if not isinstance(proposal, dict):
            continue
        if rule_id and clean_str(proposal.get("rule_id")) != clean_str(rule_id):
            continue
        candidate = build_candidate(idx, job_dir, proposal, rule_map, learned_by_id, learned_records, residual_path)
        if candidate_id and candidate.get("candidate_id") != candidate_id:
            continue
        packet["promotion_candidates"].append(candidate)
    for rejected in as_list(index_report.get("rejected_experiments")) or as_list(index_report.get("rejected_records")):
        if isinstance(rejected, dict):
            packet["rejected_candidates"].append({"record_id": rejected.get("record_id"), "rule_id": rejected.get("rule_id"), "promotion_blockers": as_list(rejected.get("reasons")) or ["rejected_by_strategy_indexer"], "safe_to_apply_rule_map_patch": False, "review_required": True})
    if candidate_id and not packet["promotion_candidates"]:
        packet["rejected_candidates"].append({"candidate_id": candidate_id, "promotion_blockers": ["candidate_id_not_found"], "safe_to_apply_rule_map_patch": False, "review_required": True})
    write_json_atomic(output_path, packet)
    return packet


def get_single_candidate(review: Dict[str, Any], candidate_id: str) -> Dict[str, Any]:
    matches = [c for c in as_list(review.get("promotion_candidates")) if isinstance(c, dict) and clean_str(c.get("candidate_id")) == clean_str(candidate_id)]
    if not matches:
        raise PromotionError(f"candidate_id not found in {REVIEW_FILENAME}: {candidate_id}")
    return matches[0]


def effective_candidate_blockers(candidate: Dict[str, Any]) -> List[str]:
    blockers = [clean_str(b) for b in as_list(candidate.get("promotion_blockers")) if clean_str(b)]
    return [b for b in blockers if b not in IGNORABLE_PATCH8_BLOCKERS]


def static_check_script(path: Path) -> Dict[str, Any]:
    result = {"passed": False, "blockers": [], "warnings": []}
    if not path.exists():
        result["blockers"].append("script_missing")
        return result
    try:
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
    except Exception as exc:
        result["blockers"].append(f"python_parse_error:{exc}")
        return result
    banned_imports = {"socket", "requests", "urllib", "http.client", "ftplib", "paramiko"}
    banned_calls = {"eval", "exec", "compile", "open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in banned_imports:
                    result["blockers"].append(f"banned_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in banned_imports:
                result["blockers"].append(f"banned_import:{node.module}")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in banned_calls:
                result["blockers"].append(f"banned_call:{fn.id}")
            if isinstance(fn, ast.Attribute) and fn.attr in {"system", "popen", "Popen", "run", "call", "check_call", "check_output"}:
                result["blockers"].append(f"banned_call:{fn.attr}")
    result["blockers"] = sorted(set(result["blockers"]))
    result["passed"] = not result["blockers"]
    return result


def stage_script(job_dir: Path, rule_map_path: Path, candidate_id: str, reviewed_by: str) -> Dict[str, Any]:
    if not candidate_id:
        raise PromotionError("--candidate-id is required for --stage-script")
    if not reviewed_by:
        raise PromotionError("--reviewed-by is required for --stage-script")
    review_path = artifact_path(job_dir, REVIEW_FILENAME)
    review = read_json(review_path, REVIEW_FILENAME, required=True)
    candidate = get_single_candidate(review, candidate_id)
    blockers = effective_candidate_blockers(candidate)
    if blockers:
        raise PromotionError("candidate is not stageable: " + ", ".join(blockers))
    source_script = path_from_record(job_dir, candidate.get("script_path"))
    expected_sha = clean_str(candidate.get("script_sha256"))
    actual_sha = sha256_file(source_script)
    if source_script is None or not source_script.exists():
        raise PromotionError("candidate script missing")
    if expected_sha and actual_sha != expected_sha:
        raise PromotionError("candidate script hash mismatch")
    checks = static_check_script(source_script)
    app_root = app_root_from_rule_map(rule_map_path)
    staged_name = f"{safe_name(candidate_id)}__{safe_name(source_script.name)}"
    if not staged_name.endswith(".py"):
        staged_name += ".py"
    staged_path = app_root / STAGING_REL_DIR / staged_name
    if not checks["passed"]:
        result = {
            "schema_version": "learned-script-promotion-result.v1",
            "created_at": utc_now_iso(),
            "mode": "stage_script",
            "status": "blocked",
            "staged": False,
            "candidate_id": candidate_id,
            "reviewed_by": reviewed_by,
            "source_script_path": str(source_script),
            "expected_script_sha256": expected_sha,
            "actual_script_sha256": actual_sha,
            "static_checks": checks,
            "generated_script_promotion_performed": False,
            "production_repair_activation_performed": False,
            "final_pdf_adoption_performed": False,
        }
        write_json_atomic(artifact_path(job_dir, SCRIPT_PROMOTION_FILENAME), result)
        raise PromotionError("static checks failed for candidate script")
    staged_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_script, staged_path)
    staged_sha = sha256_file(staged_path)
    result = {
        "schema_version": "learned-script-promotion-result.v1",
        "created_at": utc_now_iso(),
        "mode": "stage_script",
        "status": "staged",
        "staged": True,
        "candidate_id": candidate_id,
        "rule_id": candidate.get("rule_id"),
        "reviewed_by": reviewed_by,
        "source_review_packet": str(review_path),
        "source_script_path": str(source_script),
        "expected_script_sha256": expected_sha,
        "actual_script_sha256": actual_sha,
        "staged_script_path": repo_relative_to_app(app_root, staged_path),
        "staged_script_sha256": staged_sha,
        "static_checks": checks,
        "static_checks_passed": True,
        "generated_script_promotion_performed": True,
        "production_repair_activation_performed": False,
        "final_pdf_adoption_performed": False,
    }
    write_json_atomic(artifact_path(job_dir, SCRIPT_PROMOTION_FILENAME), result)
    return result


def load_script_promotion_for_candidate(job_dir: Path, candidate_id: str) -> Dict[str, Any]:
    path = artifact_path(job_dir, SCRIPT_PROMOTION_FILENAME)
    data = read_json(path, SCRIPT_PROMOTION_FILENAME, required=True)
    if clean_str(data.get("candidate_id")) == clean_str(candidate_id):
        return data
    for key in ("script_promotions", "results", "promotions"):
        for item in as_list(data.get(key)):
            if isinstance(item, dict) and clean_str(item.get("candidate_id")) == clean_str(candidate_id):
                return item
    raise PromotionError(f"script promotion result does not contain candidate_id: {candidate_id}")


def validate_staged_script(app_root: Path, candidate: Dict[str, Any], script_result: Dict[str, Any]) -> Tuple[Path, str, List[str]]:
    blockers: List[str] = []
    if script_result.get("staged") is not True and clean_str(script_result.get("status")).lower() not in {"staged", "success", "passed"}:
        blockers.append("script_not_staged")
    if script_result.get("static_checks_passed") is False:
        blockers.append("script_static_checks_failed")
    staged_value = script_result.get("staged_script_path") or script_result.get("script_path")
    if not staged_value:
        blockers.append("missing_staged_script_path")
        staged_path = app_root / STAGING_REL_DIR / "missing.py"
    else:
        staged_text = str(staged_value)
        if "/workspace/jobs/" in staged_text or "audit/self_extension/quarantine" in staged_text:
            blockers.append("staged_script_path_points_to_quarantine")
        staged_path = repo_path_for_runtime(app_root, staged_text)
    approved_dir = app_root / STAGING_REL_DIR
    if not is_relative_to(staged_path, approved_dir):
        blockers.append("staged_script_not_under_approved_directory")
    expected_sha = clean_str(script_result.get("staged_script_sha256") or script_result.get("script_sha256") or candidate.get("script_sha256"))
    actual_sha = sha256_file(staged_path)
    if not staged_path.exists():
        blockers.append("staged_script_missing")
    if expected_sha and actual_sha and expected_sha != actual_sha:
        blockers.append("staged_script_hash_mismatch")
    if expected_sha and not actual_sha:
        blockers.append("staged_script_hash_unverifiable")
    return staged_path, actual_sha or "", sorted(set(blockers))


def staged_strategy_entry(candidate: Dict[str, Any], script_result: Dict[str, Any], staged_rel_path: str, staged_sha: str, reviewed_by: str) -> Dict[str, Any]:
    evidence = {
        "source_review_packet": str(artifact_path(Path(as_dict(candidate).get("job_dir", "")), REVIEW_FILENAME)) if candidate.get("job_dir") else None,
        "source_script_promotion_result": SCRIPT_PROMOTION_FILENAME,
        "execution_attempt_id": candidate.get("execution_attempt_id"),
        "learned_strategy_record_hash": candidate.get("learned_strategy_record_hash"),
        "residual_analysis_sha256": candidate.get("residual_analysis_sha256"),
        "gate_results": candidate.get("gate_results"),
        "validation_artifacts": candidate.get("validation_artifacts"),
    }
    return {
        "source": "learned_strategy_staged",
        "production_active": False,
        "activation_status": "staged_review",
        "review_required": True,
        "reviewed_by": reviewed_by,
        "reviewed_at": utc_now_iso(),
        "candidate_id": candidate.get("candidate_id"),
        "rule_id": candidate.get("rule_id"),
        "action": candidate.get("action"),
        "script_sha256": staged_sha,
        "learned_strategy_record_hash": candidate.get("learned_strategy_record_hash"),
        "execution_attempt_id": candidate.get("execution_attempt_id"),
        "evidence": {k: v for k, v in evidence.items() if v is not None},
        "staged_script_path": staged_rel_path,
        "staged_script_sha256": staged_sha,
        "source_script_sha256": candidate.get("script_sha256"),
        "script_promotion_reviewed_by": script_result.get("reviewed_by"),
        "notes": "Review-only learned strategy metadata. The production runtime must not treat this as an active repair strategy.",
    }


def propose_rule_entry(current_entry: Optional[Dict[str, Any]], candidate: Dict[str, Any], staged_entry: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    if not current_entry:
        new_entry = {
            "description": clean_str(candidate.get("description")) or "Learned strategy staged for review.",
            "manual": True,
            "resolvability": "repairable_review",
            "review_required": True,
            "strategies": [],
            "reviewed_learned_strategies": [staged_entry],
        }
        return "add_staged_review_rule", new_entry
    new_entry = copy.deepcopy(current_entry)
    if new_entry.get("resolvability") in {"repairable_unbuilt", "repairable_review"}:
        new_entry["resolvability"] = "repairable_review"
        new_entry["review_required"] = True
    elif new_entry.get("resolvability") == "effective":
        new_entry.setdefault("review_required", False)
    else:
        new_entry.setdefault("review_required", True)
    new_entry.setdefault("reviewed_learned_strategies", [])
    new_entry["reviewed_learned_strategies"].append(staged_entry)
    return "attach_staged_review_strategy", new_entry


def validate_rule_map_shape(rule_map: Dict[str, Any]) -> None:
    if not isinstance(rule_map, dict):
        raise PromotionError("rule map must be a JSON object")
    if not isinstance(rule_map.get("rules"), dict):
        raise PromotionError("rule map must contain a top-level rules object")


def rule_map_file_hash(path: Path) -> str:
    h = sha256_file(path)
    if not h:
        raise PromotionError(f"unable to hash rule map: {path}")
    return h


def build_rule_map_adoption(job_dir: Path, rule_map_path: Path, candidate_id: str, reviewed_by: Optional[str], apply: bool) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if not candidate_id:
        raise PromotionError("--candidate-id is required")
    if apply and not reviewed_by:
        raise PromotionError("--reviewed-by is required for --apply-rule-map")
    review_path = artifact_path(job_dir, REVIEW_FILENAME)
    script_result_path = artifact_path(job_dir, SCRIPT_PROMOTION_FILENAME)
    review = read_json(review_path, REVIEW_FILENAME, required=True)
    candidate = get_single_candidate(review, candidate_id)
    candidate["job_dir"] = str(job_dir)
    app_root = app_root_from_rule_map(rule_map_path)
    blockers = effective_candidate_blockers(candidate)
    script_result: Dict[str, Any] = {}
    staged_path = app_root / STAGING_REL_DIR / "missing.py"
    staged_sha = ""
    try:
        script_result = load_script_promotion_for_candidate(job_dir, candidate_id)
        staged_path, staged_sha, staged_blockers = validate_staged_script(app_root, candidate, script_result)
        blockers.extend(staged_blockers)
    except PromotionError as exc:
        blockers.append(str(exc).replace(" ", "_"))
    rule_map_before = load_rule_map(rule_map_path)
    validate_rule_map_shape(rule_map_before)
    rule_id = clean_str(candidate.get("rule_id"))
    if not rule_id:
        blockers.append("missing_rule_id")
    staged_rel_path = repo_relative_to_app(app_root, staged_path)
    if "/workspace/jobs/" in staged_rel_path or "audit/self_extension/quarantine" in staged_rel_path:
        blockers.append("rule_map_would_reference_quarantine_path")
    current_entry = copy.deepcopy(as_dict(rule_map_before.get("rules", {}).get(rule_id))) if rule_id else None
    staged_entry = staged_strategy_entry(candidate, script_result, staged_rel_path, staged_sha, reviewed_by or "")
    action, proposed_entry = propose_rule_entry(current_entry, candidate, staged_entry)
    before_entry_hash = sha256_text(current_entry) if current_entry else None
    after_entry_hash = sha256_text(proposed_entry)
    before_hash = rule_map_file_hash(rule_map_path)
    proposed_rule_map = copy.deepcopy(rule_map_before)
    if rule_id:
        proposed_rule_map.setdefault("rules", {})[rule_id] = proposed_entry
    try:
        json.loads(json.dumps(proposed_rule_map))
    except Exception as exc:
        blockers.append(f"resulting_rule_map_not_parseable:{exc}")
    blockers = sorted(set(clean_str(b) for b in blockers if clean_str(b)))
    review_artifact = {
        "schema_version": RULE_MAP_REVIEW_SCHEMA_VERSION if not apply else RULE_MAP_APPLY_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": "dry_run" if not apply else "apply_rule_map",
        "job_dir": str(job_dir),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "reviewed_by": reviewed_by,
        "rule_map_path": str(rule_map_path),
        "rule_map_backup_path": None,
        "source_review_packet": str(review_path),
        "source_script_promotion_result": str(script_result_path),
        "staged_script_path": staged_rel_path,
        "staged_script_sha256": staged_sha,
        "action": action,
        "before_entry_hash": before_entry_hash,
        "after_entry_hash": after_entry_hash,
        "rule_map_sha256_before": before_hash,
        "rule_map_sha256_after": None,
        "canonical_rule_map_mutation_performed": False,
        "generated_script_promotion_performed": False,
        "production_repair_activation_performed": False,
        "final_pdf_adoption_performed": False,
        "activation_status": "staged_review",
        "safe_to_apply_rule_map_patch": not blockers,
        "requires_reviewed_by_for_apply": True,
        "blockers": blockers,
        "warnings": [],
        "proposed_patch_summary": {
            "rule_existed": current_entry is not None,
            "non_active_section": "reviewed_learned_strategies",
            "primary_strategies_preserved": as_list(current_entry.get("strategies")) == as_list(proposed_entry.get("strategies")) if current_entry else True,
            "production_active": False,
            "review_required": True,
        },
        "proposed_rule_map_entry": proposed_entry,
        "rollback_instructions": [
            "For dry-run, no rollback is required because the canonical rule map was not mutated.",
            "For apply, copy rule_map_backup_path over rule_map_path and rerun JSON parse/unit checks.",
            "Do not remove staged scripts unless a separate staging cleanup is explicitly reviewed.",
        ],
    }
    if blockers:
        return review_artifact, None
    return review_artifact, proposed_rule_map


def dry_run_rule_map(job_dir: Path, rule_map_path: Path, candidate_id: str) -> Dict[str, Any]:
    artifact, _ = build_rule_map_adoption(job_dir, rule_map_path, candidate_id, reviewed_by=None, apply=False)
    write_json_atomic(artifact_path(job_dir, RULE_MAP_REVIEW_FILENAME), artifact)
    return artifact


def apply_rule_map(job_dir: Path, rule_map_path: Path, candidate_id: str, reviewed_by: str) -> Dict[str, Any]:
    artifact, proposed_rule_map = build_rule_map_adoption(job_dir, rule_map_path, candidate_id, reviewed_by=reviewed_by, apply=True)
    if artifact.get("blockers"):
        write_json_atomic(artifact_path(job_dir, RULE_MAP_APPLY_FILENAME), artifact)
        raise PromotionError("rule-map apply blocked: " + ", ".join(as_list(artifact.get("blockers"))))
    if proposed_rule_map is None:
        raise PromotionError("rule-map apply blocked: no proposed rule map")
    app_root = app_root_from_rule_map(rule_map_path)
    backup_dir = app_root / BACKUP_REL_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"rule_repair_map.{timestamp}.json"
    shutil.copy2(rule_map_path, backup_path)
    write_json_atomic(rule_map_path, proposed_rule_map)
    # Parse again after write to fail loudly if impossible.
    load_rule_map(rule_map_path)
    artifact["rule_map_backup_path"] = str(backup_path)
    artifact["rule_map_sha256_after"] = rule_map_file_hash(rule_map_path)
    artifact["canonical_rule_map_mutation_performed"] = True
    artifact["safe_to_apply_rule_map_patch"] = True
    artifact["rollback_instructions"] = [
        f"cp {backup_path} {rule_map_path}",
        "python3 -m json.tool app/tools/audit/rule_repair_map.json >/dev/null",
        "git diff -- app/tools/audit/rule_repair_map.json app/tools/repair",
    ]
    write_json_atomic(artifact_path(job_dir, RULE_MAP_APPLY_FILENAME), artifact)
    return artifact




# PATCH11_ACTIVATION_POLICY_START
ACTIVATION_SCHEMA_VERSION = "learned-strategy-activation.v1"
ACTIVATION_REVIEW_FILENAME = "activation_review.json"
ACTIVATION_APPLY_FILENAME = "activation_apply_result.json"
ACTIVATION_DEACTIVATE_FILENAME = "activation_deactivate_result.json"
APPROVED_STAGING_SUFFIX = Path("app/tools/repair_staging/learned")
ALTERNATE_STAGING_SUFFIX = Path("tools/repair_staging/learned")


def repo_root_from_rule_map(rule_map_path: Path) -> Path:
    resolved = Path(rule_map_path).resolve()
    parts = list(resolved.parts)
    tail = ["app", "tools", "audit", "rule_repair_map.json"]
    for i in range(0, max(0, len(parts) - len(tail) + 1)):
        if parts[i : i + len(tail)] == tail:
            return Path(*parts[:i]) if i else Path(resolved.anchor)
    if len(resolved.parents) >= 3:
        return resolved.parents[3]
    return Path.cwd().resolve()


def activation_artifact_path(job_dir: Optional[Path], rule_map_path: Path, filename: str) -> Path:
    if job_dir:
        return Path(job_dir) / "audit" / filename
    return Path(rule_map_path).parent / "activation_artifacts" / filename


def candidate_value(strategy: Dict[str, Any]) -> str:
    for key in ("candidate_id", "promotion_candidate_id", "learned_candidate_id", "strategy_id", "id"):
        value = clean_str(strategy.get(key))
        if value:
            return value
    evidence = as_dict(strategy.get("evidence"))
    for key in ("candidate_id", "promotion_candidate_id", "learned_strategy_record_id"):
        value = clean_str(evidence.get(key))
        if value:
            return value
    return ""


def reviewed_strategy_lists(entry: Dict[str, Any]) -> List[Tuple[str, List[Any]]]:
    lists: List[Tuple[str, List[Any]]] = []
    for key in ("reviewed_learned_strategies", "staged_learned_strategies", "learned_strategies"):
        value = entry.get(key)
        if isinstance(value, list):
            lists.append((key, value))
    return lists


def find_reviewed_strategy(rule_map: Dict[str, Any], rule_id: str, candidate_id: str) -> Tuple[Dict[str, Any], str, int, Dict[str, Any]]:
    entry = as_dict(as_dict(rule_map.get("rules")).get(rule_id))
    if not entry:
        raise PromotionError(f"rule_id_not_found: {rule_id}")
    for list_key, items in reviewed_strategy_lists(entry):
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if candidate_value(item) == candidate_id:
                return entry, list_key, idx, item
    raise PromotionError(f"candidate_id_not_found_in_rule_map: {candidate_id}")


def staged_script_value(strategy: Dict[str, Any]) -> str:
    for key in (
        "staged_script_path",
        "script_path",
        "repair_script",
        "generated_script_path",
        "learned_script_path",
    ):
        value = clean_str(strategy.get(key))
        if value:
            return value
    evidence = as_dict(strategy.get("evidence"))
    for key in ("staged_script_path", "script_path", "repair_script"):
        value = clean_str(evidence.get(key))
        if value:
            return value
    return ""


def staged_script_hash_value(strategy: Dict[str, Any]) -> str:
    for key in ("staged_script_sha256", "script_sha256", "sha256", "generated_script_sha256"):
        value = clean_str(strategy.get(key))
        if value:
            return value
    evidence = as_dict(strategy.get("evidence"))
    for key in ("staged_script_sha256", "script_sha256", "sha256"):
        value = clean_str(evidence.get(key))
        if value:
            return value
    return ""


def resolve_staged_script_path(rule_map_path: Path, raw_value: str) -> Optional[Path]:
    if not raw_value:
        return None
    p = Path(raw_value)
    repo_root = repo_root_from_rule_map(rule_map_path)
    candidates: List[Path] = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.extend([
            repo_root / p,
            repo_root / "app" / p,
            Path.cwd() / p,
        ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def approved_staging_roots(rule_map_path: Path) -> List[Path]:
    repo_root = repo_root_from_rule_map(rule_map_path)
    return [
        (repo_root / APPROVED_STAGING_SUFFIX).resolve(),
        (repo_root / ALTERNATE_STAGING_SUFFIX).resolve(),
        Path("/app/tools/repair_staging/learned").resolve(),
    ]


def under_approved_staging(path: Optional[Path], rule_map_path: Path) -> bool:
    if path is None:
        return False
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in approved_staging_roots(rule_map_path):
        try:
            resolved.relative_to(root)
            return True
        except Exception:
            continue
    return False


def static_safety_checks(path: Optional[Path]) -> Dict[str, Any]:
    checks = {
        "script_exists": False,
        "python_ast_parse": False,
        "forbidden_constructs_absent": False,
        "compile_check": False,
        "blockers": [],
    }
    if path is None or not path.exists():
        checks["blockers"].append("staged_script_missing")
        return checks
    checks["script_exists"] = True
    try:
        source = path.read_text()
    except Exception as exc:
        checks["blockers"].append(f"staged_script_unreadable: {exc}")
        return checks
    try:
        tree = __import__("ast").parse(source, filename=str(path))
        checks["python_ast_parse"] = True
    except Exception as exc:
        checks["blockers"].append(f"python_ast_parse_failed: {exc}")
        return checks
    forbidden = []
    for node in __import__("ast").walk(tree):
        if isinstance(node, (__import__("ast").Import, __import__("ast").ImportFrom)):
            names = [getattr(alias, "name", "") for alias in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            if any(name.split(".")[0] in {"subprocess", "socket", "requests"} for name in names) or module.split(".")[0] in {"subprocess", "socket", "requests"}:
                forbidden.append("forbidden_import")
        if isinstance(node, __import__("ast").Call):
            func = getattr(node, "func", None)
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in {"eval", "exec", "compile", "__import__"}:
                forbidden.append(f"forbidden_call:{name}")
    if forbidden:
        checks["blockers"].extend(sorted(set(forbidden)))
    else:
        checks["forbidden_constructs_absent"] = True
    try:
        compile(source, str(path), "exec")
        checks["compile_check"] = True
    except Exception as exc:
        checks["blockers"].append(f"compile_failed: {exc}")
    return checks


def activation_blockers(strategy: Dict[str, Any], rule_map_path: Path, *, require_staged_review: bool) -> Tuple[List[str], Dict[str, Any], Optional[Path], str, str]:
    blockers: List[str] = []
    raw_script_path = staged_script_value(strategy)
    staged_path = resolve_staged_script_path(rule_map_path, raw_script_path)
    expected_sha = staged_script_hash_value(strategy)
    actual_sha = sha256_file(staged_path) if staged_path else None

    if require_staged_review:
        if strategy.get("production_active") is not False:
            blockers.append("production_active_must_be_false_before_activation")
        if clean_str(strategy.get("activation_status")) != "staged_review":
            blockers.append("activation_status_must_be_staged_review")
        if strategy.get("review_required") is not True and strategy.get("activation_review_required") is not True:
            blockers.append("review_required_metadata_missing")

    dirty_markers = []
    if strategy.get("dirty") is True:
        dirty_markers.append("dirty")
    if strategy.get("failed") is True:
        dirty_markers.append("failed")
    outcome = clean_str(strategy.get("outcome")).lower()
    if outcome in {"dirty", "failed", "refusal", "refused"}:
        dirty_markers.append(f"outcome:{outcome}")
    if strategy.get("refusal") is True or strategy.get("refused") is True:
        dirty_markers.append("refusal")
    if dirty_markers:
        blockers.extend(sorted(set(dirty_markers)))

    if not raw_script_path:
        blockers.append("missing_staged_script_path")
    if staged_path is None or not staged_path.exists():
        blockers.append("staged_script_missing")
    if staged_path is not None and not under_approved_staging(staged_path, rule_map_path):
        blockers.append("staged_script_not_under_approved_staging_dir")
    if not expected_sha:
        blockers.append("missing_staged_script_sha256")
    elif actual_sha is None:
        blockers.append("staged_script_hash_unverifiable")
    elif expected_sha != actual_sha:
        blockers.append("staged_script_hash_mismatch")

    evidence = as_dict(strategy.get("evidence"))
    if not evidence and not any(clean_str(strategy.get(k)) for k in ("learned_strategy_record_id", "script_promotion_result_path", "rule_map_adoption_review_path")):
        blockers.append("missing_patch10_evidence_metadata")

    static_checks = static_safety_checks(staged_path)
    blockers.extend(as_list(static_checks.get("blockers")))
    return sorted(set(blockers)), static_checks, staged_path, expected_sha, actual_sha or ""


def activation_common_packet(mode: str, rule_id: str, candidate_id: str, rule_map_path: Path, strategy: Dict[str, Any], blockers: List[str], checks: Dict[str, Any], staged_path: Optional[Path], expected_sha: str, actual_sha: str) -> Dict[str, Any]:
    return {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": mode,
        "rule_id": rule_id,
        "candidate_id": candidate_id,
        "rule_map_path": str(rule_map_path),
        "staged_script_path": str(staged_path) if staged_path else staged_script_value(strategy),
        "staged_script_sha256": expected_sha,
        "actual_staged_script_sha256": actual_sha,
        "activation_checks": checks,
        "activation_blockers": blockers,
        "safe_to_activate": not blockers,
        "requires_reviewed_by_for_apply": True,
        "canonical_rule_map_mutation_performed": False,
        "production_activation_performed": False,
        "production_deactivation_performed": False,
        "final_pdf_adoption_performed": False,
        "script_promotion_performed": False,
        "repair_directory_mutation_performed": False,
    }


def create_activation_dry_run(*, rule_map_path: Path, rule_id: str, candidate_id: str, job_dir: Optional[Path] = None, output_path: Optional[Path] = None) -> Dict[str, Any]:
    if not rule_id:
        raise PromotionError("--rule-id is required for activation dry-run")
    if not candidate_id:
        raise PromotionError("--candidate-id is required for activation dry-run")
    rule_map = load_rule_map(rule_map_path)
    _entry, _list_key, _idx, strategy = find_reviewed_strategy(rule_map, rule_id, candidate_id)
    blockers, checks, staged_path, expected_sha, actual_sha = activation_blockers(strategy, rule_map_path, require_staged_review=True)
    packet = activation_common_packet("activation_dry_run", rule_id, candidate_id, rule_map_path, strategy, blockers, checks, staged_path, expected_sha, actual_sha)
    out = Path(output_path) if output_path else activation_artifact_path(job_dir, rule_map_path, ACTIVATION_REVIEW_FILENAME)
    write_json_atomic(out, packet)
    return packet


def backup_rule_map_before_mutation(rule_map_path: Path) -> Path:
    backup_dir = Path(rule_map_path).parent / "rule_map_activation_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"{Path(rule_map_path).name}.{stamp}.bak"
    shutil.copy2(rule_map_path, dest)
    return dest


def apply_activation(*, rule_map_path: Path, rule_id: str, candidate_id: str, reviewed_by: str, job_dir: Optional[Path] = None, output_path: Optional[Path] = None) -> Dict[str, Any]:
    if not rule_id:
        raise PromotionError("--rule-id is required for activation apply")
    if not candidate_id:
        raise PromotionError("--candidate-id is required for activation apply")
    if not reviewed_by:
        raise PromotionError("--reviewed-by is required for activation apply")
    rule_map = load_rule_map(rule_map_path)
    _entry, list_key, idx, strategy = find_reviewed_strategy(rule_map, rule_id, candidate_id)
    before = copy.deepcopy(strategy)
    blockers, checks, staged_path, expected_sha, actual_sha = activation_blockers(strategy, rule_map_path, require_staged_review=True)
    packet = activation_common_packet("activation_apply", rule_id, candidate_id, rule_map_path, strategy, blockers, checks, staged_path, expected_sha, actual_sha)
    if blockers:
        packet["result"] = "BLOCKED"
        out = Path(output_path) if output_path else activation_artifact_path(job_dir, rule_map_path, ACTIVATION_APPLY_FILENAME)
        write_json_atomic(out, packet)
        return packet
    backup_path = backup_rule_map_before_mutation(rule_map_path)
    selected = rule_map["rules"][rule_id][list_key][idx]
    selected["production_active"] = True
    selected["activation_status"] = "active"
    selected["activated_by"] = reviewed_by
    selected["activated_at"] = utc_now_iso()
    selected["activation_review_required"] = False
    if selected.get("review_required") is True:
        selected["review_required"] = False
    write_json_atomic(rule_map_path, rule_map)
    packet.update({
        "result": "ACTIVATED",
        "backup_path": str(backup_path),
        "canonical_rule_map_mutation_performed": True,
        "production_activation_performed": True,
        "selected_strategy_before": before,
        "selected_strategy_after": selected,
        "mutated_list_key": list_key,
        "mutated_index": idx,
    })
    out = Path(output_path) if output_path else activation_artifact_path(job_dir, rule_map_path, ACTIVATION_APPLY_FILENAME)
    write_json_atomic(out, packet)
    return packet


def deactivate_strategy(*, rule_map_path: Path, rule_id: str, candidate_id: str, reviewed_by: str, job_dir: Optional[Path] = None, output_path: Optional[Path] = None) -> Dict[str, Any]:
    if not rule_id:
        raise PromotionError("--rule-id is required for deactivation")
    if not candidate_id:
        raise PromotionError("--candidate-id is required for deactivation")
    if not reviewed_by:
        raise PromotionError("--reviewed-by is required for deactivation")
    rule_map = load_rule_map(rule_map_path)
    _entry, list_key, idx, strategy = find_reviewed_strategy(rule_map, rule_id, candidate_id)
    before = copy.deepcopy(strategy)
    backup_path = backup_rule_map_before_mutation(rule_map_path)
    selected = rule_map["rules"][rule_id][list_key][idx]
    selected["production_active"] = False
    selected["activation_status"] = "deactivated"
    selected["deactivated_by"] = reviewed_by
    selected["deactivated_at"] = utc_now_iso()
    write_json_atomic(rule_map_path, rule_map)
    packet = {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": "deactivate",
        "result": "DEACTIVATED",
        "rule_id": rule_id,
        "candidate_id": candidate_id,
        "rule_map_path": str(rule_map_path),
        "backup_path": str(backup_path),
        "staged_script_path": staged_script_value(strategy),
        "canonical_rule_map_mutation_performed": True,
        "production_activation_performed": False,
        "production_deactivation_performed": True,
        "final_pdf_adoption_performed": False,
        "script_promotion_performed": False,
        "repair_directory_mutation_performed": False,
        "staged_script_deleted": False,
        "selected_strategy_before": before,
        "selected_strategy_after": selected,
        "mutated_list_key": list_key,
        "mutated_index": idx,
    }
    out = Path(output_path) if output_path else activation_artifact_path(job_dir, rule_map_path, ACTIVATION_DEACTIVATE_FILENAME)
    write_json_atomic(out, packet)
    return packet
# PATCH11_ACTIVATION_POLICY_END


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create reviewed promotion packets and activate reviewed staged learned strategies.")
    parser.add_argument("--job-dir", required=False, help="Path to the job directory")
    parser.add_argument("--rule-map", default=None, help="Path to canonical rule_repair_map.json")
    parser.add_argument("--output", default=None, help="Optional output path for the generated artifact")
    parser.add_argument("--candidate-id", default=None, help="Optional candidate_id filter or activation target")
    parser.add_argument("--rule-id", default=None, help="Optional rule_id filter or activation target")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Create review packet only; this is the default")
    parser.add_argument("--apply-rule-map", action="store_true", help="Fails closed for legacy promotion apply; use --activate for Patch 11 activation")
    parser.add_argument("--activation-dry-run", action="store_true", help="Review whether a staged learned strategy is safe to activate without mutating the rule map")
    parser.add_argument("--activate", action="store_true", help="Activate one reviewed staged learned strategy in the rule map")
    parser.add_argument("--deactivate", action="store_true", help="Deactivate one reviewed staged learned strategy in the rule map")
    parser.add_argument("--reviewed-by", default=None, help="Required for --activate and --deactivate")
    return parser

def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    rule_map = Path(args.rule_map) if args.rule_map else resolve_default_rule_map()
    job_dir = Path(args.job_dir) if args.job_dir else None
    output = Path(args.output) if args.output else None

    try:
        if args.activation_dry_run:
            packet = create_activation_dry_run(
                rule_map_path=rule_map,
                rule_id=clean_str(args.rule_id),
                candidate_id=clean_str(args.candidate_id),
                job_dir=job_dir,
                output_path=output,
            )
            print(json.dumps(packet, indent=2, sort_keys=True, default=json_default))
            return 0 if packet.get("safe_to_activate") else 3

        if args.activate:
            packet = apply_activation(
                rule_map_path=rule_map,
                rule_id=clean_str(args.rule_id),
                candidate_id=clean_str(args.candidate_id),
                reviewed_by=clean_str(args.reviewed_by),
                job_dir=job_dir,
                output_path=output,
            )
            print(json.dumps(packet, indent=2, sort_keys=True, default=json_default))
            return 0 if packet.get("result") == "ACTIVATED" else 3

        if args.deactivate:
            packet = deactivate_strategy(
                rule_map_path=rule_map,
                rule_id=clean_str(args.rule_id),
                candidate_id=clean_str(args.candidate_id),
                reviewed_by=clean_str(args.reviewed_by),
                job_dir=job_dir,
                output_path=output,
            )
            print(json.dumps(packet, indent=2, sort_keys=True, default=json_default))
            return 0

        if args.apply_rule_map:
            print(
                json.dumps(
                    {
                        "result": "ERROR",
                        "reason": "legacy --apply-rule-map remains closed; use Patch 11 --activate for reviewed staged strategies",
                        "policy": base_policy(apply_mode_requested=True),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2

        if job_dir is None:
            parser.error("--job-dir is required for promotion review dry-run")
        packet = create_review_packet(
            job_dir=job_dir,
            rule_map_path=rule_map,
            output_path=output,
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
