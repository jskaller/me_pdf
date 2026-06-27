# H12 — Agent-Generated Candidate Repair for Remaining Active Blockers

## Baseline

```text
baseline commit: 86fd27d Preserve H10K historical title marker
branch: master
```

## Terminal state

```text
AGENT_CANDIDATE_REPAIR_BLOCKED_BY_MISSING_EVIDENCE
```

This H12 result is intentionally not a PASS and not a production-readiness claim.

## Target rule selected

```text
PDF/UA-1/7.21.7
```

Reason for selection: H12 preferred `PDF/UA-1/7.21.7` before `PDF/UA-1/7.21.4.1` and `PDF/UA-1/7.18.4` because missing ToUnicode maps exercise the real no-working-script path. `PDF/UA-1/7.18.4` already has a guarded form-widget repair track and therefore was not used as the primary H12 target.

## H11 strategy artifacts

Required H11 runtime artifact paths were expected under:

```text
/app/workspace/jobs/MM-17179-H11-BATCH2_ROI4987_English_1-26_rev_Fillable
```

Artifacts expected by H12:

```text
audit/hermes_strategy_request.json
audit/strategy_gap.json
audit/hermes_strategy_proposal.json
audit/repair_plan_post.json
audit/unsupported_rule_iteration_stress.json
audit/orchestrator_outcome.json
STATUS.json
```

In this connector-backed patch execution environment, the runtime workspace is not mounted and the H11 runtime artifacts are unavailable locally. H12 therefore does not fake artifact contents.

```text
H11 runtime artifacts unavailable locally
```

The committed H12 patch records this fact as missing evidence in the ToUnicode readiness artifact schema rather than treating it as proof that repair is impossible.

## Candidate-creation loop status

The repository already contains a guarded self-extension/candidate loop:

```text
app/tools/orchestrate/self_extension.py
app/tools/orchestrate/self_extension_run_state.py
app/tools/orchestrate/self_extension_executor.py
```

Observed committed capabilities:

```text
strategy request -> compact target-rule generation request
Hermes gateway generation call expecting SCRIPT_SOURCE JSON
quarantined generated script path under app/tools/repair/generated/
per-rule max-attempt loop
run-scoped attempt state
candidate execution contract
candidate validation hook
retry feedback for failed candidate attempts
semantic refusal retry handling
transport/rate-limit blocking distinct from repair attempt use
no adoption/rule-map mutation by default
```

Therefore H12 does not classify the current source tree as `AGENT_CANDIDATE_REPAIR_LOOP_NOT_FUNCTIONAL`.

## Why no ToUnicode candidate script was created

For `PDF/UA-1/7.21.7`, H12 requires deterministic character mapping evidence before a candidate script can safely create ToUnicode CMaps. The required evidence includes:

```text
font object IDs and font names
font subtype
Encoding / Differences
embedded or missing font program
glyph widths
CID/GID mapping if present
actual text extraction before repair
rendered text comparison before/after
character-code usage in content streams
proof that visible text can be mapped deterministically
```

This H12 execution did not have the H11 job artifacts, qpdf object inventory, font object records, character-code usage records, text extraction evidence, or rendered comparison evidence. Creating a repair without those facts would require guessing Unicode mappings or relying on visual/OCR inference, both of which are forbidden for H12.

## Implemented H12 gate

Added:

```text
app/tools/audit/font_tounicode_diagnostics.py
```

Purpose:

```text
Inspect qpdf-style font records for missing /ToUnicode evidence.
Reject candidate creation unless deterministic mapping evidence exists.
Record missing evidence explicitly.
Forbid OCR, visual inference, guessed mappings, and hard-coded mapping sources.
Keep safe_to_claim_pass=false and safe_to_claim_production_ready=false.
```

The diagnostic emits:

```text
schema: h12_font_tounicode_repair_readiness_v1
target_rule: PDF/UA-1/7.21.7
missing_tounicode_font_count
per_font_deterministic_mapping_evidence
missing_report_evidence
candidate_creation_allowed
candidate_gate_state
terminal_state_if_stopped_here
safe_to_claim_pass: false
safe_to_claim_production_ready: false
```

## Attempt caps

Existing orchestrator iteration caps remain:

```text
PER_RULE_CAP: 15
JOB_WARN_AT: 20
JOB_HARD_CAP: 50
```

Existing self-extension defaults remain:

```text
HERMES_SELF_EXTENSION_MAX_ATTEMPTS_PER_RULE: 3
HERMES_SELF_EXTENSION_GENERATION_CALL_BUDGET: 10
HERMES_SELF_EXTENSION_TRANSPORT_RETRY_BUDGET: 3
```

H12 policy tests verify that the self-extension loop records a max-attempt exhaustion result without adoption or final PDF update.

## Attempts used

```text
attempts_used: 0
attempts_remaining: not consumed in this environment
stop_reason: missing deterministic ToUnicode/font/content/render/H11 runtime evidence
candidate_script_created: false
candidate_module_created: false
```

No generated repair was attempted because H12 must not create a ToUnicode candidate until deterministic mapping evidence exists.

## Validation results

No candidate PDF was created, so there are no before/after qpdf, veraPDF PDF/UA-1, WCAG, ISO, profile-accounting, preservation, text extraction, or render deltas for an H12 candidate.

This is not a successful repair. It is an evidence-backed safety block.

## Rule-map and adoption decision

```text
rule_map_changed: false
adoption_performed: false
promotion_performed: false
production_default_changed: false
```

No new repair was registered. No guarded/non-default strategy was added. No default repair path was activated.

## WebUI / production-path run

WebUI was not exercised in this connector-backed patch execution environment. The live workspace and Open WebUI/Hermes runtime were not available here.

Closest source-level substitute performed by this patch:

```text
source inspection of self_extension executor loop
policy tests for strategy request -> candidate generation request
policy tests for missing deterministic ToUnicode evidence blocking candidate creation
policy tests for rejected candidate loop attempt accounting
```

Do not treat this H12 patch as WebUI proof.

## STATUS.json / orchestrator_outcome.json / package result

No live H12 job was run here, so no runtime `STATUS.json`, `orchestrator_outcome.json`, or package artifact was produced by this execution environment.

Expected truthful runtime outcome for the same evidence state:

```text
STATUS.json: ESCALATION or REVIEW_REQUIRED, not PASS
orchestrator_outcome.json: candidate repair blocked by missing evidence
package: report-only, not successful final PDF
```

## Tests added

```text
app/tools/tests/test_font_tounicode_diagnostics_policy.py
app/tools/tests/test_agent_candidate_repair_loop_policy.py
```

Coverage added:

```text
missing deterministic ToUnicode evidence blocks repair
ToUnicode repair is not allowed from guesswork or OCR
qpdf-style font inventory can identify missing ToUnicode font records
complete authoritative evidence opens only the candidate-creation gate, not PASS
strategy request can be converted into candidate generation request
missing ToUnicode evidence blocks before generated script is allowed
attempt loop records max-attempt exhaustion without adoption/final update
```

## Tests not run in this environment

The container available to this assistant could not resolve github.com for cloning, and the live Docker/Hermes/Open WebUI runtime was not mounted. Therefore compile/runtime commands were not executed here.

Required follow-up commands to run locally inside the repo:

```bash
python3 -m py_compile \
  app/tools/orchestrate/remediate.py \
  app/tools/orchestrate/guarded_acceptance.py \
  app/tools/packaging/status_json_writer.py \
  app/tools/packaging/package_deliverables.py \
  app/tools/audit/font_tounicode_diagnostics.py
```

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_agent_candidate_repair_loop_policy.py \
  app/tools/tests/test_font_tounicode_diagnostics_policy.py \
  app/tools/tests/test_self_extension_executor.py \
  app/tools/tests/test_orchestrator_guarded_form_widget_policy.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py \
  app/tools/tests/test_lookup_repair_plan_guarded_candidates_policy.py \
  app/tools/tests/test_rule_repair_map_form_widget_metadata_policy.py \
  app/tools/tests/test_form_widget_structure_inspection_policy.py \
  app/tools/tests/test_form_widget_structure_repair_policy.py \
  app/tools/tests/test_verapdf_profile_accounting_policy.py \
  app/tools/tests/test_verapdf_iso_regression_review_policy.py \
  app/tools/tests/test_production_readiness_matrix_policy.py
```

```bash
PYTHONPATH=app python3 app/tools/tests/test_m1_gate_verdict.py
```

## Guardrail status

No private PDFs, workspace artifacts, generated PDFs, validator XML, parsed failures, profile-accounting JSON, guarded candidates, package ZIPs, or runtime outputs were intentionally added by this patch.

Files intentionally changed/added:

```text
app/tools/audit/font_tounicode_diagnostics.py
app/tools/tests/test_font_tounicode_diagnostics_policy.py
app/tools/tests/test_agent_candidate_repair_loop_policy.py
docs/H12_AGENT_GENERATED_CANDIDATE_REPAIR.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## Production-readiness statement

Production readiness is not claimed.

H12 proves that the codebase has a guarded agent-candidate loop and now has a target-specific safety gate for the preferred ToUnicode blocker. It also proves that, without deterministic font/content/text/render evidence, candidate creation for `PDF/UA-1/7.21.7` must stop truthfully instead of inventing a repair.

## Next patch

H13 should run the live WebUI or approved production-path substitute with the latest H11/H12 runtime artifacts available, generate the H12 ToUnicode readiness artifact from real qpdf/font/content evidence, and then either:

```text
1. invoke self_extension_executor.py run-attempts for PDF/UA-1/7.21.7 when the gate is READY_FOR_AGENT_CANDIDATE_CREATION, or
2. move to PDF/UA-1/7.21.4.1 only if real evidence proves ToUnicode repair remains unsafe.
```
