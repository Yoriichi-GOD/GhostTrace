from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "code"
sys.path.insert(0, str(CODE))
from evidence import (EvidenceIndex, EvidenceRecord, Person, load_person, normalize_resource_id,
                      evidence_manifest_errors, parse_time, read_csv, resolve_evidence_path)
from main import Auditor, authorizes_deletion, policy_action, present, risk_is_active

FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OP_ORDER = {
    "REPORT_REMAINING_RECORD": 0, "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2, "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0, "BLOCK_RESTORE": 1, "DELETE_RECORD": 2,
    "REDACT_RECORD": 3, "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0, "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2, "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4, "VERIFY_RESTORE_BLOCKED": 5,
}
OP_STATE = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
VALID_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}


def read_output(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def citation_is_temporally_admissible(source_time: dt.datetime | None,
                                      audit_time: dt.datetime | None) -> bool:
    return source_time is not None and audit_time is not None and source_time <= audit_time


def duplicate_logical_step_indices(steps: list[Any]) -> list[int]:
    seen: set[tuple[str, str, str, str]] = set()
    duplicates: list[int] = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        fields = (step.get("phase"), step.get("operation"),
                  step.get("system_id"), step.get("resource_id"))
        if not all(isinstance(value, str) for value in fields):
            continue
        key = (fields[0], fields[1], fields[2], fields[3])
        if key in seen:
            duplicates.append(index)
        seen.add(key)
    return duplicates


def missing_incomplete_phases(steps: list[Any]) -> list[str]:
    present = {step.get("phase") for step in steps
               if isinstance(step, dict) and isinstance(step.get("phase"), str)}
    return [phase for phase in ("FINDING", "REMEDIATION", "VERIFICATION")
            if phase not in present]


def validate_output(repo: Path, output_path: Path, auditor: Auditor | None = None) -> list[str]:
    errors: list[str] = []
    requests = read_csv(repo / "dataset" / "deletion_requests.csv")
    expected_ids = [row["case_id"] for row in requests]
    try:
        columns, rows = read_output(output_path)
    except (OSError, csv.Error) as exc:
        return [f"Cannot read output: {exc}"]
    if columns != ["case_id", "deletion_status", "steps_json"]:
        errors.append(f"Wrong output columns: {columns}")
    if len(rows) != len(expected_ids):
        errors.append(f"Expected {len(expected_ids)} rows; found {len(rows)}")
    ids = [row.get("case_id", "") for row in rows]
    if len(set(ids)) != len(ids):
        errors.append("Duplicate case_id values")
    if ids != sorted(expected_ids) or set(ids) != set(expected_ids):
        errors.append("case_id values must exactly cover the input and be sorted")

    manifest = read_csv(repo / "dataset" / "evidence_files.csv")
    activities = read_csv(repo / "dataset" / "system_activity.csv")
    for manifest_error in evidence_manifest_errors(repo, manifest):
        errors.append(f"evidence manifest: {manifest_error}")
    file_ids = {row["file_id"] for row in manifest}
    evidence_times = {row["file_id"]: parse_time(row.get("captured_at")) for row in manifest}
    evidence_times.update({row.get("activity_id", ""): parse_time(row.get("event_time")) for row in activities})
    audit_rows = read_csv(repo / "dataset" / "user_audit_log.csv")
    evidence_times.update({row.get("audit_id", ""): parse_time(row.get("event_time")) for row in audit_rows})
    allowed_evidence = set(evidence_times)
    allowed_evidence.discard("")
    request_by_case = {row["case_id"]: row for row in requests}
    for row in rows:
        case_id = row.get("case_id", "?")
        request = request_by_case.get(case_id, {})
        audit_time = parse_time(request.get("audit_at"))
        selected_evidence: set[tuple[str, str]] | None = None
        if auditor is not None and request:
            cutoff = audit_time or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
            person = load_person(request, auditor.identities, auditor.audits)
            selected_evidence = {
                (record.evidence_id, record.resource_id)
                for record in auditor._records_for(person, cutoff)
            }
        status = row.get("deletion_status", "")
        if status not in VALID_STATUSES:
            errors.append(f"{case_id}: invalid deletion_status {status!r}")
        try:
            steps = json.loads(row.get("steps_json", ""))
        except json.JSONDecodeError as exc:
            errors.append(f"{case_id}: invalid steps_json: {exc}")
            continue
        if not isinstance(steps, list):
            errors.append(f"{case_id}: steps_json is not an array")
            continue
        if status == "NOT_APPLICABLE" and steps:
            errors.append(f"{case_id}: NOT_APPLICABLE must have an empty array")
        if status == "COMPLETE" and not any(
            isinstance(step, dict) and step.get("phase") == "VERIFICATION" and step.get("evidence_id")
            for step in steps
        ):
            errors.append(f"{case_id}: COMPLETE has no evidence-backed verification")
        if status == "COMPLETE" and any(step.get("phase") != "VERIFICATION" for step in steps if isinstance(step, dict)):
            errors.append(f"{case_id}: COMPLETE contains a non-verification step")
        phases: list[int] = []
        sort_keys: list[tuple[Any, ...]] = []
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                errors.append(f"{case_id}: step {index} is not an object")
                continue
            if set(step) != set(FIELDS):
                errors.append(f"{case_id}: step {index} has the wrong fields")
                continue
            if any(not isinstance(step[field], str)
                   for field in ("phase", "system_id", "resource_id", "operation", "state")):
                errors.append(f"{case_id}: step {index} has a non-string contract field")
                continue
            if type(step["step_no"]) is not int or step["step_no"] != index:
                errors.append(f"{case_id}: step numbers must be consecutive from 1")
            pair = OP_STATE.get(step["operation"])
            if pair is None or pair != (step["phase"], step["state"]):
                errors.append(f"{case_id}: invalid phase/operation/state at step {index}")
            if not isinstance(step["system_id"], str) or not step["system_id"]:
                errors.append(f"{case_id}: invalid system_id at step {index}")
            if not isinstance(step["resource_id"], str) or normalize_resource_id(step["resource_id"]) != step["resource_id"]:
                errors.append(f"{case_id}: invalid resource_id at step {index}")
            if step["phase"] not in PHASE_ORDER:
                errors.append(f"{case_id}: invalid phase at step {index}")
                continue
            phases.append(PHASE_ORDER[step["phase"]])
            sort_keys.append((PHASE_ORDER[step["phase"]], OP_ORDER.get(step["operation"], 99),
                              step["system_id"], step["resource_id"]))
            evidence_id = step["evidence_id"]
            if not isinstance(evidence_id, str):
                errors.append(f"{case_id}: evidence_id must be a string")
            elif evidence_id and evidence_id not in allowed_evidence:
                errors.append(f"{case_id}: evidence_id {evidence_id!r} is not in participant files")
            elif evidence_id and not citation_is_temporally_admissible(evidence_times.get(evidence_id), audit_time):
                errors.append(f"{case_id}: evidence {evidence_id!r} has no admissible timestamp at audit_at")
            elif (evidence_id and evidence_id in file_ids and selected_evidence is not None
                  and (evidence_id, step["resource_id"]) not in selected_evidence):
                errors.append(f"{case_id}: file evidence does not match the cited resource at audit_at")
            if step["phase"] in {"FINDING", "REMEDIATION"} and step["phase"] == "FINDING" and not evidence_id:
                errors.append(f"{case_id}: a finding must cite evidence")
            if step["phase"] == "REMEDIATION" and evidence_id:
                errors.append(f"{case_id}: remediation must have an empty evidence_id")
            if status == "COMPLETE" and step["phase"] == "VERIFICATION" and not evidence_id:
                errors.append(f"{case_id}: COMPLETE verification must cite evidence")
            if status == "INCOMPLETE" and step["phase"] == "VERIFICATION" and evidence_id:
                errors.append(f"{case_id}: future verification must have an empty evidence_id")
        if phases != sorted(phases):
            errors.append(f"{case_id}: phases are out of order")
        if sort_keys != sorted(sort_keys):
            errors.append(f"{case_id}: steps do not follow operation/system/resource ordering")
        for duplicate_index in duplicate_logical_step_indices(steps):
            errors.append(f"{case_id}: duplicate logical step at step {duplicate_index}")
        if status == "INCOMPLETE":
            for required_phase in missing_incomplete_phases(steps):
                errors.append(f"{case_id}: INCOMPLETE is missing {required_phase.lower()} steps")
    return errors


def _step_key(step: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(step.get(field) for field in FIELDS)


def compare_sample(predictions: list[dict[str, str]], gold: list[dict[str, str]]) -> dict[str, float | int]:
    pred = {row["case_id"]: row for row in predictions}
    expected = {row["case_id"]: row for row in gold}
    common = sorted(set(pred) & set(expected))
    status_correct = sum(pred[c]["deletion_status"] == expected[c]["deletion_status"] for c in common)
    exact_sequences = 0
    true_positive = pred_steps = gold_steps = 0
    field_matches = field_total = 0
    for case_id in common:
        actual_steps = json.loads(pred[case_id]["steps_json"])
        gold_steps_list = json.loads(expected[case_id]["steps_json"])
        exact_sequences += actual_steps == gold_steps_list
        actual_counts = Counter(_step_key(step) for step in actual_steps)
        gold_counts = Counter(_step_key(step) for step in gold_steps_list)
        true_positive += sum((actual_counts & gold_counts).values())
        pred_steps += len(actual_steps)
        gold_steps += len(gold_steps_list)
        width = max(len(actual_steps), len(gold_steps_list))
        for index in range(width):
            left = actual_steps[index] if index < len(actual_steps) else {}
            right = gold_steps_list[index] if index < len(gold_steps_list) else {}
            for field in FIELDS:
                field_total += 1
                if field in left and field in right and left[field] == right[field]:
                    field_matches += 1
    precision = true_positive / pred_steps if pred_steps else 0.0
    recall = true_positive / gold_steps if gold_steps else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    count = len(common)
    return {
        "cases": count,
        "status_correct": status_correct,
        "status_accuracy": status_correct / count if count else 0.0,
        "sequence_correct": exact_sequences,
        "sequence_accuracy": exact_sequences / count if count else 0.0,
        "predicted_steps": pred_steps,
        "expected_steps": gold_steps,
        "step_precision": precision,
        "step_recall": recall,
        "step_f1": f1,
        "field_matches": field_matches,
        "field_total": field_total,
        "field_accuracy": field_matches / field_total if field_total else 0.0,
    }


def custom_tests(repo: Path) -> list[tuple[str, bool, str]]:
    tests: list[tuple[str, bool, str]] = []
    intents = [
        ("explicit deletion", "Please delete my account and personal data.", True),
        ("data export is not deletion", "Please export a copy of my data.", False),
        ("explicitly denied deletion", "Do not delete my account; send me an export instead.", False),
        ("question alone is not authorization", "How can I delete my account?", False),
        ("French deletion request", "Por favor, elimina mi cuenta y mis datos personales.", True),
    ]
    for name, text, expected in intents:
        actual = authorizes_deletion(text)
        tests.append((name, actual == expected, f"expected={expected}, actual={actual}"))

    cutoff = parse_time("2026-09-15T00:00:00Z")
    identity = [{"user_id": "custom_user", "name": "Example Person", "email": "new@example.test",
                 "phone": "", "email_hash": "", "updated_at": "2026-09-01T00:00:00Z"}]
    audit = [
        {"audit_id": "audit_old_email", "user_id": "custom_user", "field_name": "email",
         "old_value": "old@example.test", "new_value": "new@example.test", "event_time": "2026-08-01T00:00:00Z"},
        {"audit_id": "audit_future_email", "user_id": "custom_user", "field_name": "email",
         "old_value": "new@example.test", "new_value": "future@example.test", "event_time": "2026-10-01T00:00:00Z"},
    ]
    person = load_person({"email": "old@example.test", "audit_at": cutoff.isoformat()}, identity, audit)
    tests.append(("historical email and audit cutoff", person.user_ids == {"custom_user"}
                  and "new@example.test" in person.emails and "future@example.test" not in person.emails,
                  f"resolved_users={sorted(person.user_ids)}, future_email_excluded={'future@example.test' not in person.emails}"))

    before = EvidenceRecord("evidence_before", "before.json", cutoff, cutoff, "account_service", "USER_PROFILE",
                            "account_before", {"user_id": "custom_user"})
    after_time = parse_time("2026-09-16T00:00:00Z")
    after = EvidenceRecord("evidence_after", "after.json", after_time, after_time, "account_service", "USER_PROFILE",
                           "account_after", {"user_id": "custom_user"})
    index = EvidenceIndex.__new__(EvidenceIndex)
    index.records = [before, after]
    selected = index.observations_for(Person(user_ids={"custom_user"}), cutoff)
    tests.append(("evidence after audit cutoff excluded",
                  {record.evidence_id for record in selected} == {"evidence_before"},
                  f"selected={[record.evidence_id for record in selected]}"))
    tests.append(("citation timestamps must be present and no later than audit cutoff",
                  citation_is_temporally_admissible(cutoff, cutoff)
                  and not citation_is_temporally_admissible(cutoff + dt.timedelta(seconds=1), cutoff)
                  and not citation_is_temporally_admissible(None, cutoff),
                  "boundary accepted; later and missing source times rejected"))
    logical_step = {"phase": "FINDING", "operation": "REPORT_REMAINING_RECORD",
                    "system_id": "search_service", "resource_id": "search_001"}
    duplicates = duplicate_logical_step_indices([logical_step, dict(logical_step)])
    tests.append(("strict validator detects repeated logical steps",
                  duplicates == [2], f"duplicate_indices={duplicates}"))
    phase_steps = [{"phase": phase} for phase in ("FINDING", "REMEDIATION", "VERIFICATION")]
    tests.append(("strict validator requires all incomplete phases",
                  not missing_incomplete_phases(phase_steps)
                  and missing_incomplete_phases(phase_steps[:-1]) == ["VERIFICATION"],
                  f"missing_after_removal={missing_incomplete_phases(phase_steps[:-1])}"))
    source_manifest = read_csv(repo / "dataset" / "evidence_files.csv")
    valid_rel_path = source_manifest[0]["file_path"]
    valid_path, valid_issue = resolve_evidence_path(repo, valid_rel_path)
    _, traversal_issue = resolve_evidence_path(repo, "evidence/../outside.json")
    _, absolute_issue = resolve_evidence_path(repo, str(repo / "dataset" / "evidence" / "outside.json"))
    _, extension_issue = resolve_evidence_path(repo, "evidence/ignored.csv")
    tests.append(("evidence manifest paths stay inside the supported corpus root",
                  valid_path is not None and valid_path.is_file() and valid_issue is None
                  and traversal_issue == "path_traversal"
                  and absolute_issue == "absolute_path"
                  and extension_issue == "unsupported_extension",
                  f"valid={valid_issue is None}, traversal={traversal_issue}, absolute={absolute_issue}, extension={extension_issue}"))
    duplicate_manifest = source_manifest + [dict(source_manifest[0])]
    duplicate_errors = evidence_manifest_errors(repo, duplicate_manifest)
    missing_manifest = [dict(source_manifest[0], file_path="evidence/missing.json")]
    missing_errors = evidence_manifest_errors(repo, missing_manifest)
    source_errors = evidence_manifest_errors(repo, source_manifest)
    duplicate_detected = any("duplicate file_id" in error for error in duplicate_errors)
    missing_detected = any("missing_file" in error for error in missing_errors)
    tests.append(("evidence manifest rejects missing files and duplicate IDs",
                  not source_errors and duplicate_detected and missing_detected,
                  f"source_errors={len(source_errors)}, duplicate_detected={duplicate_detected}, missing_detected={missing_detected}"))
    id_index = EvidenceIndex.__new__(EvidenceIndex)
    id_index.records = []
    id_index._add("id_test", "test.log", cutoff, r'\"search_021\"', {}, "")
    id_index._add("id_test", "test.log", cutoff, "search_service", {}, "")
    tests.append(("resource IDs are concrete, normalized, and include legal holds",
                  normalize_resource_id("legal_hold_8017") == "legal_hold_8017"
                  and len(id_index.records) == 1
                  and id_index.records[0].resource_id == "search_021",
                  f"indexed_ids={[record.resource_id for record in id_index.records]}"))
    operations_log = EvidenceIndex.__new__(EvidenceIndex)
    operations_log.records = []
    started = ("2026-09-15T00:00:00Z | DEBUG | security_service | trace-001 | "
               "audit_record_query_started | instance=security-1 subject_ref=user_001")
    completed = ("2026-09-15T00:00:01Z | INFO | search_service | trace-001 | "
                 "search_query_completed | resource_id=search_123 state=not_found subject_ref=user_001")
    operations_log._parse_text("ops_log", "operations.log", cutoff, started + "\n" + completed, "log")
    log_records = operations_log.records
    tests.append(("operational log pipe fields do not become resources or states",
                  len(log_records) == 1
                  and log_records[0].resource_id == "search_123"
                  and log_records[0].system_id == "search_service"
                  and log_records[0].fields.get("state") == "not_found"
                  and not present(log_records[0]),
                  f"records={len(log_records)}, resource_id={log_records[0].resource_id if log_records else ''}, state={log_records[0].fields.get('state') if log_records else ''}"))

    link_index = EvidenceIndex.__new__(EvidenceIndex)
    link_index.activities = [
        {"activity_id": "activity_at_cutoff", "event_type": "LINK_RESOURCE_IDENTITY",
         "event_time": cutoff.isoformat(), "resource_id": "search_001",
         "reported_result": "SUCCESS", "details": "Linked user_001 and old@example.test."},
        {"activity_id": "activity_future", "event_type": "LINK_RESOURCE_IDENTITY",
         "event_time": (cutoff + dt.timedelta(seconds=1)).isoformat(), "resource_id": "search_002",
         "reported_result": "SUCCESS", "details": "Linked user_001 and old@example.test."},
        {"activity_id": "activity_conflict", "event_type": "LINK_RESOURCE_IDENTITY",
         "event_time": cutoff.isoformat(), "resource_id": "search_003",
         "reported_result": "SUCCESS", "details": "Linked user_002 and old@example.test."},
        {"activity_id": "activity_failed", "event_type": "LINK_RESOURCE_IDENTITY",
         "event_time": cutoff.isoformat(), "resource_id": "search_004",
         "reported_result": "PARTIAL", "details": "Linked user_001 and old@example.test."},
        {"activity_id": "activity_other_type", "event_type": "DELETE_RECORD",
         "event_time": cutoff.isoformat(), "resource_id": "search_005",
         "reported_result": "SUCCESS", "details": "Linked user_001 and old@example.test."},
    ]
    link_person = Person(user_ids={"user_001"}, emails={"old@example.test"})
    linked = link_index.identity_link_events(link_person, cutoff)
    tests.append(("identity-link candidates are exact, successful, and cutoff-bounded",
                  [row["activity_id"] for row in linked] == ["activity_at_cutoff"],
                  f"candidate_ids={[row['activity_id'] for row in linked]}"))
    linked_record = EvidenceRecord("linked_state", "linked.json", cutoff, cutoff,
                                   "search_service", "SEARCH_INDEX_ENTRY", "search_001",
                                   {"state": "present"})
    late_linked_record = EvidenceRecord("late_linked_state", "late.json",
                                        cutoff + dt.timedelta(seconds=1), cutoff,
                                        "search_service", "SEARCH_INDEX_ENTRY", "search_001",
                                        {"state": "present"})
    unrelated_record = EvidenceRecord("unrelated_state", "other.json", cutoff, cutoff,
                                      "search_service", "SEARCH_INDEX_ENTRY", "search_099",
                                      {"state": "present"})
    link_index.records = [linked_record, late_linked_record, unrelated_record]
    selected_linked = link_index.observations_for(link_person, cutoff)
    tests.append(("identity link selects only independently cutoff-admissible resource evidence",
                  [record.evidence_id for record in selected_linked] == ["linked_state"],
                  f"selected={[record.evidence_id for record in selected_linked]}"))

    rules = {row["data_category"]: row for row in read_csv(repo / "dataset" / "deletion_rules.csv")}
    action = policy_action("ANALYTICS_PROFILE", {"user_id": "custom_user"}, cutoff, rules)
    tests.append(("analytics policy keeps anonymization", action == "ANONYMIZE", f"action={action}"))
    tests.append(("unknown restore/sync state remains a risk",
                  risk_is_active(None) and risk_is_active(True) and not risk_is_active(False),
                  f"unknown={risk_is_active(None)}, explicitly_disabled={risk_is_active(False)}"))
    return tests


def case_coverage_rows(repo: Path, auditor: Auditor,
                       predictions: list[dict[str, str]]) -> list[dict[str, str | int]]:
    prediction_by_case = {row["case_id"]: row for row in predictions}
    identities = auditor.identities
    audits = auditor.audits
    rows: list[dict[str, str | int]] = []
    for case in read_csv(repo / "dataset" / "deletion_requests.csv"):
        case_id = case["case_id"]
        prediction = prediction_by_case.get(case_id, {})
        if not authorizes_deletion(case.get("request_text", "")):
            rows.append({"case_id": case_id, "authorized": "no", "resolved_user_ids": 0,
                         "direct_resources": 0, "identity_link_events": 0,
                         "linked_artifact_records": 0,
                         "post_cutoff_direct_records": 0,
                         "coverage": "NOT_APPLICABLE",
                         "output_status": prediction.get("deletion_status", "MISSING")})
            continue

        audit_at = parse_time(case.get("audit_at")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        person = load_person(case, identities, audits)
        selected_records = auditor._records_for(person, audit_at)
        links = auditor.evidence.identity_link_events(person, audit_at)
        linked_resources = {row.get("resource_id", "") for row in links}
        directly_matched = [record for record in selected_records if person.match_kind(record)]
        linked_artifacts = [record for record in selected_records
                            if record.resource_id in linked_resources and not person.match_kind(record)]
        direct_resources = {(record.system_id, record.resource_id, record.category)
                            for record in directly_matched}
        linked_artifact_keys = {(record.evidence_id, record.system_id, record.resource_id, record.category)
                                for record in linked_artifacts}
        late_direct_keys: set[tuple[str, str, str, str]] = set()
        if direct_resources:
            coverage = "DIRECT_EVIDENCE"
        elif linked_artifact_keys:
            coverage = "LINKED_RESOURCE_EVIDENCE"
        else:
            late_direct_keys = {
                (record.evidence_id, record.system_id, record.resource_id, record.category)
                for record in auditor.evidence.records
                if person.match_kind(record)
                and ((record.file_time is not None and record.file_time > audit_at)
                     or (record.observed_time is not None and record.observed_time > audit_at))
            }
            coverage = ("POST_CUTOFF_ONLY" if late_direct_keys
                        else "UNRESOLVED_NO_MATCHING_STATE_EVIDENCE")
        rows.append({"case_id": case_id, "authorized": "yes",
                     "resolved_user_ids": len(person.user_ids),
                     "direct_resources": len(direct_resources),
                     "identity_link_events": len(links),
                     "linked_artifact_records": len(linked_artifact_keys),
                     "post_cutoff_direct_records": len(late_direct_keys),
                     "coverage": coverage,
                     "output_status": prediction.get("deletion_status", "MISSING")})
    return rows


def write_case_coverage(path: Path, rows: list[dict[str, str | int]]) -> None:
    counts = Counter(str(row["coverage"]) for row in rows)
    lines = [
        "# Case coverage matrix",
        "",
        "This matrix contains case IDs and coverage counts only; it does not expose request text or identifiers.",
        "`system_activity.csv` identity-link events are used only to connect identities to candidate resources. Their reported results do not prove resource state; returned state observations come from separate artifacts that pass both audit-cutoff checks. `POST_CUTOFF_ONLY` means matching records exist but are inadmissible at the audit time.",
        "",
        "## Coverage totals",
        "",
    ]
    for coverage, count in sorted(counts.items()):
        lines.append(f"- `{coverage}`: {count}")
    lines.extend(["", "## Per-case matrix", "",
                  "| Case | Authorized | Resolved user IDs | Direct resources | Identity-link events | Linked artifact records by cutoff | Post-cutoff direct records | Coverage | Output status |",
                  "|---|---:|---:|---:|---:|---:|---:|---|---|"])
    for row in rows:
        lines.append("| {case_id} | {authorized} | {resolved_user_ids} | {direct_resources} | {identity_link_events} | {linked_artifact_records} | {post_cutoff_direct_records} | `{coverage}` | `{output_status}` |".format(**row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _render_step_key(key: tuple[Any, ...]) -> str:
    return " / ".join(str(value) for value in key)


def write_sample_diff(repo: Path, path: Path, predictions: list[dict[str, str]],
                      gold: list[dict[str, str]], auditor: Auditor) -> None:
    predicted = {row["case_id"]: row for row in predictions}
    expected = {row["case_id"]: row for row in gold}
    requests = {row["case_id"]: row for row in read_csv(repo / "dataset" / "sample_deletion_requests.csv")}
    manifest = read_csv(repo / "dataset" / "evidence_files.csv")
    activities = read_csv(repo / "dataset" / "system_activity.csv")
    audit_rows = read_csv(repo / "dataset" / "user_audit_log.csv")
    file_ids = {row["file_id"] for row in manifest}
    citation_times = {row["file_id"]: parse_time(row.get("captured_at")) for row in manifest}
    citation_times.update({row["activity_id"]: parse_time(row.get("event_time")) for row in activities})
    citation_times.update({row["audit_id"]: parse_time(row.get("event_time")) for row in audit_rows})

    cases: list[dict[str, Any]] = []
    macro_precision: list[float] = []
    macro_recall: list[float] = []
    macro_f1: list[float] = []
    citation_count = temporal_count = file_resource_count = 0
    for case_id in sorted(set(predicted) & set(expected)):
        actual_row, gold_row = predicted[case_id], expected[case_id]
        actual_steps = json.loads(actual_row["steps_json"])
        expected_steps = json.loads(gold_row["steps_json"])
        actual_counts = Counter(_step_key(step) for step in actual_steps)
        expected_counts = Counter(_step_key(step) for step in expected_steps)
        true_positive = sum((actual_counts & expected_counts).values())
        false_positive = len(actual_steps) - true_positive
        false_negative = len(expected_steps) - true_positive
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else (1.0 if not false_negative else 0.0)
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else (1.0 if not false_positive else 0.0)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        macro_precision.append(precision)
        macro_recall.append(recall)
        macro_f1.append(f1)

        case = requests.get(case_id, {})
        cutoff = parse_time(case.get("audit_at"))
        if case and cutoff:
            person = load_person(case, auditor.identities, auditor.audits)
            selected = {(record.evidence_id, record.resource_id)
                        for record in auditor._records_for(person, cutoff)}
        else:
            selected = set()
        case_temporal_cites = case_file_cites = 0
        for step in actual_steps:
            evidence_id = step.get("evidence_id", "")
            if not evidence_id:
                continue
            citation_count += 1
            if citation_is_temporally_admissible(citation_times.get(evidence_id), cutoff):
                temporal_count += 1
                case_temporal_cites += 1
            if evidence_id in file_ids and (evidence_id, step.get("resource_id")) in selected:
                file_resource_count += 1
                case_file_cites += 1
        cases.append({
            "case_id": case_id,
            "status_match": actual_row["deletion_status"] == gold_row["deletion_status"],
            "sequence_match": actual_steps == expected_steps,
            "actual_status": actual_row["deletion_status"],
            "expected_status": gold_row["deletion_status"],
            "true_positive": true_positive,
            "extra": false_positive,
            "missing": false_negative,
            "file_resource_cites": case_file_cites,
            "actual_counts": actual_counts,
            "expected_counts": expected_counts,
        })

    count = len(cases)
    lines = [
        "# Public sample structural diff",
        "",
        "This compares the prediction and participant-facing sample answer by case. A step matches only when all seven contract fields match; array order is checked separately.",
        "Evidence counts distinguish citations with source timestamps at or before audit_at from file citations that also resolve to the exact case/resource in the parsed index. Activity and audit citations are not counted as file/resource matches.",
        "",
        "## Aggregate results",
        "",
        f"- Cases compared: **{count}**.",
        f"- Macro step precision / recall / F1: **{sum(macro_precision) / count:.2%} / {sum(macro_recall) / count:.2%} / {sum(macro_f1) / count:.2%}**." if count else "- Macro step precision / recall / F1: unavailable.",
        f"- Predicted evidence citations with admissible source timestamps: **{temporal_count}/{citation_count}**.",
        f"- File citations matching case and resource in the parsed index: **{file_resource_count}/{citation_count}**.",
        "",
        "## Per-case matrix",
        "",
        "| Case | Status | Ordered sequence | Exact steps | Extra | Missing | File cites matched to resource |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for case in cases:
        status = "match" if case["status_match"] else "diff"
        sequence = "match" if case["sequence_match"] else "diff"
        lines.append(f"| {case['case_id']} | {status} | {sequence} | {case['true_positive']} | {case['extra']} | {case['missing']} | {case['file_resource_cites']} |")
    lines.extend(["", "## Case-level differences", ""])
    for case in cases:
        if case["status_match"] and case["sequence_match"]:
            continue
        lines.extend([f"### {case['case_id']}", "",
                      f"- Status: predicted `{case['actual_status']}`, expected `{case['expected_status']}`.",
                      f"- Ordered sequence exact: **{case['sequence_match']}**; extra steps: **{case['extra']}**; missing steps: **{case['missing']}**."])
        missing = list((case["expected_counts"] - case["actual_counts"]).elements())
        extra = list((case["actual_counts"] - case["expected_counts"]).elements())
        if missing:
            lines.append("- Missing expected steps:")
            lines.extend(f"  - `{_render_step_key(step)}`" for step in missing)
        if extra:
            lines.append("- Extra predicted steps:")
            lines.extend(f"  - `{_render_step_key(step)}`" for step in extra)
        if not missing and not extra:
            lines.append("- The same steps appear in a different order.")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _file_hash(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def write_run_manifest(repo: Path, output_path: Path, path: Path, auditor: Auditor,
                       metrics: dict[str, float | int], contract_errors: list[str],
                       custom: list[tuple[str, bool, str]],
                       coverage: list[dict[str, str | int]], evaluation_started: dt.datetime,
                       evaluation_seconds: float) -> None:
    record_counts = Counter(record.evidence_id for record in auditor.evidence.records)
    unparsed_paths = set(auditor.evidence.unparsed)
    evidence_files: list[dict[str, Any]] = []
    parse_counts: Counter[str] = Counter()
    for entry in auditor.evidence.manifest:
        file_id = entry.get("file_id", "")
        source, path_issue = resolve_evidence_path(repo, entry.get("file_path", ""))
        if path_issue or source is None:
            parse_status = path_issue or "path_rejected"
            evidence_files.append({"file_id": file_id, "parse_status": parse_status})
            parse_counts[parse_status] += 1
            continue
        record_count = record_counts.get(file_id, 0)
        if not source.is_file():
            evidence_files.append({"file_id": file_id, "parse_status": "missing",
                                   "parsed_resource_records": 0})
            parse_counts["missing"] += 1
            continue
        file_metadata = _file_hash(source)
        if entry.get("file_path", "") in unparsed_paths:
            parse_status = "unparsed"
        elif record_count:
            parse_status = "resource_records_parsed"
        else:
            parse_status = "no_resource_records"
        evidence_files.append({"file_id": file_id, **file_metadata,
                               "parsed_resource_records": record_count,
                               "parse_status": parse_status})
        parse_counts[parse_status] += 1

    input_names = [
        "dataset/deletion_requests.csv", "dataset/sample_deletion_requests.csv",
        "dataset/sample_output.csv", "dataset/user_identities.csv",
        "dataset/user_audit_log.csv", "dataset/system_activity.csv",
        "dataset/deletion_rules.csv", "dataset/evidence_files.csv",
    ]
    source_names = ["README.md", "AGENTS.md", "problem_statement.md",
                    "code/main.py", "code/evidence.py", "code/evaluation/main.py",
                    "code/evaluation/gap_audit.md"]
    hashes = {name: _file_hash(repo / name) for name in input_names + source_names
              if (repo / name).is_file()}
    output_metadata = _file_hash(output_path)
    _, output_rows = read_output(output_path)
    status_counts = Counter(row.get("deletion_status", "") for row in output_rows)
    custom_results = [{"name": name, "passed": ok} for name, ok, _ in custom]
    coverage_counts = Counter(str(row["coverage"]) for row in coverage)
    manifest = {
        "manifest_version": 1,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "evaluation_started_at_utc": evaluation_started.isoformat(),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "evaluation_validation_seconds": round(evaluation_seconds, 3),
            "full_generation_seconds": None,
            "full_generation_seconds_note": "Not instrumented by this evaluator; not inferred from shell wall time.",
        },
        "solver_usage": {
            "provider_calls": 0, "model_calls": 0, "input_tokens": 0,
            "output_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0,
            "basis": "The solver is deterministic and offline; these counts describe solver execution, not assistant development.",
        },
        "inputs_and_sources": hashes,
        "evidence_parse_matrix": evidence_files,
        "evidence_parse_totals": dict(parse_counts),
        "evidence_manifest_errors": auditor.evidence.manifest_errors,
        "parsed_resource_record_count": len(auditor.evidence.records),
        "unparsed_evidence_file_count": len(auditor.evidence.unparsed),
        "output": {"filename": output_path.name, **output_metadata,
                   "rows": len(output_rows), "status_counts": dict(status_counts)},
        "public_sample_metrics": metrics,
        "custom_tests": {"passed": sum(ok for _, ok, _ in custom),
                         "total": len(custom), "results": custom_results},
        "strict_validation": {"passed": not contract_errors,
                              "error_count": len(contract_errors),
                              "errors": contract_errors},
        "case_coverage_totals": dict(coverage_counts),
        "limitations": [
            "A file with no parsed resource records is not assumed empty or proof of deletion.",
            "The manifest covers evaluator validation time; full generation duration and per-case latency were not instrumented.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_report(path: Path, metrics: dict[str, float | int], contract_errors: list[str],
                 custom: list[tuple[str, bool, str]], unparsed_count: int) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    passed = sum(ok for _, ok, _ in custom)
    proof_gaps = sum("COMPLETE has no evidence-backed verification" in error for error in contract_errors)
    unresolved_cases = len({error.split(":", 1)[0] for error in contract_errors
                            if "INCOMPLETE is missing" in error})
    lines = [
        "# Evaluation report",
        "",
        f"Generated: `{stamp}`.",
        "",
        "## Public sample replay",
        "",
        "The replay uses only `dataset/sample_deletion_requests.csv` and its participant-facing `sample_output.csv`. It does not read organizer-only truth.",
        "",
        f"- Case-level deletion-status accuracy: **{metrics['status_correct']}/{metrics['cases']} ({pct(float(metrics['status_accuracy']))})**.",
        f"- Exact step-sequence accuracy: **{metrics['sequence_correct']}/{metrics['cases']} ({pct(float(metrics['sequence_accuracy']))})**.",
        f"- Step-level micro precision / recall / F1: **{pct(float(metrics['step_precision']))} / {pct(float(metrics['step_recall']))} / {pct(float(metrics['step_f1']))}** ({metrics['predicted_steps']} predicted steps, {metrics['expected_steps']} reference steps). A step matches when all seven contract fields match.",
        f"- Field-value accuracy: **{metrics['field_matches']}/{metrics['field_total']} ({pct(float(metrics['field_accuracy']))})**. Fields are compared by array position; missing positions count as incorrect.",
        "",
        "## Output contract",
        "",
        ("All output contract checks passed for the full dataset." if not contract_errors else
         f"**{len(contract_errors)} contract issue(s) found. This output is not ready to submit.** See the CLI output for details."),
        "The validator checks the exact header, input ID coverage and order, valid JSON and operation/state pairs, concrete resource IDs, participant evidence IDs, source timestamps at or before audit_at, file/resource relevance, duplicate logical steps, phase ordering, and required phases for incomplete cases.",
        f"Complete rows without evidence-backed verification: **{sum('COMPLETE has no evidence-backed verification' in error for error in contract_errors)}**. These rows lack admissible state proof; a missing artifact or a record captured after audit_at cannot prove deletion.",
        "",
        "## Additional custom cases",
        "",
    ]
    for name, ok, detail in custom:
        lines.append(f"- {'PASS' if ok else 'FAIL'}: {name}: {detail}.")
    lines.extend([
        "",
        f"Custom checks passed: **{passed}/{len(custom)}**.",
        "",
        "## Failures found and improvements made",
        "",
        "- A broad time-neighborhood association joined unrelated global records. It was removed; direct subject matches and exact identity-link events select only same-resource artifacts that pass both audit-cutoff checks.",
        "- Operations logs use a distinct time/level/system/trace/event layout. Parsing that layout separately prevents service names and event names from becoming shared resource IDs or resource states; trace-linked identifiers remain scoped to their trace.",
        "- A local standard-library PDF text path and optional screenshot OCR were added. Windows uses its built-in OCR through the included PowerShell script; other platforms can use Tesseract. **" + str(unparsed_count) + "** evidence files remain unread in the current runtime.",
        "- HTTP access/server failures no longer establish absence. Missing admissible state proof is flagged internally and returns a conservative INCOMPLETE CSV status without fabricated findings or citations.",
        "- Explicit conflicting stable subject IDs and email substring matches are rejected. Polite negative requests do not authorize deletion.",
        "- Replica/table scopes and simultaneous contradictory observations are preserved. Positive surviving copies are not erased by a negative lookup in another scope. Older negative account lookups do not add a new current verification obligation when a newer account observation exists.",
        "- A missing required retained record produces an unresolved obligation, never a destructive delete recommendation. SQLite imports reject ATTACH/DETACH and file/extension helper functions.",
        "- Indexed identity candidate selection retains the same final matching predicate. The benchmark harness compares all 518 outputs against exhaustive matching before claiming a speed benefit.",
        "- The public reference includes an analytics deletion step where the policy specifies anonymization. Raw reference metrics are retained without rewriting expected answers. Other disputed mappings require independent review.",
        (f"- The full output has {proof_gaps} COMPLETE rows without evidence-backed verification; these remain hard failures."
         if proof_gaps else "- No full-output COMPLETE row lacks an evidence-backed verification step under the local checker."),
        (f"- {unresolved_cases} INCOMPLETE cases cannot supply a grounded full plan. Each missing phase remains a hard validation error."
         if unresolved_cases else "- All full-output INCOMPLETE rows supply finding, remediation and verification phases under the local checker."),
        "- Escaped cloud log messages and syslog headers are parsed explicitly. Query identity is propagated only within a service/span and no later than the response; starting a lookup does not prove presence.",
        "- Correction without removal, marketing-only opt-out and information requests explicitly excluding erasure are treated as non-deletion requests.",
        "- A catalog filename can identify an object-storage screenshot record only when the selected object's size and version independently establish presence. Ambiguous filenames, mere search mentions and post-cutoff images do not establish proof.",
        "",
        "## Limits",
        "",
        "These numbers describe 32 development cases only; hidden-case accuracy is unknown. Status accuracy is not evidence completeness. The deterministic offline solver does not assume an unread or unlinked source is empty. Insufficient-evidence diagnostics are separate from the challenge's three CSV statuses. Reserved synthetic variants use the same scenario generator and do not establish independent generalization. The package remains a development candidate while any strict check fails.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    evaluation_started = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    evaluation_started_perf = time.perf_counter()
    parser = argparse.ArgumentParser(description="Evaluate public samples, custom cases, and output.csv contract")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="prediction file (default: repo/output.csv)")
    parser.add_argument("--report", type=Path, help="report path (default: code/evaluation/evaluation_report.md)")
    parser.add_argument("--coverage-report", type=Path,
                        help="case coverage matrix path (default: code/evaluation/case_coverage.md)")
    parser.add_argument("--sample-diff", type=Path,
                        help="public sample structural diff path (default: code/evaluation/sample_diff.md)")
    parser.add_argument("--manifest", type=Path,
                        help="machine-readable run manifest path (default: code/evaluation/run_manifest.json)")
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = (args.output or repo / "output.csv").resolve()
    report = (args.report or repo / "code" / "evaluation" / "evaluation_report.md").resolve()
    coverage_report = (args.coverage_report or repo / "code" / "evaluation" / "case_coverage.md").resolve()
    sample_diff = (args.sample_diff or repo / "code" / "evaluation" / "sample_diff.md").resolve()
    run_manifest = (args.manifest or repo / "code" / "evaluation" / "run_manifest.json").resolve()

    sample_requests = read_csv(repo / "dataset" / "sample_deletion_requests.csv")
    gold = read_csv(repo / "dataset" / "sample_output.csv")
    auditor = Auditor(repo)
    contract_errors = validate_output(repo, output, auditor)
    predictions = auditor.run(sample_requests)
    metrics = compare_sample(predictions, gold)
    custom = custom_tests(repo)
    write_report(report, metrics, contract_errors, custom, len(auditor.evidence.unparsed))
    _, full_predictions = read_output(output)
    coverage = case_coverage_rows(repo, auditor, full_predictions)
    write_case_coverage(coverage_report, coverage)
    write_sample_diff(repo, sample_diff, predictions, gold, auditor)
    write_run_manifest(repo, output, run_manifest, auditor, metrics, contract_errors,
                       custom, coverage, evaluation_started,
                       time.perf_counter() - evaluation_started_perf)

    print("public_sample=" + json.dumps(metrics, sort_keys=True))
    print(f"custom_tests={sum(ok for _, ok, _ in custom)}/{len(custom)}")
    print(f"unparsed_evidence_files={len(auditor.evidence.unparsed)}")
    print(f"contract_errors={len(contract_errors)}")
    print("coverage_totals=" + json.dumps(dict(Counter(str(row["coverage"]) for row in coverage)), sort_keys=True))
    for error in contract_errors[:20]:
        print("CONTRACT ERROR: " + error)
    for name, ok, detail in custom:
        if not ok:
            print(f"CUSTOM TEST FAILED: {name}: {detail}")
    print(f"report={report}")
    print(f"coverage_report={coverage_report}")
    print(f"sample_diff={sample_diff}")
    print(f"run_manifest={run_manifest}")
    return 1 if contract_errors or any(not ok for _, ok, _ in custom) else 0


if __name__ == "__main__":
    raise SystemExit(main())
