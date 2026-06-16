#!/usr/bin/env python3
"""tools/lib/verdict.py - Shared verdict computation.

Both remediate.py and status_json_writer.py call verdict() so they cannot
silently disagree on PASS/REVIEW_REQUIRED/FAIL/ESCALATION. Patch 5 extends the
input model with residual-analysis summaries while preserving the original M1
public API: GateResult is a dataclass keyed by tools.lib.gates.GateName.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Sequence

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
    pending_review_rules: Sequence[str] = field(default_factory=list)

    # Patch 5 residual-aware fields. These do not soften hard gates.
    residual_analysis: dict[str, Any] = field(default_factory=dict)
    strategy_indexing: dict[str, Any] = field(default_factory=dict)
    targetable_residual_rules: Sequence[str] = field(default_factory=list)
    non_targetable_residual_rules: Sequence[str] = field(default_factory=list)
    introduced_rules: Sequence[str] = field(default_factory=list)
    partially_resolved_rules: Sequence[str] = field(default_factory=list)
    transport_blocked: bool = False

    @classmethod
    def from_gate_dict(cls, raw: Mapping[str, object], **kwargs: Any) -> "VerdictInput":
        gates: dict[GateName, GateResult] = {}
        for key, value in raw.items():
            try:
                gate = canonicalize_gate_key(str(key))
            except KeyError:
                continue
            result_value: object = value
            source = ""
            if isinstance(value, Mapping):
                result_value = value.get("result", value)
                source = str(value.get("source", ""))
            gates[gate] = GateResult(gate=gate, value=str(result_value), source=source)
        return cls(gates=gates, **kwargs)

    @classmethod
    def from_remediate_state(
        cls,
        gate_results: Mapping[str, str],
        hermes_signals: Sequence[Mapping[str, object]] | None,
        deviations: Sequence[Mapping[str, object]] | None,
        total_iterations: int,
        job_hard_cap: int = 50,
        experimental_profile_failures: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> "VerdictInput":
        canonical_raw: dict[str, object] = {}
        for key, value in gate_results.items():
            try:
                gate = canonicalize_gate_key(str(key))
                canonical_raw[str(gate)] = {"result": value, "source": "orchestrator"}
            except KeyError:
                canonical_raw[str(key)] = {"result": value, "source": "orchestrator"}
        return cls.from_gate_dict(
            canonical_raw,
            hermes_signals_count=len(hermes_signals or []),
            deviations_count=len(deviations or []),
            total_iterations=total_iterations,
            job_hard_cap=job_hard_cap,
            experimental_profile_failures=experimental_profile_failures or [],
            **kwargs,
        )


@dataclass(frozen=True)
class VerdictResult:
    overall: str  # PASS | REVIEW_REQUIRED | FAIL | ESCALATION
    critical_fails: List[GateName | str]
    blocking_qa: List[GateName | str]
    informational_flags: List[GateName | str]
    reasons: List[str]
    source: str = "shared_verdict"
    input_gates: dict[GateName, GateResult] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "overall": self.overall,
            "critical_fails": [str(g) for g in self.critical_fails],
            "blocking_qa": [str(g) for g in self.blocking_qa],
            "informational_flags": [str(g) for g in self.informational_flags],
            "reasons": list(self.reasons),
            "source": self.source,
            "input_gates": {
                str(g): {"result": r.value, "source": r.source}
                for g, r in self.input_gates.items()
            },
        }


PASS = "PASS"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
FAIL = "FAIL"
ESCALATION = "ESCALATION"


def _normalize(gate: GateName, value: str) -> str:
    return "PASS" if value.upper() in {
        "PASS",
        "FIXED",
        "ALREADY_CORRECT",
        "PASS_WITH_MIXED_PAGES",
        "PASS_WITH_ONLY_NATIVE_TEXT",
        "SKIPPED",
        "OK",
        "PLAN_READY",
        "NO_FAILURES",
        "NOT_APPLICABLE",
    } else value.upper()


def _is_fail(value: str) -> bool:
    return value.upper() == "FAIL"


def _is_non_pass_non_fail(value: str) -> bool:
    return value.upper() in {
        "REVIEW",
        "REVIEW_REQUIRED",
        "PARTIAL",
        "WARN",
        "NEEDS_REVIEW",
        "UNKNOWN",
        "ERROR",
        "INCOMPLETE",
    }


def _merged_rules(inputs: VerdictInput, attr: str, residual_key: str) -> list[str]:
    direct = list(getattr(inputs, attr, []) or [])
    residual = inputs.residual_analysis or {}
    from_summary = list(residual.get(residual_key, []) or []) if isinstance(residual, Mapping) else []
    return sorted({str(v) for v in direct + from_summary if str(v or "").strip()})


def verdict(inputs: VerdictInput) -> VerdictResult:
    """Compute the authoritative overall outcome from consolidated input."""
    critical_fails: list[GateName | str] = []
    blocking_qa: list[GateName | str] = []
    informational_flags: list[GateName | str] = []
    reasons: list[str] = []

    for gate, result in inputs.gates.items():
        raw_value = result.value
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

    for raw_exp in inputs.experimental_profile_failures:
        try:
            exp_gate = canonicalize_gate_key(str(raw_exp))
        except KeyError:
            continue
        if exp_gate not in informational_flags:
            informational_flags.append(exp_gate)
            reasons.append(f"informational profile {exp_gate} reported failures")

    introduced = _merged_rules(inputs, "introduced_rules", "introduced_rules")
    targetable = _merged_rules(inputs, "targetable_residual_rules", "targetable_residual_rules")
    pending = _merged_rules(inputs, "pending_review_rules", "pending_review_rules")
    partial = _merged_rules(inputs, "partially_resolved_rules", "partially_resolved_rules")

    if introduced:
        critical_fails.extend(f"introduced_residual:{rule}" for rule in introduced)
        reasons.append("introduced residual rules are hard blockers")

    if critical_fails:
        return VerdictResult(
            overall=FAIL,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons,
            input_gates=inputs.gates,
        )

    if inputs.has_hard_cap_exceeded or (inputs.job_hard_cap and inputs.total_iterations >= inputs.job_hard_cap):
        return VerdictResult(
            overall=ESCALATION,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["job hard cap exceeded"],
            input_gates=inputs.gates,
        )

    if inputs.transport_blocked:
        return VerdictResult(
            overall=ESCALATION,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + ["Hermes/self-extension transport blocked"],
            input_gates=inputs.gates,
        )

    if targetable:
        extra = ["unresolved targetable residual rules require strategy work"]
        if partial:
            extra.append("partial improvements are diagnostic only and do not soften verdict")
        return VerdictResult(
            overall=ESCALATION,
            critical_fails=critical_fails,
            blocking_qa=blocking_qa,
            informational_flags=informational_flags,
            reasons=reasons + extra,
            input_gates=inputs.gates,
        )

    # Preserve M1 behavior for ordinary HERMES_REQUIRED signals: review, not fail.
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

    if blocking_qa or informational_flags or pending:
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
