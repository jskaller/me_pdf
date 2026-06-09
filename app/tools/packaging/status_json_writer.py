#!/usr/bin/env python3
"""
status_json_writer.py
Assembles a STATUS.json for a remediation job.

M1 canonicalisation:
- Authoritative result is the orchestrator's orchestrator_outcome.json.
- If that is absent, the shared verdict() is run on verdict_input.json.
- If that is also absent, fall back to a legacy scan of known gate files
  using the canonical GateName registry in tools/lib/gates.py.
- STATUS.json must never disagree silently with orchestrator_outcome.json.
"""
import sys, json
from pathlib import Path
from datetime import datetime, timezone
import argparse

from tools.lib.gates import (
 GATE_REGISTRY,
 canonicalize_gate_key,
)
from tools.lib.verdict import VerdictInput, verdict


def _build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("job_dir")
    p.add_argument("--pdf", default="", help="Source PDF path for reference")
    p.add_argument("--out", default="STATUS.json", help="Output filename")
    return p


def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _run(args):
    job_dir = Path(args.job_dir)
    audit_dir = job_dir / "audit"
    outcome_path = audit_dir / "orchestrator_outcome.json"
    verdict_input_path = audit_dir / "verdict_input.json"

    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pdf": args.pdf,
        "job_dir": str(job_dir),
        "overall_result": "UNKNOWN",
        "gates": {},
        "verdict_result_source": "none",
    }

    verdict_result_source = "none"
    verdict_result = None
    authoritative_overall = None
    collected = {}

    # P1: orchestrator_outcome.json is authoritative
    if outcome_path.exists():
        try:
            outcome = _load_json(outcome_path) or {}
            authoritative_overall = outcome.get("overall_result", "UNKNOWN")
            status["orchestrator_outcome"] = outcome
            verdict_result_source = "orchestrator_outcome.json"
        except Exception:
            pass

    # P2: shared verdict on verdict_input.json.
    # If orchestrator_outcome.json exists, it is authoritative; do not compute
    # a second overall verdict that can conflict with the orchestrator's final
    # compliance decision. STATUS.json may still include collected gates, but
    # the overall result comes from orchestrator_outcome.json.
    if authoritative_overall is None and verdict_result is None and verdict_input_path.exists():
        try:
            raw = _load_json(verdict_input_path) or {}
            vi = VerdictInput.from_gate_dict(
                raw.get("gates", {}),
                hermes_signals_count=raw.get("hermes_signals_count", 0),
                deviations_count=raw.get("deviations_count", 0),
                total_iterations=raw.get("total_iterations", 0),
                job_hard_cap=raw.get("job_hard_cap", 50),
                experimental_profile_failures=raw.get("experimental_profile_failures", []),
            )
            verdict_result = verdict(vi)
            if authoritative_overall is None:
                authoritative_overall = verdict_result.overall
            verdict_result_source = "shared_verdict_on_verdict_input.json"
        except Exception:
            pass

    # P3: legacy scan using canonical gate registry.
    # Only derive a legacy verdict when no authoritative orchestrator outcome
    # exists. This avoids stale pre-repair sidecars causing a verdict_mismatch.
    if authoritative_overall is None and verdict_result is None:
        for gate_name, gate_def in GATE_REGISTRY.items():
            found = False
            for candidate in gate_def.sidecar_paths(job_dir):
                data = _load_json(candidate)
                if data:
                    collected[str(gate_name)] = {
                        "result": data.get("result", "UNKNOWN"),
                        "source": str(candidate.relative_to(job_dir)),
                    }
                    found = True
                    break
            if found:
                continue
            for alias in (gate_def.legacy_aliases + (str(gate_name),)):
                candidate = job_dir / f"{alias}.json"
                if candidate.exists():
                    data = _load_json(candidate)
                    if data:
                        collected[str(gate_name)] = {
                            "result": data.get("result", "UNKNOWN"),
                            "source": str(candidate.relative_to(job_dir)),
                        }
                        break

        for scan_dir in (job_dir, job_dir / "audit", job_dir / "repair",
                         job_dir / "qa", job_dir / "reports"):
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
                if data and "result" in data:
                    collected.setdefault(canonical_stem, {
                        "result": data.get("result", "UNKNOWN"),
                        "source": str(json_file.relative_to(job_dir)),
                    })

        if collected:
            vi = VerdictInput.from_gate_dict(collected)
            verdict_result = verdict(vi)
            if authoritative_overall is None:
                authoritative_overall = verdict_result.overall
            verdict_result_source = "shared_verdict_legacy_scan"

    if authoritative_overall is None:
        authoritative_overall = "NO_RESULTS"

    status["overall_result"] = authoritative_overall
    status["verdict_result_source"] = verdict_result_source

    if verdict_result is not None:
        status["gates"] = {
            str(g): {"result": r.value, "source": r.source}
            for g, r in verdict_result.input_gates.items()
        }
    elif collected:
        status["gates"] = collected
    else:
        status["gates"] = {}

    status["verdict"] = verdict_result.as_dict() if verdict_result else {}

    # Reconciliation check
    if outcome_path.exists() and verdict_result is not None:
        try:
            outcome = _load_json(outcome_path) or {}
            oo = outcome.get("overall_result")
            if oo and oo != verdict_result.overall:
                status["verdict_mismatch"] = {
                    "orchestrator_outcome": oo,
                    "shared_verdict": verdict_result.overall,
                    "note": "STATUS.json uses orchestrator_outcome.json as authoritative",
                }
        except Exception:
            pass

    out_path = job_dir / args.out
    out_path.write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2))
    return 0 if status["overall_result"] in ("PASS", "REVIEW_REQUIRED") else 1


def main():
    parser = _build_parser()
    args = parser.parse_args()
    if not Path(args.job_dir).exists():
        print(json.dumps({"result": "ERROR", "error": f"Job dir not found: {args.job_dir}"}))
        sys.exit(2)
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
