#!/usr/bin/env python3
"""status_json_writer.py

Assembles STATUS.json for a remediation job. The orchestrator outcome remains
authoritative when present; otherwise the shared verdict on verdict_input.json
is used, followed by the legacy gate sidecar scan. Patch 5 adds residual and
strategy-indexing references without changing the CLI contract. H10I adds a
fail-closed guarded acceptance overlay so STATUS.json cannot claim PASS when a
guarded intermediate candidate is only review-required or rejected.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.lib.gates import GATE_REGISTRY, canonicalize_gate_key
from tools.lib.verdict import VerdictInput, verdict
from tools.lib.residual_verdict import summarize_residual_analysis, summarize_strategy_indexing
from tools.orchestrate.guarded_acceptance import status_fragment


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir")
    parser.add_argument("--pdf", default="", help="Source PDF path for reference")
    parser.add_argument("--out", default="STATUS.json", help="Output filename")
    return parser


def _load_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _vi_from_raw(raw: dict, residual: dict, strategy: dict) -> VerdictInput:
    return VerdictInput.from_gate_dict(
        raw.get("gates", {}),
        hermes_signals_count=int(raw.get("hermes_signals_count", 0) or 0),
        deviations_count=int(raw.get("deviations_count", 0) or 0),
        total_iterations=int(raw.get("total_iterations", 0) or 0),
        job_hard_cap=int(raw.get("job_hard_cap", 50) or 50),
        has_hard_cap_exceeded=bool(raw.get("has_hard_cap_exceeded", False)),
        experimental_profile_failures=raw.get("experimental_profile_failures", []),
        pending_review_rules=raw.get("pending_review_rules", residual.get("pending_review_rules", [])),
        residual_analysis=residual,
        strategy_indexing=strategy,
        targetable_residual_rules=raw.get("targetable_residual_rules", residual.get("targetable_residual_rules", [])),
        non_targetable_residual_rules=raw.get("non_targetable_residual_rules", residual.get("non_targetable_residual_rules", [])),
        introduced_rules=raw.get("introduced_rules", residual.get("introduced_rules", [])),
        partially_resolved_rules=raw.get("partially_resolved_rules", residual.get("partially_resolved_rules", [])),
        transport_blocked=bool(raw.get("transport_blocked", False)),
    )


def _guarded_decision_from(outcome: dict, audit_dir: Path) -> dict | None:
    for candidate in (
        outcome.get("guarded_acceptance") if isinstance(outcome, dict) else None,
        outcome.get("guarded_acceptance_result") if isinstance(outcome, dict) else None,
    ):
        if isinstance(candidate, dict):
            return candidate
    sidecar = audit_dir / "guarded_acceptance.json"
    data = _load_json(sidecar)
    return data if isinstance(data, dict) else None


def _guarded_status_result(decision: dict) -> str:
    status_result = str(decision.get("status_result") or "UNKNOWN")
    if status_result == "PASS" and not bool(decision.get("pass_allowed")):
        return "REVIEW_REQUIRED"
    return status_result


def _run(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir)
    audit_dir = job_dir / "audit"
    outcome_path = audit_dir / "orchestrator_outcome.json"
    verdict_input_path = audit_dir / "verdict_input.json"

    residual = summarize_residual_analysis(job_dir)
    strategy = summarize_strategy_indexing(job_dir)
    status: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pdf": args.pdf,
        "job_dir": str(job_dir),
        "overall_result": "UNKNOWN",
        "result": "UNKNOWN",
        "gates": {},
        "verdict_result_source": "none",
        "residual_analysis": residual,
        "strategy_indexing": strategy,
    }

    verdict_result = None
    authoritative_overall = None
    verdict_result_source = "none"
    collected: dict[str, object] = {}
    outcome = None
    guarded_decision = None

    if outcome_path.exists():
        outcome = _load_json(outcome_path) or {}
        authoritative_overall = outcome.get("overall_result", "UNKNOWN")
        status["orchestrator_outcome"] = outcome
        verdict_result_source = "orchestrator_outcome.json"
        guarded_decision = _guarded_decision_from(outcome, audit_dir)
    else:
        guarded_decision = _guarded_decision_from({}, audit_dir)

    if verdict_input_path.exists():
        try:
            raw = _load_json(verdict_input_path) or {}
            residual = raw.get("residual_analysis") or residual
            strategy = raw.get("strategy_indexing") or strategy
            verdict_result = verdict(_vi_from_raw(raw, residual, strategy))
            if authoritative_overall is None:
                authoritative_overall = verdict_result.overall
                verdict_result_source = "shared_verdict_on_verdict_input.json"
        except Exception as exc:
            status["verdict_input_error"] = str(exc)

    if authoritative_overall is None and verdict_result is None:
        for gate_name, gate_def in GATE_REGISTRY.items():
            found = False
            for candidate in gate_def.sidecar_paths(job_dir):
                data = _load_json(candidate)
                if data:
                    collected[str(gate_name)] = {"result": data.get("result", "UNKNOWN"), "source": str(candidate.relative_to(job_dir))}
                    found = True
                    break
            if found:
                continue
            for alias in (gate_def.legacy_aliases + (str(gate_name),)):
                candidate = job_dir / f"{alias}.json"
                if candidate.exists():
                    data = _load_json(candidate)
                    if data:
                        collected[str(gate_name)] = {"result": data.get("result", "UNKNOWN"), "source": str(candidate.relative_to(job_dir))}
                        break

        for scan_dir in (job_dir, job_dir / "audit", job_dir / "repair", job_dir / "qa", job_dir / "reports"):
            if not scan_dir.exists():
                continue
            for json_file in sorted(scan_dir.glob("*.json")):
                if json_file.name == args.out:
                    continue
                stem = json_file.stem
                try:
                    canonical_stem = str(canonicalize_gate_key(stem))
                    is_known = True
                except KeyError:
                    canonical_stem = None
                    is_known = False
                if is_known and canonical_stem and canonical_stem in collected:
                    continue
                data = _load_json(json_file)
                if data and "result" in data and canonical_stem:
                    collected.setdefault(canonical_stem, {"result": data.get("result", "UNKNOWN"), "source": str(json_file.relative_to(job_dir))})

        if collected:
            verdict_result = verdict(VerdictInput.from_gate_dict(collected, residual_analysis=residual, strategy_indexing=strategy))
            authoritative_overall = verdict_result.overall
            verdict_result_source = "shared_verdict_legacy_scan"

    if authoritative_overall is None:
        authoritative_overall = "NO_RESULTS"

    if guarded_decision:
        guarded_result = _guarded_status_result(guarded_decision)
        status.update(status_fragment(guarded_decision))
        if authoritative_overall == "PASS" and guarded_result != "PASS":
            status["guarded_acceptance_overrode_pass"] = {
                "from": authoritative_overall,
                "to": guarded_result,
                "reason": "guarded_acceptance_pass_not_allowed",
            }
            authoritative_overall = guarded_result
        if guarded_result in ("FAIL", "ESCALATION"):
            authoritative_overall = guarded_result
        elif guarded_result == "REVIEW_REQUIRED" and authoritative_overall == "PASS":
            authoritative_overall = "REVIEW_REQUIRED"

    status["overall_result"] = authoritative_overall
    status["result"] = authoritative_overall
    status["verdict_result_source"] = verdict_result_source
    status["residual_analysis"] = residual
    status["strategy_indexing"] = strategy

    if verdict_result is not None:
        status["gates"] = {str(g): {"result": r.value, "source": r.source} for g, r in verdict_result.input_gates.items()}
        status["verdict"] = verdict_result.as_dict()
    elif collected:
        status["gates"] = collected
        status["verdict"] = {}
    else:
        status["gates"] = {}
        status["verdict"] = {}

    if outcome_path.exists() and verdict_result is not None:
        try:
            outcome = outcome or (_load_json(outcome_path) or {})
            oo = outcome.get("overall_result")
            embedded = (outcome.get("verdict") or {}).get("overall") if isinstance(outcome.get("verdict"), dict) else None
            recomputed = verdict_result.overall
            consistent = (
                oo == recomputed
                or (embedded is not None and embedded == recomputed)
                or (oo == "ESCALATION" and recomputed == "FAIL" and bool(outcome.get("escalation_upgrade")))
            )
            if oo and not consistent:
                status["verdict_mismatch"] = {
                    "orchestrator_outcome": oo,
                    "shared_verdict": recomputed,
                    "note": "STATUS.json uses orchestrator_outcome.json as authoritative",
                }
        except Exception:
            pass

    out_path = job_dir / args.out
    out_path.write_text(json.dumps(status, indent=2, sort_keys=True))
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["overall_result"] in ("PASS", "REVIEW_REQUIRED") else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not Path(args.job_dir).exists():
        print(json.dumps({"result": "ERROR", "error": f"Job dir not found: {args.job_dir}"}))
        sys.exit(2)
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
