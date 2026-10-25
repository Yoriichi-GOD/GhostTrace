# GhostTrace local dashboard — Noir

This is a loopback-only, read-only browser view over the existing `code/main.py` `Auditor`. It uses one origin for the static UI and the `/api/ghosttrace/v1` API. The launcher asks the operating system for an available loopback port, prints the actual browser address, and does not inspect or stop other servers.

## Run it

From the GhostTrace repository root, run:

```powershell
python code/dashboard/serve.py
```

Open the exact dashboard address printed by the launcher. The engine builds its local evidence index and audits the cases in the background; the page displays real loading state and does not substitute mock findings. Stop this run with Ctrl+C in the terminal that started it. The dashboard uses no API keys and sends no corpus data to a network service.

The launcher accepts an optional `--repo` path for running the dashboard code against a separate GhostTrace checkout. Normal use needs no override. Binding remains loopback-only.

## What is implemented

- Case search, status filters, paging, engine verdict, audited cutoff, and masked subject label.
- Same-engine case details, evidence-backed steps, coverage counts with an explicit denominator note, identity/resource lineage table, and two-clock event timeline.
- Evidence lookup by a case-linked reference only. The server returns allowlisted metadata and masked identifiers; it never returns source paths or raw evidence text.
- A typed command preview for the documented read-only intents. Wispr Flow can enter text in the textarea; there is no claimed Wispr API or fabricated microphone state.
- A selected-case investigation command that synchronously replays the current Python auditor and reports the actual elapsed time.
- Sanitized Markdown report download; reports say no records were modified.
- Local HTTP security headers, loopback and Host checks, same-origin checks for the only POST route, request-size limit, and no mutation endpoints.
- Port discovery at runtime; all browser API paths are origin-relative.

## Known limits and QA state

The Noir redesign keeps the existing accessible native HTML/CSS/JavaScript architecture. See [NOIR_REDESIGN.md](NOIR_REDESIGN.md) for the design, verification evidence and requirement checklist. The current engine does not supply fully redacted excerpts, a dependency-aware remediation graph, worker cancellation/SSE, or an independently generated synthetic demo pack. The inspector therefore withholds raw excerpts and shows allowlisted metadata only. The lineage graph is an interactive SVG canvas over the existing engine relationships, with zoom, pan, fit, filters, source selection and a keyboard-readable relationship table. The UI marks engine `COMPLETE` cases with no admissible verification reference as **INSUFFICIENT EVIDENCE**; it does not rewrite the engine result or CSV.

The dashboard is not a submission artifact and should stay outside `code.zip`. It does not mutate the dataset or root output files. Browser data is not saved in local storage. Development screenshots are retained privately and are not bundled here. Build footage is submitted separately.

| Requirement | Status |
| --- | --- |
| Dynamic loopback browser URL | Verified; final launcher printed and opened its runtime-selected address |
| Existing Python engine as single authority | Verified; integration suite passed against the real corpus |
| Case, evidence, lineage, timeline, and action views | Implemented with current engine limits |
| Masked browser boundary and no source-file route | Verified; contact masking, case scoping, and file-route rejection tests passed |
| Safe typed/Wispr text commands | Verified; preview and real investigation replay were exercised; destructive and cross-case requests fail closed |
| Sanitized Markdown report | Verified; API test confirms no raw contact value and no-records-modified notice |
| Frontend architecture and graph | Native JavaScript retained; interactive engine-backed SVG graph with accessible table |
| Full redacted excerpts and synthetic demo pack | Not implemented; explicitly disclosed |
| Synthetic demo pack and synthetic screenshots | Not implemented |
| Browser desktop/tablet/mobile flows | Verified through live browser controls; screenshots and details in NOIR_REDESIGN.md |
| Physical mobile device and multi-project end-to-end collision replay | Not run |

Run the backend contract checks from the repository root:

```powershell
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
```

The suite binds its own temporary loopback endpoint. It does not prescribe a development port.
