# GhostTrace development benchmark checkpoint

This is an offline development candidate. It is **not submission-ready**: strict validation reports 30 missing-phase errors across 10 target cases with insufficient admissible state evidence. The program keeps these obligations unresolved rather than emitting invented resources, findings, or completion proof.

## Run

Use Python 3.10+ from the repository root. Windows screenshot OCR uses the included script and may require permission to access the native OCR service. No provider key, subscription, or model download is required by the solver.

```text
python code/main.py --diagnostics unresolved.json
python code/evaluation/main.py
python scenario_suite.py --engine code --output runs/local-check/scenarios.json
python stress_suite.py --engine code --output runs/local-check/stress.json
python benchmark.py replay-unique-tag
python -m unittest discover -s code/dashboard/tests -v
```

The generator exits with code 2 when unresolved proof obligations or unread evidence remain. The evaluator must continue to fail unresolved contract checks. A successful benchmark-runner process means the measurements were saved; inspect `contract_errors` to assess readiness. Completed runner tags cannot be overwritten.

## Measured checkpoint

The 32 public development cases produce 29/32 status agreement, 8/32 exact ordered sequences, 63.82% seven-field step F1, and 70.24% positional field accuracy. Hidden-case accuracy is unknown. The status decline from the earlier 32/32 baseline exposes three previously unproven COMPLETE decisions.

The frozen synthetic generator produces 25 scenario families with four parameter variants each. Passes improve from 56/100 to 100/100; unsafe COMPLETE decisions within those truth-known scenarios fall from 32 to 0. The 50 reserved parameter variants were also repeatedly evaluated during development and do not constitute an independent holdout. Metamorphic/security probes improve from 87/115 to 115/115. Existing custom checks pass 18/18 and dashboard API regressions pass 14/14. Keep these populations separate.

Three repeated final runs produce identical output bytes. Their median full generation time is 7.849 seconds, range 7.842–8.525 seconds, including initialization, OCR, auditing, and CSV serialization. OS cache state and external machine load were not controlled. Within paired runs, indexed matching produces the exact same 518 outputs as exhaustive matching. The median paired case-evaluation speed ratio is 8.52, excluding initialization/OCR. This is a local audit-phase comparison, not a universal end-to-end speedup.

## Interpretation and gates

- Freeze source, input, evaluator, and output hashes before comparing runs.
- Keep exact-sequence and field metrics alongside status agreement. A status alone does not prove deletion.
- Do not weaken validation or use private organizer truth, sample-label shortcuts, or other contestants' answers.
- New cases require independently specified expected states, operations, identifiers, and evidence cutoffs.
- Do not reuse this development suite as an independent generalization claim.
- Resolve the 10 remaining target cases from permitted evidence or obtain an official clarification. Do not package the candidate as ready while validation fails.
- External GDPRbench, FEBRL4, ALCE, and AgentDojo are research references. No native score for those benchmarks is claimed.

Full-run model calls, input/output tokens, and provider charges are zero for this deterministic solver. Assistant-development usage and subscription costs are outside that measurement.
