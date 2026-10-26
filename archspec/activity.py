"""Live activity: follow the Claude Code session log and map tool calls to spec nodes.

Claude Code writes one JSON line per event to ~/.claude/projects/<cwd-slug>/<session>.jsonl.
We tail only new bytes of the newest session and turn Read/Edit/Write/shell calls into
function-level events ("editing train.Trainer.fit") for the viewer. Zero tokens.
"""

from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterator

from . import schema

HISTORY_BYTES = 400_000   # how far back to read when a session is first opened
MAX_EVENTS = 200
SHELL_TOOLS = {"Bash", "PowerShell"}


def slug(path: Path) -> str:
    """Claude Code's folder name for a working directory: C:\\a\\b -> C--a-b."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


# ---------------------------------------------------------------- locating nodes

class Locator:
    """Maps a file + line range to spec node refs, using the spec and the code's ast."""

    def __init__(self, spec_path: Path):
        self.spec_path = spec_path
        self.root = spec_path.parent
        self._spec_mtime: int | None = None
        self._files: dict[str, dict] = {}   # norm(path) -> {script, nodes, helpers, rel}
        self._defs: dict[str, tuple[int, list]] = {}  # norm(path) -> (mtime, defs)

    def refresh(self) -> None:
        try:
            mtime = self.spec_path.stat().st_mtime_ns
        except OSError:
            return
        if mtime == self._spec_mtime:
            return
        self._spec_mtime = mtime
        try:
            spec = schema.load(self.spec_path)
        except Exception:  # noqa: BLE001 - keep the last good mapping
            return
        files = {}
        for script in spec.get("scripts") or []:
            if not isinstance(script, dict) or not isinstance(script.get("file"), str):
                continue
            nodes = {n["id"] for n in script.get("nodes") or [] if isinstance(n, dict) and "id" in n}
            helpers = {h: n["id"] for n in script.get("nodes") or [] if isinstance(n, dict)
                       for h in n.get("helpers") or []}
            files[norm(self.root / script["file"])] = {
                "script": script.get("id"), "nodes": nodes, "helpers": helpers, "rel": script["file"]}
        self._files = files

    def script_for(self, path: str) -> dict | None:
        return self._files.get(norm(path))

    def scripts(self) -> list[dict]:
        return list(self._files.values())

    def rel(self, path: str) -> str | None:
        """Path relative to the project root, or None if outside it."""
        try:
            return Path(norm(path)).relative_to(norm(self.root)).as_posix()
        except ValueError:
            return None

    def _definitions(self, path: str) -> list[tuple[int, int, tuple]]:
        key = norm(path)
        try:
            mtime = os.stat(key).st_mtime_ns
        except OSError:
            return []
        cached = self._defs.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            tree = ast.parse(Path(key).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return cached[1] if cached else []

        def span(n):
            start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
            return start, n.end_lineno or n.lineno

        defs = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.append((*span(n), ("function", n.name)))
            elif isinstance(n, ast.ClassDef):
                defs.append((*span(n), ("class", n.name)))
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        defs.append((*span(m), ("method", n.name, m.name)))
        self._defs[key] = (mtime, defs)
        return defs

    def refs(self, path: str, first: int, last: int) -> list[str]:
        """Node refs whose code overlaps lines first..last (most specific first)."""
        info = self.script_for(path)
        if not info:
            return []
        sid, nodes, helpers = info["script"], info["nodes"], info["helpers"]
        out: list[str] = []
        hit = [d for d in self._definitions(path) if d[0] <= last and d[1] >= first]
        # A method inside a hit class is more specific than the class itself.
        methods = {(d[2][1]) for d in hit if d[2][0] == "method"}
        for _, _, what in hit:
            if what[0] == "class" and what[1] in methods:
                continue
            ref = None
            if what[0] == "method":
                cls, name = what[1], what[2]
                ref = f"{cls}.{name}" if f"{cls}.{name}" in nodes else (cls if cls in nodes else None)
            elif what[1] in nodes:
                ref = what[1]
            elif what[1] in helpers:
                ref = helpers[what[1]]
            if ref and f"{sid}.{ref}" not in out:
                out.append(f"{sid}.{ref}")
        return out


# ---------------------------------------------------------------- watcher

USER_LINE = re.compile(rb'"type":\s*"user"')


def _prompt(entry: dict) -> str | None:
    """The text of a message the user typed (not a tool result or system note)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
        return " ".join(content.split())[:160]
    return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


class ActivityWatcher:
    def __init__(self, spec_path: Path, projects_dir: Path | None = None):
        self.spec_path = spec_path
        self.projects_dir = projects_dir or Path.home() / ".claude" / "projects"
        self.locator = Locator(spec_path)
        self.events: deque[dict] = deque(maxlen=MAX_EVENTS)
        self.seq = 0
        self.task: str | None = None
        self.session: Path | None = None
        self._offset = 0
        self._partial = b""
        self._pending: dict[str, dict] = {}  # tool_use id -> event awaiting its result
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- session discovery

    def candidate_dirs(self) -> list[Path]:
        """Log folders for the project root and its parents (Claude may run from a parent)."""
        root = self.spec_path.parent.resolve()
        return [d for p in (root, *root.parents) if (d := self.projects_dir / slug(p)).is_dir()]

    def newest_session(self) -> Path | None:
        """Newest log in the closest folder that has any; a parent folder's sessions are
        only used when Claude has never been run from the project folder itself."""
        for d in self.candidate_dirs():
            files = list(d.glob("*.jsonl"))
            if files:
                return max(files, key=lambda f: f.stat().st_mtime)
        return None

    # -- reading

    def poll(self) -> None:
        self.locator.refresh()
        newest = self.newest_session()
        if newest is None:
            return
        if newest != self.session:
            self.session = newest
            size = newest.stat().st_size
            self._offset = max(0, size - HISTORY_BYTES)
            self._partial = b""
            self._pending.clear()
            self.task = self._last_prompt_before(newest, self._offset)
            skip_first = self._offset > 0  # we probably landed mid-line
        else:
            skip_first = False
        with open(newest, "rb") as f:
            f.seek(self._offset)
            data = f.read()
        if not data:
            return
        self._offset += len(data)
        lines = (self._partial + data).split(b"\n")
        self._partial = lines.pop()  # incomplete last line, finished on the next poll
        if skip_first and lines:
            lines = lines[1:]
        for raw in lines:
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for event in self._events_from(entry):
                self._add(event)

    def _last_prompt_before(self, path: Path, end: int, chunk: int = 1 << 20) -> str | None:
        """The user's latest message before byte `end`, searching backwards in chunks."""
        pos, tail = end, b""
        with open(path, "rb") as f:
            while pos > 0:
                start = max(0, pos - chunk)
                f.seek(start)
                lines = (f.read(pos - start) + tail).split(b"\n")
                tail = lines.pop(0) if start > 0 else b""  # may be cut; finish it next round
                for raw in reversed(lines):
                    if not USER_LINE.search(raw):
                        continue
                    try:
                        entry = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if (prompt := _prompt(entry)) is not None:
                        return prompt
                pos = start
        return None

    def _add(self, event: dict) -> None:
        with self._lock:
            self.seq += 1
            event["seq"] = self.seq
            event.setdefault("task", self.task)
            self.events.append(event)

    def _events_from(self, entry: dict) -> Iterator[dict]:
        if entry.get("isSidechain"):
            return
        kind, ts = entry.get("type"), entry.get("timestamp")
        content = (entry.get("message") or {}).get("content")

        if kind == "user" and not entry.get("isMeta"):
            if (prompt := _prompt(entry)) is not None:
                self.task = prompt
                yield {"ts": ts, "kind": "task", "detail": prompt}
                return
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in self._pending:
                    yield from self._result(self._pending.pop(block["tool_use_id"]), block, ts)
            return

        if kind == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    yield from self._tool(block.get("name"), block.get("input") or {}, block.get("id"), ts)

    def _tool(self, name: str, inp: dict, tool_id: str | None, ts: str | None) -> Iterator[dict]:
        if "todos" in inp:  # TodoWrite: the item in progress refines the task label
            doing = next((t for t in inp["todos"] if t.get("status") == "in_progress"), None)
            if doing:
                yield {"ts": ts, "kind": "todo", "detail": doing.get("activeForm") or doing.get("content")}
            return

        path = inp.get("file_path")
        if path and name in ("Read", "Edit", "Write", "MultiEdit"):
            rel = self.locator.rel(path)
            if rel is None:
                return  # outside this project
            info = self.locator.script_for(path)
            refs: list[str] = []
            if name == "Read" and inp.get("offset"):
                first = int(inp["offset"])
                refs = self.locator.refs(path, first, first + int(inp.get("limit") or 2000) - 1)
            elif name in ("Edit", "MultiEdit"):
                for new in [inp.get("new_string")] + [e.get("new_string") for e in inp.get("edits") or []]:
                    refs += [r for r in self._refs_for_text(path, new) if r not in refs]
            kind = {"Read": "read", "Write": "write"}.get(name, "edit")
            yield {"ts": ts, "kind": kind, "file": rel, "script": info and info["script"], "refs": refs}
            return

        if name in SHELL_TOOLS:
            cmd = inp.get("command") or ""
            event = None
            if re.search(r"archspec(\.check|\s+check)|archcheck", cmd):
                event = {"ts": ts, "kind": "check", "detail": "checking spec against code"}
            elif re.search(r"\bpytest\b", cmd):
                event = {"ts": ts, "kind": "test", "detail": "running tests"}
            else:
                for info in self.locator.scripts():
                    module = info["rel"].removesuffix(".py").replace("/", ".")
                    names = [info["rel"], info["rel"].replace("/", "\\"), Path(info["rel"]).name, module]
                    if any(re.search(rf"(?<![\w.\\/-]){re.escape(n)}(?![\w])", cmd) for n in names):
                        event = {"ts": ts, "kind": "run", "script": info["script"], "file": info["rel"],
                                 "detail": f"running {info['rel']}"}
                        break
            if event:
                if tool_id:
                    self._pending[tool_id] = event
                yield event

    def _result(self, event: dict, block: dict, ts: str | None) -> Iterator[dict]:
        text = _text(block.get("content"))
        if event["kind"] == "check":
            ok = "archcheck: OK" in text
            m = re.search(r"(\d+) error\(s\), (\d+) warning", text)
            detail = "spec matches the code" if ok else (f"{m.group(1)} errors, {m.group(2)} warnings" if m else "check failed")
            yield {"ts": ts, "kind": "check-result", "ok": ok, "detail": detail}
        elif event["kind"] == "test":
            m = re.search(r"(\d+) failed", text)
            p = re.search(r"(\d+) passed", text)
            ok = bool(p) and not m and not block.get("is_error")
            detail = f"{p.group(1) if p else 0} passed" + (f", {m.group(1)} failed" if m else "")
            yield {"ts": ts, "kind": "test-result", "ok": ok, "detail": detail}
        elif event["kind"] == "run" and block.get("is_error"):
            yield {"ts": ts, "kind": "run-error", "script": event.get("script"), "ok": False,
                   "detail": f"{event.get('file')} exited with an error"}

    def _refs_for_text(self, path: str, new: str | None) -> list[str]:
        """Find edited text in the file now and see which functions contain it."""
        if not new or not new.strip():
            return []
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        idx = text.find(new)
        if idx < 0:
            return []  # changed again since; the file-level event still shows
        first = text.count("\n", 0, idx) + 1
        return self.locator.refs(path, first, first + new.count("\n"))

    # -- serving

    def since(self, after: int) -> dict:
        with self._lock:
            return {
                "seq": self.seq,
                "task": self.task,
                "session": self.session.stem if self.session else None,
                "events": [e for e in self.events if e["seq"] > after],
            }

    def run(self, interval: float = 1.0) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - never kill the viewer over a log hiccup
                pass
            self._stop.wait(interval)

    def start(self) -> "ActivityWatcher":
        threading.Thread(target=self.run, daemon=True, name="archspec-activity").start()
        return self

    def stop(self) -> None:
        self._stop.set()


if __name__ == "__main__":  # quick terminal view: python -m archspec.activity architecture.yaml
    import sys
    w = ActivityWatcher(Path(sys.argv[1] if len(sys.argv) > 1 else "architecture.yaml").resolve())
    seen = 0
    while True:
        w.poll()
        for e in w.since(seen)["events"]:
            print(f"{(e.get('ts') or '')[11:19]}  {e['kind']:12} {' '.join(e.get('refs') or []) or e.get('file') or ''}"
                  f"  {e.get('detail') or ''}")
        seen = w.seq
        time.sleep(1)
