import shutil
from pathlib import Path

import pytest

from archspec import schema
from archspec.check import check, main

FIXTURE = Path(__file__).parent / "fixtures" / "churn"


@pytest.fixture
def proj(tmp_path):
    dst = tmp_path / "churn"
    shutil.copytree(FIXTURE, dst)
    return dst


def edit_spec(proj, fn):
    spec = schema.load(proj / "architecture.yaml")
    fn(spec)
    schema.dump(spec, proj / "architecture.yaml")


def node(spec, script_id, node_id):
    script = next(s for s in spec["scripts"] if s["id"] == script_id)
    return next(n for n in script["nodes"] if n["id"] == node_id)


def messages(issues, level):
    return [f"{i.where}: {i.message}" for i in issues if i.level == level]


def test_clean_fixture_has_no_issues(proj):
    assert check(proj / "architecture.yaml") == []
    assert main([str(proj / "architecture.yaml")]) == 0


def test_round_trip_keeps_text_unchanged(proj):
    path = proj / "architecture.yaml"
    before = path.read_text(encoding="utf-8")
    schema.dump(schema.load(path), path)
    assert path.read_text(encoding="utf-8") == before


def test_missing_built_function(proj):
    edit_spec(proj, lambda s: node(s, "preprocess", "load_raw").update(id="load_all"))
    edit_spec(proj, lambda s: s["edges"][0].update({"from": "preprocess.load_all"}))
    errors = messages(check(proj / "architecture.yaml"), "error")
    assert errors == ["preprocess.load_all: function not found in src/preprocess.py"]
    assert main([str(proj / "architecture.yaml")]) == 1


def test_missing_file_only_matters_once_built(proj):
    edit_spec(proj, lambda s: node(s, "evaluate", "report").update(status="built", signature="report(path)"))
    errors = messages(check(proj / "architecture.yaml"), "error")
    assert errors == ["evaluate: file src/evaluate.py not found"]


def test_parameter_name_drift(proj):
    f = proj / "src" / "preprocess.py"
    f.write_text(f.read_text().replace("def load_raw(path: Path)", "def load_raw(folder: Path)"))
    [err] = messages(check(proj / "architecture.yaml"), "error")
    assert "parameters (path) vs (folder)" in err
    assert "(code: load_raw(folder: Path) -> pd.DataFrame)" in err


def test_annotation_drift_but_terse_spec_is_fine(proj):
    edit_spec(proj, lambda s: node(s, "preprocess", "load_raw").update(signature="load_raw(path: str)"))
    [err] = messages(check(proj / "architecture.yaml"), "error")
    assert "'path' annotated str vs Path" in err

    edit_spec(proj, lambda s: node(s, "preprocess", "load_raw").update(signature="load_raw(path)"))
    assert messages(check(proj / "architecture.yaml"), "error") == []


def test_method_self_and_class_constructor(proj):
    f = proj / "src" / "train.py"
    f.write_text(f.read_text().replace("lr: float, epochs: int", "lr: float"))
    [err] = messages(check(proj / "architecture.yaml"), "error")
    assert err.startswith("train.Trainer: signature drift: parameters (lr, epochs) vs (lr)")


def test_changed_status_skips_signature_check(proj):
    edit_spec(proj, lambda s: node(s, "preprocess", "load_raw").update(status="changed", signature="load_raw(src)"))
    assert messages(check(proj / "architecture.yaml"), "error") == []


def test_bad_edge(proj):
    edit_spec(proj, lambda s: s["edges"].append({"from": "train.Trainer.fit", "to": "train.Ghost", "data": "x"}))
    errors = messages(check(proj / "architecture.yaml"), "error")
    assert errors == ["edge train.Trainer.fit -> train.Ghost: 'to' points to unknown node 'train.Ghost'"]


def test_schema_errors(proj):
    def broken(s):
        node(s, "preprocess", "build_features").update(kind="widget")
        node(s, "train", "Trainer.fit").update(id="Model.fit")
        s["edges"][1].update(to="train.Model.fit")
        del node(s, "preprocess", "load_raw")["signature"]
        del s["edges"][0]["data"]
    edit_spec(proj, broken)
    errors = messages(check(proj / "architecture.yaml"), "error")
    assert "preprocess.load_raw: signature is required once status is built" in errors
    assert any(e.startswith("preprocess.build_features: kind must be one of") for e in errors)
    assert "train.Model.fit: method's class 'Model' has no class node in this script" in errors
    assert "edge preprocess.load_raw -> preprocess.build_features: data label is missing" in errors


def test_unspecced_public_imports(proj):
    f = proj / "src" / "preprocess.py"
    f.write_text(f.read_text() + "\n\ndef clean_text(s):\n    return s\n\n\ndef normalize(df):\n    return df\n\n\ndef unused():\n    pass\n")
    (proj / "src" / "__init__.py").write_text("")
    (proj / "src" / "evaluate.py").write_text(
        "from .preprocess import clean_text\n"
        "import src.preprocess as pp\n\n"
        "pp.normalize(None)\n"
    )
    warnings = messages(check(proj / "architecture.yaml"), "warning")
    assert warnings == [
        "preprocess.clean_text: imported by src/evaluate.py and has no node (node rule)",
        "preprocess.normalize: imported by src/evaluate.py and has no node (node rule)",
    ]


def test_helper_and_method_warnings(proj):
    edit_spec(proj, lambda s: node(s, "preprocess", "load_raw").update(helpers=["_parse_dates", "_gone"]))
    edit_spec(proj, lambda s: node(s, "train", "Trainer")["methods"].append("export"))
    warnings = messages(check(proj / "architecture.yaml"), "warning")
    assert warnings == [
        "preprocess.load_raw: helper '_gone' not found in src/preprocess.py",
        "train.Trainer: listed method 'export' not found",
    ]


def test_over_cap_warning(proj):
    def many(s):
        script = next(x for x in s["scripts"] if x["id"] == "evaluate")
        script["nodes"] += [{"id": f"n{i}", "kind": "function", "status": "planned", "purpose": "p", "explain": "e"} for i in range(6)]
    edit_spec(proj, many)
    count = len(next(x for x in schema.load(proj / "architecture.yaml")["scripts"] if x["id"] == "evaluate")["nodes"])
    warnings = messages(check(proj / "architecture.yaml"), "warning")
    assert warnings == [f"evaluate: {count} nodes (soft cap is 6); move some to helpers"]


def test_missing_explain_warns(proj):
    edit_spec(proj, lambda s: node(s, "train", "Trainer").pop("explain"))
    warnings = messages(check(proj / "architecture.yaml"), "warning")
    assert warnings == ["train.Trainer: explain is empty (2-4 plain sentences: in, what happens, out, why)"]
