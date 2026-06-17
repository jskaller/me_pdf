# Patch 11A: Learned Strategy Activation Metadata

Patch 11A is activation metadata only. It does not add runtime discovery or runtime use of activated learned strategies.

Allowed scope:

- activation dry-run
- activation apply
- deactivation
- rule-map backups before activation/deactivation metadata mutation
- audit artifacts under the job audit directory when `--job-dir` is provided

Out of scope:

- runtime discovery
- runtime use of activated learned strategies
- copying staged scripts into `app/tools/repair/*`
- final PDF adoption
- broad orchestrator or verdict rewrites

## Patch 12A discovery cross-reference

Patch 12A may discover active learned strategy metadata only after staged-path,
script-existence, SHA-256, static-check, and dirty/failed/refusal-marker
validation. Discovery is not execution: it does not import staged scripts, shell
out to staged scripts, mutate `app/tools/repair/*`, mutate final PDFs, adopt
final PDFs, or change normal remediation behavior.
