"""Submission regressions for intent, correlated logs and catalog-backed state.

These project-authored cases are separate from the frozen 100-scenario suite.
"""
from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import Auditor, authorizes_deletion
from evidence import EvidenceIndex, parse_time

BEFORE = '2026-09-01T08:00:00Z'
CUTOFF = '2026-09-01T10:00:00Z'
AFTER = '2026-09-01T11:00:00Z'

def csv_write(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

class SubmissionRegressions(unittest.TestCase):
    def setUp(self):
        temp_parent = (Path.cwd()/'work'/'regression-temp').resolve()
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=temp_parent)
        assert Path(self.folder.name).resolve().is_relative_to(temp_parent)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.case = {'case_id':'synthetic_request', 'email':'subject@example.test',
                     'requested_at':BEFORE, 'reported_status':'COMPLETE', 'reported_at':BEFORE,
                     'audit_at':CUTOFF, 'request_text':'Please delete my account and personal data.'}
        csv_write(self.root/'dataset/user_identities.csv', [{'user_id':'user_700001',
            'name':'Synthetic Subject', 'email':self.case['email'], 'phone':'', 'email_hash':'', 'updated_at':BEFORE}])
        csv_write(self.root/'dataset/user_audit_log.csv', [], ['audit_id','user_id','event_time','field_name','old_value','new_value'])
        csv_write(self.root/'dataset/system_activity.csv', [], ['activity_id','event_time','event_type','source_system','target_system','resource_id','reported_result','details'])
        csv_write(self.root/'dataset/deletion_rules.csv', [
            {'data_category':'USER_PROFILE','required_action':'DELETE'},
            {'data_category':'SUPPORT_ATTACHMENT','required_action':'DELETE'}])

    def audit_log(self, text):
        p = self.root/'dataset/evidence/fixture.log'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        csv_write(self.root/'dataset/evidence_files.csv', [{'file_id':'evidence_1',
            'file_path':'evidence/fixture.log','origin':'test_log','captured_at':CUTOFF}])
        auditor = Auditor(self.root)
        return auditor.audit_case(self.case), auditor

    @staticmethod
    def cloud(stamp, trace, message, service='account_service', pod='pod-a'):
        payload = f'instance="instance-a" pod="{pod}" {message}'
        return f'{stamp} requestId={trace} level=INFO function={service} message={json.dumps(payload)}\n'

    def test_cloud_lookup_links_identity_and_absence(self):
        text = self.cloud(BEFORE,'request-one','event="profile_lookup_started" lookup_key="subject@example.test"')
        text += self.cloud('2026-09-01T09:00:00Z','request-one','resource_id="account_700001" event="profile_lookup_completed" rows="0" http_status="404"')
        row, _ = self.audit_log(text)
        self.assertEqual(row['deletion_status'], 'COMPLETE')
        self.assertEqual([(s['resource_id'],s['operation']) for s in json.loads(row['steps_json'])], [('account_700001','VERIFY_RECORD_ABSENT')])

    def test_syslog_lookup_links_identity_and_presence(self):
        text = f'{BEFORE} <14>1 host-a account_service span-a - - event="profile_lookup_started" lookup_key="subject@example.test"\n'
        text += '2026-09-01T09:00:00Z <14>1 host-a account_service span-a - - resource_id="account_700001" event="profile_lookup_completed" rows="1" http_status="200"\n'
        row, _ = self.audit_log(text)
        self.assertEqual(row['deletion_status'], 'INCOMPLETE')
        self.assertEqual(len(json.loads(row['steps_json'])), 3)

    def test_query_start_is_not_present_state(self):
        row, auditor = self.audit_log(f'{BEFORE} service=account_service trace_id=span resource_id=account_700001 event=profile_lookup_started lookup_key=subject@example.test\n')
        self.assertEqual(row['steps_json'], '[]')
        self.assertTrue(auditor.diagnostics[self.case['case_id']])

    def test_same_timestamp_start_and_completion(self):
        start = f'{BEFORE} service=account_service trace_id=span resource_id=account_700001 event=profile_lookup_started lookup_key=subject@example.test\n'
        end = f'{BEFORE} service=account_service trace_id=span resource_id=account_700001 event=profile_lookup_completed rows=0 http_status=404\n'
        for text in (start+end, end+start):
            row, _ = self.audit_log(text)
            self.assertEqual(row['deletion_status'], 'COMPLETE')

    def test_future_identity_is_not_backdated(self):
        text = self.cloud(BEFORE,'request-one','resource_id="account_700001" event="profile_lookup_completed" rows="0" http_status="404"')
        text += self.cloud(AFTER,'request-one','event="profile_lookup_started" lookup_key="subject@example.test"')
        row, auditor = self.audit_log(text)
        self.assertEqual(row['steps_json'], '[]')
        self.assertTrue(auditor.diagnostics[self.case['case_id']])

    def test_reused_request_id_in_different_pod_does_not_link(self):
        text = self.cloud(BEFORE,'request-one','event="profile_lookup_started" lookup_key="subject@example.test"',pod='pod-a')
        text += self.cloud('2026-09-01T09:00:00Z','request-one','resource_id="account_700001" event="profile_lookup_completed" rows="0" http_status="404"',pod='pod-b')
        row, _ = self.audit_log(text)
        self.assertEqual(row['steps_json'], '[]')

    def test_denied_lookup_is_not_absence(self):
        text = self.cloud(BEFORE,'request-one','event="profile_lookup_started" lookup_key="subject@example.test"')
        text += self.cloud('2026-09-01T09:00:00Z','request-one','resource_id="account_700001" event="profile_lookup_completed" rows="0" http_status="403"')
        row, auditor = self.audit_log(text)
        self.assertEqual(row['deletion_status'], 'INCOMPLETE')
        self.assertEqual(auditor.diagnostics[self.case['case_id']][0]['code'],'LOOKUP_FAILED')

    def inventory(self, text, ambiguous=False, late=False):
        rows=[{'activity_id':'activity_1','event_time':BEFORE,'event_type':'LINK_RESOURCE_IDENTITY',
               'source_system':'catalog','target_system':'object_storage','resource_id':'object_700001',
               'reported_result':'SUCCESS','details':'Attachment catalog confirmed object_700001 (example.pdf) belongs only to subject@example.test and user_700001.'}]
        if ambiguous:
            rows.append({**rows[0], 'activity_id':'activity_2', 'resource_id':'object_700002'})
        csv_write(self.root/'dataset/system_activity.csv',rows)
        path=self.root/'dataset/evidence/snapshot.png'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'synthetic OCR fixture')
        csv_write(self.root/'dataset/evidence_files.csv',[{'file_id':'evidence_1','file_path':'evidence/snapshot.png','origin':'object_storage','captured_at':AFTER if late else BEFORE}])
        with patch.object(EvidenceIndex,'_external_text',return_value=text):
            return Auditor(self.root).audit_case(self.case)

    def test_catalog_and_independent_selected_object_panel(self):
        row=self.inventory('example.pdf\nSize 400 KB\nVersion v2\nContent type application/pdf')
        steps=json.loads(row['steps_json'])
        self.assertEqual(row['deletion_status'],'INCOMPLETE')
        self.assertEqual(steps[0]['resource_id'],'object_700001')
        self.assertEqual(steps[0]['evidence_id'],'evidence_1')
        self.assertEqual(steps[1]['operation'],'DELETE_RECORD')

    def test_filename_mention_alone_is_not_object_state(self):
        self.assertEqual(self.inventory('Search for example.pdf')['steps_json'],'[]')

    def test_ambiguous_filename_is_not_resource_link(self):
        self.assertEqual(self.inventory('example.pdf\nSize 400 KB\nVersion v2',ambiguous=True)['steps_json'],'[]')

    def test_future_inventory_is_not_admissible(self):
        self.assertEqual(self.inventory('example.pdf\nSize 400 KB\nVersion v2',late=True)['steps_json'],'[]')

    def test_non_deletion_intents_and_separate_explicit_request(self):
        examples = [
            ('Please correct my surname without removing any records.',False),
            ('Please remove me from marketing lists only. Keep my receipts.',False),
            ('This is an information request, not a request to erase it.',False),
            ('Unsubscribe me from email and delete my account.',True),
            ('Please do not delete my account.',False),
            ('Please delete my personal data.',True)]
        for text, expected in examples:
            with self.subTest(text=text): self.assertEqual(authorizes_deletion(text),expected)

if __name__ == '__main__':
    unittest.main()
