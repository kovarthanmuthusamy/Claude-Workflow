import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from archspec import schema
from archspec.server import ViewerServer

FIXTURE = Path(__file__).parent / "fixtures" / "churn" / "architecture.yaml"


def as_json(spec):
    """What the browser holds: a plain JSON copy of the spec."""
    return json.loads(json.dumps(spec))


@pytest.fixture
def spec_file(tmp_path):
    p = tmp_path / "architecture.yaml"
    shutil.copy(FIXTURE, p)
    return p


def test_merge_without_changes_keeps_file_identical(spec_file):
    before = spec_file.read_text(encoding="utf-8")
    old = schema.load(spec_file)
    assert schema.dumps(schema.merge(old, as_json(schema.load(spec_file)))) == before


def test_merge_edit_keeps_comments_quotes_and_unknown_fields(spec_file):
    old = schema.load(spec_file)
    new = as_json(old)
    new["scripts"][0]["nodes"][0]["purpose"] = "Read raw CSVs"
    new["scripts"][0]["nodes"][0]["signature"] = "load_raw(folder: Path) -> pd.DataFrame"
    text = schema.dumps(schema.merge(old, new))
    assert "purpose: Read raw CSVs\n" in text
    assert 'signature: "load_raw(folder: Path) -> pd.DataFrame"' in text
    assert "# function | class | method | stage" in text
    assert "reviewer_note: unknown fields must survive" in text


def test_merge_add_and_delete(spec_file):
    old = schema.load(spec_file)
    new = as_json(old)
    del new["scripts"][0]["nodes"][1]  # build_features
    new["edges"] = [e for e in new["edges"] if "preprocess.build_features" not in (e["from"], e["to"])]
    new["scripts"][2]["nodes"].append({"id": "plot", "kind": "function", "status": "planned", "purpose": "Plot ROC", "explain": "Draws the ROC curve."})
    new["edges"].append({"from": "evaluate.report", "to": "evaluate.plot", "data": "scores"})
    merged = schema.merge(old, new)
    assert schema.validate(merged) == []
    text = schema.dumps(merged)
    assert "build_features" not in text
    assert "- id: plot" in text and "data: scores" in text
    assert "# planned | built | changed" in text


def test_merge_saves_multiline_text_as_block(spec_file):
    old = schema.load(spec_file)
    new = as_json(old)
    new["scripts"][1]["nodes"][0]["explain"] = " Line one  \n- point a\n- point b\n\n"
    new["scripts"][2]["nodes"].append(
        {"id": "plot", "kind": "function", "status": "planned", "purpose": "p", "explain": "First\nSecond\n"})
    text = schema.dumps(schema.merge(old, new))
    assert "explain: |-\n          Line one\n          - point a\n          - point b\n" in text
    assert "explain: |-\n          First\n          Second\n" in text
    assert schema.load_text(text)["scripts"][1]["nodes"][0]["explain"] == "Line one\n- point a\n- point b"


@pytest.fixture
def server(spec_file):
    srv = ViewerServer(("127.0.0.1", 0), spec_file)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_put_saves_and_detects_conflicts(server, spec_file):
    _, url = server
    _, payload = call(url + "/api/spec")
    spec = payload["spec"]
    spec["project"] = "churn-v2"

    status, saved = call(url + "/api/spec", "PUT", {"spec": spec, "mtime": payload["mtime"]})
    assert status == 200 and saved["spec"]["project"] == "churn-v2"
    assert "project: churn-v2" in spec_file.read_text(encoding="utf-8")
    assert call(url + "/api/activity")[1]["mtime"] == saved["mtime"]

    # Claude edits the file meanwhile; the viewer's stale save is refused...
    spec_file.write_text(spec_file.read_text(encoding="utf-8").replace("churn-v2", "by-claude"), encoding="utf-8")
    spec["project"] = "from-viewer"
    status, body = call(url + "/api/spec", "PUT", {"spec": spec, "mtime": saved["mtime"]})
    assert status == 409 and body["conflict"] and body["spec"]["project"] == "by-claude"

    # ...unless the user chooses to overwrite.
    status, body = call(url + "/api/spec", "PUT", {"spec": spec, "mtime": saved["mtime"], "force": True})
    assert status == 200 and body["spec"]["project"] == "from-viewer"


def test_put_rejects_bad_body(server):
    _, url = server
    assert call(url + "/api/spec", "PUT", {"spec": [1, 2]})[0] == 400
