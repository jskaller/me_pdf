# PDF Remediation Pipeline Consistency Contracts

Engineering reference for developers working on the pipeline code (gates,
verdict, status writer, packaging, orchestrator). These are invariants the
*code* must uphold — they are NOT job-time instructions for the remediation
agent. (Relocated from the runtime `pdf-remediation` skill, which is now a
job-time operational runbook; see `app/hermes_skills/pdf-remediation/SKILL.md`.)

Load/consult this when working on tools that produce STATUS.json,
orchestrator_outcome.json, or any audited JSON sidecar where multiple
consumers must agree on PASS/REVIEW_REQUIRED/FAIL/ESCALATION. The diagnostic
signal that you need this doc: two files computing the overall result
independently.

## Core contracts that must hold in every job folder

1. **One authoritative overall result per job.** The orchestrator writes it
   first (`audit/orchestrator_outcome.json`). No downstream file may override
   it silently.
2. **One canonical gate namespace.** A conceptual gate lives under exactly one
   key everywhere — scaffold, orchestrator, status writer, packaging,
   sidecars, tests. Legacy filenames are tolerated by canonicalization, never
   reintroduced.
3. **Gate registry contract.** `GateDef.sidecar_paths(self, job_dir) -> list[Path]`
   must be an instance method, not a class-level Callable shadowed by a
   method. `status_json_writer.py` calls `gate_def.sidecar_paths(job_dir)` on
   every entry in `GATE_REGISTRY`; a missing method crashes iteration.
4. **Pre-repair artifacts are never compliance inputs.** Files ending in
   `_pre`, `_pre_pdfua1`, `_pre_wcag`, `metadata_pre.json`,
   `preservation_pre.json`, `table_semantics_pre.json`, `contrast_pre.json`
   must not appear in any compliance gate's `sidecar_paths` resolver. They
   belong to residual analysis, not verdict computation. (Exception added in
   P10: `contrast_pre` may be surfaced as canonical `contrast` only when
   `render_compare` passes, proving rendering was unchanged post-repair.)
5. **`metadata_pre` is not a legacy alias for `metadata_parity`.** Including it
   in `LEGACY_NAME_ALIASES` injects a pre-repair baseline into the post-repair
   compliance verdict.
6. **Informational gates surface as flags, never as FAIL.** `verapdf_iso`,
   `verapdf_pdfua2`, `verapdf_baseline`, `parse_summary`, `repair_plan` are
   `INFORMATIONAL_GATES`. Their failures populate `informational_flags` and
   route to `REVIEW_REQUIRED` at worst — never `FAIL` — unless the orchestrator
   outcome is already authoritative.
7. **`struct_tree_check` is not a hard `COMPLIANCE_GATE` for M1.** Keep it
   non-hard unless `remediate.py` confirms it is a blocking final gate.
8. **`audit/verapdf_summary.json` is diagnostic-only.** Still written by
   `run_verapdf_profiles.sh`, but `remediate.py` must not use it as the hard
   final veraPDF result. Derive canonical gate outcomes from the per-profile
   sidecar XML files instead.
9. **`parse_verapdf_summary.py` must be import-safe and expose a public API.**
   Provides `parse_verapdf_single_result(path, schema_hint)`, `GREENFIELD`,
   `ARLINGTON`. All CLI/test execution under `if __name__ == '__main__':`;
   importing must never call `sys.exit()`.

## STATUS.json verdict field structure

`status_json_writer.py` nests the verdict under a `verdict` key:

```
status["verdict"]["critical_fails"]      # e.g. ["verapdf_pdfua1"]
status["verdict"]["informational_flags"] # e.g. ["verapdf_iso"]
status["verdict"]["overall"]             # PASS / FAIL / REVIEW_REQUIRED
```

Do NOT read `status["critical_fails"]` at the top level — it does not exist
there; a test checking the wrong path passes vacuously with `None`.

## The three-path fallback chain

```
P1 (highest):  orchestrator_outcome.json exists -> authoritative
P2 (fallback): verdict_input.json exists        -> shared verdict() recomputed
P3 (legacy):   both absent                      -> sidecar scan + verdict()
```

`verdict_result_source` in STATUS.json records which ran. (Post-P6: P2 also
recomputes for gates{} population and mismatch reconciliation even when P1 is
authoritative.)

## Exit code contract for status_json_writer

```
rc = 0  ->  overall_result is PASS or REVIEW_REQUIRED
rc = 1  ->  overall_result is FAIL or ESCALATION
```

Inverse of what many callers expect; tests asserting `rc == 0` for FAIL fail.

## Verification scripts

From repo root (`/app`):
- `PYTHONPATH=. python3 skills/pdf-remediation/scripts/verify_exp_failures_ordering.py`
  — regression probe: `experimental_profile_failures` preserved when a
  compliance gate also fails.
