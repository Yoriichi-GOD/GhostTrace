# GhostTrace 👻

**Deletion isn't a status. It's something you prove.**

A local, read-only investigation workspace that checks whether a reported deletion is supported by evidence. GhostTrace links current and historical identifiers to surviving records, applies deletion policy, and shows findings, proposed remediation and verification checks.

## Wispr Flow × Hacker House Goa

Development was directed through spoken instructions dictated with Wispr Flow to an AI coding assistant. The assistant generated and revised code; the workflow was build, test, inspect the result, then dictate the next correction. The participant has confirmed that the recording captures actual voice-driven development. The public build-process video link will be added before the wildcard form is submitted.

Wispr is the dictation tool used during development. The application itself runs offline and makes no model API calls. No Wispr SDK, Gemini, NVIDIA or OpenRouter integration is required to run it.

## Try one investigation

1. Open a case and compare the reported deletion status with the evidence-backed audit result.
2. Follow its identifier/resource relationships, inspect source metadata and check the audit cutoff.
3. Review the ordered recommendations and export a sanitized Markdown report.

For example, in the supplied challenge workload, `case_104` reports COMPLETE while the local auditor finds an attributable search record, an analytics profile and an active data flow. This is a demonstration of the submitted code on that participant dataset, not a claim about a real company's systems.

The UI supports resizable panels, an expanded investigation view, a graph/table relationship view and a timeline. Its command box accepts read-only requests typed or dictated through Wispr, previews the interpreted intent, and rejects destructive commands. Voice interaction with the finished app is separate from the recorded development process.

**GhostTrace never executes deletions or remediation.** It presents recommendations and future checks; it does not certify that a deletion has happened.

## Run locally

Requires Python 3.10 or newer. The tested full-evidence environment was Windows with the included native OCR bridge. Other systems may use Tesseract; full OCR parity across platforms has not been verified.

Obtain the participant-facing `dataset/` from the [HackerRank challenge starter](https://github.com/interviewstreet/hackerrank-orchestrate-october26) and place it in this repository root. The dataset is not redistributed here. Use participant-facing evidence only.

~~~powershell
python code/dashboard/serve.py
~~~

Open the actual loopback address printed by the launcher. The server chooses an available port; there is no fixed-port requirement, Node build, hosted backend or provider API key.

To generate and evaluate the challenge output:

~~~powershell
python code/main.py --repo . --diagnostics unresolved.json
python code/evaluation/main.py --repo .
~~~

The generator exits nonzero for unresolved proof obligations or unread evidence. The evaluator fails contract errors. A CSV being written is not by itself proof that the answers are correct.

## What the current code has proved locally

| Check | Recorded result |
| --- | --- |
| Full target output | 518 rows; 0 local strict contract errors |
| Unresolved target diagnostics / unread evidence files | 0 / 0 on the tested Windows run |
| Public sample status agreement | 29/32 |
| Public exact ordered sequences | 8/32 |
| Public step F1 / positional field accuracy | 62.15% / 69.23% |
| Project-authored scenarios | 100/100 |
| Metamorphic/security probes | 115/115 |
| Built-in custom checks / new submission regressions | 18/18 / 12/12 |
| Dashboard API regressions | 14/14 |

The exact submission source was replayed from a clean extraction and reproduced the 518-row output byte for byte. These populations are separate. The 100 scenarios were reused during development and are not an independent holdout. Hidden-case accuracy is unknown, and structural validity does not establish semantic correctness. No external GDPRbench, FEBRL4, ALCE or AgentDojo score is claimed.

See [current evaluation](code/evaluation/evaluation_report.md), [runtime usage](code/evaluation/usage_report.md), [changes after the frozen research study](code/evaluation/submission_changes.md) and [benchmark methods](BENCHMARKS.md). The public step/field agreement decreased from the earlier research checkpoint while target structural failures were closed; both results are retained.

## Reproduce the software checks

The following first three commands use project-authored synthetic data and do not require the contest dataset:

~~~powershell
python scenario_suite.py --engine code --output runs/check/scenarios.json
python stress_suite.py --engine code --output runs/check/stress.json
python -m unittest discover -s code/evaluation -p "test_regressions.py" -v
~~~

Dashboard integration tests additionally require the participant dataset:

~~~powershell
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
~~~

## Architecture and limits

The same Python auditor drives both the CLI and browser API. It resolves identity history, parses evidence, enforces capture/event cutoffs, applies policy and serializes findings and recommendations. The browser renders masked, case-scoped projections; it does not generate verdicts.

Important remaining limits include public-sample sequence disagreement, parser coverage, unverified cross-platform OCR parity, and incomplete real-world validation. Evidence inspection currently exposes allowlisted metadata rather than raw document/image previews. The relationship graph shows existing engine links; it is not an inferred causal recreation model. The product is a local investigation prototype, not a production compliance service.

## Provenance

The problem, participant dataset and starter specification come from HackerRank Orchestrate's Ghost Data Still Exists challenge. Wispr Flow was used for voice-driven development with an AI coding assistant; this does not imply a partnership or endorsement. The displayed screenshot shows masked fictional participant-case metadata. Cormorant Garamond, Manrope and IBM Plex Mono are self-hosted with their OFL notices in `public/assets/fonts/`.

Private transcripts, structured traces, generated prediction files, footage and credentials are excluded from this public repository. The private research paper and decks describe a separate frozen checkpoint, not a publication or contest acceptance.
