import json

from archspec import schema
from archspec.__main__ import main as cli
from archspec.check import check
from archspec.init import END, START, STYLE, init, set_style


def test_fresh_project(tmp_path):
    done = init(tmp_path, "demo")
    assert done == ["created architecture.yaml", "created CLAUDE.md with the architecture rules"]
    spec = schema.load(tmp_path / "architecture.yaml")
    assert spec["project"] == "demo" and spec["scripts"] == []
    assert check(tmp_path / "architecture.yaml") == []  # an empty spec is valid
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith(START) and claude.rstrip().endswith(END)
    assert "archspec:check" in claude and "/archspec:view" in claude


def test_rerun_keeps_spec_and_user_text(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nUse uv for installs.\n", encoding="utf-8")
    init(tmp_path)
    (tmp_path / "architecture.yaml").write_text("version: 1\nproject: mine\nscripts: []\n", encoding="utf-8")

    # Simulate an older rules version, then rerun init.
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    old_block = text[text.index(START):]
    (tmp_path / "CLAUDE.md").write_text(text.replace(old_block, f"{START}\nold rules\n{END}\n") + "\nMore notes.\n",
                                        encoding="utf-8")
    done = init(tmp_path)

    assert done == ["kept existing architecture.yaml", "updated the architecture rules in CLAUDE.md"]
    assert "project: mine" in (tmp_path / "architecture.yaml").read_text(encoding="utf-8")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("# My project\n\nUse uv for installs.\n")
    assert claude.count(START) == 1 and "old rules" not in claude
    assert claude.rstrip().endswith("More notes.")
    assert init(tmp_path)[1] == "CLAUDE.md rules already up to date"


def test_style_is_set_without_touching_other_settings(tmp_path):
    settings = tmp_path / ".claude" / "settings.local.json"
    assert "turned on" in set_style(tmp_path)
    assert json.loads(settings.read_text(encoding="utf-8")) == {"outputStyle": STYLE}
    assert "already on" in set_style(tmp_path)

    settings.write_text('{"permissions": {"allow": ["Bash(ls)"]}, "outputStyle": "default"}', encoding="utf-8")
    set_style(tmp_path)
    assert json.loads(settings.read_text(encoding="utf-8")) == {"permissions": {"allow": ["Bash(ls)"]},
                                                                "outputStyle": STYLE}


def test_style_keeps_a_chosen_style_and_bad_json(tmp_path):
    settings = tmp_path / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text('{"outputStyle": "Learning"}', encoding="utf-8")
    assert "kept your output style 'Learning'" in set_style(tmp_path)
    settings.write_text("{oops", encoding="utf-8")
    assert "not valid JSON" in set_style(tmp_path)
    assert settings.read_text(encoding="utf-8") == "{oops"


def test_cli(tmp_path, capsys, monkeypatch):
    assert cli(["init", str(tmp_path), "--project", "x"]) == 0
    assert "created architecture.yaml" in capsys.readouterr().out
    assert not (tmp_path / ".claude").exists()  # no plugin, no style to turn on
    monkeypatch.setenv("ARCHSPEC_PLUGIN", "1")
    assert cli(["init", str(tmp_path)]) == 0
    assert "turned on" in capsys.readouterr().out
    assert cli(["check", str(tmp_path / "architecture.yaml")]) == 0
    assert cli([]) == 2
