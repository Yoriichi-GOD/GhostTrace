# GhostTrace browser API contract

All routes share the local page's origin and the `/api/ghosttrace/v1` prefix. Responses use `Cache-Control: no-store`. The API only reads the participant-facing local corpus through the existing `Auditor`; it never writes the corpus or submission output. Browser payloads use allowlisted metadata and masked identifiers. No route serves arbitrary files.

## Routes

| Method | Path suffix | Behavior |
| --- | --- | --- |
| GET | `/health` | Real index phase, number of audited cases, engine name, and local data mode. |
| GET | `/runtime-config` | Origin-relative prefix and truthful feature flags. |
| GET | `/openapi.json` | OpenAPI description for the read-only browser contract. |
| GET | `/cases?query=&status=&page=&page_size=` | Masked, paginated case summaries. |
| GET | `/cases/{case_id}` | Engine verdict, UI proof diagnostic, steps, coverage, policy, graph, and timeline. |
| GET | `/cases/{case_id}/graph` | Case-linked identity/resource/evidence relationships. |
| GET | `/cases/{case_id}/timeline` | Event time, capture time, and cutoff admission/exclusion. |
| GET | `/cases/{case_id}/coverage` | Observed references, manifest availability, and verification denominator. |
| GET | `/cases/{case_id}/steps` | Engine-emitted steps, separate from the CSV serialization. |
| GET | `/cases/{case_id}/evidence/{evidence_ref}` | Case-authorized masked evidence metadata. |
| GET | `/cases/{case_id}/report` | Sanitized Markdown report. |
| POST | `/investigations` | Synchronously replays one selected case through the existing auditor; returns real elapsed time and no source mutations. |
| POST | `/commands/interpret` | Parses a controlled command and returns a no-side-effects preview only. |

The `/commands/interpret` POST body is `{ "text": string, "case_id": string }`. It accepts only `INVESTIGATE`, `EXPLAIN_FINDING`, `SHOW_LINEAGE`, `SHOW_EVIDENCE`, `SHOW_POLICY`, `SHOW_AS_OF`, `SHOW_REMEDIATION`, and `EXPORT_SANITIZED_REPORT`. The UI first displays the preview. `INVESTIGATE` then calls `/investigations` with `{ "case_id": string }`, which synchronously replays that case through the existing auditor and returns observed elapsed time and a result summary. The UI performs all other work through read-only GET routes. Cross-case commands, ambiguous text, destructive verbs, malformed IDs, and oversized requests fail closed.

## Redaction boundary

The service never returns request text, original email/phone values, arbitrary evidence fields, raw extracted text, filesystem paths, credentials, or log contents. Subject email labels are masked. Evidence fields are selected from a small server-side allowlist. Rendered API text is inserted as text nodes. The evidence route requires a valid case ID and a reference linked to that case; there is no dataset path parameter or generic file endpoint.

Coverage fields distinguish manifest files available by cutoff from sources actually observed for a case. Neither count means data was erased. A dashboard-only `INSUFFICIENT EVIDENCE` diagnostic preserves the engine's original `deletion_status` and flags a `COMPLETE` result with no admissible evidence-backed verification step.
