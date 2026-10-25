# GhostTrace — Noir UI redesign

Implemented in the existing local Python/JavaScript application. This is a UI redesign, not a replacement forensic engine.

## Definition of Done

- [x] Neutral black glass panels, silver/cream text and restrained gold accents.
- [x] Cosmic background and the six approved individual artwork assets integrated.
- [x] Correct live GHOSTTRACE wordmark; the misspelled raster reference is never served.
- [x] Locally hosted Cormorant Garamond, Manrope and IBM Plex Mono with bundled OFL notices.
- [x] Navigation, case search, engine-result filters, pagination and queue collapse.
- [x] True unselected/empty queue/empty inspector states; evidence replaces decoration.
- [x] Case metadata, original verdicts, proof denominators and excluded future evidence preserved.
- [x] Interactive engine-backed SVG lineage: zoom, pan, fit, relationship filtering, node/edge selection, connected-edge highlighting and an accessible relationship table.
- [x] Two-clock timeline, policy/action tables and sanitized Markdown report preview/download.
- [x] Typed/dictated command previews, real engine replay, explicit rejection messages and intent-only history.
- [x] Keyboard tab navigation, mobile navigation with Escape/outside dismissal, reduced motion and persistent compact command dock.
- [x] Existing API regressions plus public asset allowlist/traversal regression checks.
- [x] Browser verification of real cases and responsive layouts.
- [x] Auditor, evidence parser and submission artifact hashes unchanged.

## Architecture and choices

The existing dashboard uses native HTML, CSS and JavaScript with a Python standard-library server. Retained that architecture. Added no JavaScript runtime dependencies, package manager, framework migration or external application service.

The existing Python Auditor and service projections remain the sole source of verdicts, source references, graph relationships, clocks and recommendations. JavaScript only arranges and filters those projections. No frontend deletion decisions or fabricated edges.

UI helpers now include artwork/empty-state builders, a consistent SVG icon helper, a lineage canvas, a mobile navigation drawer, queue controls and a sanitized report preview. The lineage canvas uses SVG attributes rather than inline styles, so the existing strict content security policy remains intact.

Artwork and fonts are served from an explicit 13-file allowlist. There is no directory-serving route. The typo logo, evidence files, logs and arbitrary paths remain unavailable.

Requests are origin-relative under the existing GhostTrace namespace. The launcher still binds loopback and asks the OS for an available address. No process is stopped to obtain a port.

Fonts: Fontsource packages 5.3.0, seven Latin WOFF2 files with three OFL notices. See [Cormorant Garamond](https://fontsource.org/fonts/cormorant-garamond), [Manrope](https://fontsource.org/fonts/manrope), [IBM Plex Mono](https://fontsource.org/fonts/ibm-plex-mono). Original artwork is preserved.

## Verification

The pre-change suite passed 11/11. The redesigned suite passed 14/14 against the real local corpus. Tests exercise engine-equivalent steps, masking, evidence scoping, command grammar, origin protection, read-only routes, exports, dynamic-port configuration and allowlisted asset delivery.

JavaScript syntax and Python compilation checked. This application has no TypeScript, bundler or configured lint command; no claim is made that those nonexistent checks ran.

Real browser checks:

- Initial queue: 518 cases from the engine, with no automatically fabricated selected case.
- case_33: original INCOMPLETE verdict; source evidence_23 opened from its actual graph.
- Graph zoom changed viewBox; fit reset it; source selection highlighted actual connections and removed inspector artwork.
- Timeline: five entries for case_33, four explicitly excluded after cutoff; event and capture clocks rendered separately.
- Search with no match: books illustration and Reset filters; existing selection retained.
- Pagination: page 2 reached and page 1 restored.
- COMPLETE engine filter: 154 matches in this local snapshot; proof-gap labels remain distinct.
- Destructive command rejected with the actual server explanation.
- Safe SHOW_LINEAGE command routed to the real view.
- INVESTIGATE replay executed through the Python Auditor and returned measured elapsed time.
- Sanitized Markdown report downloaded; masked subject and no-records-modified notice checked.
- Mobile menu opened/closed and main content was inert while navigation was open.
- All three fonts loaded; artwork decoded.
- Reduced-motion emulation returned animation-name: none.
- No horizontal page overflow at 1920×1080, 1440×900, 1366×768, 1024×768, 768×1024, 390×844 and 320×740.
- Desktop command dock remained in the viewport; tablet/mobile dock uses a fixed compact treatment.
- Final browser console contained no errors.

Development screenshots were captured against the local corpus and are retained privately; they are not included in this public repository.

## Performance scope

No new runtime JavaScript library. Fonts are local and loaded with font-display: swap; only required weights are served. Artwork uses the supplied original PNGs. Source transfer sizes are recorded in the verification manifest. A production bundle does not exist in this architecture. No Lighthouse score, benchmark improvement or internet-deployment performance claim is made.

## Remaining product limits

The original engine does not provide independently redacted source excerpts/previews, dependency-aware remediation ordering, asynchronous jobs/SSE/cancellation or an isolated synthetic demo pack. The UI states these limits. Demo Cases does not invent examples or mix fixtures into the contest corpus.

The graph displays the engine's current identity/resource/source relationships. It does not infer new recreation dependencies or classify unsupported risk paths. Confirmed and engine-correlated connections retain their engine-provided labels.

The timeline renders supplied observations and cutoff exclusions; it does not recompute the engine at an arbitrary historical time. Reports remain Markdown, not PDF. Real microphone/dictation hardware and screen-reader software were not tested. Mobile checks used browser viewport emulation, not a physical device.

Local service bindings were inventoried before/after the final launch. This is not a claim that two independently developed unrelated web projects were exercised end-to-end.

## Run

From the repository root:

~~~powershell
python code/dashboard/serve.py
~~~

Open the actual address printed by that process. An already-running server loads its routes at startup; use a newly launched instance for the new artwork/font allowlist. Existing server processes are left alone.

~~~powershell
python -m unittest discover -s code/dashboard/tests -p "test_*.py" -v
~~~

