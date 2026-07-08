# V6 Runbook

1. Confirm active source PDFs.
2. If the operator requests evidence-only self-extension smoke, run `/app/tools/orchestrate/self_extension_smoke_boundary.py` with `--expected-target-rule` and do not write/register repair scripts.
3. Run classification and source audit.
4. Preserve native text wherever possible.
5. Repair tags/structure, tables, annotations, figures, language, metadata, and contrast.
6. Run qpdf.
7. Run veraPDF PDF/UA.
8. If PDF/UA fails during normal remediation, stop and remediate, do not hand off. During evidence-only self-extension smoke, do not source-patch; record the blocker in `smoke_boundary`, `target_rule_check`, and `self_extension`.
9. Run pinned WCAG profile.
10. Run metadata Info + XMP parity audit after final save.
11. Run contrast/table/native text/preservation/visual QA gates.
12. Package outputs with logs, status JSON, rules copy, manifest, and checksums.
13. Report external axesCheck/PAC separately.

## Evidence-only self-extension smoke guardrails

When the run is H13/H13S/H13T evidence-only smoke:

- do not write source repair scripts
- do not register repair scripts
- do not edit `app/tools/audit/rule_repair_map.json`
- do not adopt generated candidates
- do not update the final PDF from failed generated candidates
- do not claim self-extension ran unless `self_extension_run_attempts_result.json` or equivalent attempt evidence exists
- if the expected target rule differs from the actual residual rule, report the mismatch instead of switching targets
- if the system asks to write/register a repair, record that action as prohibited by smoke mode
