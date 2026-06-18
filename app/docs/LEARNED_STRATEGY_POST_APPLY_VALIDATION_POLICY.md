# Learned Strategy Post-Apply Validation Policy

Patch 26A validates a Patch 25A reviewed sidecar apply after the apply has already been recorded. It is a hardening and soak gate for reviewed sidecar adoption only.

## Scope

This policy allows post-apply validation, isolated rollback proof, and a sidecar production-readiness gate for a single job, candidate, and rule.

It does not allow package-integrated adoption, default learned execution, global candidate approval, rule-map mutation, app/tools/repair mutation, production repair replacement, verdict softening, package/status authority mutation, or rollback against authoritative files.

The normal remediation pipeline final PDF remains authoritative. The reviewed adopted PDF remains a sidecar artifact unless a later explicit patch changes package/status authority.

## Required source artifacts

The post-apply validator reads only the reviewed-apply sidecar area:

- `JOB/audit/learned_strategy_reviewed_apply/apply_manifest.json`
- `JOB/audit/learned_strategy_reviewed_apply/apply_audit.json`
- `JOB/audit/learned_strategy_reviewed_apply/backup_manifest.json`
- `JOB/audit/learned_strategy_reviewed_apply/rollback_manifest.json`
- `JOB/audit/learned_strategy_reviewed_apply/post_apply_validation.json`
- `JOB/audit/learned_strategy_reviewed_apply/adopted_final.pdf`
- `JOB/audit/learned_strategy_reviewed_apply/backups/normal_final_backup.pdf`

The command requires operator, reviewer, approver, candidate id, rule id, expected adopted output hash, expected normal backup hash, expected apply manifest hash, and expected post-apply validation hash.

## Written artifacts

The command may write these reviewed sidecar artifacts:

- `JOB/audit/learned_strategy_reviewed_apply/post_apply_soak_report.json`
- `JOB/audit/learned_strategy_reviewed_apply/rollback_proof_report.json`
- `JOB/audit/learned_strategy_reviewed_apply/production_readiness_gate.json`

The rollback proof may also write inside `JOB/audit/learned_strategy_reviewed_apply/rollback_proof_isolated/` only.

## Validation requirements

The validator must verify that the adopted sidecar PDF exists and matches the expected learned trial/test hash; the normal backup exists and matches the expected original normal final PDF hash; the backup and rollback manifests exist; the rollback manifest references the normal backup; the Patch 25A post-apply validation exists and passed; qpdf can be repeated on `adopted_final.pdf`; reviewer and approver identities are recorded and separate; and protected files are not mutated during validation.

Protected targets include `app/tools/audit/rule_repair_map.json`, `app/tools/repair`, and common job package/status locations.

## Rollback proof requirements

Rollback proof is isolated validation only. It may copy `adopted_final.pdf` and `backups/normal_final_backup.pdf` into `rollback_proof_isolated`, simulate replacement inside that directory, and verify that the restored hash equals the backup hash.

Rollback proof must not delete the real `adopted_final.pdf`, must not restore over the authoritative normal final PDF, must not mutate package/status, and must not execute rollback against authoritative files.

## Required safety flags

The post-apply and readiness artifacts must include these safety flags:

```json
{
  "post_apply_validation_only": true,
  "reviewed_sidecar_adoption_validated": true,
  "package_integrated_adoption_enabled": false,
  "default_learned_execution_enabled": false,
  "global_candidate_approved": false,
  "global_candidate_production_ready": false,
  "global_apply_ready": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false,
  "rollback_execution_against_authoritative_files": false,
  "authoritative_rollback_performed": false,
  "normal_pipeline_final_pdf_remains_authoritative": true
}
```

The rollback proof artifact must include:

```json
{
  "rollback_proof_scope": "isolated_validation_directory_only",
  "rollback_execution_against_authoritative_files": false,
  "authoritative_rollback_performed": false,
  "rollback_restored_hash_matches_backup": true
}
```

## Readiness gate

The readiness gate may emit only one of these terminal states:

- `sidecar_reviewed_adoption_production_ready`
- `sidecar_reviewed_adoption_blocked`

It must not emit `package_integrated_adoption_ready`, `global_learned_execution_ready`, or `candidate_globally_approved`.

## Local validation command pattern

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_post_apply_validation.py \
  --job-dir workspace/jobs/MM-17179 \
  --repo-root . \
  --mode all \
  --operator "<operator>" \
  --reviewer "<reviewer>" \
  --approver "<approver>" \
  --candidate-id "<candidate-id>" \
  --rule-id "<rule-id>" \
  --expected-adopted-output-hash "<sha256>" \
  --expected-normal-backup-hash "<sha256>" \
  --expected-apply-manifest-hash "<sha256>" \
  --expected-post-apply-validation-hash "<sha256>"
```

A passing `--mode all` run records the post-apply soak report, isolated rollback proof report, and sidecar production-readiness gate report. A blocked or failed-closed run records why it could not declare reviewed sidecar adoption production-ready.
