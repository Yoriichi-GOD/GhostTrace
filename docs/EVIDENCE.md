# Evidence, benchmarks and deliverables

[Project overview](../README.md) · [Reviewer guide](REVIEWER_GUIDE.md) · [Safe reproduction commands](SETUP.md#generate-and-evaluate-without-replacing-recorded-reports)

## Current recorded submission checkpoint

These measurements were recorded on **25 October 2026**. This documentation pass preserves the original reports and output artifacts; it does not rerun or improve their benchmark numbers.

| Population / measure | Result | Source and interpretation |
| --- | --- | --- |
| Full target output | 518 rows; 0 local strict errors; 0 unresolved diagnostics | [Usage report](../code/evaluation/usage_report.md); structural checks, not hidden-label correctness |
| Public request statuses | 29/32 (90.62%) | [Evaluation report](../code/evaluation/evaluation_report.md); development data |
| Exact ordered step sequences | 8/32 (25.00%) | Same report; all sequence fields and ordering must match |
| Step micro precision / recall / F1 | 68.32% / 56.99% / 62.15% | 161 predicted and 193 reference steps; all seven fields define a step match |
| Positional fields | 945/1365 (69.23%) | Array-position comparison; missing positions are incorrect |
| Authored scenarios | 100/100 | [Scenario generator](../scenario_suite.py); 25 families × 4 variants, reused during development |
| Metamorphic/security probes | 115/115 | [Stress suite](../stress_suite.py); a separate authored population |
| Built-in custom checks | 18/18 | [Evaluation report](../code/evaluation/evaluation_report.md) |
| Submission regression tests | 12/12 | [Regression suite](../code/evaluation/test_regressions.py) |
| Dashboard API tests | 14/14 | [API suite](../code/dashboard/tests/test_api.py); software behavior, not scientific accuracy |
| CLI generation time | 8.465493 seconds | [Usage report](../code/evaluation/usage_report.md); one Windows run including startup, initialization, OCR, audit and serialization |
| Runtime model use | 0 calls, 0 tokens, USD 0.00 model cost | Same report; excludes development assistants, subscriptions and local compute |

The output distribution is 144 COMPLETE, 364 INCOMPLETE and 10 NOT_APPLICABLE. The recorded output SHA256 is `40a0976c92bb6cc8c2842a7c5e2aa931a36f98bc06c0323b39a3157e2cc1c5c2`. Separate CLI invocations and a clean source extraction reproduced that output byte for byte, as documented in the usage report and [benchmark methods](../BENCHMARKS.md). Reproducibility is not semantic correctness.

Do not merge the populations into one accuracy score. The scenario variants share a generator and were reused; their reserved split is not an independent holdout. The validator shares parsing logic with the solver. No external GDPRbench, FEBRL4, ALCE or AgentDojo score is claimed.

## The improvement that also regressed a metric

The later submission closed 10 unresolved cases and 30 strict errors. Public status agreement and exact sequences stayed at 29/32 and 8/32; step F1 decreased from 63.82% to 62.15%, and positional field agreement from 70.24% to 69.23%.

Read [submission changes](../code/evaluation/submission_changes.md) for intent/parser fixes, the evidence-grounded catalog finding and the unresolved semantic tradeoffs. Raw reference answers were not rewritten to improve the score.

## Frozen research study

The [historical study report](../code/evaluation/benchmark_study_report.md) and [benchmark methods](../BENCHMARKS.md) describe an earlier checkpoint. Its 7.849-second median generation and 8.52× paired audit-only ratio do **not** describe the changed submission source. The study's private paper and decks remain attached to that older checkpoint; they are not publications or evidence of contest acceptance.

## Find the deliverable

| Deliverable | Availability |
| --- | --- |
| Working source, CLI and browser UI | [code/](../code/) and [setup guide](SETUP.md) |
| Product review | [Walkthrough](REVIEWER_GUIDE.md) and [actual synthetic-screen captures](media/README.md) |
| Voice-driven development recording | [Wispr Flow × GhostTrace on YouTube](https://youtu.be/rw3gSNBh9HQ); build process, not a hosted product demo |
| Current evaluation and runtime usage | [Evaluation](../code/evaluation/evaluation_report.md) · [Usage](../code/evaluation/usage_report.md) |
| Benchmark method and checkpoint comparison | [Methods](../BENCHMARKS.md) · [Submission changes](../code/evaluation/submission_changes.md) |
| API and historical UI verification | [API contract](../code/dashboard/API_CONTRACT.md) · [Noir record](../code/dashboard/NOIR_REDESIGN.md) |
| Challenge contract | [Problem statement](../problem_statement.md) |
| Submitted ZIP/CSV, transcripts, agent traces, paper, editable decks and interview guide | Private handoff artifacts outside this public repository; intentionally not uploaded or linked as public downloads |

## Reproduce without changing history

[Setup](SETUP.md) separates dataset-free software checks from corpus-dependent integration and evaluation. Use a new ignored `runs/` directory and explicit report paths. The benchmark runner requires a unique run tag. Read the saved contract errors and limitations before citing any number.
