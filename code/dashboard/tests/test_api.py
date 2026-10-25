from __future__ import annotations

import http.client
import json
import os
import re
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("GHOSTTRACE_REPO_ROOT", Path(__file__).resolve().parents[3])).resolve()
DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))

from serve import make_handler  # noqa: E402
from service import DashboardService  # noqa: E402


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = DashboardService(ROOT)
        if not cls.service.wait_ready(180):
            raise RuntimeError(f"engine index failed to become ready: {cls.service.health()}")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.service))
        cls.server.daemon_threads = True
        cls.host, cls.port = cls.server.server_address[:2]
        cls.origin = f"http://{cls.host}:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.case_id = sorted(cls.service._requests)[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    @classmethod
    def get(cls, path: str):
        conn = http.client.HTTPConnection(cls.host, cls.port, timeout=15)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        conn.close()
        return response.status, headers, body

    @classmethod
    def post(cls, path: str, payload: object, origin: str | None = None):
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if origin is not None:
            headers["Origin"] = origin
        conn = http.client.HTTPConnection(cls.host, cls.port, timeout=15)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.read()
        conn.close()
        return response.status, json.loads(result) if result else {}

    def test_health_reports_real_engine_and_dynamic_index(self):
        status, headers, body = self.get("/api/ghosttrace/v1/health")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["engine"], "GhostTrace Python Auditor")
        self.assertTrue(payload["read_only"])
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(payload["index"]["completed"], len(self.service._requests))

    def test_case_list_pages_real_summaries_without_returning_all_case_details(self):
        status, _, body = self.get("/api/ghosttrace/v1/cases?page=1&page_size=2")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], len(self.service._requests))
        self.assertEqual(len(payload["items"]), 2)
        self.assertNotIn("steps", payload["items"][0])
        self.assertTrue(payload["items"][0]["case_id"].startswith("case_"))

    def test_case_search_rejects_contact_values_without_echoing_them(self):
        email = self.service._requests[self.case_id]["email"]
        status, _, body = self.get("/api/ghosttrace/v1/cases?query=" + email.replace("@", "%40"))
        self.assertEqual(status, 400)
        self.assertNotIn(email.encode(), body)

    def test_case_steps_match_the_existing_auditor_and_mask_identity(self):
        status, _, body = self.get(f"/api/ghosttrace/v1/cases/{self.case_id}")
        payload = json.loads(body)
        expected = self.service._results[self.case_id]
        self.assertEqual(status, 200)
        self.assertEqual(payload["deletion_status"], expected["deletion_status"])
        expected_steps = json.loads(expected["steps_json"])
        got_steps = payload["steps"]
        self.assertEqual(len(got_steps), len(expected_steps))
        for actual, source in zip(got_steps, expected_steps):
            self.assertEqual(actual["phase"], source["phase"])
            self.assertEqual(actual["operation"], source["operation"])
            self.assertEqual(actual["state"], source["state"])
            self.assertEqual(actual["resource_id"], source["resource_id"])
            self.assertEqual(actual["evidence_ref"], source["evidence_id"] or None)
        source_email = self.service._requests[self.case_id]["email"]
        serialized = json.dumps(payload)
        self.assertNotIn(source_email, serialized)
        self.assertNotRegex(serialized, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

    def test_evidence_is_case_scoped_and_has_no_path_or_raw_excerpt(self):
        detail = self.service.case_detail(self.case_id)
        if not detail["evidence_refs"]:
            self.skipTest("selected case has no admissible source references")
        ref = detail["evidence_refs"][0]
        status, _, body = self.get(f"/api/ghosttrace/v1/cases/{self.case_id}/evidence/{ref}")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["evidence_ref"], ref)
        self.assertNotIn("file_path", json.dumps(payload).casefold())
        self.assertNotIn("raw_text", json.dumps(payload).casefold())
        self.assertIn("allowlisted", payload["excerpt_note"])
        status, _, _ = self.get(f"/api/ghosttrace/v1/cases/{self.case_id}/evidence/../../README.md")
        self.assertIn(status, {400, 404})

    def test_commands_allow_queries_and_block_destructive_or_cross_case_text(self):
        prefix = "/api/ghosttrace/v1/commands/interpret"
        status, payload = self.post(prefix, {"text": "Investigate the selected case", "case_id": self.case_id}, self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["intent"], "INVESTIGATE")
        self.assertFalse(payload["side_effects"])
        status, payload = self.post(prefix, {"text": "delete now", "case_id": self.case_id}, self.origin)
        self.assertEqual(status, 422)
        status, payload = self.post(prefix, {"text": "investigate case_999", "case_id": self.case_id}, self.origin)
        self.assertEqual(status, 422)
        status, payload = self.post(prefix, {"text": "show evidence unavailable by cutoff", "case_id": self.case_id}, self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["intent"], "SHOW_AS_OF")

    def test_investigation_command_replays_the_existing_engine(self):
        before = self.service._results[self.case_id]
        status, payload = self.post("/api/ghosttrace/v1/investigations", {"case_id": self.case_id}, self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "completed")
        self.assertEqual(payload["analysis_type"], "synchronous_engine_replay")
        self.assertEqual(payload["deletion_status"], before["deletion_status"])
        self.assertTrue(payload["read_only"])
        self.assertGreaterEqual(payload["elapsed_ms"], 0)

    def test_report_and_static_api_do_not_leak_contacts_or_offer_file_access(self):
        source_email = self.service._requests[self.case_id]["email"]
        status, headers, report = self.get(f"/api/ghosttrace/v1/cases/{self.case_id}/report")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers["Content-Type"])
        self.assertNotIn(source_email.encode(), report)
        self.assertIn(b"Records modified: **No**", report)
        status, _, _ = self.get("/dataset/deletion_requests.csv")
        self.assertEqual(status, 404)
        status, _, _ = self.get("/api/ghosttrace/v1/cases/not_a_case")
        self.assertEqual(status, 404)

    def test_origin_guard_and_no_mutation_routes(self):
        path = "/api/ghosttrace/v1/commands/interpret"
        status, _ = self.post(path, {"text": "show evidence", "case_id": self.case_id})
        self.assertEqual(status, 403)
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        conn.request("DELETE", f"/api/ghosttrace/v1/cases/{self.case_id}")
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 405)

    def test_supported_command_grammar_rejects_ambiguous_text(self):
        safe = self.service.interpret_command("Show what the sync job would recreate", self.case_id)
        ambiguous = self.service.interpret_command("show evidence and policy", self.case_id)
        self.assertEqual(safe["intent"], "SHOW_LINEAGE")
        self.assertFalse(ambiguous["ok"])

    def test_project_does_not_pin_a_local_port(self):
        for path in (DASHBOARD / "serve.py", DASHBOARD / "README.md", DASHBOARD / "web" / "app.js", DASHBOARD / "web" / "openapi.json"):
            content = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?:localhost|127\.0\.0\.1):\d{2,5}", content), str(path))


    def test_noir_public_assets_are_explicitly_allowlisted(self):
        from serve import PUBLIC_FILES
        self.assertEqual(len(PUBLIC_FILES), 13)
        for route, (_, content_type) in PUBLIC_FILES.items():
            with self.subTest(route=route):
                status, headers, body = self.get(route)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], content_type)
                self.assertTrue(body.startswith(b"\x89PNG") if content_type == "image/png" else body.startswith(b"wOF2"))
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])

    def test_noir_asset_routes_cannot_expose_other_files(self):
        for route in (
            "/assets/ghosttrace/ghosttrace-logo-reference-TYPO.png",
            "/assets/ghosttrace/../../dataset/deletion_requests.csv",
            "/assets/fonts/../../../log.txt",
            "/assets/ghosttrace/%2e%2e/%2e%2e/log.txt",
            "/assets/ghosttrace/README.md",
        ):
            with self.subTest(route=route):
                status, _, _ = self.get(route)
                self.assertEqual(status, 404)

    def test_noir_shell_preserves_the_read_only_api_boundary(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8-sig")
        self.assertIn("GHOSTTRACE", html)
        self.assertNotIn("ghosttrace-logo-reference-TYPO.png", html)
        self.assertIn('id="command-input"', html)
        self.assertIn('id="evidence-inspector"', html)
        self.assertIn('aria-controls="tab-content"', html)
        status, _, css = self.get("/assets/app.css")
        self.assertEqual(status, 200)
        self.assertIn(b"prefers-reduced-motion", css)
        self.assertIn(b"font-display:swap", css)
        status, _, script = self.get("/assets/app.js")
        self.assertEqual(status, 200)
        self.assertNotIn(b".style.", script)
        self.assertNotIn(b"localStorage", script)
        self.assertNotIn(b"innerHTML", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
