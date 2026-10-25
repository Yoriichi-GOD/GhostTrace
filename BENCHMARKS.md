# GhostTrace benchmark methods and checkpoints

The current submission candidate passes local strict validation for all 518 rows, with zero unresolved target diagnostics and no unread evidence files on the tested Windows OCR runtime. Contract validity is separate from semantic answer accuracy.

## Current submission measurements

- Public development samples: 29/32 status agreement; 8/32 exact ordered sequences; 68.32% step precision, 56.99% recall, 62.15% F1; 945/1365 positional fields correct (69.23%). Hidden-case accuracy is unknown.
- Separate populations: 100/100 project-authored scenario variants, 115/115 metamorphic/security probes, 18/18 built-in custom checks, 12/12 new submission regression tests, and 14/14 dashboard API checks.
- The measured final CLI generation took 8.465493 seconds including process startup, initialization, OCR, auditing and CSV serialization. This is a single local run, not a timing guarantee.
- Separate generation invocations produced byte-identical output. Clean extraction reproduced the submitted CSV and passed strict evaluation and API regression checks.
- Runtime model providers/calls/tokens/cost: none/0/0/USD 0.00. These figures exclude development-assistant usage and subscriptions.

See code/evaluation/evaluation_report.md, usage_report.md and submission_changes.md for definitions, evidence scope, test results, failures and tradeoffs.

## Reproduce

Supply the participant-facing dataset/ separately, then run from the extracted source root:

~~~text
python code/main.py --repo . --diagnostics unresolved.json
python code/evaluation/main.py --repo .
python -m unittest discover -s code/evaluation -p "test_regressions.py" -v
python scenario_suite.py --engine code --output runs/local-check/scenarios.json
python stress_suite.py --engine code --output runs/local-check/stress.json
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
python benchmark.py unique-run-tag
~~~

The CLI returns 2 for unresolved obligations or unread evidence; the evaluator fails strict errors. A completed benchmark runner only means measurements were saved, so inspect its contract_errors. Completed run tags cannot be overwritten. The benchmark runner checks all indexed predictions against exhaustive matching before recording a speed comparison.

## Frozen research checkpoint, retained separately

The earlier private paper and decks describe 10 unresolved target cases and 30 strict errors, 29/32 public statuses, 8/32 sequences, 63.82% step F1 and 70.24% field accuracy. At that earlier checkpoint three final outputs matched; median generation was 7.849 seconds and the median paired audit-only speed ratio was 8.52. Those timing figures do not describe the changed submission source.

The original improvement study moved project-authored scenarios from 56/100 to 100/100 and unsafe COMPLETE decisions from 32 to 0; robustness checks moved from 87/115 to 115/115. Reserved variants share the scenario families and were repeatedly reused, so they are not an independent holdout. GDPRbench, FEBRL4, ALCE and AgentDojo were references only and were not run natively.

The submission closes structural evidence gaps but raw public step/field agreement decreased. No public reference labels were rewritten, no organizer truth or case-ID shortcuts were used, and validation was not weakened. Do not combine populations into one accuracy score or transfer historical speedups to this checkpoint.
