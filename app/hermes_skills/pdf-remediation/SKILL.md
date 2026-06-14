---
name: pdf-remediation
title: PDF/UA Remediation — Job Runbook
description: >
  Operational runbook for running a PDF/UA remediation job end to end. Load
  this skill whenever a job message begins with "PDF:" or the task is to
  remediate, validate, preflight, fix, or package a PDF for accessibility.
  Covers running the orchestrator, reacting to DEVIATION and HERMES_REQUIRED
  signals, writing and registering new repair scripts when a strategy gap is
  found, and reporting the final summary.
user-invocable: true
metadata: {"hermes":{"requires":{"bins":["qpdf","java"],"env":["NVIDIA_API_KEY"]},"emoji":"♿"}}
---

# PDF/UA Remediation — Job Runbook

You are the remediation agent. The orchestrator runs the pipeline; your job
is to launch it, act on the signals only it can't resolve on its own, and —
when it hits a rule with no working repair — **write the missing repair
script yourself**, register it, and rerun. That last part is the core of this
system: the pipeline is designed to extend itself through you. An escalation
you can act on is your work queue, not a handoff.

Engineering invariants about the pipeline's internals (gate namespace, verdict
cascade, exit codes) live in `app/docs/PIPELINE_CONSISTENCY_CONTRACTS.md` —
that is developer reference, not needed to run a job. This runbook is what you
follow per job.

---

## 1. Run the job

**Derive metadata** from the source text (PyMuPDF is always available):
```bash
python3 -c "
import fitz
doc = fitz.open('/app/workspace/input/{TICKET}/{basename}.pdf')
for page in doc: print(page.get_text())
"
```
- `--title`: main visible heading (not a footer or filename)
- `--subject`: one sentence on the document's purpose
- `--keywords`: 4-8 comma-separated terms

**Run the orchestrator** — the only command needed; never run individual
audit/repair/QA scripts manually:
```bash
python3 /app/tools/orchestrate/remediate.py \
  /app/workspace {TICKET} "{basename}" \
  --title "..." --subject "..." --keywords "..."
```

The orchestrator runs as one blocking command; you will see the whole JSON
stream at once when it exits. Output JSON-only between steps; reserve prose for
the final summary, hard stops, and HERMES_REQUIRED reasoning.

---

## 2. On orchestrator exit — BEFORE writing any summary

**Read `$JOB/audit/hermes_signals.json`.** ($JOB is
`/app/workspace/jobs/{TICKET}_{basename}`.) This is the gate that decides
whether the job is actually finished:

- If it contains signals with `reconciliation: "active"` (or any signals, if
  that field is absent) whose `reason` is **actionable** (see the table
  below) — **the job is NOT finished.** Do the strategy work in section 3, do
  not summarize yet.
- Only when no active actionable signals remain — or every remaining one is
  genuinely unsolvable after a real attempt — proceed to the summary in
  section 4.

An `overall_result` of `ESCALATION` whose active signals are all actionable
means the pipeline is waiting on you to extend it. That is the design, not a
failure. Do not report it to the operator as terminal.

### Actionable vs terminal signal reasons

**ACTIONABLE — your work queue. Do the section-3 loop:**
- `manual_no_strategies` — rule is in the map but marked manual with no strategies
- `unknown_rule` — rule not in the map; research it, then design a strategy
- `all_strategies_exhausted` — every mapped strategy tried and failed
- `detector_mislabeled_no_repair` — the rule's only mapped tooling is a detector
  (writes no output PDF); a real repair must be designed. The signal's
  `detector_scripts` field names the evidence tooling that already exists
- `preflight_strategy_exhausted` — OCR preflight ran out; read `ocr_strategy_request.json`
- `residual_strategy_design_required` — post-repair residual rules need
  strategies; read `hermes_strategy_request.json`

**TERMINAL — genuine escalations; report to engineering, do not write more:**
- `per_rule_cap_reached` — 15 attempts on one rule
- `job_hard_cap_reached` — 50 total iterations

A nonzero exit (especially exit 3) after HERMES_REQUIRED is a controlled
strategy-action pause, never a terminal failure. If an artifact says
`operator_question_allowed: false`, never ask the operator to choose.

---

## 3. Resolve an actionable HERMES_REQUIRED signal

For each active actionable signal:

1. **Read the strategy request artifact** named in the signal
   (`hermes_strategy_request.json`, `ocr_strategy_request.json`, or the path in
   the signal's `artifacts`). It contains the rule, failure evidence, sample
   objects, and what's been tried.
2. **Check existing repair scripts first** in `/app/tools/repair/`. Reuse
   before writing. If a script exists but wasn't mapped to this rule, the fix
   may be a rule-map entry, not new code.
3. **Write a new, focused repair script** in `/app/tools/repair/` following the
   standard contract:
   ```
   <input.pdf> <output.pdf> [--out results.json]
   ```
   It must print one JSON object on stdout with at least
   `{"result": "PASS|FIXED|PARTIAL|FAIL", "strategy": "...", "reason": "..."}`,
   exit 0 on success, nonzero on failure, and **never modify the input file**.
   Invoke pikepdf/pdfplumber-dependent scripts knowing the orchestrator runs
   them under the pinned interpreter; write standard `python3` shebangs.
4. **Iterate against the current document** until the rule resolves or you
   establish it cannot be automated. Verify with `py_compile` before running
   (large patches can silently inject bad indentation).
5. **Generalize** — strip document-specific values (object IDs, page counts,
   font names from this one PDF). Re-validate the generalized version on the
   current document.
6. **Register** the strategy in `/app/tools/audit/rule_repair_map.json` under
   the matching rule's `strategies` array; flip `manual: true` to `false` if it
   was manual. Set `resolvability` appropriately (`effective` once proven).
7. **Rerun the orchestrator** (section 1). On its next exit, repeat the
   section-2 check. Loop until no active actionable signals remain.

If a rule genuinely cannot be automated, do not register a script; let the
orchestrator emit `ESCALATION_REPORT.md` and report it as a real escalation.

### Constraints on script writing
- Existing repair scripts are read-only — add a new script, don't patch an old one.
- Never hardcode document-specific values.
- New scripts emit JSON on stdout including `strategy` and a `reason` on failure.
- Scratch/helper files go under `$JOB/scratch/` — never in `workspace/input/`,
  the `/app` root, or anywhere under `/app/tools/` except a new `repair/` script.

---

## 4. Final summary (only after section 2 clears)

Once `"phase": "COMPLETE"` is out AND no active actionable signals remain, the
`overall_result` in STATUS.json is authoritative — do not re-adjudicate
individual gate values. Report, in order:

1. Outcome line — `Job Complete — PASS` / `REVIEW_REQUIRED` / `FAIL` / `ESCALATION`
2. Document name and ticket
3. Deliverable paths — remediated PDF (PASS only), audit report, escalation report (if any)
4. Doc tags assigned by the classifier
5. Alt text outcome — how many figures received alt text, if any
6. Items requiring human review — any `REVIEW_REQUIRED` flags, listed plainly
7. Required post-delivery steps — always: "Run axesCheck and PAC 2024 before final sign-off."

Never write "no further action needed" — external validators always run before sign-off.

### Outcomes

| Outcome | Meaning | Output | Action |
|---|---|---|---|
| `PASS` | Compliant | `output/{TICKET}_remediated/{name}_remediated.pdf` + audit report | Upload after axesCheck + PAC 2024 |
| `REVIEW_REQUIRED` | Compliant, human inspection needed | `output/{TICKET}_remediated/review/` | Operator inspects first |
| `FAIL` | Critical gate failed | `output/{TICKET}_remediated/failed/` — no remediated PDF | Do not upload; escalate |
| `ESCALATION` (actionable) | Strategy work pending | `failed/` + `ESCALATION_REPORT.md` | Return to section 3 — this is yours |
| `ESCALATION` (cap/unsolvable) | Genuinely terminal | `failed/` + `ESCALATION_REPORT.md` | Engineering review |

---

## Non-negotiables

- Target **PDF/UA-1** unless the operator explicitly says PDF/UA-2.
- OCR runs BEFORE all structural repair; never after.
- Never modify `workspace/input/` — source is read-only.
- Never hand off a document where veraPDF PDF/UA still fails — the orchestrator
  enforces this (FAIL produces no remediated PDF).
- `PASS_WITH_MIXED_PAGES` means the document has both text and image pages; do
  not claim "OCR was performed" from it.
- `table_semantics REVIEW_REQUIRED` and informational pre-fails are inputs the
  orchestrator already weighed — do not re-narrate them as new problems.
