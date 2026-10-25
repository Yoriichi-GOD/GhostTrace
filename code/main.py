from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from evidence import EvidenceIndex, EvidenceRecord, Person, load_person, parse_time, read_csv, norm


PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0, "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2, "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0, "BLOCK_RESTORE": 1, "DELETE_RECORD": 2,
    "REDACT_RECORD": 3, "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0, "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2, "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4, "VERIFY_RESTORE_BLOCKED": 5,
}
PII_FIELDS = {
    "name", "full_name", "display_name", "requester_name", "customer_name",
    "email", "email_address", "requester_email", "customer_email", "owner_email",
    "phone", "phone_number", "requester_phone", "customer_phone", "email_hash",
}
REFERENCE_FIELDS = {"user_id", "customer_reference", "subject_reference", "customer_id", "subject_id"}

NEGATIVE_INTENT = re.compile(
    r"\b(?:do not|don't|dont|never)\s+(?:delete|erase|remove|purge|close|destroy|wipe)\b|"
    r"\b(?:not asking|not requesting|no deseo|no quiero|no solicito)\b|"
    r"\bkeep my account\b|\bleave (?:the )?account active\b|"
    r"\bcontinue using\b|\bleave my profile\b|\bkeep the account as it is\b", re.I
)
POSITIVE_INTENT = re.compile(
    r"(?:delet|eras|remov|purge|close.{0,30}account|elimin|borr|suprim|"
    r"suppression|effac|exclu|apag|l[oö]sch|entfern|удал|删除|刪除|削除|消去|"
    r"삭제|حذف|हट|मिट|delete my data|right to be forgotten|"
    r"profile.{0,30}gone|records?.{0,50}cannot identify me)", re.I
)
QUESTION_ONLY = re.compile(r"^\s*(?:how (?:do|can) i|what happens if|is there a way to)\b", re.I)


def authorizes_deletion(text: str) -> bool:
    if NEGATIVE_INTENT.search(text):
        # Politeness does not reverse negation ("please do not delete").
        return False
    if QUESTION_ONLY.search(text) and not re.search(r"\b(?:please|i request|i want|i would like)\b", text, re.I):
        return False
    return bool(POSITIVE_INTENT.search(text))


def values_for(fields: dict[str, Any], keys: set[str]) -> list[str]:
    values: list[str] = []
    for key, value in fields.items():
        if key.casefold() in keys:
            if isinstance(value, list):
                values.extend(str(item) for item in value if item is not None)
            elif value is not None:
                values.append(str(value))
    return values


def has_identifier(record: EvidenceRecord, person: Person) -> bool:
    aliases = person.emails | person.hashes | person.names
    for value in values_for(record.fields, PII_FIELDS):
        text = norm(value)
        if text and text in aliases:
            return True
        digits = re.sub(r"\D", "", text)
        for phone in person.phones:
            phone_digits = re.sub(r"\D", "", phone)
            if len(phone_digits) >= 8 and len(digits) >= 8 and phone_digits in digits:
                return True
    raw = norm(record.raw_text)
    return any(alias and alias in raw for alias in person.emails | person.hashes | person.names)


def linked_to_subject(record: EvidenceRecord, person: Person) -> bool:
    user_ids = {norm(uid) for uid in person.user_ids}
    for key, value in record.fields.items():
        if key.casefold() in REFERENCE_FIELDS:
            vals = value if isinstance(value, list) else [value]
            if any(norm(item) in user_ids for item in vals):
                return True
    return has_identifier(record, person)


def exposed_pii(record: EvidenceRecord, person: Person) -> bool:
    if has_identifier(record, person):
        return True
    user_ids = {norm(uid) for uid in person.user_ids}
    linked = any(
        key.casefold() in REFERENCE_FIELDS
        and any(norm(item) in user_ids for item in (value if isinstance(value, list) else [value]))
        for key, value in record.fields.items()
    )
    return linked and any(norm(value) for value in values_for(record.fields, PII_FIELDS))


def present(record: EvidenceRecord) -> bool:
    fields = record.fields
    for key in ("status_code", "http_status"):
        try:
            if int(str(fields.get(key, 0))) in {404, 410}:
                return False
        except (TypeError, ValueError):
            pass
    for key in ("rows", "row_count", "result_count", "matches"):
        try:
            if int(str(fields.get(key))) == 0:
                return False
        except (TypeError, ValueError):
            pass
    result = norm(fields.get("result") or fields.get("lookup_result") or fields.get("state"))
    if result in {"not_found", "not found", "absent", "missing", "no_match", "no match"}:
        return False
    if result in {"deleted", "not present", "no record"}:
        return False
    if "profile" in fields and fields.get("profile") is None:
        return False
    if result in {"found", "hit", "present", "success"}:
        return True
    return True


def flag(fields: dict[str, Any], names: tuple[str, ...]) -> bool | None:
    for name in names:
        if name not in fields:
            continue
        value = norm(fields[name])
        if value in {"true", "1", "yes", "enabled", "active", "allowed"}:
            return True
        if value in {"false", "0", "no", "disabled", "inactive", "blocked"}:
            return False
    return None


def risk_is_active(explicitly_active: bool | None) -> bool:
    # Without proof that a recreation path is disabled, treat it as a live risk.
    return explicitly_active is not False


def policy_action(category: str, fields: dict[str, Any], audit_at: dt.datetime,
                  rules: dict[str, dict[str, str]] | None = None) -> str:
    required = (rules or {}).get(category, {}).get("required_action", "")
    if category == "SECURITY_AUDIT_LOG":
        until = parse_time(fields.get("retention_until"))
        return "RETAIN" if until is None or until >= audit_at else "DELETE"
    if category == "LEGAL_HOLD_RECORD":
        value = norm(fields.get("active") or fields.get("hold_status"))
        return "RETAIN" if value in {"true", "active", "1", "yes"} else (required or "DELETE")
    if category == "BACKUP_ARCHIVE":
        return "BLOCK_RESTORE" if required in {"RETAIN", "BLOCK_RESTORE"} else required
    if category == "DATA_FLOW":
        return "DISABLE_DATA_FLOW"
    if category == "SUPPORT_MESSAGE":
        event = norm(fields.get("event"))
        source = norm(fields.get("source"))
        if "contact_query" in event or "legacy_contact_index" in source:
            return "DELETE"
        return required or "REDACT"
    if category == "EMAIL_DELIVERY_LOG":
        return required or "REDACT"
    return required


def step(phase: str, record: EvidenceRecord, operation: str, state: str, evidence_id: str) -> dict[str, Any]:
    return {
        "step_no": 0, "phase": phase, "system_id": record.system_id,
        "resource_id": record.resource_id, "operation": operation,
        "state": state, "evidence_id": evidence_id,
    }


def sort_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in steps:
        key = (item["phase"], item["operation"], item["system_id"], item["resource_id"])
        old = unique.get(key)
        if old is None or (not old["evidence_id"] and item["evidence_id"]):
            unique[key] = item
    ordered = sorted(unique.values(), key=lambda item: (
        PHASE_ORDER[item["phase"]], OPERATION_ORDER.get(item["operation"], 99),
        item["system_id"], item["resource_id"],
    ))
    for index, item in enumerate(ordered, 1):
        item["step_no"] = index
    return ordered


class Auditor:
    def __init__(self, repo: Path):
        self.repo = repo
        self.identities = read_csv(repo / "dataset" / "user_identities.csv")
        self.audits = read_csv(repo / "dataset" / "user_audit_log.csv")
        self.rules = {row["data_category"]: row for row in read_csv(repo / "dataset" / "deletion_rules.csv")}
        self.evidence = EvidenceIndex(repo)
        self.diagnostics: dict[str, list[dict[str, str]]] = {}

    def _records_for(self, person: Person, audit_at: dt.datetime) -> list[EvidenceRecord]:
        records = self.evidence.observations_for(person, audit_at)
        accounts = [r for r in records if r.category == "USER_PROFILE" and r.system_id == "account_service"]
        latest = max((r.observed_time or r.file_time for r in accounts), default=None)
        # Historical negative lookups add no present-day remediation obligation.
        # Keep surviving copies in every scope, even when a newer lookup elsewhere
        # reports absence. This is deliberately asymmetric for safety.
        if latest:
            records = [r for r in records if not (r in accounts and not present(r)
                       and (r.observed_time or r.file_time) < latest)]
        return records

    def audit_case(self, case: dict[str, str]) -> dict[str, str]:
        diagnostics: list[dict[str, str]] = []
        self.diagnostics[case["case_id"]] = diagnostics
        if not authorizes_deletion(case.get("request_text", "")):
            return {"case_id": case["case_id"], "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}
        audit_at = parse_time(case.get("audit_at")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        person = load_person(case, self.identities, self.audits)
        if len(person.user_ids) > 1:
            diagnostics.append({"code": "AMBIGUOUS_IDENTITY", "reason": "Multiple stable subjects resolve from the supplied identifier."})
            records = []
        else:
            records = self._records_for(person, audit_at)
        steps: list[dict[str, Any]] = []
        issue = False
        for record in records:
            failed_lookup = False
            for key in ("status_code", "http_status"):
                try:
                    code = int(str(record.fields.get(key, 0)))
                    failed_lookup = failed_lookup or (code >= 400 and code not in {404, 410})
                except (ValueError, TypeError):
                    pass
            if failed_lookup:
                issue = True
                diagnostics.append({"code": "LOOKUP_FAILED", "evidence_id": record.evidence_id,
                                    "resource_id": record.resource_id, "reason": "An access or server error does not prove absence."})
                continue
            action = policy_action(record.category, record.fields, audit_at, self.rules)
            if not action or not record.system_id or not record.resource_id:
                continue
            exists = present(record)
            pii = exposed_pii(record, person)
            attributable = linked_to_subject(record, person)
            ev = record.evidence_id

            if action == "DELETE":
                if exists:
                    issue = True
                    steps.extend([
                        step("FINDING", record, "REPORT_REMAINING_RECORD", "PRESENT", ev),
                        step("REMEDIATION", record, "DELETE_RECORD", "ABSENT", ""),
                        step("VERIFICATION", record, "VERIFY_RECORD_ABSENT", "ABSENT", ""),
                    ])
                else:
                    steps.append(step("VERIFICATION", record, "VERIFY_RECORD_ABSENT", "ABSENT", ev))
            elif action == "REDACT":
                if exists and pii:
                    issue = True
                    steps.extend([
                        step("FINDING", record, "REPORT_EXPOSED_PII", "PRESENT", ev),
                        step("REMEDIATION", record, "REDACT_RECORD", "REDACTED", ""),

                        step("VERIFICATION", record, "VERIFY_RECORD_REDACTED", "REDACTED", ""),
                    ])
                elif exists:
                    steps.append(step("VERIFICATION", record, "VERIFY_RECORD_REDACTED", "REDACTED", ev))
            elif action == "ANONYMIZE":
                if exists and attributable:
                    issue = True
                    steps.extend([
                        step("FINDING", record, "REPORT_EXPOSED_PII", "PRESENT", ev),
                        step("REMEDIATION", record, "ANONYMIZE_RECORD", "ANONYMIZED", ""),
                        step("VERIFICATION", record, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ""),
                    ])
                elif exists:
                    steps.append(step("VERIFICATION", record, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ev))
            elif action == "RETAIN":
                if exists:
                    steps.append(step("VERIFICATION", record, "VERIFY_RECORD_PRESENT", "PRESENT", ev))
                else:
                    issue = True
                    diagnostics.append({"code": "REQUIRED_RETAINED_RECORD_MISSING", "evidence_id": ev,
                                        "resource_id": record.resource_id,
                                        "reason": "Required retention is unproven. No allowed deletion operation can restore a missing retained record."})
            elif action == "BLOCK_RESTORE":
                allowed = flag(record.fields, ("restore_allowed", "restore_access", "can_restore"))
                if allowed is None and "eligible" in record.fields:
                    eligible = flag(record.fields, ("eligible",))
                    blocked = flag(record.fields, ("deletion_block",))
                    allowed = bool(eligible and not blocked) if eligible is not None and blocked is not None else eligible
                if allowed is None:
                    state = norm(record.fields.get("state"))
                    allowed = True if state in {"active", "allowed"} else False if state in {"blocked", "disabled"} else None
                if allowed is None:
                    allowed = risk_is_active(allowed)
                if allowed is True:
                    issue = True
                    steps.extend([
                        step("FINDING", record, "REPORT_RESTORE_RISK", "ACTIVE", ev),
                        step("REMEDIATION", record, "BLOCK_RESTORE", "BLOCKED", ""),
                        step("VERIFICATION", record, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ""),
                    ])
                elif allowed is False:
                    steps.append(step("VERIFICATION", record, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ev))
            elif action == "DISABLE_DATA_FLOW":
                enabled = flag(record.fields, ("enabled", "active", "is_active"))
                if enabled is None:
                    state = norm(record.fields.get("state"))
                    enabled = True if state in {"active", "enabled"} else False if state in {"disabled", "blocked"} else None
                if enabled is None:
                    enabled = risk_is_active(enabled)
                if enabled is True:
                    issue = True
                    steps.extend([
                        step("FINDING", record, "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", ev),
                        step("REMEDIATION", record, "DISABLE_DATA_FLOW", "DISABLED", ""),
                        step("VERIFICATION", record, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""),
                    ])
                elif enabled is False:
                    steps.append(step("VERIFICATION", record, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ev))

        final_steps = sort_steps(steps)
        if not final_steps:
            issue = True
            if not diagnostics:
                diagnostics.append({"code": "NO_ADMISSIBLE_STATE_PROOF", "reason": "No attributable state proof is available by the audit cutoff."})
        if issue:
            for item in final_steps:
                if item["phase"] == "VERIFICATION":
                    item["evidence_id"] = ""
        return {
            "case_id": case["case_id"],
            "deletion_status": "INCOMPLETE" if issue else "COMPLETE",
            "steps_json": json.dumps(final_steps, ensure_ascii=False, separators=(",", ":")),
        }

    def run(self, requests: list[dict[str, str]]) -> list[dict[str, str]]:
        return [self.audit_case(case) for case in sorted(requests, key=lambda row: row["case_id"])]


def write_output(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "deletion_status", "steps_json"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline deletion audit agent")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--input", type=Path, help="request CSV (defaults to dataset/deletion_requests.csv)")
    parser.add_argument("--output", type=Path, help="output CSV (defaults to repo/output.csv)")
    parser.add_argument("--diagnostics", type=Path, help="optional JSON sidecar for unresolved proof obligations")
    args = parser.parse_args()
    repo = args.repo.resolve()
    input_path = args.input.resolve() if args.input else repo / "dataset" / "deletion_requests.csv"
    output_path = args.output.resolve() if args.output else repo / "output.csv"
    auditor = Auditor(repo)
    results = auditor.run(read_csv(input_path))
    write_output(results, output_path)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["deletion_status"]] = counts.get(row["deletion_status"], 0) + 1
    print(f"wrote {len(results)} rows to {output_path}")
    print("statuses=" + json.dumps(dict(sorted(counts.items()))))
    unresolved = {key: value for key, value in auditor.diagnostics.items() if value}
    if args.diagnostics:
        args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
        args.diagnostics.write_text(json.dumps(unresolved, indent=2) + "\n", encoding="utf-8")
    if unresolved:
        print(f"unresolved proof obligations: {len(unresolved)}; output is not submission-ready", file=sys.stderr)
    if auditor.evidence.unparsed:
        print(f"evidence files without local OCR/text support: {len(auditor.evidence.unparsed)}", file=sys.stderr)
    return 2 if unresolved or auditor.evidence.unparsed else 0


if __name__ == "__main__":
    raise SystemExit(main())

