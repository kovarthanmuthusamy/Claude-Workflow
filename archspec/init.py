"""archview init: set up a project for the workflow.

Adds architecture.yaml and the CLAUDE.md rules, and (when run from the Claude Code plugin)
turns on the plugin's output style for this project. Safe to rerun: an existing spec is
never overwritten, and the rules block in CLAUDE.md (between the markers) is replaced in
place.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

RULES = Path(__file__).resolve().parent / "templates" / "claude_rules.md"
START = "<!-- archspec:start (managed by `archview init`; rerun it to update this section) -->"
END = "<!-- archspec:end -->"
BLOCK_RE = re.compile(r"<!-- archspec:start\b.*?-->.*?<!-- archspec:end -->", re.S)
STYLE = "archspec:Explain as you go"  # plugin output styles are namespaced by plugin name

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


def set_style(root: Path) -> str:
    """Turn on the plan/recap output style in the project's personal Claude settings."""
    path = root / ".claude" / "settings.local.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return f"left {path.as_posix()} alone (not valid JSON); pick '{STYLE}' in /output-style"
    current = settings.get("outputStyle")
    if current == STYLE:
        return f"output style '{STYLE}' already on"
    if current and current.lower() != "default":
        return f"kept your output style '{current}'; to switch, pick '{STYLE}' in /output-style"
    settings["outputStyle"] = STYLE
    path.parent.mkdir(exist_ok=True)
    path.write_bytes((json.dumps(settings, indent=2) + "\n").encode("utf-8"))
    return f"turned on the '{STYLE}' output style (in .claude/settings.local.json)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archview init", description="Add architecture.yaml and CLAUDE.md rules to a project.")
    ap.add_argument("folder", nargs="?", default=".", help="project root (default: current folder)")
    ap.add_argument("--project", help="project name (default: folder name)")
    args = ap.parse_args(argv)

    root = Path(args.folder)
    if not root.is_dir():
        print(f"archview init: {root} is not a folder", file=sys.stderr)
        return 2
    plugin = bool(os.environ.get("ARCHSPEC_PLUGIN"))
    done = init(root, args.project)
    if plugin:  # the style lives in the plugin, so only set it when the plugin is installed
        done.append(set_style(root))
    for line in done:
        print(f"  {line}")
    if plugin:
        print("Next: ask Claude for a feature. It plans first; review the plan in the diagram\n"
              "(/archspec:view), say 'go ahead', and run /archspec:walkthrough to understand a change.")
    else:
        print("Next: open the diagram with  python -m archspec view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
