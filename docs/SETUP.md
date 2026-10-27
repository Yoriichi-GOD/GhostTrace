# Run GhostTrace locally

[Project overview](../README.md) · [Reviewer guide](REVIEWER_GUIDE.md) · [Architecture](ARCHITECTURE.md)

Run commands from the repository root. On systems where Python 3 is named `python3`, substitute that executable for `python`.

## Requirements

- Python **3.10 or newer**. The recorded submission run used Python 3.14.6 on Windows 11; this is not a claim of a freshly tested cross-platform matrix.
- No third-party Python package, Node build or model API key is required for the auditor and dashboard.
- To inspect the challenge workload, obtain the participant-facing corpus separately from the [HackerRank starter repository](https://github.com/interviewstreet/hackerrank-orchestrate-october26). Do not use organizer-only truth.
- For PNG evidence, the parser prefers Tesseract if it is on PATH. On Windows it otherwise uses the included PowerShell bridge to native Windows OCR. Non-Windows PNG support needs Tesseract. PDF text uses the local parser with an optional `pdftotext` fallback. Readability and full OCR parity are not guaranteed on every machine.

```sh
git clone https://github.com/Yoriichi-GOD/GhostTrace.git
cd GhostTrace
python --version
```

## Check the code without the dataset

These commands use existing project-authored synthetic fixtures and temporary test data:

```sh
python -m unittest discover -s code/evaluation -p "test_regressions.py" -v
python scenario_suite.py --engine code --output runs/local-check/scenarios/result.json
python stress_suite.py --engine code --output runs/local-check/stress/result.json
```

Expected suite sizes are 12 regressions, 100 scenarios and 115 robustness probes. Inspect the reported passed/total counts: the scenario scripts save JSON and do not make every failed assertion a nonzero process exit. Passing these suites does not establish independent real-world accuracy.

## Supply the participant corpus

Place the supplied files directly under `dataset/`, preserving the evidence manifest's relative paths:

```text
GhostTrace/
  code/
  dataset/
    deletion_requests.csv
    sample_deletion_requests.csv
    sample_output.csv
    user_identities.csv
    user_audit_log.csv
    system_activity.csv
    deletion_rules.csv
    evidence_files.csv
    evidence/
```

The public clone intentionally has no participant dataset or ready-made result gallery. Its dashboard requires this corpus; the documentation screenshots alone are not an interactive demo.

## Open the dashboard

```sh
python code/dashboard/serve.py
```

Open the exact `http://127.0.0.1:…` address printed by the launcher. It binds loopback and selects a free port. Wait for indexing and case auditing to finish, then select a case. Stop your server with Ctrl+C in its terminal. Do not expose this development server to a public interface.

An optional `--repo PATH` points at another complete local GhostTrace checkout with its `code/` and `dataset/`. It is not a switch to a hosted backend.

## Generate and evaluate without replacing recorded reports

**Default paths can overwrite results:** the CLI defaults to root `output.csv`, and the evaluator defaults to the tracked evaluation report. Use the explicit paths below for a new local run. These commands are for an authorized local corpus; do not run them against a frozen submission folder.

```sh
python -c "from pathlib import Path; Path('runs/local-review').mkdir(parents=True, exist_ok=True)"
python code/main.py --repo . --output runs/local-review/output.csv --diagnostics runs/local-review/diagnostics.json
```

Then evaluate that CSV, sending **all** generated reports to the new run directory:

```sh
python code/evaluation/main.py --repo . --output runs/local-review/output.csv --report runs/local-review/evaluation_report.md --coverage-report runs/local-review/case_coverage.md --sample-diff runs/local-review/sample_diff.md --manifest runs/local-review/run_manifest.json
```

The CLI exits `2` for unresolved obligations or unread evidence. The evaluator exits nonzero for strict errors or failed custom checks. A written CSV alone does not establish correctness.

## Dashboard contract checks

With the corpus installed:

```sh
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
```

The 14 API tests create their own temporary loopback server. They check engine agreement, case scoping, masking, command interpretation, origin guards, static asset access and report boundaries. Browser rendering and physical-device testing are separate forms of evidence.

For timing and paired matching studies, see [benchmark methods](../BENCHMARKS.md). Use a new run tag and inspect contract errors; do not transfer older speedups to changed code.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing dataset file or index failure | Corpus location, required CSVs and manifest-relative evidence paths |
| Unread PNGs or unresolved diagnostics | OCR tool availability and the diagnostic JSON; a missing source does not prove absence |
| Browser cannot connect | Use the address from the currently running terminal; no fixed port is promised |
| Local socket permission error | Local security/network policy; it is not evidence of a wrong audit result |
| Typed command rejected | Select a case and use supported read-only wording; destructive and cross-case requests are rejected |

`dataset/`, `runs/`, credentials and generated submission files are excluded by the existing ignore rules. Keep private transcripts, databases and archives out of commits.
