#!/usr/bin/env python3
"""Guarded repair acceptance contract.

This module is intentionally mutation-free. H10I does not execute or activate
the guarded form-widget repair; it defines the acceptance/status/package
contract that H10J/H11 can call after an explicitly opted-in guarded runtime
produces an intermediate candidate PDF.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

TARGET_RULE = "PDF/UA-1/7.18.4"

PASS_RESULTS = {
    "PASS",
    "OK",
    "FIXED",
    "ALREADY_CORRECT",
    "CLEARED",
    "VALIDATED",
    "VALIDATED_FOR_ADOPTION_CONSIDERATION",
    "BENIGN_INFORMATIONAL",
    "NO_REGRESSION",
    "NO_FAILURES",
}

NON_PASS_RESULTS = {
    "FAIL",
    "ERROR",
    "BLOCKED",
    "REGRESSION",
    "MISSING",
    "INCOMPLETE",
    "UNKNOWN",
    "NOT_RUN",
}

AUTHORITATIVE_GATE_FIELDS = (
    "qpdf_result",
    "verapdf_pdfua1_result",
    "verapdf_wcag_result",
    "verapdf_iso_result",
    "profile_accounting_result",
    "iso_regression_result",
    "post_form_widget_inspection_result",
    "preservation_result",
)


def _result_value(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("result", "status", "verdict", "terminal_state", "target_rule_status"):
            if value.get(key) is not None:
                return str(value.get(key)).strip().upper()
        return "UNKNOWN"
    if value is True:
        return "PASS"
    if value is False or value is None:
        return "UNKNOWN"
    return str(value).strip().upper() or "UNKNOWN"


def _is_pass(value: Any) -> bool:
    return _result_value(value) in PASS_RESULTS


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _path_text(value: Any) -> str:
    return str(value or "").strip()


def _same_path(left: Any, right: Any) -> bool:
    left_text = _path_text(left)
    right_text = _path_text(right)
    if not left_text or not right_text:
        return False
    try:
        return Path(left_text) == Path(right_text)
    except Exception:
        return left_text == right_text


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_json_object(path_value: Any) -> Mapping[str, Any]:
    path_text = _path_text(path_value)
    if not path_text:
        return {}
    try:
        data = json.loads(Path(path_text).read_text())
    except Exception:
        return {}
    return data if isinstance(data, Mapping) else {}


def _post_form_widget_inspection_report(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the detailed post-repair form-widget inspection evidence.

    H10K exposed a result-string contract mismatch: the inspection tool reports
    successful read-only inspection as INSPECTED, while guarded acceptance needs
    to know whether the inspected structure is acceptable. Do not treat
    INSPECTED as a global pass token. It is acceptable only for this gate and
    only when the detailed object evidence proves all widgets are represented by
    complete Form structure evidence with no diagnostic blockers.
    """
    for key in (
        "post_form_widget_inspection",
        "post_form_widget_inspection_report",
        "form_widget_structure_after",
    ):
        report = _as_mapping(data.get(key))
        if report:
            return report

    artifacts = _as_mapping(data.get("artifacts"))
    for key in ("post_inspection", "post_form_widget_inspection"):
        report = _load_json_object(artifacts.get(key))
        if report:
            return report

    return _load_json_object(data.get("post_form_widget_inspection_path"))


def _post_form_widget_inspection_blockers(data: Mapping[str, Any]) -> list[str]:
    result = _result_value(data.get("post_form_widget_inspection_result"))
    if result in PASS_RESULTS:
        return []
    if result != "INSPECTED":
        return ["post_form_widget_inspection_result_not_pass"]

    report = _post_form_widget_inspection_report(data)
    if not report:
        return ["post_form_widget_inspection_evidence_missing"]

    blockers: list[str] = []
    if _result_value(report) != "INSPECTED":
        blockers.append("post_form_widget_inspection_report_not_inspected")

    decision = _as_mapping(report.get("decision"))
    decision_blockers = _as_list(decision.get("blockers"))
    if decision_blockers:
        blockers.append("post_form_widget_inspection_decision_blockers")
    required_next = _as_list(decision.get("required_next_evidence"))
    if required_next:
        blockers.append("post_form_widget_inspection_requires_more_evidence")

    evidence = _as_mapping(report.get("pdf_object_evidence")) or report
    if evidence.get("available") is not True:
        blockers.append("post_form_widget_inspection_unavailable")
    if evidence.get("widget_evidence_complete") is not True:
        blockers.append("post_form_widget_inspection_evidence_incomplete")
    if evidence.get("widgets_truncated") is not False:
        blockers.append("post_form_widget_inspection_widgets_truncated")

    widget_count = _safe_int(evidence.get("widget_annotation_count"), 0)
    if widget_count <= 0:
        blockers.append("post_form_widget_inspection_no_widgets")

    if _safe_int(evidence.get("widgets_with_struct_parent_count"), -1) != widget_count:
        blockers.append("post_form_widget_inspection_struct_parent_mismatch")
    if _safe_int(evidence.get("widgets_with_parent_tree_mapping_count"), -1) != widget_count:
        blockers.append("post_form_widget_inspection_parent_tree_mapping_mismatch")
    if _safe_int(evidence.get("widgets_referenced_from_non_form_count"), 0) != 0:
        blockers.append("post_form_widget_inspection_non_form_references")
    if _safe_int(evidence.get("form_struct_element_count"), 0) <= 0:
        blockers.append("post_form_widget_inspection_no_form_structure")

    widgets = evidence.get("widgets")
    if isinstance(widgets, list) and len(widgets) == widget_count:
        bad_widgets = [
            widget for widget in widgets
            if isinstance(widget, Mapping)
            and (
                widget.get("already_nested_in_form") is not True
                or widget.get("referenced_from_non_form_element") is True
                or widget.get("parent_tree_mapping_present") is not True
                or widget.get("struct_parent") is None
            )
        ]
        if bad_widgets:
            blockers.append("post_form_widget_inspection_widget_records_not_form_nested")
    elif _safe_int(evidence.get("widgets_already_nested_in_form_count"), -1) != widget_count:
        blockers.append("post_form_widget_inspection_form_nesting_count_mismatch")

    return blockers


def _decision(
    *,
    terminal_state: str,
    status_result: str,
    package_policy: str,
    promote_candidate_to_final: bool,
    review_required: bool,
    pass_allowed: bool,
    failure_reason: str,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_copy = deepcopy(dict(evidence or {}))
    required_reports = [
        "guarded_acceptance.json",
        "orchestrator_outcome.json",
        "STATUS.json",
        "AUDIT_REPORT.md",
    ]
    return {
        "schema_version": "guarded-acceptance-contract.v1",
        "guarded_acceptance_result": terminal_state,
        "terminal_state": terminal_state,
        "status_result": status_result,
        "package_policy": package_policy,
        "promote_candidate_to_final": bool(promote_candidate_to_final),
        "review_required": bool(review_required),
        "pass_allowed": bool(pass_allowed),
        "failure_reason": failure_reason,
        "blockers": blockers or [],
        "warnings": warnings or [],
        "required_reports": required_reports,
        "target_rule": evidence_copy.get("target_rule", TARGET_RULE),
        "repair_strategy_id": evidence_copy.get("repair_strategy_id"),
        "input_pdf": evidence_copy.get("input_pdf"),
        "candidate_pdf": evidence_copy.get("candidate_pdf"),
        "final_pdf": evidence_copy.get("final_pdf"),
        "intermediate_output": not bool(promote_candidate_to_final),
        "evidence_summary": {
            field: _result_value(evidence_copy.get(field))
            for field in AUTHORITATIVE_GATE_FIELDS
        },
        "residual_failures_count": len(_as_list(evidence_copy.get("residual_failures"))),
        "new_authoritative_failures_count": len(_as_list(evidence_copy.get("new_authoritative_failures"))),
        "increased_authoritative_failures_count": len(_as_list(evidence_copy.get("increased_authoritative_failures"))),
        "target_rule_before_count": evidence_copy.get("target_rule_before_count"),
        "target_rule_after_count": evidence_copy.get("target_rule_after_count"),
        "target_rule_status": evidence_copy.get("target_rule_status"),
    }


def evaluate_guarded_acceptance(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return the authoritative H10I acceptance decision for a guarded candidate.

    The candidate is an intermediate output by default. PASS is allowed only
    when the target repair cleared, every authoritative gate passes, artifact
    path discipline is safe, and there are no residual/new/increased
    authoritative PDF/UA or WCAG failures.
    """
    data = dict(evidence or {})
    blockers: list[str] = []
    warnings: list[str] = []

    target_rule = str(data.get("target_rule") or TARGET_RULE)
    if target_rule != TARGET_RULE:
        blockers.append("unsupported_target_rule")

    input_pdf = data.get("input_pdf")
    candidate_pdf = data.get("candidate_pdf")
    final_pdf = data.get("final_pdf")
    status_path = data.get("status_path")
    package_path = data.get("package_path")
    orchestrator_outcome_path = data.get("orchestrator_outcome_path")

    if not _path_text(candidate_pdf):
        blockers.append("candidate_pdf_missing")
    if _same_path(candidate_pdf, input_pdf):
        blockers.append("candidate_overwrites_input_pdf")
    for name, path_value in (
        ("final_pdf", final_pdf),
        ("status_path", status_path),
        ("package_path", package_path),
        ("orchestrator_outcome_path", orchestrator_outcome_path),
    ):
        if _same_path(candidate_pdf, path_value):
            blockers.append(f"candidate_collides_with_{name}")

    if blockers:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_ARTIFACT_POLICY",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="artifact_policy_failed",
            blockers=blockers,
            warnings=warnings,
            evidence=data,
        )

    qpdf_result = _result_value(data.get("qpdf_result"))
    if qpdf_result not in PASS_RESULTS:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_QPDF",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="qpdf_failed",
            blockers=["qpdf_result_not_pass"],
            evidence=data,
        )

    profile_accounting_result = _result_value(data.get("profile_accounting_result"))
    if profile_accounting_result not in PASS_RESULTS:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_PROFILE_ACCOUNTING",
            status_result="ESCALATION",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="profile_accounting_incomplete_or_failed",
            blockers=["profile_accounting_result_not_pass"],
            evidence=data,
        )

    post_inspection_blockers = _post_form_widget_inspection_blockers(data)
    if post_inspection_blockers:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="post_form_widget_inspection_failed",
            blockers=post_inspection_blockers,
            evidence=data,
        )

    preservation_result = _result_value(data.get("preservation_result"))
    if preservation_result not in PASS_RESULTS:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_PRESERVATION",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="preservation_failed",
            blockers=["preservation_result_not_pass"],
            evidence=data,
        )

    iso_regression_result = _result_value(data.get("iso_regression_result"))
    verapdf_iso_result = _result_value(data.get("verapdf_iso_result"))
    new_iso = _as_list(data.get("new_iso_rule_ids")) or _as_list(data.get("new_or_increased_iso_checks"))
    increased_iso = _as_list(data.get("increased_iso_rule_ids"))
    if iso_regression_result not in PASS_RESULTS or verapdf_iso_result not in PASS_RESULTS or new_iso or increased_iso:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_ISO_REGRESSION",
            status_result="REVIEW_REQUIRED",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=True,
            pass_allowed=False,
            failure_reason="iso_no_regression_failed",
            blockers=["iso_regression_or_profile_not_pass"],
            evidence=data,
        )

    target_status = _result_value(data.get("target_rule_status"))
    target_after = data.get("target_rule_after_count")
    try:
        target_after_count = int(target_after) if target_after is not None else None
    except Exception:
        target_after_count = None
    target_cleared = target_status in {"CLEARED", "PASS", "FIXED", "NO_FAILURES"} or target_after_count == 0
    if not target_cleared:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_VERAPDF_REGRESSION",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="target_rule_not_cleared",
            blockers=["target_rule_not_cleared"],
            evidence=data,
        )

    new_authoritative = _as_list(data.get("new_authoritative_failures"))
    increased_authoritative = _as_list(data.get("increased_authoritative_failures"))
    if new_authoritative or increased_authoritative:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_REJECTED_VERAPDF_REGRESSION",
            status_result="FAIL",
            package_policy="REPORT_ONLY",
            promote_candidate_to_final=False,
            review_required=False,
            pass_allowed=False,
            failure_reason="new_or_increased_authoritative_failures",
            blockers=["new_or_increased_authoritative_failures"],
            evidence=data,
        )

    residual_failures = _as_list(data.get("residual_failures"))
    pdfua_result = _result_value(data.get("verapdf_pdfua1_result"))
    wcag_result = _result_value(data.get("verapdf_wcag_result"))
    if residual_failures or pdfua_result not in PASS_RESULTS or wcag_result not in PASS_RESULTS:
        return _decision(
            terminal_state="GUARDED_CANDIDATE_ACCEPTED_REVIEW_REQUIRED",
            status_result="REVIEW_REQUIRED",
            package_policy="REVIEW_REQUIRED_WITH_CANDIDATE",
            promote_candidate_to_final=False,
            review_required=True,
            pass_allowed=False,
            failure_reason="target_rule_cleared_but_residual_authoritative_failures_remain",
            warnings=["candidate_is_intermediate_review_required_not_pass"],
            evidence=data,
        )

    return _decision(
        terminal_state="GUARDED_CANDIDATE_ACCEPTED_PASS_ALLOWED",
        status_result="PASS",
        package_policy="PASS_FINAL_ALLOWED",
        promote_candidate_to_final=True,
        review_required=False,
        pass_allowed=True,
        failure_reason="none",
        evidence=data,
    )


def build_orchestrator_outcome(decision: Mapping[str, Any], *, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build truthful orchestrator_outcome-style data from a decision."""
    result = dict(base or {})
    status_result = str(decision.get("status_result") or "UNKNOWN")
    if status_result == "PASS" and not bool(decision.get("pass_allowed")):
        status_result = "REVIEW_REQUIRED"
    result.update({
        "overall_result": status_result,
        "guarded_acceptance": deepcopy(dict(decision)),
        "guarded_acceptance_terminal_state": decision.get("terminal_state"),
        "guarded_candidate_intermediate": not bool(decision.get("promote_candidate_to_final")),
        "guarded_candidate_promoted_to_final": bool(decision.get("promote_candidate_to_final")),
    })
    return result


def status_fragment(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Return the STATUS.json fragment for a guarded decision."""
    return {
        "guarded_acceptance": deepcopy(dict(decision)),
        "guarded_acceptance_terminal_state": decision.get("terminal_state"),
        "guarded_acceptance_result": decision.get("guarded_acceptance_result"),
        "guarded_candidate_intermediate": not bool(decision.get("promote_candidate_to_final")),
        "guarded_candidate_promoted_to_final": bool(decision.get("promote_candidate_to_final")),
        "guarded_pass_allowed": bool(decision.get("pass_allowed")),
    }


def package_routing(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Return package routing policy for a guarded candidate."""
    policy = str(decision.get("package_policy") or "REPORT_ONLY")
    status_result = str(decision.get("status_result") or "UNKNOWN")
    return {
        "package_policy": policy,
        "overall_result": status_result,
        "copy_pdf_to_deliverables": policy in {"PASS_FINAL_ALLOWED", "REVIEW_REQUIRED_WITH_CANDIDATE"},
        "label": "successful final PDF" if policy == "PASS_FINAL_ALLOWED" else "review-required candidate" if policy == "REVIEW_REQUIRED_WITH_CANDIDATE" else "report-only",
        "promote_candidate_to_final": bool(decision.get("promote_candidate_to_final")),
    }
