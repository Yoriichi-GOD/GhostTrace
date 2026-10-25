"""Read-only browser facade over GhostTrace's existing Python audit engine."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any


CASE_ID = re.compile(r"^case_\d{1,6}$")
EVIDENCE_ID = re.compile(r"^(?:evidence_\d+|activity_\d+|audit_\d+)$")
SAFE_FIELD_NAMES = {
    "state", "status", "event_type", "operation", "enabled", "active",
    "is_active", "restore_allowed", "restore_access", "can_restore",
    "deletion_block", "eligible", "deleted", "is_deleted", "redacted",
    "anonymized", "record_type", "data_category", "category", "phase",
    "result", "reported_result", "retention_period_days", "held",
    "legal_hold", "policy_action", "action", "sync_enabled", "flow_enabled",
    "replica_state", "source_state", "target_state", "status_code",
}
EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
COMMANDS = (
    "INVESTIGATE", "EXPLAIN_FINDING", "SHOW_LINEAGE", "SHOW_EVIDENCE",
    "SHOW_POLICY", "SHOW_AS_OF", "SHOW_REMEDIATION", "EXPORT_SANITIZED_REPORT",
)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _masked_email(value: str) -> str:
    match = EMAIL_RE.fullmatch(str(value or "").strip())
    if not match:
        return "masked identifier"
    local = match.group(0).split("@", 1)[0]
    return (local[:1] or "*") + "•••@•••"


def _safe_scalar(value: Any) -> str | bool | int | float | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    text = EMAIL_RE.sub("[masked email]", text)
    text = PHONE_RE.sub("[masked phone]", text)
    return text[:120]


def _case_ref(value: str) -> str:
    return value if CASE_ID.fullmatch(value or "") else ""


class DashboardService:
    """Loads the corpus once, then exposes only explicitly sanitized projections."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.code_root = self.repo_root / "code"
        if str(self.code_root) not in sys.path:
            sys.path.insert(0, str(self.code_root))
        from evidence import load_person, parse_time, read_csv  # noqa: PLC0415
        from main import Auditor, authorizes_deletion  # noqa: PLC0415

        self._read_csv = read_csv
        self._parse_time = parse_time
        self._load_person = load_person
        self._auditor_type = Auditor
        self._authorizes_deletion = authorizes_deletion
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._state: dict[str, Any] = {
            "phase": "starting", "completed": 0, "total": 0,
            "started_at": _iso(dt.datetime.now(dt.timezone.utc)),
            "error": None,
        }
        self._auditor: Any = None
        self._records_by_ref: dict[str, list[Any]] = {}
        self._requests: dict[str, dict[str, str]] = {}
        self._results: dict[str, dict[str, str]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}
        threading.Thread(target=self._build_index, name="ghosttrace-index", daemon=True).start()

    def _build_index(self) -> None:
        try:
            requests = self._read_csv(self.repo_root / "dataset" / "deletion_requests.csv")
            with self._lock:
                self._state.update(phase="loading_evidence", total=len(requests))
            auditor = self._auditor_type(self.repo_root)
            records_by_ref: dict[str, list[Any]] = {}
            for record in auditor.evidence.records:
                records_by_ref.setdefault(record.evidence_id, []).append(record)
            with self._lock:
                self._auditor = auditor
                self._records_by_ref = records_by_ref
                self._requests = {row["case_id"]: row for row in requests}
                self._state["phase"] = "auditing_cases"
            for index, case in enumerate(sorted(requests, key=lambda row: int(row["case_id"].rsplit("_", 1)[1])), start=1):
                result = auditor.audit_case(case)
                with self._lock:
                    self._results[case["case_id"]] = result
                    self._state["completed"] = index
            with self._lock:
                self._state.update(phase="ready", finished_at=_iso(dt.datetime.now(dt.timezone.utc)))
        except Exception as exc:  # an API must show failure, never a green fallback
            with self._lock:
                # Exception strings can contain absolute paths or source values.
                self._state.update(phase="failed", error=f"Engine initialization failed ({type(exc).__name__}). See the local launcher output.")
        finally:
            self._ready.set()

    def wait_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout) and self._state["phase"] == "ready"

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ready" if self._state["phase"] == "ready" else self._state["phase"],
                "engine": "GhostTrace Python Auditor",
                "data_mode": "private_local_corpus",
                "read_only": True,
                "index": {k: v for k, v in self._state.items() if k != "error"},
                "error": self._state.get("error"),
            }

    def _require_ready(self) -> None:
        if self._state["phase"] == "failed":
            raise RuntimeError(self._state.get("error") or "Engine initialization failed")
        if self._state["phase"] != "ready":
            raise RuntimeError("GhostTrace is still loading its local evidence index")

    def _context(self, case_id: str) -> dict[str, Any]:
        case_id = _case_ref(case_id)
        if not case_id:
            raise KeyError("Invalid case ID")
        with self._lock:
            self._require_ready()
            if case_id not in self._requests:
                raise KeyError("Case not found")
            cached = self._contexts.get(case_id)
            if cached is not None:
                return cached
            case = self._requests[case_id]
            result = self._results[case_id]
            auditor = self._auditor

        cutoff = self._parse_time(case.get("audit_at"))
        person = self._load_person(case, auditor.identities, auditor.audits)
        records = auditor.evidence.observations_for(person, cutoff) if cutoff else []
        direct_records = [record for record in auditor.evidence.records if person.match_kind(record)]
        future_records = []
        for record in direct_records:
            if cutoff and ((record.file_time and record.file_time > cutoff)
                           or (record.observed_time and record.observed_time > cutoff)):
                future_records.append(record)
        user_ids = {str(value) for value in person.user_ids}
        identity_audits = [
            row for row in auditor.audits
            if row.get("user_id") in user_ids
            and str(row.get("field_name", "")).casefold() in {"email", "phone", "email_hash"}
            and (not cutoff or not self._parse_time(row.get("event_time"))
                 or self._parse_time(row.get("event_time")) <= cutoff)
        ]
        identity_links = auditor.evidence.identity_link_events(person, cutoff) if cutoff else []
        context = {
            "case": case, "result": result, "person": person, "cutoff": cutoff,
            "records": records, "future_records": future_records,
            "identity_audits": identity_audits, "identity_links": identity_links,
            "auditor": auditor,
        }
        with self._lock:
            return self._contexts.setdefault(case_id, context)

    def _step_rows(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            raw = json.loads(context["result"].get("steps_json", "[]"))
        except (TypeError, json.JSONDecodeError):
            raw = []
        rows = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "phase": _safe_scalar(item.get("phase")),
                "system_id": _safe_scalar(item.get("system_id")),
                "resource_id": _safe_scalar(item.get("resource_id")),
                "operation": _safe_scalar(item.get("operation")),
                "state": _safe_scalar(item.get("state")),
                "evidence_ref": _safe_scalar(item.get("evidence_id")) or None,
                "execution_state": {"REMEDIATION": "proposed_only", "FINDING": "observed_finding"}.get(
                    item.get("phase"), "future_verification"),
            })
        return rows

    def _summary(self, context: dict[str, Any]) -> dict[str, Any]:
        case = context["case"]
        result = context["result"]
        steps = self._step_rows(context)
        admissible_refs = {record.evidence_id for record in context["records"]}
        verified = [step for step in steps if step["phase"] == "VERIFICATION"
                    and step["evidence_ref"] in admissible_refs]
        verification_count = sum(1 for step in steps if step["phase"] == "VERIFICATION")
        engine_status = result.get("deletion_status", "INCOMPLETE")
        unresolved = bool(getattr(context["auditor"], "diagnostics", {}).get(case["case_id"]))
        proof_gap = (engine_status == "COMPLETE" and not verified) or (unresolved and not steps)
        ui_verdict = "INSUFFICIENT EVIDENCE" if proof_gap else engine_status
        manifest_by_id = {row.get("file_id", ""): row for row in context["auditor"].evidence.manifest}
        eligible_manifest = 0
        for row in manifest_by_id.values():
            captured = self._parse_time(row.get("captured_at"))
            if not context["cutoff"] or not captured or captured <= context["cutoff"]:
                eligible_manifest += 1
        observed_sources = sorted({record.evidence_id for record in context["records"]})
        systems = sorted({record.system_id for record in context["records"] if record.system_id})
        return {
            "case_id": case["case_id"],
            "reported_status": _safe_scalar(case.get("reported_status")),
            "deletion_status": engine_status,
            "ui_verdict": ui_verdict,
            "proof_label": "proof gap" if proof_gap else ("evidence-backed checks available" if verified else "unresolved"),
            "audit_at": _safe_scalar(case.get("audit_at")),
            "requested_at": _safe_scalar(case.get("requested_at")),
            "subject_label_masked": _masked_email(case.get("email", "")),
            "deletion_authorized": bool(self._authorizes_deletion(case.get("request_text", ""))),
            "source_coverage": {
                "observed_for_case": len(observed_sources),
                "manifest_files_available_by_cutoff": eligible_manifest,
                "systems_observed": systems,
                "future_direct_matches_excluded": len(context["future_records"]),
                "verification_checks": verification_count,
                "checks_with_admissible_evidence": len(verified),
                "denominator_note": "The verification denominator is engine-emitted verification steps; parsed-file count is not proof of erasure.",
            },
            "evidence_refs": observed_sources,
            "data_mode": "private_local_corpus",
            "read_only": True,
            "notice": "Audit recommendation only — no records modified" if engine_status == "INCOMPLETE" else None,
        }

    def _case_list_status(self, case_id: str) -> tuple[dict[str, Any], str]:
        """Filter list rows from computed engine output without rebuilding evidence context."""
        case = self._requests[case_id]
        result = self._results[case_id]
        cutoff = self._parse_time(case.get("audit_at"))
        steps = self._step_rows({"result": result})
        backed = False
        for step in steps:
            if step["phase"] != "VERIFICATION" or not step["evidence_ref"]:
                continue
            candidates = self._records_by_ref.get(step["evidence_ref"], [])
            if any((not cutoff or not record.file_time or record.file_time <= cutoff)
                   and (not cutoff or not record.observed_time or record.observed_time <= cutoff)
                   and record.resource_id == step["resource_id"]
                   and record.system_id == step["system_id"]
                   for record in candidates):
                backed = True
                break
        engine_status = result.get("deletion_status", "INCOMPLETE")
        unresolved = bool(getattr(self._auditor, "diagnostics", {}).get(case_id))
        proof_gap = (engine_status == "COMPLETE" and not backed) or (unresolved and not steps)
        ui_verdict = "INSUFFICIENT EVIDENCE" if proof_gap else engine_status
        return case, ui_verdict

    def list_cases(self, query: str = "", status: str = "", page: int = 1, page_size: int = 40) -> dict[str, Any]:
        self._require_ready()
        query = query.strip().casefold()[:80]
        if query and not re.fullmatch(r"case_?\d{1,6}", query):
            raise ValueError("Case search accepts case IDs only")
        status = status.strip().upper()
        page = max(1, min(int(page), 10000))
        page_size = max(1, min(int(page_size), 100))
        matching_ids = []
        for case_id in sorted(self._requests, key=lambda value: int(value.rsplit("_", 1)[1])):
            if query and query not in case_id.casefold():
                continue
            case, ui_verdict = self._case_list_status(case_id)
            engine_status = self._results[case_id].get("deletion_status", "INCOMPLETE")
            if status and status not in {engine_status, ui_verdict}:
                continue
            matching_ids.append(case_id)
        start = (page - 1) * page_size
        page_ids = matching_ids[start:start + page_size]
        # Full evidence context is built only for the rows actually shown.
        summaries = [self._summary(self._context(case_id)) for case_id in page_ids]
        return {"items": summaries, "page": page,
                "page_size": page_size, "total": len(matching_ids), "read_only": True}

    def case_detail(self, case_id: str) -> dict[str, Any]:
        context = self._context(case_id)
        steps = self._step_rows(context)
        admissible_refs = {record.evidence_id for record in context["records"]}
        for step in steps:
            if step["phase"] == "VERIFICATION" and step["evidence_ref"] in admissible_refs:
                step["execution_state"] = "evidence_backed_check"
        return {**self._summary(context), "steps": steps,
                "timeline": self._timeline(context), "graph": self._graph(context),
                "coverage_note": "Coverage counts report corpus availability and sources actually observed for this case. They do not establish erasure.",
                "policy": self._policy(context)}

    def investigate(self, case_id: str) -> dict[str, Any]:
        context = self._context(case_id)
        started = dt.datetime.now(dt.timezone.utc)
        timer = time.perf_counter()
        # Replay one selected case through the real engine; this is synchronous and does not write source data.
        result = self._auditor.audit_case(context["case"])
        elapsed_ms = round((time.perf_counter() - timer) * 1000, 2)
        with self._lock:
            self._results[case_id] = result
            self._contexts.pop(case_id, None)
        refreshed = self._context(case_id)
        finished = dt.datetime.now(dt.timezone.utc)
        detail = self.case_detail(case_id)
        return {"case_id": case_id, "state": "completed", "analysis_type": "synchronous_engine_replay",
                "started_at": _iso(started), "finished_at": _iso(finished), "elapsed_ms": elapsed_ms,
                "deletion_status": refreshed["result"].get("deletion_status"),
                "ui_verdict": detail["ui_verdict"], "step_count": len(detail["steps"]),
                "read_only": True, "message": "Case replayed through the existing Python auditor; no source data was changed."}

    def _policy(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        categories = {record.category for record in context["records"]}
        result = []
        rules = context["auditor"].rules
        for category in sorted(categories):
            row = rules.get(category)
            if not row:
                continue
            result.append({str(key): _safe_scalar(value) for key, value in row.items()
                           if str(key).casefold() in {"data_category", "action", "retention_period_days",
                                                     "condition", "notes", "rule_id", "policy"}})
        return result

    def _timeline(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in context["records"]:
            items.append({
                "kind": "admissible_observation", "evidence_ref": record.evidence_id,
                "source_type": record.kind or "structured evidence",
                "system_id": record.system_id, "resource_id": record.resource_id,
                "event_at": _iso(record.observed_time), "captured_at": _iso(record.file_time),
                "admissible": True,
            })
        for record in context["future_records"]:
            items.append({
                "kind": "future_evidence_excluded", "evidence_ref": record.evidence_id,
                "source_type": record.kind or "structured evidence",
                "system_id": record.system_id, "resource_id": record.resource_id,
                "event_at": _iso(record.observed_time), "captured_at": _iso(record.file_time),
                "admissible": False,
            })
        for row in context["identity_audits"]:
            items.append({
                "kind": "identity_change", "evidence_ref": row.get("audit_id"),
                "source_type": "identity audit", "system_id": "identity_service",
                "resource_id": None, "event_at": _safe_scalar(row.get("event_time")),
                "captured_at": None, "admissible": True,
            })
        items.sort(key=lambda item: (item.get("event_at") or item.get("captured_at") or "", item.get("evidence_ref") or ""))
        return items

    def _graph(self, context: dict[str, Any]) -> dict[str, Any]:
        case_id = context["case"]["case_id"]
        nodes: dict[str, dict[str, Any]] = {
            f"subject:{case_id}": {"id": f"subject:{case_id}", "type": "subject", "label": "Subject · masked", "confidence": "resolved"}
        }
        edges: list[dict[str, Any]] = []
        seen_aliases: set[str] = set()
        for row in context["identity_audits"]:
            old_value = str(row.get("old_value", ""))
            new_value = str(row.get("new_value", ""))
            for value in (old_value, new_value):
                if not value:
                    continue
                masked = _masked_email(value) if "@" in value else "masked identifier"
                alias_id = "identifier:" + masked
                if alias_id not in seen_aliases:
                    nodes[alias_id] = {"id": alias_id, "type": "historical_identifier", "label": masked, "confidence": "confirmed by identity audit"}
                    seen_aliases.add(alias_id)
                    edges.append({"from": f"subject:{case_id}", "to": alias_id,
                                  "label": "identity audit link", "evidence_ref": row.get("audit_id"),
                                  "confidence": "confirmed"})
        records_by_resource: dict[str, list[Any]] = {}
        for record in context["records"]:
            if record.resource_id:
                records_by_resource.setdefault(record.resource_id, []).append(record)
        for resource_id, records in sorted(records_by_resource.items()):
            rid = "resource:" + resource_id
            latest = records[-1]
            nodes[rid] = {"id": rid, "type": "resource", "label": resource_id,
                          "system_id": latest.system_id, "confidence": "engine-correlated"}
            refs = sorted({record.evidence_id for record in records})
            if refs:
                edges.append({"from": f"subject:{case_id}", "to": rid,
                              "label": "correlated in admissible evidence", "evidence_ref": refs[0],
                              "confidence": "engine-correlated"})
            for evidence_ref in refs:
                eid = "evidence:" + evidence_ref
                nodes.setdefault(eid, {"id": eid, "type": "evidence", "label": evidence_ref,
                                       "confidence": "admissible at cutoff"})
                edges.append({"from": rid, "to": eid, "label": "observed by", "evidence_ref": evidence_ref,
                              "confidence": "source reference"})
        for link in context["identity_links"]:
            resource_id = str(link.get("resource_id", ""))
            if resource_id and "resource:" + resource_id in nodes:
                edges.append({"from": f"subject:{case_id}", "to": "resource:" + resource_id,
                              "label": "identity link event", "evidence_ref": link.get("activity_id"),
                              "confidence": "confirmed event"})
        return {"nodes": list(nodes.values()), "edges": edges,
                "text_alternative": "The table lists each evidence-backed relationship and its source reference."}

    def evidence_detail(self, case_id: str, evidence_ref: str) -> dict[str, Any]:
        if not EVIDENCE_ID.fullmatch(evidence_ref or ""):
            raise KeyError("Invalid evidence reference")
        context = self._context(case_id)
        records = [record for record in context["records"] + context["future_records"]
                   if record.evidence_id == evidence_ref]
        audit_rows = [row for row in context["identity_audits"] if row.get("audit_id") == evidence_ref]
        activity_rows = [row for row in context["identity_links"] if row.get("activity_id") == evidence_ref]
        if not records and not audit_rows and not activity_rows:
            raise KeyError("Evidence reference is not linked to this case")
        summaries = []
        for record in records:
            safe_fields = {str(key): _safe_scalar(value) for key, value in record.fields.items()
                           if str(key).casefold() in SAFE_FIELD_NAMES
                           and not isinstance(value, (dict, list))}
            summaries.append({
                "source_type": record.kind or "structured evidence",
                "system_id": record.system_id, "category": record.category,
                "resource_id": record.resource_id, "event_at": _iso(record.observed_time),
                "captured_at": _iso(record.file_time), "admissible": record not in context["future_records"],
                "safe_fields": safe_fields,
            })
        for row in audit_rows:
            summaries.append({"source_type": "identity audit", "event_at": _safe_scalar(row.get("event_time")),
                              "admissible": True, "safe_fields": {"field_name": _safe_scalar(row.get("field_name")),
                                                                   "old_value": _masked_email(row.get("old_value", "")),
                                                                   "new_value": _masked_email(row.get("new_value", ""))}})
        for row in activity_rows:
            summaries.append({"source_type": "identity-link activity", "event_at": _safe_scalar(row.get("event_time")),
                              "admissible": True, "safe_fields": {"event_type": _safe_scalar(row.get("event_type")),
                                                                   "resource_id": _safe_scalar(row.get("resource_id")),
                                                                   "reported_result": _safe_scalar(row.get("reported_result"))}})
        return {"evidence_ref": evidence_ref, "case_id": case_id,
                "items": summaries,
                "excerpt_note": "Only allowlisted, masked metadata is shown. Raw evidence text and disk paths are withheld.",
                "read_only": True}

    def coverage(self, case_id: str) -> dict[str, Any]:
        summary = self._summary(self._context(case_id))
        return {"case_id": case_id, **summary["source_coverage"],
                "evidence_refs": summary["evidence_refs"], "read_only": True}

    def report(self, case_id: str) -> str:
        context = self._context(case_id)
        summary = self._summary(context)
        lines = ["# GhostTrace local audit report", "", f"- Case: `{case_id}`",
                 f"- Data mode: `{summary['data_mode']}`", f"- Subject: `{summary['subject_label_masked']}`",
                 f"- Reported workflow status: `{summary['reported_status']}`",
                 f"- Engine status: `{summary['deletion_status']}`", f"- Dashboard proof label: `{summary['ui_verdict']}`",
                 f"- Audit cutoff: `{summary['audit_at']}`", "- Records modified: **No**", "",
                 "## Evidence coverage", "",
                 f"- Sources observed for this case: {summary['source_coverage']['observed_for_case']}",
                 f"- Manifest files available by cutoff: {summary['source_coverage']['manifest_files_available_by_cutoff']}",
                 f"- Future direct matches excluded: {summary['source_coverage']['future_direct_matches_excluded']}",
                 f"- Verification checks with admissible evidence: {summary['source_coverage']['checks_with_admissible_evidence']} / {summary['source_coverage']['verification_checks']}",
                 "", "## Engine steps", ""]
        for item in self._step_rows(context):
            lines.append("- " + " · ".join(str(item.get(key) or "—") for key in
                         ("phase", "operation", "state", "system_id", "resource_id", "evidence_ref")))
        lines += ["", "## Limits", "", summary["source_coverage"]["denominator_note"],
                  "Audit recommendations are advisory. No source records were changed."]
        return "\n".join(lines) + "\n"

    def interpret_command(self, text: str, selected_case_id: str) -> dict[str, Any]:
        if len(text) > 2000:
            return {"ok": False, "error": "Command is too long; keep it under 2,000 characters."}
        selected_case_id = _case_ref(selected_case_id)
        if not selected_case_id:
            return {"ok": False, "error": "Select a valid case before running a command."}
        normalized = re.sub(r"\s+", " ", (text or "").strip().casefold())
        if not normalized:
            return {"ok": False, "error": "Enter a command or dictate it with Wispr Flow."}
        if re.search(r"\b(delete|erase|remove|purge|modify|change|update|execute|run sql|shell)\b", normalized):
            return {"ok": False, "error": "That request could change data or run code. This console is read-only."}
        requested_cases = set(re.findall(r"\bcase_\d{1,6}\b", normalized))
        if requested_cases and requested_cases != {selected_case_id.casefold()}:
            return {"ok": False, "error": "The command refers to a different case. Select that case explicitly first."}
        spoken_case_numbers = {int(value) for value in re.findall(r"\bcase[\s_-]+(\d{1,6})\b", normalized)}
        selected_case_number = int(selected_case_id.rsplit("_", 1)[1])
        if spoken_case_numbers and spoken_case_numbers != {selected_case_number}:
            return {"ok": False, "error": "The case number did not match the selected case. Select the intended case and try again."}
        if re.search(r"\b(evidence|source|proof)\b.*\b(unavailable|after|future|cutoff|cut-off)\b", normalized):
            return {"ok": True, "intent": "SHOW_AS_OF", "target_case_id": selected_case_id,
                    "preview": "Show the audit cutoff and evidence excluded after it.", "side_effects": False,
                    "notice": "Audit recommendation only — no records modified"}
        if re.search(r"\b(sync|restore|recreate|resurrect)\b", normalized):
            return {"ok": True, "intent": "SHOW_LINEAGE", "target_case_id": selected_case_id,
                    "preview": "Show case-linked sync, restore, or recreation relationships.", "side_effects": False,
                    "notice": "Audit recommendation only — no records modified"}
        patterns = [
            (r"\b(investigate|audit|inspect)\b", "INVESTIGATE"),
            (r"\b(explain|why|finding|verdict)\b", "EXPLAIN_FINDING"),
            (r"\b(lineage|identity|graph|historical)\b", "SHOW_LINEAGE"),
            (r"\b(evidence|source|proof)\b", "SHOW_EVIDENCE"),
            (r"\b(policy|retention|hold)\b", "SHOW_POLICY"),
            (r"\b(as of|cutoff|cut-off|time)\b", "SHOW_AS_OF"),
            (r"\b(remediation|recommendation|steps|actions)\b", "SHOW_REMEDIATION"),
            (r"\b(export|download|report)\b", "EXPORT_SANITIZED_REPORT"),
        ]
        matches = [intent for pattern, intent in patterns if re.search(pattern, normalized)]
        if len(set(matches)) != 1:
            return {"ok": False, "error": "I couldn't identify one supported request. Try: investigate selected case, show evidence, show lineage, show policy, show cutoff, show remediation, or export sanitized report."}
        intent = matches[0]
        preview = {
            "INVESTIGATE": "Run the existing Python audit engine for the selected case and show its result.",
            "EXPLAIN_FINDING": "Explain the selected case's computed verdict and proof gaps.",
            "SHOW_LINEAGE": "Show only identity and resource links backed by case-linked evidence.",
            "SHOW_EVIDENCE": "Open case-linked evidence metadata with raw text withheld.",
            "SHOW_POLICY": "Show the policy rows used for observed categories.",
            "SHOW_AS_OF": "Show the audit cutoff and evidence excluded after it.",
            "SHOW_REMEDIATION": "Show engine-generated actions as recommendations only.",
            "EXPORT_SANITIZED_REPORT": "Create a report with masked identity and allowlisted metadata.",
        }[intent]
        return {"ok": True, "intent": intent, "target_case_id": selected_case_id,
                "preview": preview, "side_effects": False,
                "notice": "Audit recommendation only — no records modified"}

