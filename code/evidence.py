from __future__ import annotations

import base64
import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
import sys
import subprocess
import unicodedata
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


SYSTEM_PREFIXES = {
    "account": "account_service", "search": "search_service",
    "analytics": "analytics_platform", "support": "support_platform",
    "export": "export_service", "data_flow": "integration_service",
    "backup": "backup_service", "audit_record": "security_service",
    "tombstone": "identity_service", "marketing": "marketing_platform",
    "email_delivery": "email_service", "cache": "cache_service",
    "object": "object_storage", "legal_hold": "legal_service",
}
SYSTEM_NAMES = set(SYSTEM_PREFIXES.values())
RESOURCE_ID_PREFIXES = tuple(SYSTEM_PREFIXES)
RESOURCE_ID_PATTERN = re.compile(
    rf"^(?:{'|'.join(re.escape(prefix) for prefix in RESOURCE_ID_PREFIXES)})_\d+$", re.I
)
RESOURCE_ID_SCAN = re.compile(
    rf"\b(?:{'|'.join(re.escape(prefix) for prefix in RESOURCE_ID_PREFIXES)})_\d+\b", re.I
)
CATEGORY_RULES = [
    (("account_tombstone", "tombstone"), "ACCOUNT_TOMBSTONE"),
    (("security_audit", "audit_record", "audit_records"), "SECURITY_AUDIT_LOG"),
    (("legal_hold", "legal_retention"), "LEGAL_HOLD_RECORD"),
    (("backup", "restore_entry", "restore_entries", "archive"), "BACKUP_ARCHIVE"),
    (("data_flow", "connector", "integration"), "DATA_FLOW"),
    (("search", "index_query", "search_document"), "SEARCH_INDEX_ENTRY"),
    (("cache",), "CACHE_ENTRY"), (("analytics",), "ANALYTICS_PROFILE"),
    (("telemetry",), "PRODUCT_TELEMETRY"),
    (("support_attachment", "attachment"), "SUPPORT_ATTACHMENT"),
    (("support", "ticket", "conversation"), "SUPPORT_MESSAGE"),
    (("export",), "USER_EXPORT"), (("marketing",), "MARKETING_PROFILE"),
    (("email_delivery", "delivery_log"), "EMAIL_DELIVERY_LOG"),
    (("customer_profile", "customer_profiles", "user_profile", "account_service"), "USER_PROFILE"),
    (("secondary_identifier",), "SECONDARY_IDENTIFIER"),
]
PII_FIELDS = {
    "name", "full_name", "display_name", "requester_name", "customer_name",
    "email", "email_address", "requester_email", "customer_email", "owner_email",
    "phone", "phone_number", "requester_phone", "customer_phone", "email_hash",
}
TIMESTAMP_FIELDS = (
    "event_time", "observed_at", "updated_at", "captured_at", "recorded_at",
    "created_at", "indexed_at", "generated_at", "snapshot_at", "timestamp",
)
SUPPORTED_EVIDENCE_SUFFIXES = {".json", ".sql", ".log", ".txt", ".pdf", ".png"}


def resolve_evidence_path(repo: Path, rel_path: str) -> tuple[Path | None, str | None]:
    """Resolve a participant evidence path without allowing manifest escapes."""
    raw = str(rel_path or "").strip()
    if not raw:
        return None, "empty_path"
    windows_path = PureWindowsPath(raw)
    if Path(raw).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return None, "absolute_path"
    if ".." in windows_path.parts or ".." in Path(raw).parts:
        return None, "path_traversal"

    dataset_root = (repo / "dataset").resolve()
    evidence_root = (dataset_root / "evidence").resolve()
    try:
        evidence_root.relative_to(dataset_root)
    except ValueError:
        return None, "evidence_root_escape"

    candidate = (dataset_root / Path(raw)).resolve()
    try:
        candidate.relative_to(evidence_root)
    except ValueError:
        return None, "outside_evidence_root"
    if candidate.suffix.casefold() not in SUPPORTED_EVIDENCE_SUFFIXES:
        return None, "unsupported_extension"
    if not candidate.is_file():
        return None, "missing_file"
    return candidate, None


def evidence_manifest_errors(repo: Path, manifest: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for row in manifest:
        evidence_id = str(row.get("file_id", "")).strip()
        rel_path = str(row.get("file_path", ""))
        if not evidence_id:
            errors.append("manifest row has an empty file_id")
        elif evidence_id in seen_ids:
            errors.append(f"manifest has duplicate file_id {evidence_id!r}")
        seen_ids.add(evidence_id)
        _, issue = resolve_evidence_path(repo, rel_path)
        if issue:
            errors.append(f"manifest file {evidence_id or '<empty>'}: {issue}")
    return errors


def norm(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def normalize_resource_id(value: Any) -> str:
    """Return a concrete corpus resource ID, stripping only wrapper noise."""
    raw = str(value or "").strip()
    if RESOURCE_ID_PATTERN.fullmatch(raw):
        return raw
    wrappers = "\\\"'`<>()[]{}"
    candidate = raw
    while candidate and candidate[0] in wrappers:
        candidate = candidate[1:]
    while candidate and candidate[-1] in wrappers:
        candidate = candidate[:-1]
    return candidate if RESOURCE_ID_PATTERN.fullmatch(candidate) else ""


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def scalar_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_strings(child)
    elif value is not None:
        yield str(value)


def flatten(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(child, (dict, list)):
                    visit(child)
                elif key in result:
                    prior = result[key]
                    result[key] = prior + [child] if isinstance(prior, list) else [prior, child]
                else:
                    result[key] = child
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return result


@dataclass
class Person:
    user_ids: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)

    def match_kind(self, record: "EvidenceRecord") -> str | None:
        # A conflicting explicit subject cannot be overridden by copied email,
        # display-name text, or instructions embedded in an unrelated record.
        subject_keys = {"user_id", "customer_reference", "subject_reference", "customer_id", "subject_id",
                        "subject_ref", "subject_key", "correlation_key", "lookup_key"}
        explicit_subjects = {norm(v) for k, value in record.fields.items() if k.casefold() in subject_keys
                             for v in (value if isinstance(value, list) else [value])
                             if re.fullmatch(r"user_[a-z0-9_-]+", norm(v))}
        if explicit_subjects and self.user_ids:
            if not explicit_subjects <= {norm(v) for v in self.user_ids}:
                return None
            return "user_id"
        values = list(scalar_strings(record.fields))
        joined = "\n".join(norm(v) for v in values if norm(v))
        if any(re.search(rf"(?<![a-z0-9_]){re.escape(uid)}(?![a-z0-9_])", joined)
               for uid in self.user_ids if uid):
            return "user_id"
        if any(alias and re.search(rf"(?<![a-z0-9._%+@-]){re.escape(alias)}(?![a-z0-9._%+@-])", joined)
               for alias in self.emails | self.hashes):
            return "identifier"
        phone_fields = {"phone", "phone_number", "requester_phone", "customer_phone"}
        phone_digits = {re.sub(r"\D", "", value) for value in self.phones
                        if len(re.sub(r"\D", "", value)) >= 8}
        for key, value in record.fields.items():
            if key.casefold() not in phone_fields:
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                digits = re.sub(r"\D", "", str(item or ""))
                if len(digits) >= 8 and digits in phone_digits:
                    return "identifier"
        name_fields = {"name", "full_name", "display_name", "requester_name", "customer_name"}
        for key, value in record.fields.items():
            if key.casefold() not in name_fields:
                continue
            items = value if isinstance(value, list) else [value]
            if any(norm(item) in self.names for item in items if item is not None):
                return "name"
        raw = norm(record.raw_text)
        if any(name and len(name) >= 5 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", raw)
               for name in self.names):
            return "name"
        return None


def load_person(case: dict[str, str], identities: list[dict[str, str]],
                audits: list[dict[str, str]]) -> Person:
    email = norm(case.get("email"))
    cutoff = parse_time(case.get("audit_at"))
    email_owner: dict[str, set[str]] = defaultdict(set)
    for row in identities:
        changed = parse_time(row.get("updated_at"))
        if cutoff and changed and changed > cutoff:
            continue
        if row.get("email"):
            email_owner[norm(row["email"])].add(row["user_id"])
    for row in audits:
        happened = parse_time(row.get("event_time"))
        if cutoff and happened and happened > cutoff:
            continue
        if norm(row.get("field_name")) == "email":
            for value in (row.get("old_value"), row.get("new_value")):
                if value:
                    email_owner[norm(value)].add(row["user_id"])
    person = Person(user_ids=email_owner.get(email, set()), emails={email} if email else set())
    for row in identities:
        changed = parse_time(row.get("updated_at"))
        if row["user_id"] not in person.user_ids or (cutoff and changed and changed > cutoff):
            continue
        for field_name, target in (("email", person.emails), ("phone", person.phones),
                                   ("name", person.names), ("email_hash", person.hashes)):
            if row.get(field_name):
                target.add(norm(row[field_name]))
    for row in audits:
        happened = parse_time(row.get("event_time"))
        if row["user_id"] not in person.user_ids or (cutoff and happened and happened > cutoff):
            continue
        target = {
            "email": person.emails, "phone": person.phones,
            "name": person.names, "email_hash": person.hashes,
        }.get(norm(row.get("field_name")))
        if target:
            target.update(norm(v) for v in (row.get("old_value"), row.get("new_value")) if v)
    return person


@dataclass
class EvidenceRecord:
    evidence_id: str
    path: str
    file_time: dt.datetime | None
    observed_time: dt.datetime | None
    system_id: str
    category: str
    resource_id: str
    fields: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    kind: str = ""

    def values(self) -> list[str]:
        values = list(scalar_strings(self.fields))
        if self.raw_text:
            values.append(self.raw_text)
        return values


def infer_system(resource_id: str, fields: dict[str, Any], context: str = "") -> str:
    for key in ("system_id", "source_system", "origin_system", "service", "system"):
        value = norm(fields.get(key))
        if value in SYSTEM_NAMES:
            return value
    rid = resource_id.casefold()
    for prefix, system in sorted(SYSTEM_PREFIXES.items(), key=lambda item: -len(item[0])):
        if rid.startswith(prefix + "_"):
            return system
    context = norm(context)
    return next((system for system in SYSTEM_NAMES if system in context), "")


def infer_category(resource_id: str, fields: dict[str, Any], context: str = "") -> str:
    explicit = str(fields.get("data_category") or fields.get("category") or fields.get("record_type") or "")
    known = {category for _, category in CATEGORY_RULES}
    if explicit.upper() in known:
        return explicit.upper()
    source = " ".join([explicit, context, resource_id, " ".join(fields.keys())]).casefold()
    rid = resource_id.casefold()
    # Resource prefixes are stronger evidence than generic UI words such as "search".
    prefix_categories = (
        ("tombstone_", "ACCOUNT_TOMBSTONE"), ("audit_record_", "SECURITY_AUDIT_LOG"),
        ("legal_hold_", "LEGAL_HOLD_RECORD"), ("backup_", "BACKUP_ARCHIVE"),
        ("data_flow_", "DATA_FLOW"),
        ("search_", "SEARCH_INDEX_ENTRY"), ("cache_", "CACHE_ENTRY"),
        ("analytics_", "ANALYTICS_PROFILE"), ("export_", "USER_EXPORT"),
        ("marketing_", "MARKETING_PROFILE"), ("email_delivery_", "EMAIL_DELIVERY_LOG"),
        ("account_", "ACCOUNT_TOMBSTONE" if "tombstone" in source else "USER_PROFILE"),
    )
    for prefix, category in prefix_categories:
        if rid.startswith(prefix):
            return category
    if rid.startswith("support_"):
        return "SUPPORT_ATTACHMENT" if "attachment" in source else "SUPPORT_MESSAGE"
    return next((category for words, category in CATEGORY_RULES
                 if any(word in source for word in words)), "")


def get_record_time(fields: dict[str, Any], file_time: dt.datetime | None) -> dt.datetime | None:
    for key in TIMESTAMP_FIELDS:
        value = fields.get(key)
        if isinstance(value, list):
            value = next((item for item in reversed(value) if parse_time(item)), None)
        parsed = parse_time(value)
        if parsed:
            return parsed
    return file_time


def resource_ids(text: str) -> list[str]:
    return list(dict.fromkeys(RESOURCE_ID_SCAN.findall(text)))


class EvidenceIndex:
    def __init__(self, repo: Path):
        self.repo = repo
        self.manifest = read_csv(repo / "dataset" / "evidence_files.csv")
        self.activities = read_csv(repo / "dataset" / "system_activity.csv")
        self.activities_by_resource: dict[str, list[dict[str, str]]] = defaultdict(list)
        for activity in self.activities:
            resource_id = activity.get("resource_id", "")
            if resource_id:
                self.activities_by_resource[resource_id].append(activity)
        self.records: list[EvidenceRecord] = []
        self.account_evidence: list[tuple[dt.datetime | None, str]] = []
        self.unparsed: list[str] = []
        self.manifest_errors = evidence_manifest_errors(repo, self.manifest)
        self._load()
        self.use_identity_index = True
        self._identity_lookup: dict[str, set[int]] = defaultdict(set)
        self._raw_name_candidates: list[tuple[int, str]] = []
        for index, record in enumerate(self.records):
            values = [norm(value) for value in scalar_strings(record.fields)]
            joined = "\n".join(values)
            keys = set(values)
            keys.update(re.findall(r"(?<![a-z0-9_])user_[a-z0-9_]+(?![a-z0-9_])", joined))
            keys.update(re.findall(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", joined))
            keys.update(re.findall(r"(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])", joined))
            for key, value in record.fields.items():
                if key.casefold() in {"phone", "phone_number", "requester_phone", "customer_phone"}:
                    for item in (value if isinstance(value, list) else [value]):
                        digits = re.sub(r"\D", "", str(item or ""))
                        if len(digits) >= 8:
                            keys.add(digits)
            for key in keys:
                if key:
                    self._identity_lookup[key].add(index)
            if record.raw_text:
                self._raw_name_candidates.append((index, norm(record.raw_text)))

    def _identity_candidate_indices(self, person: Person) -> set[int]:
        keys = person.user_ids | person.emails | person.hashes | person.names
        keys |= {re.sub(r"\D", "", value) for value in person.phones}
        candidates: set[int] = set()
        for key in keys:
            candidates.update(self._identity_lookup.get(norm(key), ()))
        for index, raw in self._raw_name_candidates:
            if any(len(name) >= 5 and name in raw for name in person.names):
                candidates.add(index)
        return candidates

    def _add(self, evidence_id: str, rel_path: str, captured: dt.datetime | None,
             rid: str, fields: dict[str, Any], context: str, raw: str = "", kind: str = "") -> None:
        rid = normalize_resource_id(rid)
        if not rid:
            return
        self.records.append(EvidenceRecord(
            evidence_id, rel_path, captured, get_record_time(fields, captured),
            infer_system(rid, fields, context),
            infer_category(rid, fields, context), str(rid), fields, raw, kind
        ))

    def _walk_json(self, evidence_id: str, rel_path: str, captured: dt.datetime | None,
                   node: Any, context: str = "") -> None:
        if isinstance(node, dict):
            local = context
            for key in ("system_id", "source_system", "origin_system", "service", "system"):
                if isinstance(node.get(key), str):
                    local += " " + node[key]
            rid = node.get("resource_id") or node.get("record_id")
            if rid:
                self._add(evidence_id, rel_path, captured, str(rid), flatten(node), local, kind="json")
            for key, child in node.items():
                next_context = local if key == "service_exports" else local + " " + str(key)
                self._walk_json(evidence_id, rel_path, captured, child, next_context)
        elif isinstance(node, list):
            for child in node:
                self._walk_json(evidence_id, rel_path, captured, child, context)

    def _parse_line(self, line: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        pipe = [part.strip() for part in line.strip().lstrip("- ").split("|")]
        if len(pipe) >= 6 and re.match(r"^\d{4}-\d{2}-\d{2}T", pipe[0]):
            if norm(pipe[1]) in {"trace", "debug", "info", "warn", "warning", "error", "fatal"}:
                # Operational streams use time | level | system | trace | event | details.
                # Do not mistake the service name for a resource or the event
                # name for the resource's state.
                fields.update({
                    "event_time": pipe[0],
                    "level": pipe[1],
                    "system_id": pipe[2],
                    "trace_id": pipe[3],
                    "event_name": pipe[4],
                    "message": " | ".join(pipe[5:]),
                })
            else:
                # Resource snapshots use time | system | resource | category | state | details.
                fields.update({
                    "event_time": pipe[0],
                    "system_id": pipe[1],
                    "resource_id": pipe[2],
                    "data_category": pipe[3],
                    "state": pipe[4],
                    "message": " | ".join(pipe[5:]),
                })
                if re.fullmatch(r"user_\d+", pipe[5], re.I):
                    fields["subject_reference"] = pipe[5]
        start, end = line.find("{"), line.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(line[start:end + 1])
                if isinstance(obj, dict):
                    fields.update(obj)
            except json.JSONDecodeError:
                pass
        # Cloud log envelopes contain escaped key/value messages. Decode the
        # quoted value before reading its fields; splitting at an escaped quote
        # loses both resource IDs and the request/response correlation.
        pattern = re.compile(r'''([A-Za-z_][A-Za-z0-9_]*)=(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^,\s]+))''')
        def key_values(value: str) -> dict[str, str]:
            result: dict[str, str] = {}
            for match in pattern.finditer(value):
                quoted, single, bare = match.groups()[1:]
                item = quoted if quoted is not None else single if single is not None else bare or ""
                if quoted is not None:
                    try:
                        item = json.loads('"' + quoted + '"')
                    except json.JSONDecodeError:
                        pass
                result.setdefault(match.group(1), item)
            return result
        outer = key_values(line)
        for key, value in outer.items():
            fields.setdefault(key, value)
        if isinstance(outer.get("message"), str):
            for key, value in key_values(outer["message"]).items():
                fields.setdefault(key, value)
        if fields.get("requestId"):
            fields.setdefault("trace_id", fields["requestId"])
        if fields.get("function") in SYSTEM_NAMES:
            fields.setdefault("system_id", fields["function"])
        syslog = re.match(r"^\S+\s+<\d+>1\s+\S+\s+(\S+)\s+(\S+)\s+-\s+-\s+", line)
        if syslog and syslog.group(1) in SYSTEM_NAMES:
            fields.setdefault("system_id", syslog.group(1))
            fields.setdefault("trace_id", syslog.group(2))
        stamp = re.match(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+Z?)", line)
        if stamp:
            fields.setdefault("event_time", stamp.group(1))
        if not fields:
            fields["message"] = line
        return fields

    def _parse_text(self, evidence_id: str, rel_path: str, captured: dt.datetime | None,
                    text: str, kind: str) -> None:
        parsed: list[tuple[str, dict[str, Any], list[str]]] = []
        trace_context: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        identity_keys = {"user_id", "customer_reference", "subject_reference", "customer_id", "subject_id",
                         "subject_ref", "subject_key", "correlation_key", "lookup_key", "match_key",
                         "email", "email_address", "email_hash", "phone", "phone_number", "source"}
        def trace_key(fields: dict[str, Any]) -> tuple[str, ...] | None:
            trace = str(fields.get("trace_id") or "")
            if not trace:
                return None
            service = fields.get("system_id") or fields.get("service") or fields.get("function") or ""
            return (str(service), trace, str(fields.get("instance") or ""), str(fields.get("pod") or ""))
        image_resources = set(resource_ids(text)) if kind == "png" else set()
        image_emails = set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)) if kind == "png" else set()
        image_subjects = set(re.findall(r"\buser_\d+\b", text, re.I)) if kind == "png" else set()
        single_image_resource = next(iter(image_resources)) if len(image_resources) == 1 and len(image_emails) <= 1 else ""
        filtered_subject = next(iter(image_subjects)) if len(image_subjects) == 1 and re.search(r"subject filter", text, re.I) else ""
        image_aggregate: dict[tuple[str, str], dict[str, Any]] = {}
        for line in text.splitlines():
            fields = self._parse_line(line)
            ids = resource_ids(line)
            if kind == "png" and not ids and single_image_resource:
                ids = [single_image_resource]
            explicit = fields.get("resource_id") or fields.get("record_id")
            if explicit:
                ids.insert(0, str(explicit))
            trace = trace_key(fields)
            if trace:
                trace_context[trace].append(fields)
            parsed.append((line, fields, list(dict.fromkeys(ids))))
        for line, fields, ids in parsed:
            trace = trace_key(fields)
            if trace:
                # Carry only identity query context from earlier events in the
                # same service/span. Never move state across rows or import an
                # identity discovered after the state observation.
                observed = get_record_time(fields, captured)
                context: dict[str, Any] = {}
                conflict = False
                for prior in trace_context[trace]:
                    happened = get_record_time(prior, captured)
                    if observed is None or happened is None or happened > observed:
                        continue
                    for key in identity_keys & prior.keys():
                        if key in context and norm(context[key]) != norm(prior[key]):
                            conflict = True
                        context.setdefault(key, prior[key])
                if not conflict:
                    fields = {**context, **fields}
            fields.setdefault("line_text", line)
            if str(fields.get("event") or fields.get("event_name") or "").endswith("_started"):
                # A query starting (even with a known resource ID) does not
                # prove that its target exists. Its context remains available
                # to the eventual response in the same span.
                continue
            if kind == "png" and filtered_subject:
                fields.setdefault("subject_reference", filtered_subject)
            if kind == "png":
                for rid in ids:
                    key = (evidence_id, rid)
                    entry = image_aggregate.setdefault(key, {"fields": {}, "lines": []})
                    entry["lines"].append(line)
                    for name, value in fields.items():
                        if name == "line_text":
                            continue
                        previous = entry["fields"].get(name)
                        if previous is None:
                            entry["fields"][name] = value
                        elif value != previous:
                            values = previous if isinstance(previous, list) else [previous]
                            if value not in values:
                                values.append(value)
                            entry["fields"][name] = values
            else:
                for rid in ids:
                    self._add(evidence_id, rel_path, captured, rid, fields, rel_path + " " + line, line, kind)
        if kind == "png":
            for (aggregate_evidence_id, rid), entry in list(image_aggregate.items()):
                if aggregate_evidence_id != evidence_id:
                    continue
                image_text = "\n".join(entry["lines"])
                combined = dict(entry["fields"])
                combined["line_text"] = list(entry["lines"])
                self._add(evidence_id, rel_path, captured, rid, combined, rel_path + " " + image_text, image_text, kind)
                del image_aggregate[(aggregate_evidence_id, rid)]

    def _catalog_inventory(self, evidence_id: str, rel_path: str, captured: dt.datetime | None,
                           text: str, origin: str) -> None:
        """Join an exact catalog filename to a visible object metadata panel.

        The catalog supplies identity/resource membership only; the screenshot
        must independently show a size and version for that selected object.
        """
        if origin != "object_storage" or captured is None:
            return
        aliases: dict[str, list[dict[str, str]]] = defaultdict(list)
        for activity in self.activities:
            if (norm(activity.get("event_type")) != "link_resource_identity"
                    or norm(activity.get("reported_result")) != "success"
                    or norm(activity.get("target_system")) != origin):
                continue
            # The supplied attachment policy permits deletion only for an
            # exclusively owned attachment. Do not infer exclusivity from a
            # filename or from a shared ticket.
            details = str(activity.get("details") or "")
            if not re.search(r"\bbelongs only to\b", details, re.I):
                continue
            for filename in re.findall(r"[a-z0-9][a-z0-9_.-]*\.(?:pdf|png|jpe?g|txt|csv|zip)\b", details, re.I):
                aliases[norm(filename)].append(activity)
        for filename, links in aliases.items():
            resource_ids_ = {row.get("resource_id") for row in links}
            if len(resource_ids_) != 1:
                continue
            match = re.search(rf"(?<![\w.-]){re.escape(filename)}(?![\w.-])", text, re.I)
            if not match:
                continue
            panel = text[match.start():match.end() + 350]
            # A search query or a filename mentioned in an activity feed is
            # insufficient. Require the selected object's metadata panel.
            if (not re.search(r"\bSize\s+\d+(?:\.\d+)?\s*(?:KB|MB|GB|bytes)\b", panel, re.I)
                    or not re.search(r"\bVersion\s+v\d+\b", panel, re.I)
                    or re.search(r"\b(?:not found|deleted|no match)\b", panel, re.I)):
                continue
            resource_id = next(iter(resource_ids_))
            fields = {"system_id": origin, "data_category": "SUPPORT_ATTACHMENT",
                      "file_name": filename, "state": "PRESENT", "observed_at": captured.isoformat(),
                      "exclusive_attachment": True}
            self._add(evidence_id, rel_path, captured, str(resource_id), fields,
                      "object storage selected attachment metadata", panel, "png")

    def _pdf_text(self, path: Path) -> str:
        data = path.read_bytes()
        decoded_streams: list[bytes] = []
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
            start = match.start()
            dictionary_start = data.rfind(b"<<", max(0, start - 1024), start)
            dictionary = data[dictionary_start:start] if dictionary_start >= 0 else b""
            stream = match.group(1).rstrip(b"\r\n")
            try:
                if b"ASCII85Decode" in dictionary:
                    stream = base64.a85decode(stream.rstrip(b"~>"), adobe=False)
                if b"FlateDecode" in dictionary:
                    stream = zlib.decompress(stream)
            except (ValueError, zlib.error):
                continue
            decoded_streams.append(stream)

        cmap: dict[bytes, str] = {}
        for stream in decoded_streams:
            if b"begincmap" not in stream:
                continue
            for block in re.findall(rb"beginbfchar(.*?)endbfchar", stream, re.S):
                for source, target in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                    try:
                        cmap[bytes.fromhex(source.decode("ascii"))] = bytes.fromhex(target.decode("ascii")).decode("utf-16-be")
                    except (ValueError, UnicodeDecodeError):
                        continue
        code_sizes = sorted({len(code) for code in cmap}, reverse=True)

        def decode_codes(raw: bytes) -> str:
            if not cmap:
                return raw.decode("latin-1", errors="replace")
            chars: list[str] = []
            i = 0
            while i < len(raw):
                found = False
                for width in code_sizes:
                    code = raw[i:i + width]
                    if len(code) == width and code in cmap:
                        chars.append(cmap[code])
                        i += width
                        found = True
                        break
                if not found:
                    chars.append(raw[i:i + 1].decode("latin-1", errors="replace"))
                    i += 1
            return "".join(chars)

        def literal_bytes(token: bytes) -> bytes:
            output = bytearray()
            i = 1
            while i < len(token) - 1:
                byte = token[i]
                if byte != 0x5C:
                    output.append(byte)
                    i += 1
                    continue
                i += 1
                if i >= len(token) - 1:
                    break
                escaped = token[i]
                if escaped in b"nrtbf":
                    output.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[escaped])
                    i += 1
                elif escaped in b"()\\":
                    output.append(escaped)
                    i += 1
                elif escaped in b"\r\n":
                    if escaped == 13 and i + 1 < len(token) and token[i + 1] == 10:
                        i += 1
                    i += 1
                elif 48 <= escaped <= 55:
                    digits = bytearray([escaped])
                    i += 1
                    for _ in range(2):
                        if i < len(token) - 1 and 48 <= token[i] <= 55:
                            digits.append(token[i]); i += 1
                        else:
                            break
                    output.append(int(digits.decode("ascii"), 8) & 0xFF)
                else:
                    output.append(escaped)
                    i += 1
            return bytes(output)

        chunks: list[str] = []
        for stream in decoded_streams:
            if b"BT" not in stream or b"Tj" not in stream or b"ET" not in stream:
                continue
            for block in re.findall(rb"BT(.*?)ET", stream, re.S):
                i = 0
                while i < len(block):
                    if block[i] == 0x28:
                        start = i
                        depth = 1
                        i += 1
                        while i < len(block) and depth:
                            if block[i] == 0x5C:
                                i += 2
                                continue
                            if block[i] == 0x28:
                                depth += 1
                            elif block[i] == 0x29:
                                depth -= 1
                            i += 1
                        token = block[start:i]
                        if len(token) > 2:
                            chunks.append(decode_codes(literal_bytes(token)))
                    elif block[i] == 0x3C and i + 1 < len(block) and block[i + 1] != 0x3C:
                        end = block.find(b">", i + 1)
                        if end >= 0:
                            digits = re.sub(rb"\s+", b"", block[i + 1:end])
                            try:
                                raw = bytes.fromhex(digits.decode("ascii"))
                                chunks.append(decode_codes(raw))
                            except (ValueError, UnicodeDecodeError):
                                pass
                            i = end + 1
                    else:
                        i += 1
        return " ".join(chunk for chunk in chunks if chunk.strip())

    @staticmethod
    def _group_windows_ocr(output: str) -> str:
        try:
            items = json.loads(output)
        except json.JSONDecodeError:
            return output.strip()
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return ""
        lines = [item for item in items if isinstance(item, dict) and item.get("text")]
        image_width = max((float(item.get("image_width", 0)) for item in lines), default=0.0)
        side_threshold = image_width * 0.78 if image_width else float("inf")
        groups: list[dict[str, Any]] = []
        for item in sorted(lines, key=lambda row: (float(row.get("y", 0)), float(row.get("x", 0)))):
            y = float(item.get("y", 0))
            height = float(item.get("height", 0))
            region = "side" if float(item.get("x", 0)) >= side_threshold else "main"
            match = next((group for group in groups
                          if group["region"] == region
                          and abs(y - group["y"]) <= max(8.0, height * 0.55, group["height"] * 0.55)), None)
            if match is None:
                groups.append({"y": y, "height": height, "region": region, "items": [item]})
            else:
                match["items"].append(item)
                match["y"] = sum(float(row.get("y", 0)) for row in match["items"]) / len(match["items"])
                match["height"] = max(match["height"], height)
        active_side_resource = ""
        output_lines: list[str] = []
        for group in sorted(groups, key=lambda row: (row["y"], row["region"])):
            parts = sorted(group["items"], key=lambda row: float(row.get("x", 0)))
            text = " ".join(str(item["text"]).strip() for item in parts if str(item["text"]).strip())
            if group["region"] == "side":
                if re.search(r"\bactivity\b", text, re.I):
                    active_side_resource = ""
                else:
                    ids = resource_ids(text)
                    if ids:
                        active_side_resource = ids[0]
                    elif active_side_resource:
                        text = active_side_resource + " " + text
            output_lines.append(text)
        return "\n".join(output_lines)

    def _external_text(self, path: Path, kind: str) -> str:
        if kind == "pdf":
            executable = shutil.which("pdftotext")
            if not executable:
                return ""
            command = [executable, "-layout", str(path), "-"]
        elif kind == "png":
            executable = shutil.which("tesseract")
            if executable:
                command = [executable, str(path), "stdout", "--psm", "6"]
            elif sys.platform == "win32":
                executable = shutil.which("powershell.exe") or shutil.which("powershell")
                script = Path(__file__).with_name("windows_ocr.ps1")
                if not executable or not script.is_file():
                    return ""
                command = [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(script), "-ImagePath", str(path)]
            else:
                return ""
        else:
            return ""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
            if result.returncode != 0:
                return ""
            if kind == "png" and any(part.casefold().endswith("windows_ocr.ps1") for part in command):
                return self._group_windows_ocr(result.stdout)
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def _load(self) -> None:
        for item in self.manifest:
            evidence_id, rel_path = item["file_id"], item["file_path"]
            captured = parse_time(item.get("captured_at"))
            path, path_issue = resolve_evidence_path(self.repo, rel_path)
            if path_issue or path is None:
                self.unparsed.append(rel_path)
                continue
            try:
                suffix = path.suffix.casefold()
                if suffix == ".json":
                    context = path.stem.replace("service_resource_export_", "")
                    self._walk_json(evidence_id, rel_path, captured,
                                    json.loads(path.read_text(encoding="utf-8-sig")), context)
                elif suffix == ".sql":
                    db = sqlite3.connect(":memory:")
                    def sql_authorizer(action: int, arg1: str | None, arg2: str | None,
                                       database: str | None, trigger: str | None) -> int:
                        if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
                            return sqlite3.SQLITE_DENY
                        if action == sqlite3.SQLITE_FUNCTION and norm(arg2) in {"load_extension", "readfile", "writefile"}:
                            return sqlite3.SQLITE_DENY
                        return sqlite3.SQLITE_OK
                    db.set_authorizer(sql_authorizer)
                    db.executescript(path.read_text(encoding="utf-8-sig"))
                    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                        quoted_table = table.replace('"', '""')
                        columns = [c[1] for c in db.execute(f'PRAGMA table_info("{quoted_table}")')]
                        for row in db.execute(f'SELECT * FROM "{quoted_table}"'):
                            fields = dict(zip(columns, row))
                            nested = fields.get("record_json")
                            if isinstance(nested, str):
                                try:
                                    obj = json.loads(nested)
                                    if isinstance(obj, dict):
                                        fields.update(flatten(obj))
                                except json.JSONDecodeError:
                                    pass
                            fields["__storage_scope"] = table
                            rid = fields.get("resource_id") or fields.get("record_id")
                            if rid:
                                context = rel_path + " " + table + " " + str(fields.get("collection_name") or "")
                                self._add(evidence_id, rel_path, captured, str(rid), fields, context, kind="sql")
                            if "customer_profiles" in table.casefold() or "customer_profiles" in str(fields.get("collection_name", "")).casefold():
                                self.account_evidence.append((captured, evidence_id))
                    db.close()
                elif suffix in {".log", ".txt"}:
                    self._parse_text(evidence_id, rel_path, captured,
                                     path.read_text(encoding="utf-8-sig", errors="replace"), suffix[1:])
                elif suffix in {".pdf", ".png"}:
                    kind = "pdf" if suffix == ".pdf" else "png"
                    text = self._pdf_text(path) if kind == "pdf" else ""
                    if not text:
                        text = self._external_text(path, kind)
                    if text:
                        self._parse_text(evidence_id, rel_path, captured, text, kind)
                        if kind == "png":
                            self._catalog_inventory(evidence_id, rel_path, captured, text, item.get("origin", ""))
                    else:
                        self.unparsed.append(rel_path)
            except (OSError, sqlite3.Error, json.JSONDecodeError, ValueError):
                self.unparsed.append(rel_path)

    def identity_link_events(self, person: Person, audit_at: dt.datetime) -> list[dict[str, str]]:
        """Return activity rows that can connect an identity to a resource.

        These are relationship candidates only. Their reported result never
        establishes the current state of the referenced resource.
        """
        person_ids = {norm(value) for value in person.user_ids if value}
        person_emails = {norm(value) for value in person.emails if value}
        person_hashes = {norm(value) for value in person.hashes if value}
        matches: list[dict[str, str]] = []
        for activity in getattr(self, "activities", []):
            if norm(activity.get("event_type")) != "link_resource_identity":
                continue
            if norm(activity.get("reported_result")) != "success":
                continue
            if not activity.get("resource_id"):
                continue
            event_time = parse_time(activity.get("event_time"))
            if event_time is None or event_time > audit_at:
                continue

            details = norm(activity.get("details", ""))
            mentioned_ids = {value.casefold() for value in
                             re.findall(r"\buser_[a-z0-9_-]+\b", details, flags=re.I)}
            if mentioned_ids:
                # Reject mixed or conflicting identity references. A stable ID
                # is stronger than a name or a loose text match.
                if len(mentioned_ids) == 1 and mentioned_ids <= person_ids:
                    matches.append(activity)
                continue

            # Some catalog events identify a subject by email/hash only. Use
            # exact token boundaries and require one unambiguous resolved user.
            if len(person_ids) > 1:
                continue
            mentioned_emails = {norm(value) for value in re.findall(
                r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", details, flags=re.I)}
            if mentioned_emails:
                if mentioned_emails <= person_emails:
                    matches.append(activity)
                continue
            for alias in person_hashes:
                if alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", details):
                    matches.append(activity)
                    break
        return sorted(matches, key=lambda row: (parse_time(row.get("event_time")) or audit_at,
                                                row.get("activity_id", "")))

    def observations_for(self, person: Person, audit_at: dt.datetime) -> list[EvidenceRecord]:
        eligible = [
            record for record in self.records
            if record.file_time is not None and record.file_time <= audit_at
            and record.observed_time is not None and record.observed_time <= audit_at
        ]
        if getattr(self, "use_identity_index", False):
            candidates = self._identity_candidate_indices(person)
            candidate_ids = {id(self.records[index]) for index in candidates}
            direct = [record for record in eligible if id(record) in candidate_ids and person.match_kind(record)]
        else:
            direct = [record for record in eligible if person.match_kind(record)]
        # A successful, exact identity-link event can connect a subject to a
        # resource whose state is documented in a separate evidence artifact.
        # The activity row is not added as a state observation: only the
        # separately parsed, cutoff-admissible artifact is returned.
        linked_resources = {
            row.get("resource_id", "")
            for row in self.identity_link_events(person, audit_at)
            if row.get("resource_id")
        }
        # Once a resource is directly tied to the subject, keep every response
        # for that same resource in the same artifact (for example, a lookup
        # start followed by its 404 completion). Do not attach other resources
        # merely because their timestamps are nearby; global snapshots contain
        # unrelated customers with interleaved observation times.
        direct_keys = {(record.evidence_id, record.resource_id) for record in direct}
        direct_keys.update((record.evidence_id, record.resource_id) for record in eligible
                           if record.resource_id in linked_resources)
        selected = [
            record for record in eligible
            if (record.evidence_id, record.resource_id) in direct_keys
        ]
        latest: dict[tuple[str, str, str, str], list[EvidenceRecord]] = {}
        for record in selected:
            # A primary and its replica are independent copies. A negative
            # lookup in one store cannot erase a surviving record in another.
            scope = str(record.fields.get("__storage_scope") or record.fields.get("storage_scope") or "")
            key = (record.system_id, record.resource_id, record.category, scope)
            previous = latest.get(key, [])
            order = record.observed_time or record.file_time or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            prior_order = (previous[0].observed_time or previous[0].file_time) if previous else None
            if not previous or prior_order is None or order > prior_order:
                latest[key] = [record]
            elif order == prior_order:
                # Keep simultaneous contradictory observations rather than
                # resolving the verdict according to input row order.
                latest[key].append(record)
        return [record for group in latest.values() for record in group]
