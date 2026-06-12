#!/usr/bin/env python3
"""tools/lib/gates.py — Canonical gate-name registry for the M1 remediation pipeline.

This module is the single source of truth for gate names across the orchestrator,
status writer, and packager. All runtime code must import from here; no ad-hoc
gate-key strings should appear in active logic.

Gate names are grouped by role:
 compliance — gates that can independently drive FAIL (verapdf_pdfua1,
 verapdf_wcag, metadata_parity, preservation)
 information — gates that surface as REVIEW_REQUIRED informational
 flags but never hard-fail (verapdf_iso, verapdf_pdfua2,
 verapdf_baseline, parse_summary, repair_plan)
 pre-repair — gates recorded before repairs run, informational only
 (failures_pre)
 qa — structural and visual QA gates that surface as REVIEW_REQUIRED
 (qpdf, ocr_detection, render_compare, visual_qa, contrast,
 alt_text, table_semantics, font_inventory)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from pathlib import Path


class GateName(StrEnum):
    """Canonical gate identifiers used throughout the M1 pipeline."""
    verapdf_pdfua1 = "verapdf_pdfua1"
    verapdf_wcag = "verapdf_wcag"
    metadata_parity = "metadata_parity"
    preservation = "preservation"
    verapdf_iso = "verapdf_iso"
    verapdf_pdfua2 = "verapdf_pdfua2"
    verapdf_baseline = "verapdf_baseline"
    parse_summary = "parse_summary"
    repair_plan = "repair_plan"
    failures_pre = "failures_pre"
    qpdf = "qpdf"
    ocr_detection = "ocr_detection"
    render_compare = "render_compare"
    visual_qa = "visual_qa"
    contrast = "contrast"
    alt_text = "alt_text"
    table_semantics = "table_semantics"
    font_inventory = "font_inventory"
    struct_tree_check = "struct_tree_check"
    form_fields = "form_fields"


@dataclass(frozen=True)
class GateDef:
    name: GateName
    description: str = ""
    profiles: tuple[str, ...] = ()
    sidecar_resolver: Callable[[Path], list[Path]] | None = None
    is_compliance_gate: bool = False
    is_informational: bool = False
    legacy_aliases: tuple[str, ...] = ()

    def sidecar_paths(self, job_dir: Path) -> list[Path]:
        """Resolve sidecar paths for this gate using its registered resolver."""
        if self.sidecar_resolver is None:
            return []
        return list(self.sidecar_resolver(job_dir))


# --- Legacy name aliases (Fix 4: metadata_pre removed) -------------------------

LEGACY_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "verapdf_pdfua1": ("verapdf_pdfua", "verapdf_pdfua1", "verapdf_post"),
    "metadata_parity": (
        "metadata_parity",
        "metadata_parity_final",
        "metadata_post",
        "metadata_xmp_parity_audit",
    ),
    "preservation": ("preservation", "preservation_post", "preservation_audit"),
    "table_semantics": (
        "table_semantics",
        "table_semantics_post",
        "table_semantics_audit",
    ),
    "contrast": ("contrast", "contrast_post", "contrast_audit"),
    "verapdf_baseline": (
        "verapdf_baseline",
        "verapdf_baseline_pdfua1",
        "verapdf_baseline_wcag",
    ),
    "parse_summary": ("parse_summary", "parse_verapdf_summary", "failures"),
    "repair_plan": ("repair_plan", "repair_plan_final"),
    "form_fields": ("form_fields", "form_fields_post", "form_field_preservation"),
}
def is_compliance_gate(gate_name):
    """Return True if gate_name is a compliance (hard-fail) gate."""
    gn = GateName(gate_name) if isinstance(gate_name, str) else gate_name
    gdef = GATE_REGISTRY.get(gn)
    return gdef.is_compliance_gate if gdef else False


def is_informational_gate(gate_name):
    """Return True if gate_name is an informational (never hard-fail) gate."""
    gn = GateName(gate_name) if isinstance(gate_name, str) else gate_name
    gdef = GATE_REGISTRY.get(gn)
    return gdef.is_informational if gdef else False


COMPLIANCE_GATES: set[str] = {
    "verapdf_pdfua1",
    "verapdf_wcag",
    "metadata_parity",
    "preservation",
    "form_fields",
    # struct_tree_check intentionally excluded from hard COMPLIANCE_GATES
    # (Fix 11 — not confirmed as final/blocking in orchestrator; M1-safe)
}

INFORMATIONAL_GATES: set[str] = {
    "verapdf_iso",
    "verapdf_pdfua2",
    "verapdf_baseline",
    "parse_summary",
    "repair_plan",
}


# --- Sidecar path resolvers (Fix 3: pre-repair artifacts excluded) ---------------


def _verapdf_pdfua1_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair veraPDF XML for PDF/UA-1. Pre-repair file excluded."""
    post = job_dir / "qa" / "verapdf_post_pdfua1.xml"
    # verapdf_pre_pdfua1.xml excluded (Fix 3)
    return [p for p in (post,) if p.exists()]


def _verapdf_wcag_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair veraPDF XML for WCAG 2.2 Machine. Pre-repair file excluded."""
    post = job_dir / "qa" / "verapdf_post_wcag.xml"
    # verapdf_pre_wcag.xml excluded (Fix 3)
    return [p for p in (post,) if p.exists()]


def _metadata_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair metadata parity files. Pre-repair file excluded."""
    post = job_dir / "audit" / "metadata_parity_final.json"
    parity = job_dir / "audit" / "metadata_xmp_parity_audit.json"
    # metadata_pre.json excluded (Fix 3 + Fix 4)
    return [p for p in (post, parity) if p.exists()]


def _preservation_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair preservation files. Pre-repair files excluded."""
    post = job_dir / "audit" / "preservation_post.json"
    final_p = job_dir / "qa" / "preservation_final.json"
    # preservation_pre.json excluded (both audit/ and qa/) (Fix 3)
    return [p for p in (post, final_p) if p.exists()]


def _form_fields_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair form-field preservation audit."""
    post = job_dir / "audit" / "form_fields_post.json"
    return [p for p in (post,) if p.exists()]


def _table_semantics_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair table semantics files. Pre-repair file excluded."""
    post = job_dir / "audit" / "table_semantics_post.json"
    final_t = job_dir / "audit" / "table_semantics_final.json"
    # table_semantics_pre.json excluded (Fix 3)
    return [p for p in (post, final_t) if p.exists()]


def _contrast_sidecar_paths(job_dir: Path) -> list[Path]:
    """Post-repair contrast files. Pre-repair file excluded."""
    post = job_dir / "audit" / "contrast_post.json"
    final_c = job_dir / "qa" / "contrast_final.json"
    # contrast_pre.json excluded (Fix 3)
    return [p for p in (post, final_c) if p.exists()]


# --- GATE_REGISTRY (dict[GateName, GateDef]) ------------------------------------

GATE_REGISTRY: dict[GateName, GateDef] = {
    # --- Compliance (can independently drive FAIL) -----------------------------
    GateName.verapdf_pdfua1: GateDef(
        name=GateName.verapdf_pdfua1,
        description="Post-repair veraPDF compliance check (PDF/UA-1)",
        sidecar_resolver=_verapdf_pdfua1_sidecar_paths,
        is_compliance_gate=True,
        legacy_aliases=("verapdf_pdfua",),
    ),
    GateName.verapdf_wcag: GateDef(
        name=GateName.verapdf_wcag,
        description="Post-repair veraPDF compliance check (WCAG 2.2 Machine)",
        sidecar_resolver=_verapdf_wcag_sidecar_paths,
        is_compliance_gate=True,
        legacy_aliases=("verapdf_wcag",),
    ),
    GateName.metadata_parity: GateDef(
        name=GateName.metadata_parity,
        description="XMP/metadata parity after repair",
        sidecar_resolver=_metadata_sidecar_paths,
        is_compliance_gate=True,
        legacy_aliases=(
            "metadata_parity",
            "metadata_parity_final",
            "metadata_post",
            "metadata_xmp_parity_audit",
        ),
    ),
    GateName.preservation: GateDef(
        name=GateName.preservation,
        description="Preservation check (no font changes, no content loss)",
        sidecar_resolver=_preservation_sidecar_paths,
        is_compliance_gate=True,
        legacy_aliases=("preservation", "preservation_post", "preservation_audit"),
    ),
    GateName.form_fields: GateDef(
        name=GateName.form_fields,
        description="AcroForm/widget interactivity preserved after repair",
        sidecar_resolver=_form_fields_sidecar_paths,
        is_compliance_gate=True,
        legacy_aliases=("form_fields", "form_fields_post", "form_field_preservation"),
    ),
    # struct_tree_check present in GateName enum but not in hard COMPLIANCE_GATES
    # (Fix 11 — M1-safe: non-hard unless orchestrator confirms blocking)
    GateName.struct_tree_check: GateDef(
        name=GateName.struct_tree_check,
        description="Struct tree intact after repair",
        legacy_aliases=("struct_tree_check",),
    ),
    # --- Informational (never hard-fail) ---------------------------------------
    GateName.verapdf_iso: GateDef(
        name=GateName.verapdf_iso,
        description="veraPDF ISO 32000-1 Tagged (informational)",
        is_informational=True,
        legacy_aliases=("verapdf_iso",),
    ),
    GateName.verapdf_pdfua2: GateDef(
        name=GateName.verapdf_pdfua2,
        description="veraPDF PDF/UA-2 (informational for PDF/UA-1 targets)",
        is_informational=True,
        legacy_aliases=("verapdf_pdfua2",),
    ),
    GateName.verapdf_baseline: GateDef(
        name=GateName.verapdf_baseline,
        description="Pre-repair veraPDF baseline (informational)",
        is_informational=True,
        legacy_aliases=(
            "verapdf_baseline",
            "verapdf_baseline_pdfua1",
            "verapdf_baseline_wcag",
        ),
    ),
    GateName.parse_summary: GateDef(
        name=GateName.parse_summary,
        description="Parsed veraPDF failure summary (informational)",
        is_informational=True,
        legacy_aliases=("parse_summary", "parse_verapdf_summary", "failures"),
    ),
    GateName.repair_plan: GateDef(
        name=GateName.repair_plan,
        description="Repair plan emitted by lookup_repair_plan.py",
        is_informational=True,
        legacy_aliases=("repair_plan", "repair_plan_final"),
    ),
    GateName.failures_pre: GateDef(
        name=GateName.failures_pre,
        description="Failures list captured before repair runs",
        is_informational=True,
        legacy_aliases=("failures_pre", "pre_repair_failures", "pre_failures"),
    ),
    # --- QA / structural -------------------------------------------------------
    GateName.qpdf: GateDef(
        name=GateName.qpdf,
        description="qpdf check",
        legacy_aliases=("qpdf",),
    ),
    GateName.ocr_detection: GateDef(
        name=GateName.ocr_detection,
        description="OCR detection for image-only pages",
        legacy_aliases=("ocr_detection",),
    ),
    GateName.render_compare: GateDef(
        name=GateName.render_compare,
        description="Render comparison pre/post repair",
        legacy_aliases=("render_compare",),
    ),
    GateName.visual_qa: GateDef(
        name=GateName.visual_qa,
        description="Visual QA pass/fail",
        legacy_aliases=("visual_qa",),
    ),
    GateName.contrast: GateDef(
        name=GateName.contrast,
        description="Contrast ratio audit",
        sidecar_resolver=_contrast_sidecar_paths,
        legacy_aliases=("contrast", "contrast_post", "contrast_audit"),
    ),
    GateName.alt_text: GateDef(
        name=GateName.alt_text,
        description="Alt text presence/quality",
        legacy_aliases=("alt_text",),
    ),
    GateName.table_semantics: GateDef(
        name=GateName.table_semantics,
        description="Table semantics (TH, TD, headers, scope)",
        sidecar_resolver=_table_semantics_sidecar_paths,
        legacy_aliases=(
            "table_semantics",
            "table_semantics_post",
            "table_semantics_audit",
        ),
    ),
    GateName.font_inventory: GateDef(
        name=GateName.font_inventory,
        description="Font inventory audit",
        legacy_aliases=("font_inventory",),
    ),
}


# --- Helpers -------------------------------------------------------------------


def canonicalize_gate_key(key: str) -> GateName:
    """Return GateName for a raw key.

    Order: exact GateName match -> LEGACY_NAME_ALIASES -> KeyError.
    (Fix 2: simplified -- no __members__ scan.)
    """
    try:
        return GateName(key)
    except ValueError:
        pass

    for canonical, aliases in LEGACY_NAME_ALIASES.items():
        if key in aliases:
            return GateName(canonical)

    raise KeyError(key)
