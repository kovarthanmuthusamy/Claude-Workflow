import shutil
import subprocess
from pathlib import Path

import pytest

from archspec.walkthrough import render

FIXTURE = Path(__file__).parent / "fixtures" / "churn"


@pytest.fixture
def proj(tmp_path):
    dst = tmp_path / "churn"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_code_marker_extracts_method_dedented(proj):
    out, problems = render("<!-- code: src/train.py:Trainer.fit -->", proj)
    assert problems == []
    assert "```python\ndef fit(self, X: pd.DataFrame, y: pd.Series) -> None:" in out
    assert "def _step" not in out and out.endswith("<!-- /code -->")


def test_run_marker_inserts_real_output_and_rerender_replaces(proj):
    doc = "Result:\n<!-- run: python -c \"print(6*7)\" -->\nafter"
    once, _ = render(doc, proj)
    assert "```text\n42\n```" in once
    twice, _ = render(once, proj)
    assert twice == once  # idempotent: old output replaced, not duplicated
    assert twice.endswith("<!-- /run -->\nafter")


def test_failing_command_shows_exit_code(proj):
    out, _ = render('<!-- run: python -c "import sys; print(1); sys.exit(3)" -->', proj)
    assert "*(exit code 3)*" in out


def test_problems_are_reported(proj):
    out, problems = render("<!-- code: src/train.py:Ghost -->", proj)
    assert problems and "could not render" in out


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_diff_marker(proj):
    git = lambda *a: subprocess.run(["git", *a], cwd=proj, capture_output=True, check=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    f = proj / "src" / "train.py"
    f.write_text(f.read_text().replace("for _ in range(self.epochs):", "for epoch in range(self.epochs):"))
    (proj / "src" / "new.py").write_text("x = 1\n")
    out, problems = render("<!-- diff: src/train.py -->\n<!-- diff: src/new.py -->\n<!-- diff: src/preprocess.py -->", proj)
    assert problems == []
    assert "-        for _ in range(self.epochs):\n+        for epoch in range(self.epochs):" in out
    assert "*New file:*" in out and "x = 1" in out
    assert "*(no changes since the last commit)*" in out
