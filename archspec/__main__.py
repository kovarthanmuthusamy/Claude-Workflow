"""python -m archspec init | view | check  (works even when the scripts folder is not on PATH)."""

from __future__ import annotations

import sys

from . import check, init, server, walkthrough

COMMANDS = {"init": init.main, "view": server.main, "check": check.main, "walkthrough": walkthrough.main}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print("usage: python -m archspec {init|view|check|walkthrough} [options]\n"
              "  init         add architecture.yaml and the CLAUDE.md rules to this project\n"
              "  view         open the diagram in the browser\n"
              "  check        compare architecture.yaml with the code\n"
              "  walkthrough  fill code/diff/run markers in a walkthrough document", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
