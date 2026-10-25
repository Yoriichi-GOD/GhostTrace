# Final full-dataset usage and cost report

Generated: 2026-10-25T11:31:28.651502+00:00.

This report describes the actual run that produced the separate submission output.csv, not the historical CSV in the development repository root.

- Command: `python code/main.py --repo . --diagnostics runs/submission-final/diagnostics.json`
- Runtime: Python 3.14.6 on Windows-11-10.0.26200-SP0.
- Generation elapsed time: **8.465493 seconds**, measured around the CLI subprocess, including interpreter startup, evidence initialization, local OCR, auditing and CSV serialization. This single-run wall time is not a latency guarantee.
- Output: **518 rows**, sorted by case_id; 144 COMPLETE, 364 INCOMPLETE, 10 NOT_APPLICABLE.
- Output SHA256: `40a0976c92bb6cc8c2842a7c5e2aa931a36f98bc06c0323b39a3157e2cc1c5c2`.
- Generation exit code: 0. Strict evaluation exit code: 0. Strict errors: 0. Unresolved target diagnostics: 0.
- Evidence files unread by the current runtime: 0. Parsed resource observations: 2974.
- A second independently invoked CLI generation reproduced the preceding full benchmark output byte for byte.

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Estimated total cost USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| None (offline solver) | None | 0 | 0 | 0 | 0 | 0.00 |
| Overall | N/A | 0 | 0 | 0 | 0 | 0.00 |

Average tokens per request: 0. Estimated model cost per request: USD 0.00. Local CPU/OCR electricity, development-assistant usage and user subscriptions are not included in model inference cost. No live model inference or external OCR was invoked by the solver. No credentials are needed to reproduce the submitted solver.

Usage counts apply to the submitted program run only. They do not describe the AI coding assistants used to build the project; those assistants are documented separately in log.txt and the structured development sessions.
