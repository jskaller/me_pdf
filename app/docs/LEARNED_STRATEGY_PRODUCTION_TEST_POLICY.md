# Learned Strategy Production Test Policy

Patch 19A adds a controlled, opt-in production-testing diagnostic mode for learned strategy candidates.

This mode is not adoption. It is a sidecar-only workflow that evaluates a learned replacement-trial output after the existing diagnostic stack has already produced complete production-testing readiness evidence.

## Required opt-in chain

`--learned-production-test` requires all of the following flags:

- `--learned-execution-dry-run`
- `--learned-replacement-trial`
- `--learned-production-readiness`

If any prerequisite is absent, the orchestrator must fail closed before normal execution begins.

## Authoritative output boundary

The normal final PDF remains authoritative. `STATUS.json`, package deliverables, verdicts, rule maps, activation metadata, and `app/tools/repair/*` must not be mutated by production-test mode.

The production-test report must include these policy flags:

```json
{
  "production_test_only": true,
  "normal_final_pdf_remains_authoritative": true,
  "candidate_is_adoptable": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false
}
```

## Artifact

The diagnostic report is written to:

```text
JOB/audit/learned_strategy_production_test_report.json
```

Learned trial PDFs may be copied only under:

```text
JOB/audit/learned_strategy_production_test/
```

These copies are evidence for controlled production testing only and are never package deliverables.

## Blocking behavior

Production-test mode blocks when:

- the production readiness report is missing;
- readiness does not contain `production_testing_evidence_complete`;
- the replacement-trial report is missing;
- a complete readiness record has no learned trial output;
- protected package/status snapshots change during the diagnostic.

Blocking the production-test diagnostic must not alter the normal remediation result.
