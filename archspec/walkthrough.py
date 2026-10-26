"""Fill a walkthrough document with real code, diffs and program output.

Claude writes the explanation and places markers; this renderer fills them, so
snippets and numbers in the document always come from the actual project:

    <!-- code: src/train.py:Trainer.fit -->   source of a function/class/method (or a whole file)
    <!-- diff: src/train.py -->               changes since the last commit (or the whole new file)
    <!-- run: python examples/demo.py -->     the command's real output

Each marker is followed by its filled block and a closing <!-- /code --> (etc.),
so rendering again replaces the old content instead of duplicating it.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

MARKER = re.compile(r"<!-- (code|diff|run): (.+?) -->(?:\n.*?<!-- /\1 -->)?", re.S)
MAX_LINES = 80
LANG = {".py": "python", ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".md": "markdown", ".toml": "toml"}


def _fence(body: str, lang: str = "") -> str:
    body = body.rstrip("\n")
    lines = body.splitlines()
    if len(lines) > MAX_LINES:
        body = "\n".join(lines[:MAX_LINES] + [f"... ({len(lines) - MAX_LINES} more lines)"])
    return f"```{lang}\n{body}\n```"


def code(root: Path, target: str) -> str:
    path, _, qual = target.partition(":")
    file = root / path.strip()
    text = file.read_text(encoding="utf-8")
    lang = LANG.get(file.suffix, "")
    if not qual:
        return _fence(text, lang)
    node: ast.AST = ast.parse(text)
    for part in qual.strip().split("."):
        node = next((n for n in getattr(node, "body", [])
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part), None)
        if node is None:
            raise LookupError(f"{qual} not found in {path}")
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = text.splitlines()[start - 1:node.end_lineno]
    indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return _fence("\n".join(l[indent:] for l in lines), lang)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")


def diff(root: Path, target: str) -> str:
    path = target.strip()
    if _git(root, "ls-files", "--error-unmatch", path).returncode != 0:
        if (root / path).is_file():
            return "*New file:*\n\n" + code(root, path)
        return "*(file not found)*"
    out = _git(root, "diff", "HEAD", "--", path).stdout
    return _fence(out, "diff") if out.strip() else "*(no changes since the last commit)*"


def run(root: Path, command: str) -> str:
    try:
        p = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return "*(command timed out after 300 s)*"
    out = (p.stdout + (("\n" + p.stderr) if p.stderr.strip() else "")).strip() or "(no output)"
    note = f"\n\n*(exit code {p.returncode})*" if p.returncode else ""
    return _fence(out, "text") + note


FILLERS = {"code": code, "diff": diff, "run": run}


def render(text: str, root: Path) -> tuple[str, list[str]]:
    """Return the filled document and a list of problems (markers that failed)."""
    problems: list[str] = []

    def fill(m: re.Match) -> str:
        kind, arg = m.group(1), m.group(2)
        try:
            body = FILLERS[kind](root, arg)
        except Exception as e:  # noqa: BLE001 - show the problem in the document
            problems.append(f"{kind}: {arg} -> {e}")
            body = f"*(could not render: {e})*"
        return f"<!-- {kind}: {arg} -->\n{body}\n<!-- /{kind} -->"

    return MARKER.sub(fill, text), problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archspec walkthrough", description="Fill code/diff/run markers in a walkthrough.")
    ap.add_argument("file", help="the walkthrough markdown file")
    ap.add_argument("--root", default=".", help="project root (default: current folder)")
    args = ap.parse_args(argv)

    file, root = Path(args.file), Path(args.root).resolve()
    text, problems = render(file.read_text(encoding="utf-8"), root)
    file.write_bytes(text.encode("utf-8"))
    for p in problems:
        print(f"  problem: {p}", file=sys.stderr)
    print(f"rendered {file} ({len(MARKER.findall(text))} markers, {len(problems)} problems)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
