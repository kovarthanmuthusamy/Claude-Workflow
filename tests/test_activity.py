import json
import shutil
from pathlib import Path

import pytest

from archspec.activity import ActivityWatcher, slug

FIXTURE = Path(__file__).parent / "fixtures" / "churn"


@pytest.fixture
def setup(tmp_path):
    proj = tmp_path / "churn"
    shutil.copytree(FIXTURE, proj)
    logs = tmp_path / "projects" / slug(proj.resolve())
    logs.mkdir(parents=True)
    log = logs / "session-1.jsonl"
    log.write_text("", encoding="utf-8")
    watcher = ActivityWatcher(proj / "architecture.yaml", projects_dir=tmp_path / "projects")
    return proj, log, watcher


def user(text):
    return {"type": "user", "timestamp": "2026-10-26T10:00:00Z", "message": {"role": "user", "content": text}}


def tool(name, tool_id="t", **inp):
    return {"type": "assistant", "timestamp": "2026-10-26T10:00:01Z",
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}


def result(tool_id, text, is_error=False):
    return {"type": "user", "timestamp": "2026-10-26T10:00:02Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}]}}


def append(log, *entries):
    with open(log, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def brief(events):
    return [(e["kind"], e.get("refs") or e.get("script") or e.get("detail")) for e in events]


def test_tool_calls_map_to_nodes(setup):
    proj, log, w = setup
    train, pre = str(proj / "src" / "train.py"), str(proj / "src" / "preprocess.py")
    append(log,
           user("add early stopping"),
           tool("Read", file_path=train, offset=10, limit=3),                        # lines of fit()
           tool("Edit", file_path=train, old_string="x", new_string="            self._step(X, y)"),
           tool("Edit", file_path=train, old_string="x", new_string="    def _step(self, X, y):\n        pass"),
           tool("Edit", file_path=pre, old_string="x", new_string="    return df\n"),  # helper of load_raw
           tool("Write", file_path=str(proj / "src" / "evaluate.py"), content="..."),
           tool("Edit", file_path=str(proj.parent / "elsewhere.py"), old_string="a", new_string="b"),
           {**tool("Edit", file_path=train, old_string="a", new_string="b"), "isSidechain": True})
    w.poll()
    assert brief(w.since(0)["events"]) == [
        ("task", "add early stopping"),
        ("read", ["train.Trainer.fit"]),
        ("edit", ["train.Trainer.fit"]),
        ("edit", ["train.Trainer"]),          # _step has no node -> its class
        ("edit", ["preprocess.load_raw"]),    # _parse_dates is a helper of load_raw
        ("write", "evaluate"),                # whole file -> script level
    ]
    assert all(e["task"] == "add early stopping" for e in w.since(0)["events"])


def test_commands_and_results_are_tailed(setup):
    proj, log, w = setup
    append(log, user("run it"))
    w.poll()
    seq = w.seq
    append(log,
           tool("PowerShell", "b1", command="python src\\train.py --epochs 3"),
           result("b1", "Traceback ...", is_error=True),
           tool("Bash", "c1", command="python -m archspec check"),
           result("c1", "archcheck: OK"),
           tool("Bash", "p1", command="python -m pytest -q"),
           result("p1", "2 failed, 23 passed in 3.1s"))
    with open(log, "a", encoding="utf-8") as f:  # a half-written line is not parsed yet
        f.write('{"type": "user", "message"')
    w.poll()
    assert brief(w.since(seq)["events"]) == [
        ("run", "train"),
        ("run-error", "train"),
        ("check", "checking spec against code"),
        ("check-result", "spec matches the code"),
        ("test", "running tests"),
        ("test-result", "23 passed, 2 failed"),
    ]


def test_task_found_before_history_window(setup, monkeypatch):
    proj, log, w = setup
    monkeypatch.setattr("archspec.activity.HISTORY_BYTES", 300)
    append(log, user("the real task"), *[tool("Read", f"r{i}", file_path="elsewhere.py") for i in range(20)])
    w.poll()
    assert w.task == "the real task"
    assert all(e["kind"] != "task" for e in w.since(0)["events"])  # it was outside the window


def test_project_sessions_win_over_newer_parent_sessions(setup, tmp_path):
    proj, log, w = setup
    append(log, user("task in the project"))
    parent = tmp_path / "projects" / slug(proj.resolve().parent)
    parent.mkdir()
    append(parent / "other.jsonl", user("unrelated task in the parent folder"))
    w.poll()
    assert w.task == "task in the project" and w.session == log


def test_switches_to_newest_session(setup):
    proj, log, w = setup
    append(log, user("old task"))
    w.poll()
    newer = log.with_name("session-2.jsonl")
    append(newer, user("new task"))
    import os
    os.utime(newer, (log.stat().st_mtime + 5, log.stat().st_mtime + 5))
    w.poll()
    assert w.task == "new task" and w.session == newer
