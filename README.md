# GhostTrace

**Deletion isn't a status. It's something you prove.**

GhostTrace is a local, read-only deletion-audit tool with an illustrated Noir investigation workspace. It checks supplied evidence against a deletion request, resolves current and historical identity references, applies policy, and presents findings with source references and audit cutoffs.

> **Development candidate.** The latest full-corpus check has 30 strict contract errors across 10 unresolved cases. GhostTrace is not an accepted contest submission, a compliance certification, or a production erasure service.

## What you can do

- Search and filter cases, compare a reported workflow status with the engine's finding, and inspect proof coverage.
- Resize desktop panels with the dividers; use the expand button beside the tabs for more investigation space. Drag the map's bottom handle to adjust its height. Dividers also support arrow keys and double-click to reset.
- Explore engine-backed identity/resource relationships in a selectable graph with zoom, pan, fit, filtering, and a relationship-table alternative.
- Review separate event and evidence-capture clocks, including sources excluded after the cutoff.
- Inspect case-scoped, masked source metadata and policy/action tables.
- Type or dictate a command with Wispr Flow, preview its read-only intent, then run the supported query.
- Preview and download a sanitized Markdown audit report.

The dashboard never executes deletion or remediation. Source records remain local. Recommendations and future verification are distinguished from completed actions.

## Run locally

Requires **Python 3.10+**. The runtime uses the Python standard library; there is no Node build step, provider API key, or hosted backend.

### 1. Supply the participant dataset

The contest dataset, generated answers, personal development transcripts, and local verification captures are intentionally excluded from this repository.

Obtain the participant-facing dataset from the [original HackerRank challenge repository](https://github.com/interviewstreet/hackerrank-orchestrate-october26) and place its dataset/ directory in this repository root. See [problem_statement.md](problem_statement.md) for the expected input contract. Do not replace it with organizer-only truth.

### 2. Start the browser workspace

~~~powershell
python code/dashboard/serve.py
~~~

Open the actual browser address printed by the launcher. It binds loopback only and asks the operating system for an available address. Browser requests use the same origin and the /api/ghosttrace/v1 namespace.

The first launch builds the evidence index. Its status reflects real engine work, with no simulated findings. Stop only the process you started when you are finished.

Windows image extraction uses the included native OCR bridge. Other systems can use Tesseract if installed; full cross-platform OCR parity has not been established.

### 3. Run the command-line auditor

~~~powershell
python code/main.py --diagnostics unresolved.json
python code/evaluation/main.py
~~~


The auditor produces the challenge's three-column CSV. It exits nonzero for unresolved proof obligations or unread evidence. The evaluator also fails when the output contract is not satisfied. A CSV file being written does not mean it is ready to submit.

## Verification

### Synthetic checks — no contest dataset required

~~~powershell
python scenario_suite.py --engine code --output runs/check/scenarios.json
python stress_suite.py --engine code --output runs/check/stress.json
~~~

The repository includes 100 project-authored scenario variants and 115 metamorphic/security probes. They are development checks, not independent real-world benchmarks. Both scripts print their pass totals; inspect the reported results.

### Dashboard integration checks — participant dataset required

~~~powershell
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
~~~

The API suite tests the real auditor bridge, case scoping, masking, commands, report export, same-origin guards, public-asset allowlisting, and rejected file traversal.

Measured development results:

| Population / check | Result |
| --- | --- |
| Public sample status agreement | 29/32 |
| Public sample exact ordered step sequences | 8/32 |
| Public sample seven-field step F1 | 63.82% |
| Public sample positional field accuracy | 70.24% |
| Current full-corpus strict validation | 30 errors across 10 unresolved cases |
| Dashboard API regressions | 14/14 in the recorded local check |

Hidden-case accuracy is unknown. Sample disagreement and unresolved proof obligations remain visible. See [BENCHMARKS.md](BENCHMARKS.md) and the [development evaluation report](code/evaluation/benchmark_study_report.md) for scope and limitations.

## Architecture

~~~text
Browser workspace
    -> Same-origin, loopback-only Python API
        -> Sanitized case/evidence projections
            -> Existing Python Auditor
                -> Identity history + policy + cutoff-admissible evidence
~~~

The browser does not classify deletion outcomes. It renders the original engine's projections. UI diagnostics are separate from the challenge's three scored verdicts.

- code/main.py: deterministic audit decisions and ordered output.
- code/evidence.py: identity/evidence parsing and matching.
- code/dashboard/service.py: read-only, masked case projections.
- code/dashboard/serve.py: local HTTP server and explicit static-file routes.
- code/dashboard/web/: native HTML/CSS/JavaScript workstation.
- code/evaluation/: public-sample metrics, strict validation and development report.
- public/assets/: supplied individual illustrations and self-hosted fonts.

## Current limitations

- Ten target cases still lack a grounded complete plan under strict validation.
- Raw evidence excerpts and redacted source-image/PDF previews are not implemented; the inspector exposes allowlisted metadata.
- The graph shows existing engine relationships and does not infer new recreation dependencies.
- Remediation uses scored serialization order; a separate dependency-aware execution planner is not implemented.
- There is no asynchronous job/SSE/cancellation workflow.
- The dashboard's separate synthetic-demo gallery is not implemented. The test fixtures above are not presented as contest findings.
- Reports are Markdown, not PDF.
- Real microphone/Wispr hardware and a physical mobile device were not verified by the automated checks. Voice-driven build footage is submitted separately by the participant.

## Design and third-party resources

Neutral black panels, warm gold accents, independent cosmic/ghost illustrations, and responsive layouts form the Noir visual system. Inactive controls remain muted; captions use brighter text and fonts are 1px larger than the original design baseline.

Cormorant Garamond, Manrope, and IBM Plex Mono are self-hosted with their OFL notices in public/assets/fonts/. The application makes no third-party font request.

The project was developed against HackerRank Orchestrate's **Ghost Data Still Exists** challenge. This public source repository is separate from the final contest upload package. No provided dataset, generated prediction file, local chat log, credentials, or build footage is included here.
