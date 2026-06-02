#!/usr/bin/env python3
"""
tools/lib/verdict.py — Shared verdict computation.

Both remediate.py and status_json_writer.py call verdict() so they cannot
disagree silently on PASS/REVIEW_REQUIRED/FAIL/ESCALATION.

M1 policy:
 - Compliance gates (verapdf_pdfua1, verapdf_wcag, metadata_parity,
   preservation) hard-fail the job when FAIL.
 - Informational gates (verapdf_iso, verapdf_pdfua2, verapdf_baseline,
   parse_summary, repair_plan) become review flags only; they never drive FAIL.
 - Other QA/audit non-PASS results route to REVIEW_REQUIRED unless
   orchestrator_outcome.json is already authoritative.

Callers MUST pass a VerdictInput populated from artifacts on disk, not
re-derive gate values independently. See RESIDUAL_AND_CAPTURE_CONTRACT.md
for the design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from tools.lib.gates import (
    GateName,
    canonicalize_gate_key,
    is_compliance_gate,
    is_informational_gate,
)


@dataclass(frozen=True)
class GateResult:
    gate: GateName
    value: str
    source: str = ""


@dataclass(frozen=True)
class VerdictInput:
    gates: dict[GateName, GateResult] = field(default_factory=dict)
    hermes_signals_count: int = 0
    deviations_count: int = 0
    total_iterations: int = 0
    job_hard_cap: int = 50
    has_hard_cap_exceeded: bool = False
    experimental_profile_failures: Sequence[str] = field(default_factory=list)
    # Future: residual analysis outcomes will drive REVIEW_REQUIRED for
    # repairable_review rules. Not wired yet; M1 ignores this field.
    pending_review_rules: Sequence[str] = field(default_factory=list)

    @classmethod
    def from_gate_dict(cls, raw: dict[str, object], **kwargs) -> VerdictInput:
        gates: dict[GateName, GateResult] = {}
        for key, value in raw.items():
            try:
                gate = canonicalize_gate_key(key)
            except KeyError:
                continue
            gates[gate] = GateResult(
                gate=gate,
                value=str(value.get("result", value) if isinstance(value, dict) else value),
                source=value.get("source", "") if isinstance(value, dict) else "",
            )
        return cls(gates=gates, **kwargs)

    @classmethod
    def from_remediate_state(
        cls,
        gate_results: dict[str, str],
        hermes_signals: list[dict],
        deviations: list[dict],
        total_iterations: int,
        job_hard_cap: int = 50,
        experimental_profile_failures: Sequence[str] | None = None,
    ) -> VerdictInput:
        canonical_raw: dict[str, object] = {}
        for k, v in gate_results.items():
            try:
                gate = canonicalize_gate_key(k)
                canonical_raw[str(gate)] = {"result": v, "source": "orchestrator"}
            except KeyError:
                canonical_raw[k] = {"result": v, "source": "orchestrator"}
        return cls(
            gates=cls.from_gate_dict(canonical_raw).gates,
            hermes_signals_count=len(hermes_signals),
            deviations_count=len(deviations),
            total_iterations=total_iterations,
            job_hard_cap=job_hard_cap,
            experimental_profile_failures=experimental_profile_failures or [],
        )


@dataclass(frozen=True)
class VerdictResult:
    overall: str  # PASS | REVIEW_REQUIRED | FAIL | ESCALATION
    critical_fails: List[GateName]
    blocking_qa: List[GateName]
    informational_flags: List[GateName]
    reasons: List[str]
    source: str = "shared_verdict"
    # Echo of the input gate dict so writers can populate STATUS.json gates{}
    # without re-deriving from artifacts on disk.
    input_gates: dict[GateName, GateResult] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "critical_fails": [str(g) for g in self.critical_fails],
            "blocking_qa": [str(g) for g in self.blocking_qa],
            "informational_flags": [str(g) for g in self.informational_flags],
            "reasons": self.reasons,
            "source": self.source,
            "input_gates": {
                str(g): {"result": r.value, "source": r.source}
                for g, r in self.input_gates.items()
            },
        }


# Outcome strings (authoritative vocabulary).
PASS = "PASS"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
FAIL = "FAIL"
ESCALATION = "ESCALATION"


def _normalize(gate: GateName, value: str) -> str:
    return "PASS" if value.upper() in {
        "PASS", "FIXED", "ALREADY_CORRECT",
        "PASS_WITH_MIXED_PAGES", "PASS_WITH_ONLY_NATIVE_TEXT",
        "SKIPPED", "OK", "PLAN_READY", "NO_FAILURES",
    } else value.upper()


def _is_fail(value: str) -> bool:
    return value.upper() == "FAIL"


def _is_non_pass_non_fail(value: str) -> bool:
    return value.upper() in {
        "REVIEW", "REVIEW_REQUIRED", "PARTIAL", "WARN", "NEEDS_REVIEW",
        "UNKNOWN", "ERROR", "INCOMPLETE",
    }


def verdict(inputs: VerdictInput) -> VerdictResult:
    """Compute the authoritative overall outcome from the consolidated input."""
    critical_fails: list[GateName] = []
    blocking_qa: list[GateName] = []
    informational_flags: list[GateName] = []
    reasons: list[str] = []

    for gate, result in inputs.gates.items():
        raw_value = result.value
        if isinstance(raw_value, dict):
            raw_value = str(raw_value.get("result", "UNKNOWN"))
        norm = _normalize(gate, str(raw_value))

        if _is_fail(norm):
            if is_compliance_gate(gate):
                critical_fails.append(gate)
                reasons.append(f"compliance gate {gate} is FAIL")
            elif is_informational_gate(gate):
                informational_flags.append(gate)
                reasons.append(f"informational profile {gate} is FAIL")
            else:
                blocking_qa.append(gate)
                reasons.append(f"blocking QA/audit gate {gate} is FAIL")
        elif _is_non_pass_non_fail(norm) and not is_informational_gate(gate):
            blocking_qa.append(gate)
            reasons.append(f"{gate} is {norm}")

    if critical_fails:
        return VerdictResult(
            overall=FAIL,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons,
            input_gates=inputs.gates,
        )

    # Preserving existing M1 semantics: remediate.py uses >=.
    # Do not change to > without confirming a deliberate off-by-one fix.
    if inputs.has_hard_cap_exceeded:
        return VerdictResult(
            overall=ESCALATION,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["job hard cap exceeded"],
            input_gates=inputs.gates,
        )

    if inputs.hermes_signals_count > 0:
        return VerdictResult(
            overall=REVIEW_REQUIRED,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["unresolved HERMES_REQUIRED signals present"],
            input_gates=inputs.gates,
        )

    if inputs.deviations_count > 0:
        return VerdictResult(
            overall=REVIEW_REQUIRED,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["layer-1 deviations present"],
            input_gates=inputs.gates,
        )

    # Translate experimental_profile_failures into informational_flags so
    # callers never have to reason about them separately.
    for raw_exp in inputs.experimental_profile_failures:
        try:
            exp_gate = canonicalize_gate_key(str(raw_exp))
        except KeyError:
            continue
        if exp_gate not in informational_flags:
            informational_flags.append(exp_gate)
            reasons.append(f"informational profile {exp_gate} reported failures")

    if blocking_qa or informational_flags or inputs.pending_review_rules:
        return VerdictResult(
            overall=REVIEW_REQUIRED,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["blocking QA or review flags present"],
            input_gates=inputs.gates,
        )

    return VerdictResult(
        overall=PASS,
        critical_fails=[],
        blocking_qa=[],
        informational_flags=informational_flags,
        reasons=reasons,
        input_gates=inputs.gates,
    )
