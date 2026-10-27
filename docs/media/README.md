# Product screenshot provenance

[Project overview](../../README.md) · [Reviewer walkthrough](../REVIEWER_GUIDE.md)

Both PNGs are **actual screenshots of the working local GhostTrace dashboard**, captured on 27 October 2026 at a 1600 × 1000 desktop viewport. They are not design mockups or generated illustrations.

| File | What it shows |
| --- | --- |
| [investigation-overview.png](investigation-overview.png) | Workflow claim COMPLETE, real auditor result INCOMPLETE, case context and proof coverage |
| [evidence-lineage.png](evidence-lineage.png) | Engine-linked current/historical identifiers, surviving search resource and admissible source metadata |

Input: the existing [scenario_suite.py](../../scenario_suite.py) `fixture(root, 'historical_alias', 0)`. Its generated request ID `test_historical_alias_0` was changed to `case_1` to satisfy the dashboard's numeric case-ID contract. No evidence facts or expected results were altered. The expected-label return value was discarded; the dashboard ran the normal auditor on the fixture files.

The fixture uses fictional `example.test` identities. The application masks them at the browser boundary. No challenge participant data, private document, credential, transcript or source path is shown. The screenshot's “PRIVATE LOCAL CORPUS” text is the application's normal label; this particular corpus was authored synthetic test data.

Application files were copied byte for byte into an isolated local review directory. No runtime code or product feature was changed to produce the captures. Capture requests were restricted to loopback; no external preview service was used.

The ghost illustrations and cosmic background are existing interface artwork. They are decoration, not evidence diagrams. The relationship graph itself renders the auditor's links. These captures do not establish a built-in demo gallery, real-world accuracy or production readiness.
