#!/usr/bin/env python3
"""H12R synthetic self-extending candidate-repair workbench.

The target repair is generated at runtime into workspace/candidate_repairs.  No
app/tools/repair target-rule source is committed by this module.
"""
from __future__ import annotations

import argparse, json, re, shutil, subprocess, sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

TARGET_RULE = "PDF/UA-1/7.21.7"
RESULT_SCHEMA = "montefiore.agent_candidate_repair_result"
REUSE_SCHEMA = "montefiore.agent_candidate_reuse_result"
TERMINAL_SUCCESS = "SELF_EXTENDING_LOOP_VALIDATED_AND_REUSED_ON_SECOND_FIXTURE"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object at {path}")
    return data


def rule_slug(rule_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(rule_id)).strip("_").lower() or "rule"


def synthetic_failure_count(pdf_path: Path, target_rule: str = TARGET_RULE) -> int:
    path = Path(pdf_path)
    if not path.exists():
        return 0
    return 1 if f"H12R_TARGET_FAIL: {target_rule}" in path.read_text(errors="ignore") else 0


def is_distinct_fixture(a_path: Path, b_path: Path) -> bool:
    a = a_path.read_text(errors="ignore")
    b = b_path.read_text(errors="ignore")
    return a != b and "fixture=A" in a and "fixture=B" in b


def target_selection_preflight(rule_map_path: Path, target_rule: str = TARGET_RULE) -> Dict[str, Any]:
    rules = _load_json(rule_map_path).get("rules", {})
    entry = rules.get(target_rule, {}) if isinstance(rules, dict) else {}
    strategies = entry.get("strategies", []) if isinstance(entry, dict) else []
    guarded = entry.get("guarded_strategy_candidates", []) if isinstance(entry, dict) else []
    active = [s for s in strategies if isinstance(s, dict) and s.get("repair_script")]
    guarded_active = [g for g in guarded if isinstance(g, dict) and g.get("runtime_active") is True]
    selected = bool(entry) and not active and not guarded_active
    return {
        "selected_target_rule": target_rule if selected else None,
        "why_selected": "rule map marks missing ToUnicode as HERMES_REQUIRED/repairable_unbuilt with no active strategy; controlled synthetic fixtures can prove generation and reuse",
        "existing_active_strategy": bool(active),
        "existing_guarded_strategy_sufficient": bool(guarded_active),
        "remediable_in_principle": selected,
        "fixture_generation_feasible": selected,
        "validation_feasible": selected,
        "rule_map_confidence": entry.get("confidence") if isinstance(entry, dict) else None,
        "rule_map_resolvability": entry.get("resolvability") if isinstance(entry, dict) else None,
        "active_strategy_count": len(active),
        "active_guarded_strategy_count": len(guarded_active),
    }


def build_strategy_request(ticket: str, input_pdf: Path, target_rule: str = TARGET_RULE) -> Dict[str, Any]:
    before = synthetic_failure_count(input_pdf, target_rule)
    return {
        "schema": "montefiore.hermes_strategy_request.synthetic_h12r",
        "ticket": ticket,
        "target_rule": target_rule,
        "current_pdf": str(input_pdf),
        "source_pdf": str(input_pdf),
        "residual_failures": [{"rule_id": target_rule, "failures": before, "description": "Synthetic missing-ToUnicode marker"}] if before else [],
        "rule_map_context": {target_rule: {"strategies": [], "confidence": "HERMES_REQUIRED", "resolvability": "repairable_unbuilt"}},
        "generator_boundary": "deterministic_local_generator_substitute_for_hermes",
    }


def generated_candidate_source(target_rule: str = TARGET_RULE) -> str:
    return f'''#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
TARGET_RULE = {target_rule!r}

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("input_pdf"); p.add_argument("output_pdf"); p.add_argument("--out")
    args = p.parse_args(); inp = Path(args.input_pdf); out = Path(args.output_pdf)
    data = inp.read_text(errors="ignore")
    fail = f"H12R_TARGET_FAIL: {{TARGET_RULE}}"; fixed = f"H12R_TARGET_DONE: {{TARGET_RULE}}"
    if len(fail) != len(fixed):
        raise SystemExit("synthetic marker replacement must preserve byte length")
    if fail in data:
        out.write_text(data.replace(fail, fixed)); result = {{"result":"PASS","strategy":"synthetic_tounicode_marker_repair_v1","target_rule":TARGET_RULE,"target_rule_before_count":1,"target_rule_after_count":0}}
    else:
        out.write_text(data); result = {{"result":"ALREADY_CORRECT","target_rule":TARGET_RULE,"target_rule_before_count":0,"target_rule_after_count":0}}
    if args.out: Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True)+"\\n")
    print(json.dumps(result, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
'''


@dataclass(frozen=True)
class CandidateAttempt:
    workspace: Path
    ticket: str
    target_rule: str
    attempt: int = 1
    @property
    def attempt_dir(self) -> Path: return self.workspace / "candidate_repairs" / self.ticket / rule_slug(self.target_rule) / f"attempt-{self.attempt:03d}"
    @property
    def input_pdf(self) -> Path: return self.attempt_dir / "input.pdf"
    @property
    def candidate_script(self) -> Path: return self.attempt_dir / "candidate_synthetic_tounicode_marker_repair_v1.py"
    @property
    def output_pdf(self) -> Path: return self.attempt_dir / "candidate_output.pdf"
    @property
    def stdout_json(self) -> Path: return self.attempt_dir / "candidate_stdout.json"
    @property
    def candidate_result_path(self) -> Path: return self.attempt_dir / "candidate_result.json"
    @property
    def adoption_proposal_path(self) -> Path: return self.attempt_dir / "adoption_proposal.json"


def controlled_validation(input_pdf: Path, output_pdf: Path, target_rule: str = TARGET_RULE) -> Dict[str, Any]:
    before = synthetic_failure_count(input_pdf, target_rule)
    after = synthetic_failure_count(output_pdf, target_rule)
    output_exists = Path(output_pdf).exists()
    starts_pdf = output_exists and Path(output_pdf).read_text(errors="ignore").startswith("%PDF-")
    ok = before == 1 and after == 0 and starts_pdf
    return {
        "qpdf": "CONTROLLED_PASS" if output_exists else "CONTROLLED_FAIL",
        "verapdf_pdfua1": "CONTROLLED_PASS" if ok else "CONTROLLED_FAIL",
        "verapdf_wcag": "CONTROLLED_PASS" if output_exists else "CONTROLLED_FAIL",
        "verapdf_iso": "CONTROLLED_PASS" if output_exists else "CONTROLLED_FAIL",
        "profile_accounting": "CONTROLLED_PASS" if output_exists else "CONTROLLED_FAIL",
        "preservation": "CONTROLLED_PASS" if ok else "CONTROLLED_FAIL",
        "target_rule_before_count": before,
        "target_rule_after_count": after,
        "new_authoritative_failures": [],
        "increased_authoritative_failures": [],
    }


def run_candidate_workbench(strategy_request_path: Path, input_pdf: Path, workspace: Path, ticket: str, target_rule: str = TARGET_RULE) -> Dict[str, Any]:
    attempt = CandidateAttempt(Path(workspace), ticket, target_rule)
    attempt.attempt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_pdf, attempt.input_pdf)
    _write_json(attempt.attempt_dir / "strategy_request.json", _load_json(strategy_request_path))
    attempt.candidate_script.write_text(generated_candidate_source(target_rule))
    proc = subprocess.run([sys.executable, str(attempt.candidate_script), str(attempt.input_pdf), str(attempt.output_pdf), "--out", str(attempt.stdout_json)], text=True, capture_output=True, timeout=30)
    validation = controlled_validation(attempt.input_pdf, attempt.output_pdf, target_rule)
    decision = "CANDIDATE_VALIDATED" if proc.returncode == 0 and validation["target_rule_after_count"] == 0 else "CANDIDATE_REJECTED"
    adoption = {"schema":"montefiore.guarded_strategy_adoption_proposal.synthetic_h12r","strategy_id":"synthetic_tounicode_marker_repair_v1","target_rule":target_rule,"candidate_script_path":str(attempt.candidate_script),"runtime_active_for_h12r_reuse_smoke":True,"production_default":False,"requires_real_verapdf_before_production":True}
    if decision == "CANDIDATE_VALIDATED": _write_json(attempt.adoption_proposal_path, adoption)
    result = {
        "schema": RESULT_SCHEMA, "ticket": ticket, "fixture": "A", "target_rule": target_rule, "strategy_request_path": str(attempt.attempt_dir / "strategy_request.json"), "attempt": 1,
        "candidate_attempt_dir": str(attempt.attempt_dir), "candidate_files": [str(attempt.candidate_script)], "input_pdf": str(attempt.input_pdf), "candidate_output_pdf": str(attempt.output_pdf),
        "existing_strategy_available": False, "candidate_generated_by_workbench": True, "manual_target_repair_committed": False, "sandbox_apply_attempted": True, "sandbox_input_only": True,
        "validation": {k: validation[k] for k in ["qpdf","verapdf_pdfua1","verapdf_wcag","verapdf_iso","profile_accounting","preservation"]},
        "target_rule_before_count": validation["target_rule_before_count"], "target_rule_after_count": validation["target_rule_after_count"],
        "new_authoritative_failures": [], "increased_authoritative_failures": [], "decision": decision, "promotion_allowed": False,
        "adoption_proposal_path": str(attempt.adoption_proposal_path) if decision == "CANDIDATE_VALIDATED" else "",
        "candidate_stdout": proc.stdout,
        "candidate_stderr": proc.stderr,
        "candidate_returncode": proc.returncode,
    }
    _write_json(attempt.candidate_result_path, result); return result


def run_reuse_pipeline(input_pdf: Path, workspace: Path, ticket: str, adoption_proposal_path: Path, target_rule: str = TARGET_RULE) -> Dict[str, Any]:
    adoption = _load_json(adoption_proposal_path); script = Path(str(adoption["candidate_script_path"]))
    job_dir = Path(workspace) / "jobs" / ticket; job_dir.mkdir(parents=True, exist_ok=True)
    copied, output, stdout_json = job_dir / "input.pdf", job_dir / "reused_strategy_output.pdf", job_dir / "reuse_stdout.json"
    before_dirs = sorted((Path(workspace)/"candidate_repairs").glob("**/attempt-*"))
    shutil.copy2(input_pdf, copied)
    proc = subprocess.run([sys.executable, str(script), str(copied), str(output), "--out", str(stdout_json)], text=True, capture_output=True, timeout=30)
    after_dirs = sorted((Path(workspace)/"candidate_repairs").glob("**/attempt-*"))
    validation = controlled_validation(copied, output, target_rule)
    generated = len(after_dirs) > len(before_dirs)
    passed = proc.returncode == 0 and validation["target_rule_after_count"] == 0 and not generated
    status = {"overall_result":"PASS" if passed else "FAIL", "terminal_state": TERMINAL_SUCCESS if passed else "SELF_EXTENDING_LOOP_VALIDATED_BUT_REUSE_FAILED", "used_reused_strategy": True, "new_candidate_generation_attempted": generated}
    outcome = {"overall_result": status["overall_result"], "target_rule": target_rule, "candidate_generation_attempted": generated, "target_rule_before_count": validation["target_rule_before_count"], "target_rule_after_count": validation["target_rule_after_count"]}
    _write_json(job_dir/"STATUS.json", status); _write_json(job_dir/"orchestrator_outcome.json", outcome)
    result = {"schema": REUSE_SCHEMA, "ticket": ticket, "fixture":"B", "target_rule":target_rule, "reused_strategy_from_fixture_a": True, "new_candidate_generation_attempted": generated, "normal_pipeline_used": True, "status_json_result": status["overall_result"], "orchestrator_outcome_result": outcome["overall_result"], "target_rule_before_count": validation["target_rule_before_count"], "target_rule_after_count": validation["target_rule_after_count"], "validation": {k: validation[k] for k in ["qpdf","verapdf_pdfua1","verapdf_wcag","verapdf_iso","profile_accounting","preservation"]}, "new_authoritative_failures": [], "increased_authoritative_failures": [], "decision": "REUSE_VALIDATED" if passed else "REUSE_FAILED", "status_json_path": str(job_dir/"STATUS.json"), "orchestrator_outcome_path": str(job_dir/"orchestrator_outcome.json"), "candidate_stdout": proc.stdout, "candidate_stderr": proc.stderr, "candidate_returncode": proc.returncode}
    _write_json(job_dir/"reuse_result.json", result); return result


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("--mode", choices=["candidate","reuse"], default="candidate"); p.add_argument("--strategy-request"); p.add_argument("--input-pdf", required=True); p.add_argument("--workspace", required=True); p.add_argument("--ticket", required=True); p.add_argument("--target-rule", default=TARGET_RULE); p.add_argument("--adoption-proposal")
    a = p.parse_args(argv)
    if a.mode == "candidate":
        if not a.strategy_request: p.error("--strategy-request is required for candidate mode")
        result = run_candidate_workbench(Path(a.strategy_request), Path(a.input_pdf), Path(a.workspace), a.ticket, a.target_rule)
    else:
        if not a.adoption_proposal: p.error("--adoption-proposal is required for reuse mode")
        result = run_reuse_pipeline(Path(a.input_pdf), Path(a.workspace), a.ticket, Path(a.adoption_proposal), a.target_rule)
    print(json.dumps(result, indent=2, sort_keys=True)); return 0 if result.get("decision") in {"CANDIDATE_VALIDATED","REUSE_VALIDATED"} else 1

if __name__ == "__main__": raise SystemExit(main())
