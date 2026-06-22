# H10B Form-Widget Metadata Adoption Decision

## Terminal state

```text
ADOPTION_DEFERRED_FOR_ISO_REGRESSION_REVIEW
```

## Reason

H10A-V reached `VERAPDF_DELTA_VALIDATED` for the target `PDF/UA-1/7.18.4` form-widget repair evidence, including target-rule clearance from 204 failures to 0 failures, qpdf pass, object diagnostics pass, preservation pass, and required PDF/UA-1/WCAG profile accounting.

H10B does **not** adopt rule-map metadata yet because H10A-V also recorded an informational ISO profile regression:

```text
PDF_UA/ISO-32000-1-Tagged.xml
before: PASS
after: FAIL
classification: informational
```

Although this ISO profile is not authoritative for the current PDF/UA-1 verdict policy, the regression is close enough to the tagged-PDF structure-construction behavior that H10B defers metadata adoption until a later review can determine whether the regression is expected, benign, or evidence of a structural side effect.

## Production-readiness boundary

H10B does not make the strategy production-active.

H10B does not change `app/tools/orchestrate/remediate.py`.

H10B does not change `app/tools/packaging/` or STATUS/package behavior.

H10B does not claim production readiness.

H10B does not add `tools/repair/repair_form_widget_structure.py` to active `strategies[]` for `PDF/UA-1/7.18.4`.

H10B does not make `lookup_repair_plan.py` emit `tools/repair/repair_form_widget_structure.py` as an executable production repair step.

## Required future work before runtime activation

A later patch may reconsider guarded metadata adoption or runtime integration only after it proves:

```text
lookup gating
precondition checking
safe CLI args for production
workspace output discipline
post-repair veraPDF cycle
review package generation
truthful STATUS/package outcomes
orchestrator E2E behavior
```

If the ISO regression is resolved or accepted by explicit policy, the next adoption patch should record non-runtime metadata only, with `runtime_active: false`, `production_default: false`, required profile accounting, PDF20 prohibition, experimental/custom profile non-authoritative status, and the ISO caution retained.
