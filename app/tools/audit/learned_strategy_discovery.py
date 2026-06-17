#!/usr/bin/env python3
"""
learned_strategy_discovery.py

Patch 12A discovery-only contract for already-activated learned strategies.

This module inspects reviewed learned strategy metadata in rule_repair_map.json,
validates that an active staged script is safe to *consider*, and emits an audit
artifact. It does not import, shell out to, or execute staged learned scripts.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "active-learned-strategy-discovery.v1"
ARTIFACT_NAME = "learned_strategy_discovery.json"
APPROVED_STAGING_DIR = Path("app/tools/repair_staging/learned")
APPROVED_STAGING_DIR_ALT = Path("tools/repair_staging/learned")
LEARNED_SECTION = "reviewed_learned_strategies"

DANGEROUS_IMPORT_ROOTS = {
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "paramiko",
    "telnetlib",
    "multiprocessing",
}
DANGEROUS_BUILTINS = {"eval", "exec", "compile", "__import__", "input"}
DANGEROUS_OS_CALLS = {
    "system",
    "popen",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "remove",
    "unlink",
    "rmdir",
    "removedirs",
    "renames",
}
DANGEROUS_SHUTIL_CALLS = {"rmtree"}
DIRTY_MARKER_KEYS = (
    "dirty",
    "failed",
    "failure",
    "semantic_refusal",
    "refusal",
    "refused",
    "deactivated",
)
BLOCKER_KEYS = (
    "promotion_blockers",
    "activation_blockers",
    "blockers",
    "indexing_blockers",
    "dirty_markers",
    "failure_reasons",
    "refusal_reasons",
)


class DiscoveryError(Exception):
    """Raised for malformed discovery inputs."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default))
    tmp.replace(path)


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_str(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def as_bool(value: Any) -> bool:
    return value is True


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def infer_repo_root(rule_map_path: Path) -> Path:
    resolved = rule_map_path.resolve()
    parts = resolved.parts
    suffix = ("app", "tools", "audit")
    for idx in range(0, len(parts) - len(suffix)):
        if tuple(parts[idx : idx + len(suffix)]) == suffix:
            return Path(*parts[:idx]) if idx else Path("/")
    # Fallback for tests that place rule_map.json at a temp repo root.
    return resolved.parent


def discovery_policy() -> Dict[str, Any]:
    return {
        "mode": "discovery_only",
        "reviewed_learned_strategy_section": LEARNED_SECTION,
        "required_source": "learned_strategy_staged",
        "requires_production_active_true": True,
        "requires_activation_status_active": True,
        "requires_candidate_id": True,
        "requires_staged_script_path": True,
        "approved_staging_directory": str(APPROVED_STAGING_DIR),
        "requires_script_exists": True,
        "requires_staged_script_sha256_match": True,
        "requires_static_checks_pass": True,
        "rejects_dirty_failed_refusal_markers": True,
        "execution_performed": False,
        "final_pdf_adoption_performed": False,
        "production_execution_enabled_by_patch_12a": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
    }


def load_rule_map(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise DiscoveryError(f"cannot read rule map {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rules"), dict):
        raise DiscoveryError(f"malformed rule map {path}: expected top-level rules object")
    return data


def script_path_value(entry: Dict[str, Any]) -> str:
    for key in ("staged_script_path", "script_path", "repair_script"):
        value = clean_str(entry.get(key))
        if value:
            return value
    return ""


def script_sha_value(entry: Dict[str, Any]) -> str:
    for key in ("staged_script_sha256", "script_sha256"):
        value = clean_str(entry.get(key))
        if value:
            return value.lower()
    return ""


def strategy_identifier(rule_id: str, candidate_id: str, entry: Dict[str, Any]) -> str:
    explicit = clean_str(entry.get("strategy_id"))
    if explicit:
        return explicit
    basis = f"{rule_id}\0{candidate_id}\0{script_path_value(entry)}\0{script_sha_value(entry)}"
    return "learned-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def contains_quarantine_reference(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        "audit/self_extension/quarantine/" in normalized
        or "/workspace/jobs/" in normalized
        or normalized.startswith("workspace/jobs/")
        or normalized.startswith("/app/workspace/jobs/")
    )


def resolve_staged_path(raw_value: str, repo_root: Path) -> Tuple[Optional[Path], List[str]]:
    reasons: List[str] = []
    if not raw_value:
        return None, ["missing_staged_script_path"]
    if contains_quarantine_reference(raw_value):
        reasons.append("staged_script_path_references_job_quarantine")
    raw_path = Path(raw_value)
    if raw_path.is_absolute():
        resolved = raw_path
        if not is_relative_to(resolved, repo_root):
            reasons.append("absolute_staged_script_path_outside_repo")
    else:
        if raw_path.parts[:3] == APPROVED_STAGING_DIR_ALT.parts:
            raw_path = Path("app") / raw_path
        resolved = repo_root / raw_path
    approved_root = repo_root / APPROVED_STAGING_DIR
    if not is_relative_to(resolved, approved_root):
        reasons.append("staged_script_path_not_under_approved_staging_dir")
    return resolved, reasons


def static_check_script(path: Optional[Path]) -> Dict[str, Any]:
    result = {"passed": False, "reasons": [], "checks": []}
    if path is None:
        result["reasons"].append("missing_staged_script_path")
        return result
    if not path.exists() or not path.is_file():
        result["reasons"].append("staged_script_missing")
        return result
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        result["reasons"].append(f"syntax_error:{exc.lineno}:{exc.msg}")
        return result
    except Exception as exc:
        result["reasons"].append(f"static_check_read_error:{exc}")
        return result

    reasons: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DANGEROUS_IMPORT_ROOTS:
                    reasons.append(f"dangerous_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in DANGEROUS_IMPORT_ROOTS:
                reasons.append(f"dangerous_import:{module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_BUILTINS:
                reasons.append(f"dangerous_builtin:{func.id}")
            elif isinstance(func, ast.Attribute):
                base = func.value
                if isinstance(base, ast.Name):
                    if base.id == "os" and func.attr in DANGEROUS_OS_CALLS:
                        reasons.append(f"dangerous_os_call:os.{func.attr}")
                    if base.id == "shutil" and func.attr in DANGEROUS_SHUTIL_CALLS:
                        reasons.append(f"dangerous_shutil_call:shutil.{func.attr}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "environ":
                reasons.append("dangerous_os_environ_access")

    result["reasons"] = sorted(set(reasons))
    result["checks"] = [
        "python_ast_parse",
        "reject_dangerous_builtins",
        "reject_network_process_imports",
        "reject_process_execution_calls",
        "reject_destructive_filesystem_calls",
        "reject_os_environ_access",
    ]
    result["passed"] = not result["reasons"]
    return result


def dirty_failed_refusal_reasons(entry: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    for key in DIRTY_MARKER_KEYS:
        if entry.get(key) is True:
            reasons.append(f"marker_{key}_true")
    for key in BLOCKER_KEYS:
        if as_list(entry.get(key)):
            reasons.append(f"{key}_present")
    status = clean_str(entry.get("status") or entry.get("outcome") or entry.get("activation_result")).lower()
    for token in ("dirty", "fail", "failed", "refusal", "refused", "unsafe", "deactivated"):
        if token in status:
            reasons.append(f"status_contains_{token}")
    if entry.get("clean") is False:
        reasons.append("clean_false")
    return sorted(set(reasons))


def ignored_record(rule_id: str, candidate_id: str, entry: Dict[str, Any], reasons: Sequence[str]) -> Dict[str, Any]:
    return {
        "rule_id": rule_id,
        "candidate_id": candidate_id or clean_str(entry.get("candidate_id")),
        "reason": sorted(set(reasons)) or ["not_runtime_eligible"],
        "production_active": entry.get("production_active"),
        "activation_status": entry.get("activation_status"),
        "runtime_eligible": False,
        "execution_performed": False,
    }


def evaluate_entry(rule_id: str, entry: Dict[str, Any], repo_root: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    reasons: List[str] = []
    candidate_id = clean_str(entry.get("candidate_id"))
    source = clean_str(entry.get("source"))
    activation_status = clean_str(entry.get("activation_status"))
    production_active = as_bool(entry.get("production_active"))

    if source != "learned_strategy_staged":
        reasons.append("source_not_learned_strategy_staged")
    if not production_active:
        reasons.append("not_production_active")
    if activation_status != "active":
        reasons.append("activation_status_not_active")
        if activation_status == "deactivated":
            reasons.append("deactivated")
    if not candidate_id:
        reasons.append("missing_candidate_id")
    reasons.extend(dirty_failed_refusal_reasons(entry))

    raw_path = script_path_value(entry)
    resolved_path, path_reasons = resolve_staged_path(raw_path, repo_root)
    reasons.extend(path_reasons)
    script_exists = bool(resolved_path and resolved_path.exists() and resolved_path.is_file())
    if not script_exists:
        reasons.append("staged_script_missing")

    expected_sha = script_sha_value(entry)
    actual_sha = sha256_file(resolved_path) if resolved_path else None
    hash_verified = bool(expected_sha and actual_sha and expected_sha == actual_sha)
    if not expected_sha:
        reasons.append("missing_staged_script_sha256")
    elif actual_sha and expected_sha != actual_sha:
        reasons.append("staged_script_hash_mismatch")
    elif not actual_sha:
        reasons.append("staged_script_hash_unverifiable")

    static_checks = static_check_script(resolved_path)
    if not static_checks.get("passed"):
        reasons.append("static_checks_failed")

    if reasons:
        return None, ignored_record(rule_id, candidate_id, entry, reasons + as_list(static_checks.get("reasons")))

    discovered = {
        "rule_id": rule_id,
        "candidate_id": candidate_id,
        "strategy_id": strategy_identifier(rule_id, candidate_id, entry),
        "source": "learned_strategy_staged",
        "production_active": True,
        "activation_status": "active",
        "staged_script_path": raw_path,
        "staged_script_sha256": expected_sha,
        "script_exists": script_exists,
        "hash_verified": hash_verified,
        "static_checks": static_checks,
        "execution_order": entry.get("execution_order", entry.get("repair_order", 99)),
        "run_after_builtin_strategies": True,
        "runtime_eligible": True,
        "execution_performed": False,
    }
    return discovered, None


def discover_active_learned_strategies(
    rule_map_path: Path,
    rule_ids: Optional[List[str]] = None,
    repo_root: Optional[Path] = None,
    audit_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Discover active reviewed learned strategies without executing them."""
    rule_map_path = Path(rule_map_path)
    repo_root = Path(repo_root) if repo_root else infer_repo_root(rule_map_path)
    requested = [clean_str(r) for r in (rule_ids or []) if clean_str(r)]
    requested_set = set(requested)
    data = load_rule_map(rule_map_path)
    discovered: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rule_id, rule_entry in sorted(as_dict(data.get("rules")).items()):
        if requested_set and rule_id not in requested_set:
            continue
        if not isinstance(rule_entry, dict):
            warnings.append(f"rule_entry_not_object:{rule_id}")
            continue
        learned_entries = rule_entry.get(LEARNED_SECTION, [])
        if learned_entries is None:
            learned_entries = []
        if not isinstance(learned_entries, list):
            warnings.append(f"reviewed_learned_strategies_not_list:{rule_id}")
            continue
        for raw in learned_entries:
            if not isinstance(raw, dict):
                ignored.append(
                    {
                        "rule_id": rule_id,
                        "candidate_id": "",
                        "reason": ["learned_strategy_entry_not_object"],
                        "production_active": None,
                        "activation_status": None,
                        "runtime_eligible": False,
                        "execution_performed": False,
                    }
                )
                continue
            good, bad = evaluate_entry(rule_id, raw, repo_root)
            if good is not None:
                discovered.append(good)
            if bad is not None:
                ignored.append(bad)

    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "mode": "discovery_only",
        "rule_map_path": str(rule_map_path),
        "rule_ids_requested": requested or None,
        "discovered_strategies": discovered,
        "ignored_strategies": ignored,
        "warnings": warnings,
        "policy": discovery_policy(),
        "execution_performed": False,
        "final_pdf_adoption_performed": False,
        "production_execution_enabled_by_patch_12a": False,
        "rule_map_mutation_performed": False,
        "app_tools_repair_mutation_performed": False,
    }
    if audit_dir:
        write_json_atomic(Path(audit_dir) / ARTIFACT_NAME, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover active learned strategies without executing them.")
    parser.add_argument("--rule-map", required=True, help="Path to rule_repair_map.json")
    parser.add_argument("--rule-id", action="append", default=None, help="Optional rule ID filter; may be repeated")
    parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to inference from --rule-map")
    parser.add_argument("--audit-dir", default=None, help="Optional audit directory for learned_strategy_discovery.json")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = discover_active_learned_strategies(
            rule_map_path=Path(args.rule_map),
            rule_ids=args.rule_id,
            repo_root=Path(args.repo_root) if args.repo_root else None,
            audit_dir=Path(args.audit_dir) if args.audit_dir else None,
        )
    except DiscoveryError as exc:
        print(json.dumps({"result": "ERROR", "reason": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=json_default))
    return 0


if __name__ == "__main__":
    sys.exit(main())
