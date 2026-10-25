> Historical frozen research checkpoint. The ten unresolved cases and metrics below describe an earlier version. See evaluation_report.md and submission_changes.md for the current source.

# Evaluation report

Generated: `2026-10-25T08:30:52+00:00`.

## Public sample replay

The replay uses only `dataset/sample_deletion_requests.csv` and its participant-facing `sample_output.csv`. It does not read organizer-only truth.

- Case-level deletion-status accuracy: **29/32 (90.62%)**.
- Exact step-sequence accuracy: **8/32 (25.00%)**.
- Step-level micro precision / recall / F1: **70.89% / 58.03% / 63.82%** (158 predicted steps, 193 reference steps). A step matches when all seven contract fields match.
- Field-value accuracy: **949/1351 (70.24%)**. Fields are compared by array position; missing positions count as incorrect.

## Output contract

**30 contract issue(s) found. This output is not ready to submit.** See the CLI output for details.
The validator checks the exact header, input ID coverage and order, valid JSON and operation/state pairs, concrete resource IDs, participant evidence IDs, source timestamps at or before audit_at, file/resource relevance, duplicate logical steps, phase ordering, and required phases for incomplete cases.
Complete rows without evidence-backed verification: **0**. These rows lack admissible state proof; a missing artifact or a record captured after audit_at cannot prove deletion.

## Additional custom cases

- PASS: explicit deletion: expected=True, actual=True.
- PASS: data export is not deletion: expected=False, actual=False.
- PASS: explicitly denied deletion: expected=False, actual=False.
- PASS: question alone is not authorization: expected=False, actual=False.
- PASS: French deletion request: expected=True, actual=True.
- PASS: historical email and audit cutoff: resolved_users=['custom_user'], future_email_excluded=True.
- PASS: evidence after audit cutoff excluded: selected=['evidence_before'].
- PASS: citation timestamps must be present and no later than audit cutoff: boundary accepted; later and missing source times rejected.
- PASS: strict validator detects repeated logical steps: duplicate_indices=[2].
- PASS: strict validator requires all incomplete phases: missing_after_removal=['VERIFICATION'].
- PASS: evidence manifest paths stay inside the supported corpus root: valid=True, traversal=path_traversal, absolute=absolute_path, extension=unsupported_extension.
- PASS: evidence manifest rejects missing files and duplicate IDs: source_errors=0, duplicate_detected=True, missing_detected=True.
- PASS: resource IDs are concrete, normalized, and include legal holds: indexed_ids=['search_021'].
- PASS: operational log pipe fields do not become resources or states: records=1, resource_id=search_123, state=not_found.
- PASS: identity-link candidates are exact, successful, and cutoff-bounded: candidate_ids=['activity_at_cutoff'].
- PASS: identity link selects only independently cutoff-admissible resource evidence: selected=['linked_state'].
- PASS: analytics policy keeps anonymization: action=ANONYMIZE.
- PASS: unknown restore/sync state remains a risk: unknown=True, explicitly_disabled=False.

Custom checks passed: **18/18**.

## Failures found and improvements made

- A broad time-neighborhood association joined unrelated global records. It was removed; direct subject matches and exact identity-link events select only same-resource artifacts that pass both audit-cutoff checks.
- Operations logs use a distinct time/level/system/trace/event layout. Parsing that layout separately prevents service names and event names from becoming shared resource IDs or resource states; trace-linked identifiers remain scoped to their trace.
- A local standard-library PDF text path and optional screenshot OCR were added. Windows uses its built-in OCR through the included PowerShell script; other platforms can use Tesseract. **0** evidence files remain unread in the current runtime.
- HTTP access/server failures no longer establish absence. Missing admissible state proof is flagged internally and returns a conservative INCOMPLETE CSV status without fabricated findings or citations.
- Explicit conflicting stable subject IDs and email substring matches are rejected. Polite negative requests do not authorize deletion.
- Replica/table scopes and simultaneous contradictory observations are preserved. Positive surviving copies are not erased by a negative lookup in another scope. Older negative account lookups do not add a new current verification obligation when a newer account observation exists.
- A missing required retained record produces an unresolved obligation, never a destructive delete recommendation. SQLite imports reject ATTACH/DETACH and file/extension helper functions.
- Indexed identity candidate selection retains the same final matching predicate. The benchmark harness compares all 518 outputs against exhaustive matching before claiming a speed benefit.
- The public reference includes an analytics deletion step where the policy specifies anonymization. Raw reference metrics are retained without rewriting expected answers. Other disputed mappings require independent review.
- The full output has evidence gaps: 0 rows are labeled COMPLETE without an evidence-backed verification step. They are flagged by the contract checker and are not upload-ready.
- 10 INCOMPLETE cases cannot supply a grounded full plan. Each missing required phase remains a hard validation error. Do not re-label the cases COMPLETE or invent steps to make the checker pass.

## Limits

These numbers describe 32 development cases only; hidden-case accuracy is unknown. Status accuracy is not evidence completeness. The deterministic offline solver does not assume an unread or unlinked source is empty. Insufficient-evidence diagnostics are separate from the challenge's three CSV statuses. Reserved synthetic variants use the same scenario generator and do not establish independent generalization. The package remains a development candidate while any strict check fails.
