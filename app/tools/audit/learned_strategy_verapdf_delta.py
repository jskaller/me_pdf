#!/usr/bin/env python3
"""veraPDF delta diagnostics for isolated learned replacement trials.

This helper is evidence-only. It compares the normal final PDF against the
learned trial PDF inside the replacement-trial audit directory and never adopts,
promotes, installs, or mutates production repair assets.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SCHEMA_VERSION = "learned-strategy-verapdf-delta.v1"
CHECK_NAME = "verapdf_delta"


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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _int_attr(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _rule_id_from(rule: ET.Element) -> str:
    attrs = rule.attrib
    explicit = (
        attrs.get("ruleId")
        or attrs.get("rule_id")
        or attrs.get("id")
        or attrs.get("name")
        or ""
    )
    explicit = str(explicit).strip()
    if explicit.startswith("PDF/UA"):
        return explicit
    clause = str(attrs.get("clause") or "").strip()
    if clause:
        return f"PDF/UA-1/{clause}"
    if explicit:
        return explicit
    test_number = str(attrs.get("testNumber") or attrs.get("test_number") or "").strip()
    return f"unknown-rule/{test_number or 'unspecified'}"


def _failure_count_from(rule: ET.Element) -> int:
    attrs = rule.attrib
    for key in ("failedChecks", "failed_checks", "failures", "failureCount", "count"):
        if key in attrs:
            return max(1, _int_attr(attrs.get(key), 1))
    child_failures = 0
    for child in rule.iter():
        if child is rule:
            continue
        name = _local_name(child.tag).lower()
        status = str(child.attrib.get("status") or "").lower()
        if name in {"check", "test", "assertion"} and status in {"failed", "fail", "false"}:
            child_failures += 1
    return child_failures or 1


def parse_verapdf_failures(xml_text: str) -> List[Dict[str, Any]]:
    """Parse veraPDF XML into normalized rule-level failure records.

    The parser is intentionally tolerant across veraPDF schema variants. It
    recognizes failed <rule> elements and aggregates by stable rule id when
    available, falling back to PDF/UA-1/<clause>.
    """
    root = ET.fromstring(xml_text)
    counts: Counter[str] = Counter()
    details: Dict[str, Dict[str, Any]] = {}
    for elem in root.iter():
        if _local_name(elem.tag).lower() != "rule":
            continue
        status = str(elem.attrib.get("status") or "").strip().lower()
        failed_checks = _int_attr(elem.attrib.get("failedChecks"), 0)
        if status not in {"failed", "fail"} and failed_checks <= 0:
            continue
        rule_id = _rule_id_from(elem)
        count = _failure_count_from(elem)
        counts[rule_id] += count
        details.setdefault(
            rule_id,
            {
                "rule_id": rule_id,
                "clause": elem.attrib.get("clause"),
                "test_number": elem.attrib.get("testNumber") or elem.attrib.get("test_number"),
                "description": elem.attrib.get("description") or elem.attrib.get("object"),
            },
        )
    records: List[Dict[str, Any]] = []
    for rule_id in sorted(counts):
        record = {k: v for k, v in details.get(rule_id, {}).items() if v not in (None, "")}
        record["count"] = int(counts[rule_id])
        records.append(record)
    return records


def _counts(records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for record in records:
        rule_id = str(record.get("rule_id") or "").strip()
        if not rule_id:
            continue
        out[rule_id] = out.get(rule_id, 0) + max(0, int(record.get("count") or 0))
    return out


def compute_verapdf_delta(normal_records: List[Dict[str, Any]], learned_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    normal_counts = _counts(normal_records)
    learned_counts = _counts(learned_records)
    all_rules = sorted(set(normal_counts) | set(learned_counts))
    introduced_rules = [rule for rule in all_rules if normal_counts.get(rule, 0) == 0 and learned_counts.get(rule, 0) > 0]
    resolved_rules = [rule for rule in all_rules if normal_counts.get(rule, 0) > 0 and learned_counts.get(rule, 0) == 0]
    worsened_rules = [rule for rule in all_rules if normal_counts.get(rule, 0) > 0 and learned_counts.get(rule, 0) > normal_counts.get(rule, 0)]
    improved_rules = [rule for rule in all_rules if 0 < learned_counts.get(rule, 0) < normal_counts.get(rule, 0)]
    unchanged_rules = [rule for rule in all_rules if learned_counts.get(rule, 0) == normal_counts.get(rule, 0)]
    return {
        "normal_failure_count": int(sum(normal_counts.values())),
        "learned_failure_count": int(sum(learned_counts.values())),
        "introduced_failure_count": int(sum(learned_counts[rule] for rule in introduced_rules)),
        "resolved_failure_count": int(sum(normal_counts[rule] for rule in resolved_rules)),
        "worsened_failure_count": int(sum(learned_counts[rule] - normal_counts[rule] for rule in worsened_rules)),
        "improved_failure_count": int(sum(normal_counts[rule] - learned_counts[rule] for rule in improved_rules)),
        "introduced_rules": introduced_rules,
        "resolved_rules": resolved_rules,
        "worsened_rules": worsened_rules,
        "improved_rules": improved_rules,
        "unchanged_rules": unchanged_rules,
        "normal_failures_by_rule": normal_records,
        "learned_failures_by_rule": learned_records,
    }


def _candidate_record(source: str, value: Any) -> Dict[str, Any]:
    raw_value = str(value or "").strip() if value is not None else ""
    record: Dict[str, Any] = {
        "source": source,
        "value": raw_value or None,
        "exists": False,
        "is_file": False,
        "executable": False,
    }
    if not raw_value:
        return record
    path = Path(raw_value)
    try:
        record["exists"] = path.exists()
        record["is_file"] = path.is_file()
        record["executable"] = path.is_file() and os.access(path, os.X_OK)
    except OSError:
        pass
    return record


S6_ENV_DIR = Path("/run/s6/container_environment")
FALLBACK_VERAPDF_PATHS = (
    Path("/opt/verapdf-greenfield/verapdf"),
    Path("/opt/verapdf/verapdf"),
)


def _read_s6_env_value(name: str) -> Optional[str]:
    path = S6_ENV_DIR / name
    try:
        if path.exists() and path.is_file():
            value = path.read_text(encoding="utf-8", errors="replace").strip()
            return value or None
    except OSError:
        return None
    return None


def _first_available(checked: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for record in checked:
        if record.get("exists") and record.get("is_file") and record.get("executable"):
            return record
    return None


def resolve_verapdf_runner(env: Mapping[str, str] | None = None) -> Dict[str, Any]:
    """Resolve the canonical veraPDF runner with auditable diagnostics.

    Docker may expose veraPDF through container environment files or fixed paths
    rather than PATH. This resolver records every candidate it considered and
    only returns available=True for an existing executable file.
    """
    env_map: Mapping[str, str] = os.environ if env is None else env
    checked: List[Dict[str, Any]] = []

    for name in ("VERAPDF_GREENFIELD_BIN", "VERAPDF_ARLINGTON_BIN"):
        checked.append(_candidate_record(name, env_map.get(name)))

    for name in ("VERAPDF_GREENFIELD_BIN", "VERAPDF_ARLINGTON_BIN"):
        checked.append(_candidate_record(f"s6:{name}", _read_s6_env_value(name)))

    for path in FALLBACK_VERAPDF_PATHS:
        checked.append(_candidate_record(f"fallback:{path}", str(path)))

    for binary in ("verapdf", "veraPDF"):
        checked.append(_candidate_record(f"PATH:{binary}", shutil.which(binary)))

    selected = _first_available(checked)
    if selected:
        return {
            "available": True,
            "runner_path": selected.get("value"),
            "runner_source": selected.get("source"),
            "checked": checked,
        }
    return {
        "available": False,
        "readiness_blocker": "verapdf_runner_unavailable",
        "checked": checked,
    }


def _run_verapdf(verapdf_bin: str, pdf: Path, stem: str, trial_dir: Path, timeout_seconds: int) -> Tuple[str, Dict[str, str]]:
    xml_path = trial_dir / f"{stem}.xml"
    stdout_path = trial_dir / f"{stem}.stdout.txt"
    stderr_path = trial_dir / f"{stem}.stderr.txt"
    cmd = [verapdf_bin, "--format", "xml", str(pdf)]
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout_seconds or 120)),
    )
    stdout = cp.stdout or ""
    stderr = cp.stderr or ""
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    xml_text = stdout.strip()
    if xml_text:
        xml_path.write_text(xml_text, encoding="utf-8", errors="replace")
    return xml_text, {
        "xml": str(xml_path),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "returncode": str(cp.returncode),
    }


def _base_payload(trial_dir: Path, normal_final_pdf: Path, learned_trial_pdf: Path) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "check_name": CHECK_NAME,
        "performed": False,
        "normal_final_pdf": str(normal_final_pdf),
        "learned_trial_pdf": str(learned_trial_pdf),
        "trial_dir": str(trial_dir),
        "policy": {
            "diagnostic_sidecar_only": True,
            "normal_final_pdf_remains_authoritative": True,
            "candidate_is_adoptable": False,
            "final_pdf_adoption_performed": False,
            "production_repair_replacement_performed": False,
            "verdict_softening_performed": False,
            "rule_map_mutation_performed": False,
            "app_tools_repair_mutation_performed": False,
        },
    }


def _finish(trial_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    delta_path = trial_dir / "verapdf_delta.json"
    payload.setdefault("artifacts", {})["delta"] = str(delta_path)
    write_json_atomic(delta_path, payload)
    return payload


def run_verapdf_delta_for_trial(
    normal_final_pdf: Path,
    learned_trial_pdf: Path,
    trial_dir: Path,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Run bounded veraPDF normal-vs-learned delta evidence for one trial."""
    normal_final_pdf = Path(normal_final_pdf)
    learned_trial_pdf = Path(learned_trial_pdf)
    trial_dir = Path(trial_dir)
    trial_dir.mkdir(parents=True, exist_ok=True)
    payload = _base_payload(trial_dir, normal_final_pdf, learned_trial_pdf)

    runner_discovery = resolve_verapdf_runner()
    runner_discovery_path = trial_dir / "verapdf_runner_discovery.json"
    write_json_atomic(runner_discovery_path, runner_discovery)
    payload["runner_discovery"] = runner_discovery
    payload["runner_discovery_artifact"] = str(runner_discovery_path)
    payload.setdefault("artifacts", {})["runner_discovery"] = str(runner_discovery_path)
    if runner_discovery.get("available"):
        payload["runner_path"] = runner_discovery.get("runner_path")
        payload["runner_source"] = runner_discovery.get("runner_source")

    if not normal_final_pdf.exists() or not learned_trial_pdf.exists():
        payload.update(
            {
                "result": "SKIPPED",
                "reason": "input_pdf_unavailable",
                "readiness_blocker": "verapdf_input_pdf_unavailable",
            }
        )
        return _finish(trial_dir, payload)

    if not runner_discovery.get("available"):
        payload.update(
            {
                "result": "SKIPPED",
                "reason": "verapdf_runner_unavailable",
                "readiness_blocker": "verapdf_runner_unavailable",
                "blockers": ["verapdf_runner_unavailable"],
            }
        )
        return _finish(trial_dir, payload)

    verapdf_bin = str(runner_discovery.get("runner_path") or "")
    artifacts: Dict[str, Any] = dict(payload.get("artifacts") or {})
    try:
        normal_xml, normal_artifacts = _run_verapdf(
            verapdf_bin, normal_final_pdf, "verapdf_normal_final", trial_dir, timeout_seconds
        )
        learned_xml, learned_artifacts = _run_verapdf(
            verapdf_bin, learned_trial_pdf, "verapdf_learned_trial", trial_dir, timeout_seconds
        )
        artifacts["normal_verapdf"] = normal_artifacts
        artifacts["learned_verapdf"] = learned_artifacts
    except subprocess.TimeoutExpired as exc:
        payload.update(
            {
                "performed": True,
                "result": "ERROR",
                "reason": "verapdf_command_timeout",
                "readiness_blocker": "verapdf_delta_timeout",
                "error": str(exc),
                "artifacts": artifacts,
            }
        )
        return _finish(trial_dir, payload)
    except Exception as exc:
        payload.update(
            {
                "performed": True,
                "result": "ERROR",
                "reason": "verapdf_process_failed",
                "readiness_blocker": "verapdf_process_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "artifacts": artifacts,
            }
        )
        return _finish(trial_dir, payload)

    if not normal_xml or not learned_xml:
        payload.update(
            {
                "performed": True,
                "result": "ERROR",
                "reason": "verapdf_output_missing",
                "readiness_blocker": "verapdf_output_missing",
                "artifacts": artifacts,
            }
        )
        return _finish(trial_dir, payload)

    try:
        normal_records = parse_verapdf_failures(normal_xml)
        learned_records = parse_verapdf_failures(learned_xml)
    except Exception as exc:
        payload.update(
            {
                "performed": True,
                "result": "ERROR",
                "reason": "verapdf_parse_failed",
                "readiness_blocker": "verapdf_delta_parse_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "artifacts": artifacts,
            }
        )
        return _finish(trial_dir, payload)

    delta = compute_verapdf_delta(normal_records, learned_records)
    regression = bool(delta["introduced_rules"] or delta["worsened_rules"])
    payload.update(delta)
    payload.update(
        {
            "performed": True,
            "result": "FAIL" if regression else "PASS",
            "readiness_blocker": "verapdf_delta_regression_detected" if regression else None,
            "blockers": ["verapdf_delta_regression_detected"] if regression else [],
            "artifacts": artifacts,
        }
    )
    return _finish(trial_dir, payload)
