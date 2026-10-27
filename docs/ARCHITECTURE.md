# How GhostTrace works

[Project overview](../README.md) · [Setup](SETUP.md) · [API contract](../code/dashboard/API_CONTRACT.md)

## One auditor, two interfaces

The offline CLI and local browser API call the same Python `Auditor`. The frontend displays and filters server projections; it does not produce deletion verdicts.

```text
Participant corpus: requests, identities, policy, evidence
                         |
                 EvidenceIndex + Auditor
                         |
              +----------+-----------+
              |                      |
       CLI: output.csv       DashboardService
                                     |
                           Local HTTP API + browser
```

| Module | Responsibility |
| --- | --- |
| [code/main.py](../code/main.py) | Deletion-intent checks, policy application, audit decisions, step ordering and CSV serialization |
| [code/evidence.py](../code/evidence.py) | Identity history, path-bounded evidence loading, format parsing, matching, timestamps and resource observations |
| [code/windows_ocr.ps1](../code/windows_ocr.ps1) | Local native Windows OCR bridge for PNG evidence when Tesseract is unavailable |
| [code/dashboard/service.py](../code/dashboard/service.py) | Masked, case-scoped summaries, source metadata, graph, timeline, commands and reports |
| [code/dashboard/serve.py](../code/dashboard/serve.py) | Dynamic loopback server, origin/Host checks, API routes and allowlisted static assets |
| [code/dashboard/web/](../code/dashboard/web/) | Native HTML, CSS, JavaScript and OpenAPI schema; no bundler or frontend decision engine |
| [code/evaluation/main.py](../code/evaluation/main.py) | Public-reference comparisons, output-contract checks, custom checks and diagnostic reports |

## The audit workflow

1. Decide whether the request actually authorizes deletion. Export, correction and opt-out requests are not automatically deletion requests.
2. Resolve current and historical identifiers from the supplied identity snapshot and audit history.
3. Match evidence to the subject and resource. Scope observations to their source/table/replica and admit evidence only under the audit cutoff rules.
4. Apply the supplied policy: delete, redact, anonymize, retain or preserve the permitted account tombstone. Consider active synchronization and restore risks.
5. Emit `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE`, plus the challenge's ordered steps. Unresolved proof obligations are separate diagnostics; missing evidence is not proof of deletion.

The output is `case_id,deletion_status,steps_json`. Findings cite evidence. Remediation and future verification steps are proposals with empty evidence IDs. The system never executes those proposals.

## Browser boundary

The standard-library server binds loopback and uses one origin for the UI and `/api/ghosttrace/v1`. Browser responses mask identifiers and expose an allowlist of case-linked metadata. There is no generic file route, raw source-text viewer or mutation endpoint.

The command dock parses a controlled grammar, previews the result and rejects destructive or cross-case requests. `INVESTIGATE` synchronously replays the selected case through the auditor; it is not an LLM tool loop. Wispr can dictate text into that input, just as it can dictate development prompts.

Coverage counters distinguish observed case references from corpus files available by cutoff. They are not an erasure percentage. A dashboard-only **INSUFFICIENT EVIDENCE** diagnostic can flag a COMPLETE engine row without admissible verification proof; it does not rewrite the original engine status or CSV.

See the [route contract](../code/dashboard/API_CONTRACT.md) and [OpenAPI schema](../code/dashboard/web/openapi.json) for request/response details.

## Implementation status and limitations

| Area | Current boundary |
| --- | --- |
| Evidence | Heuristic parsers and matching; not comprehensive discovery across real enterprise systems |
| Correctness | 32 public development cases; exact sequences disagree on 24/32; hidden-case accuracy unknown |
| Validation | Solver and strict checker share parsing; not independent proof of semantic completeness |
| OCR | Full-evidence results recorded on Windows; cross-platform parity unverified |
| Lineage | Engine relationships, not an independently inferred causal remediation graph |
| Inspector | Masked metadata; full redacted excerpts and raw document/image previews absent |
| Runtime | Local, synchronous investigation replay; no streaming/cancellation or production connectors |
| Models and hosting | No live Nebius/NVIDIA inference, autonomous model agent or public deployment in this checkout |
| Demo data | Authored test fixtures exist; no built-in synthetic demo gallery |

There are no mocked model responses being presented as live inference. The documentation's synthetic case is processed by the real auditor, with its origin explicitly labeled. New capabilities described in extension briefs remain planned until implemented and verified.

The [Noir redesign record](../code/dashboard/NOIR_REDESIGN.md) preserves historical UI verification. Its case counts belong to that earlier snapshot; use the [submission usage report](../code/evaluation/usage_report.md) for the later frozen output distribution.
