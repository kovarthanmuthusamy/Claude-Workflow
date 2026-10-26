import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from archspec.server import ViewerServer

FIXTURE = Path(__file__).parent / "fixtures" / "churn" / "architecture.yaml"


@pytest.fixture
def base_url():
    server = ViewerServer(("127.0.0.1", 0), FIXTURE)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def test_spec_endpoint(base_url):
    status, body = get(base_url + "/api/spec")
    payload = json.loads(body)
    assert status == 200
    assert payload["spec"]["project"] == "churn-model"
    assert payload["spec"]["scripts"][2]["nodes"][0]["reviewer_note"] == "unknown fields must survive"
    assert payload["issues"] == []
    assert payload["mtime"].isdigit()  # string, so JavaScript can't round it


def test_static_files_and_no_escape(base_url):
    assert get(base_url + "/")[0] == 200
    assert get(base_url + "/vendor/xyflow-react.mjs")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base_url + "/../server.py")
    assert e.value.code == 404
