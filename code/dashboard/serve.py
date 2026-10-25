"""Single-origin, loopback-only launcher with an automatically assigned port."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.dont_write_bytecode = True

from service import DashboardService  # noqa: E402


API_PREFIX = "/api/ghosttrace/v1"
MAX_BODY_BYTES = 16_384
STATIC_DIR = Path(__file__).resolve().parent / "web"
PUBLIC_ASSETS = Path(__file__).resolve().parents[2] / "public" / "assets"
# Explicit public allowlist; never serve arbitrary files or source evidence.
PUBLIC_FILES = {
    "/assets/ghosttrace/" + name: (PUBLIC_ASSETS / "ghosttrace" / name, "image/png")
    for name in (
        "cosmic-background.png", "ghost-brand-emblem-only.png", "ghost-lemonade-rocks.png",
        "ghost-cases-books.png", "ghost-central-evidence.png", "ghost-detective-rocks.png",
    )
}
PUBLIC_FILES.update({
    "/assets/fonts/" + name: (PUBLIC_ASSETS / "fonts" / name, "font/woff2")
    for name in (
        "cormorant-garamond-latin-500-normal.woff2", "cormorant-garamond-latin-600-normal.woff2",
        "manrope-latin-400-normal.woff2", "manrope-latin-500-normal.woff2", "manrope-latin-600-normal.woff2",
        "ibm-plex-mono-latin-400-normal.woff2", "ibm-plex-mono-latin-500-normal.woff2",
    )
})


def _host_is_local(value: str) -> bool:
    host = urlsplit("//" + (value or "")).hostname
    return host in {"127.0.0.1", "localhost", "::1"}


def _origin_matches(origin: str, host: str) -> bool:
    if not origin or origin == "null":
        return False
    parsed = urlsplit(origin)
    return parsed.scheme == "http" and parsed.netloc.casefold() == host.casefold() and _host_is_local(parsed.netloc)


def make_handler(service: DashboardService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "GhostTraceLocal/1"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            # Avoid writing request bodies, query text, or personal data to logs.
            return

        def _security_headers(self, content_type: str) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self._security_headers(content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(status, encoded, "application/json; charset=utf-8")

        def _local_request(self) -> bool:
            return (self.client_address[0] in {"127.0.0.1", "::1"}
                    and _host_is_local(self.headers.get("Host", "")))

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def do_GET(self) -> None:  # noqa: N802
            if not self._local_request():
                self._error(403, "loopback_only", "GhostTrace accepts loopback requests only.")
                return
            path = urlsplit(self.path).path
            try:
                if path == "/":
                    return self._static("index.html", "text/html; charset=utf-8")
                if path in PUBLIC_FILES:
                    target, content_type = PUBLIC_FILES[path]
                    try:
                        return self._send(200, target.read_bytes(), content_type)
                    except OSError:
                        return self._error(404, "asset_missing", "Public artwork or font is missing.")
                if path == "/assets/app.css":
                    return self._static("app.css", "text/css; charset=utf-8")
                if path == "/assets/app.js":
                    return self._static("app.js", "text/javascript; charset=utf-8")
                if path == API_PREFIX + "/openapi.json":
                    return self._static("openapi.json", "application/json; charset=utf-8")
                if not path.startswith(API_PREFIX + "/"):
                    self._error(404, "not_found", "Route not found.")
                    return
                suffix = path[len(API_PREFIX):]
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=False)
                if suffix == "/health":
                    return self._json(200, service.health())
                if suffix == "/runtime-config":
                    return self._json(200, {"api_prefix": API_PREFIX, "data_mode": "private_local_corpus", "read_only": True, "features": {"evidence_metadata": True, "lineage_table": True, "sanitized_report": True, "engine_replay": True, "synthetic_demo": False}})
                if suffix == "/cases":
                    try:
                        return self._json(200, service.list_cases(
                            query.get("query", [""])[0], query.get("status", [""])[0],
                            int(query.get("page", ["1"])[0]), int(query.get("page_size", ["40"])[0])))
                    except RuntimeError as exc:
                        status = 503 if service.health()["status"] != "failed" else 500
                        return self._error(status, "engine_unavailable", str(exc))
                    except ValueError:
                        return self._error(400, "invalid_query", "Search by case ID only; contact values are not accepted.")
                pieces = suffix.strip("/").split("/")
                if len(pieces) >= 2 and pieces[0] == "cases":
                    case_id = unquote(pieces[1])
                    try:
                        if len(pieces) == 2:
                            return self._json(200, service.case_detail(case_id))
                        if pieces[2] == "graph" and len(pieces) == 3:
                            return self._json(200, service.case_detail(case_id)["graph"])
                        if pieces[2] == "timeline" and len(pieces) == 3:
                            return self._json(200, service.case_detail(case_id)["timeline"])
                        if pieces[2] == "coverage" and len(pieces) == 3:
                            return self._json(200, service.coverage(case_id))
                        if pieces[2] == "steps" and len(pieces) == 3:
                            return self._json(200, {"case_id": case_id, "steps": service.case_detail(case_id)["steps"], "read_only": True})
                        if pieces[2] == "report" and len(pieces) == 3:
                            return self._send(200, service.report(case_id).encode("utf-8"), "text/markdown; charset=utf-8")
                        if pieces[2] == "evidence" and len(pieces) == 4:
                            return self._json(200, service.evidence_detail(case_id, unquote(pieces[3])))
                    except KeyError as exc:
                        return self._error(404, "not_found", str(exc).strip("'"))
                    except RuntimeError as exc:
                        status = 503 if service.health()["status"] != "failed" else 500
                        return self._error(status, "engine_unavailable", str(exc))
                self._error(404, "not_found", "Route not found.")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                self._error(500, "internal_error", "The local request failed. Check the launcher output for engine status.")

        def do_POST(self) -> None:  # noqa: N802
            if not self._local_request():
                self._error(403, "loopback_only", "GhostTrace accepts loopback requests only.")
                return
            if not _origin_matches(self.headers.get("Origin", ""), self.headers.get("Host", "")):
                self._error(403, "origin_rejected", "POST requests must come from this local browser origin.")
                return
            route = urlsplit(self.path).path
            if route not in {API_PREFIX + "/commands/interpret", API_PREFIX + "/investigations"}:
                self._error(405, "read_only", "Only safe, read-only case analysis is accepted; no data mutations are available.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._error(400, "invalid_length", "Invalid request length.")
            if length <= 0 or length > MAX_BODY_BYTES:
                return self._error(413, "request_too_large", "Command requests must be non-empty and within the size limit.")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                if route == API_PREFIX + "/investigations":
                    if not isinstance(payload.get("case_id"), str):
                        raise ValueError("expected case_id")
                    result = service.investigate(payload["case_id"])
                    self._json(200, result)
                else:
                    if not isinstance(payload.get("text"), str):
                        raise ValueError("expected text")
                    result = service.interpret_command(payload["text"], str(payload.get("case_id", "")))
                    self._json(200 if result.get("ok") else 422, result)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self._error(400, "invalid_body", "Send the required JSON fields for a read-only case request.")
            except KeyError as exc:
                self._error(404, "not_found", str(exc).strip("'"))
            except RuntimeError as exc:
                status = 503 if service.health()["status"] != "failed" else 500
                self._error(status, "engine_unavailable", str(exc))

        def do_HEAD(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "HEAD is not supported.")

        def do_PUT(self) -> None:  # noqa: N802
            self._error(405, "read_only", "GhostTrace has no mutation routes.")

        def do_PATCH(self) -> None:  # noqa: N802
            self._error(405, "read_only", "GhostTrace has no mutation routes.")

        def do_DELETE(self) -> None:  # noqa: N802
            self._error(405, "read_only", "GhostTrace has no mutation routes.")

        def _static(self, name: str, content_type: str) -> None:
            target = STATIC_DIR / name
            try:
                content = target.read_bytes()
            except OSError:
                self._error(500, "ui_missing", "Dashboard assets are missing from the local installation.")
                return
            self._send(200, content, content_type)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only GhostTrace local browser dashboard")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                        help="GhostTrace repository root (defaults to this checkout)")
    args = parser.parse_args()
    repo_root = args.repo.expanduser().resolve()
    service = DashboardService(repo_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    server.daemon_threads = True
    host, port = server.server_address[:2]
    print(f"GhostTrace dashboard: http://{host}:{port}/", flush=True)
    print(f"GhostTrace API: http://{host}:{port}{API_PREFIX}", flush=True)
    print(f"Repository: {repo_root}", flush=True)
    print("Binding: loopback only; the system selected this available address.", flush=True)
    print("Startup: evidence index is warming in the background; health reports real progress.", flush=True)
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("Stopping this GhostTrace dashboard process.", flush=True)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
