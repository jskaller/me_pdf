#!/usr/bin/env python3
"""Set up or clean up a temporary active learned strategy smoke candidate.

Patch 16B helper.

This is a development/test smoke utility only. It creates a safe staged learned
script plus temporary rule-map metadata so the orchestrator's opt-in learned
execution dry-run path can prove that a live active candidate is executed
diagnostically.

The helper supports two smoke script modes:

* copy: existing no-op behavior; output hash equals input hash.
* changed-valid: synthetic changed-output behavior; output hash differs from
  input hash while preserving basic PDF validity for diagnostics.

Cleanup restores the canonical rule map from backup and removes staged smoke
scripts. The helper never adopts a final PDF, softens a verdict, mutates
app/tools/repair, or promotes learned scripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

RULE_MAP_BACKUP_NAME = "learned_execution_smoke_rule_map_backup.json"
SETUP_ARTIFACT_NAME = "learned_execution_smoke_setup.json"
DEFAULT_RULE_ID = "PDF/UA-1/7.21.7"
DEFAULT_CANDIDATE_ID = "smoke-active-candidate"
SCRIPT_MODE_COPY = "copy"
SCRIPT_MODE_CHANGED_VALID = "changed-valid"
SCRIPT_MODES = (SCRIPT_MODE_COPY, SCRIPT_MODE_CHANGED_VALID)

COPY_STAGED_SCRIPT_TEMPLATE = """#!/usr/bin/env python3
from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: smoke_active_candidate.py input.pdf output.pdf", file=sys.stderr)
        return 2

    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2])

    if not input_pdf.exists() or not input_pdf.is_file():
        print(f"input missing: {input_pdf}", file=sys.stderr)
        return 2

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.write_bytes(input_pdf.read_bytes())
    print(f"smoke learned strategy copied {input_pdf} to {output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

CHANGED_VALID_STAGED_SCRIPT_TEMPLATE = """#!/usr/bin/env python3
from pathlib import Path
import sys

MARKER = b"\\n% learned-smoke-changed-valid\\n"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: smoke_changed_valid_candidate.py input.pdf output.pdf", file=sys.stderr)
        return 2

    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2])

    if not input_pdf.exists() or not input_pdf.is_file():
        print(f"input missing: {input_pdf}", file=sys.stderr)
        return 2

    data = input_pdf.read_bytes()
    if not data.startswith(b"%PDF-"):
        print(f"input is not a PDF header: {input_pdf}", file=sys.stderr)
        return 2

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.write_bytes(data + MARKER)
    print(f"smoke learned strategy wrote deterministic changed-valid output {output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

SCRIPT_TEMPLATES = {
    SCRIPT_MODE_COPY: COPY_STAGED_SCRIPT_TEMPLATE,
    SCRIPT_MODE_CHANGED_VALID: CHANGED_VALID_STAGED_SCRIPT_TEMPLATE,
}

EXPECTED_CLASSIFICATION = {
    SCRIPT_MODE_COPY: "no_effect",
    SCRIPT_MODE_CHANGED_VALID: "changed_valid_pdf",
}

EXPECTED_QUALITY_DECISION = {
    SCRIPT_MODE_COPY: "rejected_no_effect",
    SCRIPT_MODE_CHANGED_VALID: "candidate_valid_changed",
}

EXPECTED_DEEPER_VALIDATION_DECISION = {
    SCRIPT_MODE_COPY: "skipped_not_eligible",
    SCRIPT_MODE_CHANGED_VALID: "deeper_validation_passed_or_needs_manual_review",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object at {path}")
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def safe_token(value: str) -> str:
    cleaned = []
    for ch in str(value or ""):
        cleaned.append(ch if ch.isalnum() or ch in {"-", "_", "."} else "-")
    return "".join(cleaned).strip("-_.") or "smoke-active-candidate"


def infer_layout(repo_root_arg: Optional[str], rule_map_arg: Optional[str]) -> Tuple[Path, Path, Path, str]:
    """Return (repo_root_for_discovery, rule_map_path, staging_abs, staged_rel_dir)."""
    cwd = Path.cwd().resolve()

    if repo_root_arg:
        repo_root = Path(repo_root_arg).resolve()
        rule_map = Path(rule_map_arg).resolve() if rule_map_arg else repo_root / "app/tools/audit/rule_repair_map.json"
        return (
            repo_root,
            rule_map,
            repo_root / "app/tools/repair_staging/learned",
            "app/tools/repair_staging/learned",
        )

    if rule_map_arg:
        rule_map = Path(rule_map_arg).resolve()
        parts = rule_map.parts
        for idx in range(0, len(parts) - 3):
            if parts[idx : idx + 3] == ("app", "tools", "audit"):
                repo_root = Path(*parts[:idx]) if idx else Path("/")
                return (
                    repo_root,
                    rule_map,
                    repo_root / "app/tools/repair_staging/learned",
                    "app/tools/repair_staging/learned",
                )
        return (cwd, rule_map, cwd / "app/tools/repair_staging/learned", "app/tools/repair_staging/learned")

    container_rule_map = cwd / "tools/audit/rule_repair_map.json"
    if container_rule_map.exists():
        return (
            Path("/"),
            container_rule_map,
            cwd / "tools/repair_staging/learned",
            "app/tools/repair_staging/learned",
        )

    repo_root = cwd
    return (
        repo_root,
        repo_root / "app/tools/audit/rule_repair_map.json",
        repo_root / "app/tools/repair_staging/learned",
        "app/tools/repair_staging/learned",
    )


def backup_path(job_dir: Path) -> Path:
    return job_dir / "audit" / RULE_MAP_BACKUP_NAME


def setup_artifact_path(job_dir: Path) -> Path:
    return job_dir / "audit" / SETUP_ARTIFACT_NAME


def script_name(candidate_id: str) -> str:
    return f"smoke_{safe_token(candidate_id)}.py"


def load_setup_artifact(job_dir: Path) -> Dict[str, Any]:
    path = setup_artifact_path(job_dir)
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def create_smoke_candidate(
    *,
    job_dir: Path,
    rule_id: str,
    candidate_id: str,
    repo_root_arg: Optional[str],
    rule_map_arg: Optional[str],
    script_mode: str = SCRIPT_MODE_COPY,
) -> Dict[str, Any]:
    if script_mode not in SCRIPT_MODES:
        raise ValueError(f"unsupported script_mode: {script_mode}")

    repo_root, rule_map_path, staging_dir, staged_rel_dir = infer_layout(repo_root_arg, rule_map_arg)
    if not rule_map_path.exists():
        raise FileNotFoundError(f"rule map not found: {rule_map_path}")

    job_dir = job_dir.resolve()
    audit_dir = job_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    backup = backup_path(job_dir)
    if not backup.exists():
        shutil.copy2(rule_map_path, backup)

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_script = staging_dir / script_name(candidate_id)
    staged_script.write_text(SCRIPT_TEMPLATES[script_mode])
    staged_script.chmod(0o755)
    staged_sha = sha256_file(staged_script)
    staged_rel = f"{staged_rel_dir}/{staged_script.name}"

    rule_map = read_json(rule_map_path)
    rules = rule_map.setdefault("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("rule map top-level 'rules' value is not an object")

    rule_entry = rules.setdefault(rule_id, {})
    if not isinstance(rule_entry, dict):
        raise ValueError(f"rule entry is not an object: {rule_id}")

    learned = rule_entry.setdefault("reviewed_learned_strategies", [])
    if not isinstance(learned, list):
        raise ValueError(f"reviewed_learned_strategies is not a list for {rule_id}")

    smoke_entry = {
        "source": "learned_strategy_staged",
        "production_active": True,
        "activation_status": "active",
        "review_required": False,
        "candidate_id": candidate_id,
        "strategy_id": f"{safe_token(candidate_id)}-diagnostic-{script_mode}",
        "staged_script_path": staged_rel,
        "staged_script_sha256": staged_sha,
        "runtime_eligible": True,
        "execution_order": 999,
        "smoke_only": True,
        "script_mode": script_mode,
        "expected_comparison_classification": EXPECTED_CLASSIFICATION[script_mode],
        "expected_quality_decision": EXPECTED_QUALITY_DECISION[script_mode],
        "expected_deeper_validation_decision": EXPECTED_DEEPER_VALIDATION_DECISION[script_mode],
        "created_by": "setup_learned_execution_smoke_candidate.py",
        "created_at": utc_now_iso(),
    }

    replaced = False
    for idx, entry in enumerate(learned):
        if isinstance(entry, dict) and entry.get("candidate_id") == candidate_id:
            learned[idx] = smoke_entry
            replaced = True
            break
    if not replaced:
        learned.append(smoke_entry)

    write_json_atomic(rule_map_path, rule_map)

    artifact = {
        "schema_version": "learned-execution-smoke-setup.v2",
        "created_at": utc_now_iso(),
        "mode": "setup",
        "script_mode": script_mode,
        "job_dir": str(job_dir),
        "rule_id": rule_id,
        "candidate_id": candidate_id,
        "repo_root_for_discovery": str(repo_root),
        "rule_map_path": str(rule_map_path),
        "rule_map_backup_path": str(backup),
        "staged_script_path": str(staged_script),
        "staged_script_relpath": staged_rel,
        "staged_script_sha256": staged_sha,
        "production_active": True,
        "activation_status": "active",
        "runtime_eligible": True,
        "expected_comparison_classification": EXPECTED_CLASSIFICATION[script_mode],
        "expected_quality_decision": EXPECTED_QUALITY_DECISION[script_mode],
        "expected_deeper_validation_decision": EXPECTED_DEEPER_VALIDATION_DECISION[script_mode],
        "rule_map_mutation_performed": True,
        "app_tools_repair_mutation_performed": False,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "production_repair_replacement_performed": False,
        "cleanup_command": (
            "PYTHONPATH=app python3 app/tools/dev/setup_learned_execution_smoke_candidate.py "
            f"--job-dir {job_dir} --cleanup"
        ),
    }
    write_json_atomic(setup_artifact_path(job_dir), artifact)
    return artifact


def cleanup_smoke_candidate(
    *,
    job_dir: Path,
    repo_root_arg: Optional[str],
    rule_map_arg: Optional[str],
) -> Dict[str, Any]:
    repo_root, rule_map_path, staging_dir, _staged_rel_dir = infer_layout(repo_root_arg, rule_map_arg)
    job_dir = job_dir.resolve()
    audit_dir = job_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    setup_artifact = load_setup_artifact(job_dir)
    backup = Path(setup_artifact.get("rule_map_backup_path") or backup_path(job_dir))

    restored = False
    if backup.exists():
        shutil.copy2(backup, rule_map_path)
        restored = True

    removed_scripts = []
    candidate_script = setup_artifact.get("staged_script_path")
    paths_to_remove = []
    if candidate_script:
        paths_to_remove.append(Path(candidate_script))
    paths_to_remove.extend(staging_dir.glob("smoke_*.py"))

    for path in sorted(set(paths_to_remove)):
        try:
            if path.exists() and path.is_file():
                path.unlink()
                removed_scripts.append(str(path))
        except Exception:
            pass

    artifact = {
        "schema_version": "learned-execution-smoke-setup.v2",
        "created_at": utc_now_iso(),
        "mode": "cleanup",
        "job_dir": str(job_dir),
        "repo_root_for_discovery": str(repo_root),
        "rule_map_path": str(rule_map_path),
        "rule_map_backup_path": str(backup),
        "rule_map_restored_from_backup": restored,
        "removed_staged_scripts": removed_scripts,
        "rule_map_mutation_performed": restored,
        "app_tools_repair_mutation_performed": False,
        "final_pdf_adoption_performed": False,
        "verdict_softening_performed": False,
        "production_repair_replacement_performed": False,
    }
    write_json_atomic(setup_artifact_path(job_dir), artifact)
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set up or clean up the active learned candidate smoke fixture."
    )
    parser.add_argument("--job-dir", required=True, help="Job directory; audit artifacts/backups are written below audit/.")
    parser.add_argument("--rule-id", default=DEFAULT_RULE_ID)
    parser.add_argument("--candidate-id", default=DEFAULT_CANDIDATE_ID)
    parser.add_argument("--script-mode", choices=SCRIPT_MODES, default=SCRIPT_MODE_COPY)
    parser.add_argument("--repo-root", default=None, help="Host checkout root for app/tools layout. Optional.")
    parser.add_argument("--rule-map", default=None, help="Override rule_repair_map.json path. Optional.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--setup", action="store_true")
    action.add_argument("--cleanup", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.setup:
            result = create_smoke_candidate(
                job_dir=Path(args.job_dir),
                rule_id=args.rule_id,
                candidate_id=args.candidate_id,
                repo_root_arg=args.repo_root,
                rule_map_arg=args.rule_map,
                script_mode=args.script_mode,
            )
        else:
            result = cleanup_smoke_candidate(
                job_dir=Path(args.job_dir),
                repo_root_arg=args.repo_root,
                rule_map_arg=args.rule_map,
            )
    except Exception as exc:
        print(json.dumps({"result": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
