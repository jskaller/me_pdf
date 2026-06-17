# Learned Strategy Adoption Policy Design — Patch 20A

Patch 20A defines policy requirements for any future learned-strategy adoption workflow. It is design-only and non-operative.

## Non-operative boundary

Patch 20A does not implement adoption dry-run, adoption apply, rollback execution, production repair replacement, final PDF replacement, verdict softening, package/status mutation, rule-map mutation, or activation mutation.

The normal final PDF remains authoritative. The existing package/status/verdict flow remains authoritative.

## Artifact

The design command may write only this audit artifact:

```text
JOB/audit/learned_strategy_adoption_policy_design.json
```

This artifact may record whether the evidence package is complete for policy discussion. It must not say a candidate is approved, adoptable, production-ready, ready for adoption, adoption-unblocked, or apply-ready.

## Allowed outcomes

Allowed design-only outcomes are limited to:

```text
policy_design_recorded
policy_design_incomplete
policy_design_blocked
```

## Forbidden states

The following terminal states are forbidden in Patch 20A:

```text
approved
adoptable
production_ready
ready_for_adoption
adoption_unblocked
apply_ready
```

## Mandatory future evidence requirements

Any future adoption workflow must define and require, at minimum:

- Reviewer identity.
- Separate approver identity, in a future patch, not used for approval in Patch 20A.
- Candidate id.
- Rule id.
- Production readiness report hash.
- Production test report hash.
- Production test review report hash.
- Normal final PDF hash.
- Learned trial/test PDF hash.
- Normal-vs-learned comparison summary.
- Manual review notes.
- Known risks.
- Rollback requirements.
- Backup requirements.
- Explicit future apply flag requirement.
- Explicit future rollback command requirement.

## Required safety flags

Every Patch 20A design artifact must state:

```json
{
  "adoption_policy_design_only": true,
  "adoption_plan_created": false,
  "adoption_apply_performed": false,
  "candidate_is_adoptable": false,
  "candidate_approved": false,
  "candidate_production_ready": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false,
  "normal_final_pdf_remains_authoritative": true
}
```

## Mutation policy

Patch 20A authorizes no mutations outside its design artifact.

Future adoption work must define exact allowed mutation targets, exact backup requirements, exact rollback requirements, exact apply flags, and exact protected-mutation checks before any adoption apply command can exist.

Patch 20A specifically must not mutate:

- Authoritative normal final PDF.
- Authoritative `STATUS.json`.
- Package deliverables.
- `app/tools/repair/*`.
- `app/tools/audit/rule_repair_map.json`.
- Learned activation metadata.

## Future command family

A future adoption workflow, if ever implemented, must use an explicit command family such as:

```text
tools/audit/learned_strategy_adoption_* --apply
```

Patch 20A does not create that workflow.
