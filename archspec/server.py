"""archview: serve the viewer for an architecture.yaml on 127.0.0.1.

GET /api/spec   -> {path, mtime, spec, issues}
PUT /api/spec   <- {spec, mtime, force?}; 409 if the file changed since mtime
GET /api/activity?after=N -> {seq, events, task, session, live, mtime}
GET /*          -> files from archspec/static/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import check, schema
from .activity import ActivityWatcher

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json"}


class ViewerServer(ThreadingHTTPServer):
    def __init__(self, addr, spec_path: Path, watcher: ActivityWatcher | None = None):
        super().__init__(addr, Handler)
        self.spec_path = spec_path
        self.save_lock = threading.Lock()
        self.watcher = watcher

    def activity(self, after: int) -> dict:
        live = self.watcher.since(after) if self.watcher else {"seq": 0, "events": [], "task": None, "session": None}
        return {**live, "live": self.watcher is not None, "mtime": self.mtime()}

    def payload(self) -> dict:
        p = self.spec_path
        out = {"path": str(p), "mtime": self.mtime()}
        try:
            out["spec"] = schema.load(p)
        except Exception as e:  # noqa: BLE001 - shown to the user in the page
            out["error"] = f"cannot read {p.name}: {e}"
            return out
        out["issues"] = [asdict(i) for i in check.check(p)]
        return out

    def mtime(self) -> str | None:
        # A string: nanosecond timestamps exceed JavaScript's exact integer range.
        return str(self.spec_path.stat().st_mtime_ns) if self.spec_path.exists() else None

    def save(self, new_spec: dict, base_mtime: str | None, force: bool) -> tuple[int, dict]:
        """Merge the viewer's spec into the file. 409 if the file changed since `base_mtime`."""
        with self.save_lock:
            if not force and self.mtime() != base_mtime:
                return 409, {**self.payload(), "conflict": True}
            p = self.spec_path
            spec = schema.merge(schema.load(p), new_spec)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(schema.dumps(spec).encode("utf-8"))
            os.replace(tmp, p)  # atomic: Claude never sees a half-written file
            return 200, self.payload()


class Handler(BaseHTTPRequestHandler):
    server: ViewerServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/spec":
            self._json(200, self.server.payload())
            return
        if path == "/api/activity":  # live session events after ?after=<seq>, plus mtime
            after = parse_qs(urlsplit(self.path).query).get("after", ["0"])[0]
            self._json(200, self.server.activity(int(after) if after.isdigit() else 0))
            return
        target = (STATIC / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_file() or STATIC not in target.parents:
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"))

    def do_PUT(self) -> None:
        if urlsplit(self.path).path != "/api/spec":
            self._send(404, b"not found", "text/plain")
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            spec = body["spec"]
            if not isinstance(spec, dict):
                raise ValueError("spec must be an object")
        except (ValueError, KeyError) as e:
            self._json(400, {"error": f"bad request: {e}"})
            return
        self._json(*self.server.save(spec, body.get("mtime"), bool(body.get("force"))))

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["init"]:
        from . import init
        return init.main(argv[1:])
    ap = argparse.ArgumentParser(prog="archview", description="Open the architecture viewer. (`archview init` sets up a project.)")
    ap.add_argument("spec", nargs="?", default="architecture.yaml", help="path to the spec (default: ./architecture.yaml)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    ap.add_argument("--no-live", action="store_true", help="don't follow the Claude Code session log")
    args = ap.parse_args(argv)

    spec_path = Path(args.spec).resolve()
    if not spec_path.is_file():
        print(f"archview: {args.spec} not found", file=sys.stderr)
        return 2
    watcher = None if args.no_live else ActivityWatcher(spec_path).start()
    try:
        server = ViewerServer(("127.0.0.1", args.port), spec_path, watcher)
    except OSError:  # port busy: let the OS pick one
        server = ViewerServer(("127.0.0.1", 0), spec_path, watcher)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"archview: {spec_path} -> {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
