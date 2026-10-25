(() => {
  "use strict";
  const API = "/api/ghosttrace/v1";
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = { page: 1, pageSize: 20, total: 0, query: "", status: "", selected: "", detail: null, tab: "overview", history: [], navView: "investigations", busy: false, listRequest: 0, caseRequest: 0, evidenceRequest: 0, items: [], loadingCase: false };

  function el(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  }
  function button(text, className, onClick, attrs = {}) {
    const item = el("button", className, text);
    item.type = "button";
    for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
    item.addEventListener("click", onClick);
    return item;
  }

  const iconPaths = {
    folder: ["M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z", "M3 9h18"],
    layers: ["m12 3 10 5-10 5L2 8l10-5Z", "m2 12 10 5 10-5", "m2 16 10 5 10-5"],
    nodes: ["M12 7v5M5 12h14M5 12v5M19 12v5", "M9 2h6v5H9zM2 17h6v5H2zM16 17h6v5h-6z"],
    shield: ["M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6l-9-4Z", "m8 12 3 3 5-6"],
    report: ["M14 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9l-7-7Z", "M14 2v7h7M7 13h10M7 17h7"],
    sparkles: ["m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z", "M21 2v4M19 4h4"],
    lock: ["M6 10V7a6 6 0 0 1 12 0v3", "M4 10h16v12H4zM12 14v4"],
    search: ["M21 21l-5-5", "M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"],
    filter: ["M3 3h18l-7 8v9l-4 2V11L3 3Z"],
    database: ["M21 6c0 2-4 4-9 4S3 8 3 6s4-4 9-4 9 2 9 4Z", "M3 6v12c0 2 4 4 9 4s9-2 9-4V6M3 12c0 2 4 4 9 4s9-2 9-4"],
    clock: ["M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z", "M12 6v6l4 2"],
    panel: ["M3 3h18v18H3zM9 3v18M6 7v4"], close: ["m6 6 12 12M18 6 6 18"],
    menu: ["M4 6h16M4 12h16M4 18h16"], terminal: ["m5 7 5 5-5 5M13 17h6"], arrow: ["M5 19 19 5M5 5h14v14"]
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
    for (const d of iconPaths[name] || iconPaths.report) {
      const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", d); svg.append(path);
    }
    return svg;
  }
  function hydrateIcons() {
    document.querySelectorAll("[data-icon]").forEach(item => {
      const svg = icon(item.dataset.icon); if (item.className) svg.setAttribute("class", "icon " + item.className); item.replaceWith(svg);
    });
  }
  function artwork(file, className) {
    const img = el("img", className); img.src = "/assets/ghosttrace/" + file; img.alt = ""; img.decoding = "async"; return img;
  }
  function emptyWorkspace() {
    const box = el("div", "investigation-empty");
    box.append(artwork("ghost-central-evidence.png"), el("span", "eyebrow", "FOLLOW WHAT REMAINS"), el("h2", "", "Select a case to begin"), el("p", "", "Choose an investigation from the queue. We'll follow the traces, one source at a time."));
    return box;
  }
  function clearCase() {
    state.caseRequest++; state.evidenceRequest++; state.selected = ""; state.detail = null; state.loadingCase = false;
    $(".investigation-panel").removeAttribute("aria-busy");
    $("#case-title").textContent = "Select a case"; $("#case-index-label").textContent = "/ —";
    $("#case-subtitle").textContent = "Every trace has a story. Follow the evidence.";
    $("#verdict-badge").textContent = "WAITING"; $("#verdict-badge").className = "verdict-badge unresolved";
    for (const id of ["subject-label","reported-status","audit-time","authorization","metric-observed","metric-available","metric-proof","metric-future"]) $("#" + id).textContent = "—";
    $("#command-scope").textContent = "select a case"; $("#cutoff-chip").textContent = "AS OF —"; $("#clear-case").hidden = true;
    $("#inspector-hint").textContent = "A finding is only as strong as its source.";
    $("#evidence-detail").replaceChildren(emptyInspector()); renderEvidenceRefs([]); renderCases(state.items); setTab("overview");
    setCommandFeedback("Select a case to preview a read-only command.");
  }
  async function request(path, options = {}) {
    const response = await fetch(API + path, { cache: "no-store", ...options });
    const type = response.headers.get("content-type") || "";
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      if (type.includes("json")) {
        const body = await response.json().catch(() => ({}));
        message = (typeof body?.error === "string" ? body.error : body?.error?.message) || message;
      }
      throw new Error(message);
    }
    return type.includes("json") ? response.json() : response.text();
  }

  function showNotice(message, tone = "info") {
    const bar = $("#notice-bar"); bar.hidden = !message; bar.textContent = message || "";
    bar.className = "notice-bar" + (tone === "error" ? " error" : "");
    if (message) bar.append(button("×", "notice-dismiss", () => { bar.hidden = true; }, { "aria-label": "Dismiss notification" }));
  }

  function statusTone(value) {
    if (value === "COMPLETE") return "complete";
    if (value === "INCOMPLETE") return "incomplete";
    if (value === "INSUFFICIENT EVIDENCE") return "gap";
    return "unresolved";
  }
  function formatTime(value) {
    if (!value) return "Not available";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
  }

  async function checkHealth() {
    try {
      const health = await request("/health");
      const footer = $(".rail-footer");
      footer.classList.toggle("ready", health.status === "ready");
      footer.classList.toggle("failed", health.status === "failed");
      $("#engine-label").textContent = health.status === "ready" ? "Engine connected" : health.status === "failed" ? "Engine failed" : `Engine ${health.status.replaceAll("_", " ")}`;
      const index = health.index || {};
      const progress = index.total ? Math.min(100, Math.round((index.completed / index.total) * 100)) : 0;
      $("#startup-progress").value = progress;
      $("#startup-count").textContent = index.total ? `${index.completed || 0} / ${index.total} cases audited by the real engine` : "No findings are being simulated.";
      if (health.status === "ready") {
        $("#startup-copy").textContent = "The evidence index is ready. Loading your investigation queue.";
        if (await loadCases()) {
          $("#startup-panel").hidden = true;
          $("#workspace").hidden = false;
          return true;
        }
        return false;
      }
      if (health.status === "failed") {
        $("#startup-panel").classList.add("failed");
        $("#startup-panel h1").textContent = "Engine did not start";
        $("#startup-copy").textContent = health.error || "The local engine reported a failure. No demo result has been substituted.";
        return true;
      }
      const phases = { loading_evidence: "Loading the local evidence index.", auditing_cases: "Running each case through the existing Python auditor.", starting: "Preparing the existing Python auditor." };
      $("#startup-copy").textContent = phases[health.status] || "The local engine is warming up.";
      return false;
    } catch (error) {
      $("#startup-copy").textContent = `${error.message}. Retry will continue polling the local engine.`;
      return false;
    }
  }

  async function pollStartup() {
    const done = await checkHealth();
    if (!done) window.setTimeout(pollStartup, 1200);
  }


  async function loadCases(resetPage = false) {
    const requestId = ++state.listRequest;
    if (resetPage) state.page = 1;
    const params = new URLSearchParams({ page: String(state.page), page_size: String(state.pageSize) });
    if (state.query) params.set("query", state.query);
    if (state.status) params.set("status", state.status);
    try {
      const payload = await request("/cases?" + params);
      if (requestId !== state.listRequest) return false;
      state.items = payload.items || []; state.total = payload.total;
      renderCases(state.items); $("#case-count").textContent = String(payload.total);
      $("#page-label").textContent = payload.page + " / " + Math.max(1, Math.ceil(payload.total / state.pageSize));
      $("#previous-page").disabled = state.page <= 1; $("#next-page").disabled = state.page * state.pageSize >= state.total;
      return true;
    } catch (error) { if (requestId === state.listRequest) showNotice(error.message, "error"); return false; }
  }
  function renderCases(items) {
    const list = $("#case-list"); list.replaceChildren();
    if (!items.length) {
      const empty = el("div", "queue-empty");
      empty.append(artwork("ghost-cases-books.png"), el("h3", "", "No cases in queue"), el("p", "", "No cases match your search or filter."));
      empty.append(button("Reset filters", "text-button", () => {
        state.query = ""; state.status = ""; $("#case-search").value = ""; $("#status-filter").value = ""; loadCases(true);
      })); list.append(empty); return;
    }
    for (const item of items) {
      const row = button("", "case-row" + (item.case_id === state.selected ? " selected" : ""), () => loadCase(item.case_id),
        { role: "option", "aria-selected": String(item.case_id === state.selected), "aria-label": item.case_id + " · " + item.ui_verdict });
      row.append(el("span", "case-id", item.case_id), el("span", "case-arrow", "↗"),
        el("span", "case-verdict " + statusTone(item.ui_verdict), item.ui_verdict), el("span", "case-reported", "REPORTED " + (item.reported_status || "—")));
      list.append(row);
    }
  }
  async function loadCase(caseId) {
    if (!caseId) return;
    const requestId = ++state.caseRequest; state.evidenceRequest++; state.loadingCase = true;
    $(".investigation-panel").setAttribute("aria-busy", "true");
    try {
      const detail = await request("/cases/" + encodeURIComponent(caseId));
      if (requestId !== state.caseRequest) return;
      state.detail = detail; state.selected = caseId; $("#clear-case").hidden = false;
      $("#command-scope").textContent = caseId; $("#case-index-label").textContent = "/ " + (detail.data_mode === "private_local_corpus" ? "PRIVATE" : "DEMO");
      $("#case-title").textContent = detail.case_id;
      $("#case-subtitle").textContent = detail.deletion_authorized ? "Deletion request authorized · reviewed by the local engine" : "No deletion authorization identified by the engine";
      $("#verdict-badge").textContent = detail.ui_verdict; $("#verdict-badge").className = "verdict-badge " + statusTone(detail.ui_verdict);
      $("#subject-label").textContent = detail.subject_label_masked; $("#reported-status").textContent = detail.reported_status || "—";
      $("#audit-time").textContent = formatTime(detail.audit_at); $("#cutoff-chip").textContent = "AS OF " + formatTime(detail.audit_at);
      $("#authorization").textContent = detail.deletion_authorized ? "Authorized" : "Not identified";
      $("#metric-observed").textContent = detail.source_coverage.observed_for_case;
      $("#metric-available").textContent = detail.source_coverage.manifest_files_available_by_cutoff;
      $("#metric-proof").textContent = detail.source_coverage.checks_with_admissible_evidence + " / " + detail.source_coverage.verification_checks;
      $("#metric-future").textContent = detail.source_coverage.future_direct_matches_excluded;
      renderTab(); renderEvidenceRefs(detail.evidence_refs || []); renderCases(state.items);
      $("#inspector-hint").textContent = "Select a linked source. Only masked, allowlisted metadata is shown.";
      $("#evidence-detail").replaceChildren(emptyInspector()); setCommandFeedback("Case selected. Type or dictate a read-only query.");
      if (state.navView === "reports") await showReportPreview();
    } catch (error) { if (requestId === state.caseRequest) showNotice(error.message + " Previous case retained; retry selection.", "error"); }
    finally { if (requestId === state.caseRequest) { state.loadingCase = false; $(".investigation-panel").removeAttribute("aria-busy"); } }
  }
  function emptyInspector() {
    const box = el("div", "empty-state"); const card = el("div", "empty-inspector-card");

    card.append(icon("report"), el("p", "", "Evidence opens here"), el("small", "", "Select a source to reveal its provenance. Raw files stay private."));
    box.append(card, artwork("ghost-detective-rocks.png", "detective-art")); return box;
  }


  function renderEvidenceRefs(refs) {
    const list = $("#evidence-refs");
    list.replaceChildren();
    $("#evidence-ref-count").textContent = String(refs.length);
    for (const ref of refs.slice(0, 30)) {
      list.append(button(ref, "ref-chip", () => loadEvidence(ref)));
    }
    if (refs.length > 30) list.append(el("span", "no-data", `+${refs.length - 30} more in case details`));
    if (!refs.length) list.append(el("span", "no-data", state.selected ? "No admissible source references for this case." : "Choose a case to see its references."));
  }


  async function loadEvidence(ref) {
    if (!state.selected || state.loadingCase) return;
    const caseId = state.selected; const requestId = ++state.evidenceRequest;
    try {
      const payload = await request("/cases/" + encodeURIComponent(caseId) + "/evidence/" + encodeURIComponent(ref));
      if (caseId !== state.selected || requestId !== state.evidenceRequest) return;
      document.querySelectorAll(".ref-chip").forEach(item => item.classList.toggle("selected", item.textContent === ref));
      renderEvidence(payload);
      if (window.matchMedia("(max-width: 1100px)").matches) {
        $("#evidence-inspector").scrollIntoView({ block: "start", behavior: "instant" });
        $("#evidence-detail").setAttribute("tabindex", "-1"); $("#evidence-detail").focus({ preventScroll: true });
      }
    } catch (error) { if (requestId === state.evidenceRequest) showNotice(error.message, "error"); }
  }

  function renderEvidence(payload) {
    const root = $("#evidence-detail");
    root.replaceChildren();
    const card = el("article", "evidence-card");
    card.append(el("h3", "", payload.evidence_ref));
    for (const item of payload.items || []) {
      const segment = el("section", "evidence-item");
      segment.append(el("span", "", item.source_type || "Source"));
      const detail = [item.system_id, item.category, item.resource_id].filter(Boolean).join(" · ");
      if (detail) segment.append(el("strong", "", detail));
      if (item.event_at) { segment.append(el("span", "", "EVENT TIME"), el("strong", "", formatTime(item.event_at))); }
      if (item.captured_at) { segment.append(el("span", "", "EVIDENCE CAPTURED"), el("strong", "", formatTime(item.captured_at))); }
      segment.append(el("span", `status-text ${item.admissible ? "good" : "excluded"}`, item.admissible ? "Admissible at cutoff" : "Excluded after cutoff"));
      for (const [key, value] of Object.entries(item.safe_fields || {})) {
        const field = el("div", "safe-field");
        field.append(el("span", "", key.replaceAll("_", " ")), el("b", "", value));
        segment.append(field);
      }
      card.append(segment);
    }
    card.append(el("p", "", payload.excerpt_note || "Raw evidence withheld."));
    root.append(card);
  }

  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tab-button").forEach(item => {
      const active = item.dataset.tab === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active)); item.tabIndex = active ? 0 : -1;
    });
    $("#tab-content").setAttribute("aria-labelledby", "tab-" + tab); renderTab();
  }

  function renderTab() {
    const root = $("#tab-content");
    root.replaceChildren();
    const detail = state.detail;
    if (state.navView === "demos") {
      const empty = el("div", "empty-inline"); empty.append(artwork("ghost-cases-books.png", "demo-art"), el("strong", "", "A separate story, coming later"), "Synthetic demos aren't available in this build. This workspace uses the private local corpus only."); root.append(empty); return;
    }
    if (!detail) { root.append(emptyWorkspace()); return; }
    if (state.tab === "overview") renderOverview(root, detail);
    else if (state.tab === "lineage") renderLineage(root, detail);
    else if (state.tab === "timeline") renderTimeline(root, detail);
    else renderActions(root, detail);
  }

  function renderOverview(root, detail) {
    const grid = el("div", "overview-grid");
    const left = el("article", "content-card");
    const tone = statusTone(detail.ui_verdict);
    const callout = el("div", `proof-callout ${tone}`);
    callout.append(el("div", "proof-symbol", tone === "complete" ? "✓" : "!"));
    const text = el("div");
    const heading = detail.ui_verdict === "INSUFFICIENT EVIDENCE" ? "The engine result has a proof gap" : detail.deletion_status === "INCOMPLETE" ? "The engine found unresolved obligations" : detail.deletion_status === "COMPLETE" ? "Evidence-backed checks are available" : "No deletion audit applies";
    text.append(el("h3", "", heading));
    let explanation = `Engine status: ${detail.deletion_status}. Dashboard diagnostic: ${detail.ui_verdict}.`;
    if (detail.ui_verdict === "INSUFFICIENT EVIDENCE") explanation += " A COMPLETE label without an admissible verification reference is shown as insufficient evidence here.";
    else if (detail.deletion_status === "INCOMPLETE") explanation += " Audit recommendation only — no records modified.";
    else if (detail.deletion_status === "COMPLETE") explanation += " Parsed-file counts are not proof of erasure; review the cited checks and their cutoff.";
    text.append(el("p", "", explanation));
    callout.append(text);
    left.append(callout, el("h3", "", "Audit proof coverage"));
    const coverage = el("div", "coverage-list");
    for (const [label, value] of [
      ["Sources observed for this case", detail.source_coverage.observed_for_case],
      ["Corpus manifest files available by cutoff", detail.source_coverage.manifest_files_available_by_cutoff],
      ["Direct matches excluded after cutoff", detail.source_coverage.future_direct_matches_excluded],
      ["Engine verification checks", detail.source_coverage.verification_checks],
      ["Checks with admissible evidence", detail.source_coverage.checks_with_admissible_evidence],
    ]) {
      const row = el("div", "coverage-row"); row.append(el("span", "", label), el("b", "", value)); coverage.append(row);
    }
    left.append(coverage, el("p", "coverage-note", detail.source_coverage.denominator_note));
    const right = el("article", "content-card");
    right.append(el("h3", "", "Case context"));
    const points = el("div", "data-points");
    for (const [label, value] of [
      ["Subject", detail.subject_label_masked], ["Request", detail.deletion_authorized ? "Deletion authorized" : "Authorization not identified"],
      ["Workflow claim", detail.reported_status || "—"], ["Computed result", detail.deletion_status], ["Audit cutoff", formatTime(detail.audit_at)],
      ["Source systems", detail.source_coverage.systems_observed.join(", ") || "None observed"],
    ]) { const row = el("div", "data-point"); row.append(el("span", "", label), el("strong", "", value)); points.append(row); }
    right.append(points);
    grid.append(left, right);
    root.append(grid);
    const rows = (detail.steps || []).filter(step => step.evidence_ref).slice(0, 6);
    if (rows.length) {
      const card = el("article", "content-card");
      card.classList.add("spaced-card");
      card.append(el("h3", "", "Proof chain · engine-emitted steps"));
      const table = makeTable(["PHASE", "OPERATION", "STATE", "RESOURCE", "EVIDENCE"], rows.map(step => [step.phase, step.operation, step.state, step.resource_id, refCell(step.evidence_ref)]));
      card.append(table); root.append(card);
    }
  }

  function makeTable(headers, rows) {
    const wrap = el("div", "table-wrap"); const table = el("table", "data-table");
    const thead = el("thead"); const headRow = el("tr");
    for (const label of headers) headRow.append(el("th", "", label));
    thead.append(headRow); table.append(thead);
    const tbody = el("tbody");
    for (const cells of rows) { const row = el("tr"); for (const cell of cells) { const td = el("td"); if (cell instanceof Node) td.append(cell); else td.textContent = String(cell ?? "—"); row.append(td); } tbody.append(row); }
    table.append(tbody); wrap.append(table); return wrap;
  }
  function refCell(ref) { return button(ref || "—", "ref-button", () => ref && loadEvidence(ref)); }


  function lineageCanvas(graph) {
    const panel = el("section", "lineage-graph");
    const tools = el("div", "graph-toolbar");
    tools.append(el("span", "eyebrow", "EVIDENCE MAP"));
    const filter = el("select", "graph-filter"); filter.setAttribute("aria-label", "Filter graph relationships");
    const all = el("option", "", "All relationships"); all.value = ""; filter.append(all);
    for (const value of [...new Set(graph.edges.map(edge => edge.confidence))]) {
      const option = el("option", "", value); option.value = value; filter.append(option);
    }
    tools.append(filter);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "lineage-canvas"); svg.setAttribute("role", "group"); svg.setAttribute("aria-label", "Evidence-backed lineage graph");
    let fullHeight = 300, fullWidth = 1020, view = { x: -10, y: -10, w: 1020, h: 320 };
    function setViewBox() { svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].join(" ")); }
    function fit() { view = { x: -10, y: -10, w: fullWidth, h: fullHeight + 20 }; setViewBox(); }
    function zoom(factor) {
      const w = Math.max(260, Math.min(3000, view.w * factor)); const ratio = w / view.w;
      const h = view.h * ratio; view.x += (view.w-w)/2; view.y += (view.h-h)/2; view.w = w; view.h = h; setViewBox();
    }
    tools.append(button("−", "icon-button", () => zoom(1.25), {"aria-label":"Zoom out graph"}),
      button("+", "icon-button", () => zoom(.8), {"aria-label":"Zoom in graph"}),
      button("Fit", "text-button", fit, {"aria-label":"Fit graph to view"}));
    const caption = el("p", "graph-caption", "Select a node or connection to inspect its source. Drag empty space to pan.");
    function svgEl(tag, attrs, text) {
      const item = document.createElementNS(svg.namespaceURI, tag);
      for (const [key,value] of Object.entries(attrs || {})) item.setAttribute(key, value);
      if (text !== undefined) item.textContent = text; return item;
    }
    function draw() {
      svg.replaceChildren();
      const edges = graph.edges.filter(edge => !filter.value || edge.confidence === filter.value);
      const usedIds = new Set(edges.flatMap(edge => [edge.from, edge.to]));
      const nodes = graph.nodes.filter(node => usedIds.has(node.id));
      const types = ["subject", "historical_identifier", "resource", "evidence"].filter(type => nodes.some(node => node.type === type));
      fullWidth = Math.max(300, types.length*254);
      const maxRows = Math.max(1, ...types.map(type => nodes.filter(node => node.type === type).length));
      fullHeight = Math.max(300, maxRows * 90 + 70);
      const positions = new Map();
      types.forEach((type, column) => {
        const group = nodes.filter(node => node.type === type);
        group.forEach((node,index) => positions.set(node.id, { x: 18 + column*254, y: 45+(index+1)*((fullHeight-60)/(group.length+1)) }));
        svg.append(svgEl("text", { x: 18+column*254, y: 22, class: "graph-column-label" }, type.replaceAll("_"," ").toUpperCase()));
      });
      const edgeItems = [], nodeItems = [];
      function highlight(nodeId, edgeIndex) {
        const connected = new Set([nodeId]);
        edges.forEach((edge,index) => {
          const active = edgeIndex === index || nodeId && (edge.from === nodeId || edge.to === nodeId);
          edgeItems[index].classList.toggle("selected", Boolean(active));
          if (active) { connected.add(edge.from); connected.add(edge.to); }
        });
        nodeItems.forEach(({node,item}) => item.classList.toggle("selected", connected.has(node.id)));
      }
      edges.forEach((edge,index) => {
        const from = positions.get(edge.from), to = positions.get(edge.to); if (!from || !to) return;
        const x1 = from.x+194, x2=to.x, y1=from.y+26, y2=to.y+26, middle=(x1+x2)/2;
        const group=svgEl("g", {class:"graph-edge", role:"button", tabindex:"0", "aria-label":edge.label+" · "+edge.confidence+" · "+edge.evidence_ref});
        const path="M "+x1+" "+y1+" C "+middle+" "+y1+", "+middle+" "+y2+", "+x2+" "+y2;
        group.append(svgEl("path",{d:path,class:"edge-hit"}),svgEl("path",{d:path,class:"edge-line"+(edge.confidence.includes("confirmed")?" confirmed":"")}));
        group.append(svgEl("title",{},edge.label+" · "+edge.confidence+" · "+edge.evidence_ref));
        const select=()=>{ highlight(null,index); caption.textContent=edge.label+" · "+edge.confidence+" · "+edge.evidence_ref; if(edge.evidence_ref) loadEvidence(edge.evidence_ref); };

        group.addEventListener("click",select); group.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();select();}});
        edgeItems.push(group);svg.append(group);
      });
      nodes.forEach(node=>{
        const position=positions.get(node.id);
        const group=svgEl("g",{class:"graph-node "+node.type, transform:"translate("+position.x+" "+position.y+")",role:"button",tabindex:"0","aria-label":node.label+" · "+node.confidence});
        group.append(svgEl("rect",{width:"194",height:"57",rx:"9"}),svgEl("text",{x:"13",y:"23",class:"graph-node-label"},node.label.length>25?node.label.slice(0,23)+"…":node.label),
          svgEl("text",{x:"13",y:"43",class:"graph-node-detail"},node.system_id || node.confidence),
          svgEl("title",{},node.label+" · "+node.confidence));
        const select=()=>{
          highlight(node.id,null);caption.textContent=node.label+" · "+node.confidence;
          const link=edges.find(edge=>edge.evidence_ref&&(edge.to===node.id||edge.from===node.id));
          if(link)loadEvidence(link.evidence_ref);
        };
        group.addEventListener("click",select);group.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();select();}});
        nodeItems.push({node,item:group});svg.append(group);
      });
      fit();
    }
    let drag=null;
    svg.addEventListener("pointerdown",event=>{if(event.target!==svg)return;drag={x:event.clientX,y:event.clientY,vx:view.x,vy:view.y};svg.setPointerCapture(event.pointerId);});
    svg.addEventListener("pointermove",event=>{if(!drag)return;view.x=drag.vx-(event.clientX-drag.x)*view.w/svg.clientWidth;view.y=drag.vy-(event.clientY-drag.y)*view.h/svg.clientHeight;setViewBox();});
    svg.addEventListener("pointerup",()=>{drag=null;});svg.addEventListener("pointercancel",()=>{drag=null;});
    filter.addEventListener("change",draw); panel.append(tools,svg,caption);draw();return panel;
  }



  function renderLineage(root, detail) {
    root.append(el("p", "lineage-intro", "Identity and resource relationships supplied by the local engine. Confirmed and engine-correlated links remain distinct; each connection retains its supporting source."));
    const key = el("div", "graph-key"); key.append(el("span", "", "Identity audit"), el("span", "", "Engine-correlated resource"), el("span", "", "Evidence reference")); root.append(key);
    const graph = detail.graph || { nodes: [], edges: [] };
    if (!graph.edges.length) { const empty = el("div", "empty-inline"); empty.append(el("strong", "", "No linked graph edges"), "The current case has no admissible identity or resource relationship in the engine output."); root.append(empty); return; }
    root.prepend(lineageCanvas(graph));
    root.append(el("h3", "relationship-heading", "All relationships · accessible table"));
    const rows = graph.edges.map(edge => {
      const from = (graph.nodes.find(node => node.id === edge.from) || {}).label || edge.from;
      const to = (graph.nodes.find(node => node.id === edge.to) || {}).label || edge.to;
      return [from, edge.label, to, edge.confidence, refCell(edge.evidence_ref)];
    });
    root.append(makeTable(["FROM", "RELATION", "TO", "CONFIDENCE", "PROVENANCE"], rows));
    root.append(el("p", "coverage-note", graph.text_alternative));
  }

  function renderTimeline(root, detail) {
    root.append(el("p", "timeline-intro", "Two clocks are shown separately. The event clock describes when the source says something happened; the capture clock describes when the evidence entered the local corpus. Post-cutoff direct matches are visibly excluded."));
    const items = detail.timeline || [];
    if (!items.length) { root.append(el("div", "empty-inline", "No case-linked timeline events are available from the current engine index.")); return; }
    const track = el("div", "timeline-track");
    for (const item of items) {
      const entry = el("div", `timeline-entry${item.admissible ? "" : " excluded"}`);
      const spine = el("div", "timeline-spine"); spine.append(el("span", "timeline-dot"));
      const card = el("article", "timeline-card");
      const title = el("div", "timeline-title");
      title.append(el("strong", "", item.kind.replaceAll("_", " ")), el("span", `timeline-tag ${item.admissible ? "" : "excluded"}`, item.admissible ? "ADMISSIBLE" : "EXCLUDED AFTER CUTOFF"));
      card.append(title);
      const times = el("div", "timeline-times");
      times.append(el("span", "", `EVENT · ${formatTime(item.event_at)}`), el("span", "", `CAPTURED · ${formatTime(item.captured_at)}`)); card.append(times);
      const resource = [item.system_id, item.resource_id].filter(Boolean).join(" · ");
      if (resource) card.append(el("p", "muted", resource));
      if (item.evidence_ref) card.append(refCell(item.evidence_ref));
      entry.append(spine, card); track.append(entry);
    }
    root.append(track);
  }

  function renderActions(root, detail) {
    const banner = el("div", "risk-banner", "Recommendations and verification steps are shown as engine output. No action button can mutate customer data. Dependency order is not computed by the current engine; the scored CSV ordering is preserved.");
    root.append(banner, el("p", "actions-note", "REMEDIATION rows are proposed future work. VERIFICATION rows describe an existing check or a check required after remediation; they are never represented as already executed when the engine has no admissible evidence."));
    const steps = detail.steps || [];
    if (!steps.length) { root.append(el("div", "empty-inline", "The engine emitted no action or verification steps for this case.")); return; }
    const stateLabels = { proposed_only: ["PROPOSED ONLY", "status-text"], observed_finding: ["OBSERVED", "status-text good"], evidence_backed_check: ["EVIDENCE-BACKED", "status-text good"], future_verification: ["FUTURE CHECK", "status-text"] };
    const rows = steps.map(step => { const [label, cls] = stateLabels[step.execution_state] || ["UNRESOLVED", "status-text excluded"]; return [step.phase, step.operation, step.state, step.system_id, step.resource_id, el("span", cls, label), refCell(step.evidence_ref)]; });
    root.append(makeTable(["PHASE", "OPERATION", "TARGET STATE", "SYSTEM", "RESOURCE", "EXECUTION", "EVIDENCE"], rows));
    const policy = detail.policy || [];
    const policyCard = el("article", "content-card"); policyCard.classList.add("spaced-card"); policyCard.append(el("h3", "", "Policy rows used for observed categories"));
    if (!policy.length) policyCard.append(el("p", "", "No matching policy row was available from the current engine context."));
    else {
      const rows = policy.map(row => Object.entries(row).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · "));
      for (const line of rows) policyCard.append(el("p", "", line));
    }
    root.append(policyCard);
  }


  function setView(view) {
    const previousView = state.navView; state.navView = view;
    document.querySelectorAll(".nav-item").forEach(item => {
      item.classList.toggle("active", item.dataset.view === view);
      if (item.dataset.view === view) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
    });
    const labels = { investigations: "INVESTIGATIONS", evidence: "EVIDENCE ATLAS", lineage: "IDENTITY LINEAGE", risks: "SYSTEM RISKS", reports: "AUDIT REPORTS", demos: "DEMO CASES" };
    $("#view-label").textContent = labels[view] || "INVESTIGATIONS";
    if (previousView === "risks" && view !== "risks") { state.status = ""; $("#status-filter").value = ""; loadCases(true); }
    closeMenu();
    if (view === "lineage") setTab("lineage");
    else if (view === "evidence") setTab("timeline");
    else if (view === "risks") { state.status = "INCOMPLETE"; $("#status-filter").value = "INCOMPLETE"; setTab("actions"); loadCases(true); }
    else if (view === "reports") { if (state.selected) showReportPreview(); else setTab("overview"); }
    else setTab("overview");
  }


  async function showReportPreview() {
    if (!state.selected) return;
    const caseId = state.selected; setTab("actions");
    try {
      const report = await request("/cases/" + encodeURIComponent(caseId) + "/report");
      if (caseId !== state.selected) return;
      const panel = el("article", "content-card report-preview");
      panel.append(el("p", "eyebrow", "SANITIZED EXPORT"), el("h3", "", "An audit you can take with you"));
      const download = button("Download Markdown report ↗", "run-button", () => {
        const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob); const anchor = el("a"); anchor.href = url; anchor.download = "ghosttrace-" + caseId + "-sanitized.md";
        document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      const preview = el("details", "report-details"); preview.append(el("summary", "", "Read the sanitized report"), el("pre", "", report));
      panel.append(download, preview); $("#tab-content .report-preview")?.remove(); $("#tab-content").prepend(panel);
      $("#command-feedback").textContent = "Report prepared with masked identity and allowlisted fields.";
    } catch (error) { showNotice(error.message, "error"); }
  }

  async function runIntent(intent) {
    if (!state.selected) return;
    const scopedCase = state.selected;
    let replay = null;
    if (intent === "INVESTIGATE") {
      replay = await request("/investigations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: state.selected }) });
      if (state.selected !== scopedCase) { showNotice("Read-only replay completed for " + scopedCase + ". Your current selection is unchanged."); return; }
      await loadCases();
      await loadCase(scopedCase);
      setTab("overview");
    }
    if (intent === "EXPLAIN_FINDING") { await loadCase(state.selected); setTab("overview"); }
    if (intent === "SHOW_LINEAGE") setTab("lineage");
    if (intent === "SHOW_EVIDENCE") { setTab("timeline"); const refs = state.detail?.evidence_refs || []; if (refs.length) await loadEvidence(refs[0]); }
    if (intent === "SHOW_POLICY" || intent === "SHOW_REMEDIATION") setTab("actions");
    if (intent === "SHOW_AS_OF") setTab("timeline");
    if (intent === "EXPORT_SANITIZED_REPORT") await showReportPreview();
    state.history.unshift(intent); state.history = state.history.slice(0, 5); renderHistory();
    $("#command-feedback").textContent = replay ? `Completed real ${replay.analysis_type.replaceAll("_", " ")} in ${replay.elapsed_ms} ms; no source data changed.` : `Completed read-only query: ${intent.replaceAll("_", " ")}.`;
    $("#command-feedback").className = "command-feedback success";
  }

  function renderHistory() {
    const root = $("#command-history"); root.replaceChildren();
    for (const item of state.history) root.append(el("span", "history-chip", item));
  }


  async function previewCommand(event) {
    event.preventDefault();
    if (state.busy || state.loadingCase) return;
    const text = $("#command-input").value.trim();
    if (!text) { setCommandFeedback("Enter a read-only command first.", "error"); $("#command-input").focus(); return; }
    if (!state.selected) { setCommandFeedback("Select a case before previewing a command.", "error"); return; }
    state.busy = true; const run = $("#command-form .run-button"); run.disabled = true;
    const previewScope = state.selected;
    try {
      const plan = await request("/commands/interpret", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, case_id: previewScope }) });
      if (state.selected !== previewScope || state.loadingCase) { setCommandFeedback("Case scope changed. Preview your command again.", "error"); return; }
      if (!plan.ok) { setCommandFeedback(plan.error || "Command could not be interpreted.", "error"); return; }
      const feedback = $("#command-feedback"); feedback.replaceChildren(); feedback.className = "command-feedback";
      feedback.append(document.createTextNode("Preview · " + plan.intent.replaceAll("_", " ") + " · " + plan.preview + " "));
      const execute = button("Run safe query", "text-button", async () => {
        if (state.selected !== previewScope || state.loadingCase) { setCommandFeedback("Case scope changed. Preview your command again.", "error"); return; }
        if (state.busy) return;
        state.busy = true; execute.disabled = true;
        try { await runIntent(plan.intent); }
        catch (error) { setCommandFeedback(error.message, "error"); }
        finally { state.busy = false; }
      });
      feedback.append(execute);
    } catch (error) { setCommandFeedback(error.message, "error"); }
    finally { state.busy = false; run.disabled = false; }
  }

  function setCommandFeedback(message, tone) { const target = $("#command-feedback"); target.textContent = message; target.className = `command-feedback ${tone || ""}`; }

  document.querySelectorAll(".tab-button").forEach(item => item.addEventListener("click", () => setTab(item.dataset.tab)));
  document.querySelectorAll(".nav-item").forEach(item => item.addEventListener("click", () => setView(item.dataset.view)));
  $("#case-search").addEventListener("input", event => {
    const candidate = event.target.value.trim().toLowerCase();
    const partial = /^case_?\d{0,6}$/.test(candidate) || "case".startsWith(candidate);
    if (!partial) {
      event.target.value = "";
      state.query = "";
      window.clearTimeout(window.caseSearchTimer);
      showNotice("Search accepts case IDs only; contact values are not sent to the API.");
      loadCases(true);
      return;
    }
    const complete = /^case_?\d{1,6}$/.test(candidate);
    if (!complete && candidate) {
      window.clearTimeout(window.caseSearchTimer);
      showNotice("Finish entering a case ID to search.");
      return;
    }
    state.query = candidate.includes("_") ? candidate : candidate.replace(/^case/, "case_");
    window.clearTimeout(window.caseSearchTimer);
    window.caseSearchTimer = window.setTimeout(() => loadCases(true), 180);
  });
  $("#status-filter").addEventListener("change", event => { state.status = event.target.value; loadCases(true); });
  $("#previous-page").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadCases(); } });
  $("#next-page").addEventListener("click", () => { if (state.page * state.pageSize < state.total) { state.page += 1; loadCases(); } });
  $("#command-form").addEventListener("submit", previewCommand);
  $("#clear-history").addEventListener("click", () => { state.history = []; renderHistory(); setCommandFeedback("Command history cleared. No transcript is stored."); });

  function closeMenu() {
    $(".main-area").inert = false;
    $("#navigation-rail").classList.remove("mobile-open"); $("#mobile-menu").setAttribute("aria-expanded", "false"); $("#mobile-menu").setAttribute("aria-label", "Open navigation");
  }
  $("#mobile-menu").addEventListener("click", () => {
    const open = $("#navigation-rail").classList.toggle("mobile-open");
    $("#mobile-menu").setAttribute("aria-expanded", String(open)); $("#mobile-menu").setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    $(".main-area").inert = open;
    if (open) $(".nav-item.active").focus();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && $("#navigation-rail").classList.contains("mobile-open")) { closeMenu(); $("#mobile-menu").focus(); }
  });
  document.addEventListener("click", event => {
    if (!event.target.closest("#navigation-rail") && !event.target.closest("#mobile-menu")) closeMenu();
  });
  $(".tab-bar").addEventListener("keydown", event => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault(); const tabs = [...document.querySelectorAll(".tab-button")]; const index = tabs.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    setTab(tabs[next].dataset.tab); tabs[next].focus();
  });
  $("#case-list").addEventListener("keydown", event => {
    if (!["ArrowUp","ArrowDown","Home","End"].includes(event.key)) return;
    const rows = [...document.querySelectorAll(".case-row")]; if (!rows.length) return;
    event.preventDefault(); const index = rows.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length-1 : Math.max(0, Math.min(rows.length-1, index + (event.key === "ArrowDown" ? 1 : -1)));
    rows[next].focus();
  });
  $("#collapse-queue").addEventListener("click", () => {
    const collapsed = $(".main-area").classList.toggle("queue-collapsed");
    $("#collapse-queue").setAttribute("aria-expanded", String(!collapsed)); $("#collapse-queue").setAttribute("aria-label", collapsed ? "Expand case queue" : "Collapse case queue");
  });
  $("#clear-case").addEventListener("click", clearCase);
  $("#command-help").addEventListener("click", () => {
    const examples = $("#command-examples"); examples.hidden = !examples.hidden; $("#command-help").setAttribute("aria-expanded", String(!examples.hidden));
  });
  document.querySelectorAll("[data-command]").forEach(item => item.addEventListener("click", () => {
    $("#command-input").value = item.dataset.command; $("#command-input").focus(); setCommandFeedback("Command inserted. Preview it before running.");
  }));
  $("#command-input").addEventListener("input", () => {
    if (!state.busy) setCommandFeedback("Command changed. Preview it before running.");
  });
  $("#command-input").addEventListener("keydown", event => {

    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); $("#command-form").requestSubmit(); }
  });
  hydrateIcons(); clearCase(); pollStartup();
})();
