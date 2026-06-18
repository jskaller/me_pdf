# Learned Strategy Evidence Hash Policy

Patch 22A records a sidecar-only evidence hash artifact for the learned-strategy adoption/apply chain.

The artifact is written to:

```text
JOB/audit/learned_strategy_evidence_hashes.json
```

This artifact is evidence-only. It does not approve a candidate, does not make a candidate adoptable, does not mark a candidate production-ready or apply-ready, does not create backups, does not execute rollback, does not mutate the rule map, does not mutate `app/tools/repair`, does not mutate package/status artifacts, and does not adopt any final PDF.

Allowed outcomes:

```text
evidence_hashes_recorded
evidence_hashes_incomplete
evidence_hashes_blocked
```

Forbidden states and outcomes include approval, adoptability, production readiness, apply readiness, adoption unblocking, rollback readiness, actual apply, rollback execution, and backup creation.

The artifact records each expected evidence item with:

```text
path
sha256
exists
source_artifact
verified_at
missing_reason
```

Missing evidence is incomplete, not failed-open. Hash completion means only that the dry-run simulation can refer to verified evidence. It never means apply readiness.
