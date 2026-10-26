"""archview init: set up a project for the workflow.

Adds architecture.yaml and the CLAUDE.md rules (the output style and skills come from the
Claude Code plugin). Safe to rerun: an existing spec is never overwritten, and the rules
block in CLAUDE.md (between the markers) is replaced in place.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

RULES = Path(__file__).resolve().parent / "templates" / "claude_rules.md"
START = "<!-- archspec:start (managed by `archview init`; rerun it to update this section) -->"
END = "<!-- archspec:end -->"
BLOCK_RE = re.compile(r"<!-- archspec:start\b.*?-->.*?<!-- archspec:end -->", re.S)

STARTER = """\
version: 1
project: {project}

# Structure contract for this project; see "Architecture spec" in CLAUDE.md.
# Open the diagram:  python -m archspec view
# Check against code: python -m archspec check
scripts: []

edges: []
"""


def rules_block() -> str:
    return f"{START}\n{RULES.read_text(encoding='utf-8').strip()}\n{END}"


def init(root: Path, project: str | None = None) -> list[str]:
    """Set up `root`; returns one line per action taken."""
    done = []
    spec = root / "architecture.yaml"
    if spec.exists():
        done.append("kept existing architecture.yaml")
    else:
        spec.write_bytes(STARTER.format(project=project or root.resolve().name).encode("utf-8"))
        done.append("created architecture.yaml")

    claude = root / "CLAUDE.md"
    block = rules_block()
    if not claude.exists():
        claude.write_bytes((block + "\n").encode("utf-8"))
        done.append("created CLAUDE.md with the architecture rules")
    else:
        text = claude.read_text(encoding="utf-8")
        if BLOCK_RE.search(text):
            new = BLOCK_RE.sub(lambda _: block, text, count=1)
            done.append("updated the architecture rules in CLAUDE.md" if new != text else "CLAUDE.md rules already up to date")
        else:
            new = text.rstrip() + "\n\n" + block + "\n"
            done.append("added the architecture rules to CLAUDE.md")
        if new != text:
            claude.write_bytes(new.encode("utf-8"))
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archview init", description="Add architecture.yaml and CLAUDE.md rules to a project.")
    ap.add_argument("folder", nargs="?", default=".", help="project root (default: current folder)")
    ap.add_argument("--project", help="project name (default: folder name)")
    args = ap.parse_args(argv)

    root = Path(args.folder)
    if not root.is_dir():
        print(f"archview init: {root} is not a folder", file=sys.stderr)
        return 2
    for line in init(root, args.project):
        print(f"  {line}")
    plugin = bool(os.environ.get("ARCHSPEC_PLUGIN"))
    view, walk = ("/archspec:view", "/archspec:walkthrough") if plugin else ("python -m archspec view", "/archspec:walkthrough (plugin)")
    print("Next:\n"
          "  1. In Claude Code, run  /output-style  and pick 'archspec:Explain as you go'\n"
          f"  2. Ask Claude to plan a feature; review it with  {view}\n"
          f"  3. After a change, run  {walk}  for a worked example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
