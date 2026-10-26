"""Download the viewer's browser libraries into archspec/static/vendor/.

Dev-only. The downloaded files are committed, so users never run this and
nothing needs Node.js. To upgrade a library, change its version here and rerun.
"""

import re
import urllib.request
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "archspec" / "static" / "vendor"

REACT = "18.3.1"
XYFLOW = "12.3.6"
HTM = "3.1.1"

FILES = {
    "react.production.min.js": f"https://cdn.jsdelivr.net/npm/react@{REACT}/umd/react.production.min.js",
    "react-dom.production.min.js": f"https://cdn.jsdelivr.net/npm/react-dom@{REACT}/umd/react-dom.production.min.js",
    "htm.mjs": f"https://cdn.jsdelivr.net/npm/htm@{HTM}/dist/htm.module.js",
    "xyflow.css": f"https://cdn.jsdelivr.net/npm/@xyflow/react@{XYFLOW}/dist/style.css",
    # esm.sh bundles React Flow's own dependencies; React stays external and is
    # supplied by the shim files next to it (see index.html import map).
    "xyflow-react.mjs": f"https://esm.sh/@xyflow/react@{XYFLOW}?bundle&external=react,react-dom&target=es2020",
}


def get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8")


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        text = get(url)
        # esm.sh answers with a one-line stub that re-exports the real bundle.
        stub = re.fullmatch(r'\s*(?:/\*.*?\*/\s*)?export \* from "(/[^"]+)";\s*', text, re.S)
        if stub:
            text = get("https://esm.sh" + stub.group(1))
        (VENDOR / name).write_bytes(text.encode("utf-8"))
        print(f"{name:32} {len(text):>9,} bytes")


if __name__ == "__main__":
    main()
