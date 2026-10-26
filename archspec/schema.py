"""Spec format for architecture.yaml: loading and validation.

The spec is kept as plain dicts/lists (ruamel round-trip types) rather than
model objects, so unknown fields survive a load/save cycle untouched.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

SPEC_VERSION = 1
KINDS = {"function", "class", "method", "stage"}
STATUSES = {"planned", "built", "changed"}
SOFT_NODE_CAP = 6

# Kinds whose signature must be filled in once the node is built.
SIGNATURE_REQUIRED = {"function", "method"}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    where: str  # e.g. "preprocess.load_raw" or "edges[2]"
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.where}: {self.message}"


def yaml_rt() -> YAML:
    """Round-trip YAML: keeps key order, comments and unknown fields."""
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


def load(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml_rt().load(f)


def load_text(text: str) -> Any:
    return yaml_rt().load(text)


def dump(spec: Any, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml_rt().dump(spec, f)


def dumps(spec: Any) -> str:
    buf = io.StringIO()
    yaml_rt().dump(spec, buf)
    return buf.getvalue()


def _item_key(x: Any) -> tuple | None:
    """Identity of a list item, so edits match the right existing entry."""
    if isinstance(x, dict):
        if "id" in x:
            return ("id", x["id"])
        if "from" in x and "to" in x:
            return ("edge", x["from"], x["to"])
    return None


def merge(old: Any, new: Any) -> Any:
    """Apply `new` (plain JSON from the viewer) onto `old` (round-trip YAML).

    Unchanged parts keep their original objects, so comments, key order and
    quoting survive. Keys missing from `new` are removed, new keys appended.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        for k in [k for k in old if k not in new]:
            del old[k]
        for k, v in new.items():
            old[k] = merge(old[k], v) if k in old else _fresh(v)
        return old
    if isinstance(old, list) and isinstance(new, list):
        pool: dict[tuple, Any] = {}
        for x in old:
            if (key := _item_key(x)) is not None:
                pool.setdefault(key, x)
        merged = []
        for x in new:
            key = _item_key(x)
            merged.append(merge(pool.pop(key), x) if key in pool else _fresh(x))
        old[:] = merged
        return old
    if isinstance(old, str) and isinstance(new, str):
        if old == new:
            return old
        if "\n" in new.strip():
            return block_text(new)
        return type(old)(new) if type(old) is not str else new  # keep the quoting style
    if isinstance(new, str) and "\n" in new.strip():
        return block_text(new)
    return old if type(old) is type(new) and old == new else new


def _fresh(value: Any) -> Any:
    """A value that is new to the file: format its multi-line text as blocks."""
    if isinstance(value, dict):
        return {k: _fresh(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fresh(v) for v in value]
    if isinstance(value, str) and "\n" in value.strip():
        return block_text(value)
    return value


def block_text(text: str) -> LiteralScalarString:
    """Multi-line text from the viewer, saved as a readable `|-` block."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return LiteralScalarString("\n".join(lines))


def iter_nodes(spec: Any) -> Iterator[tuple[dict, dict]]:
    """Yield (script, node) pairs."""
    for script in spec.get("scripts") or []:
        for node in script.get("nodes") or []:
            yield script, node


def node_ref(script: dict, node: dict) -> str:
    return f"{script.get('id')}.{node.get('id')}"


def node_refs(spec: Any) -> set[str]:
    return {node_ref(s, n) for s, n in iter_nodes(spec)}


def _is_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(_is_str(x) for x in v)


def validate(spec: Any) -> list[Issue]:
    """Structural checks that need only the spec, not the code."""
    issues: list[Issue] = []

    def err(where: str, msg: str) -> None:
        issues.append(Issue("error", where, msg))

    def warn(where: str, msg: str) -> None:
        issues.append(Issue("warning", where, msg))

    if not isinstance(spec, dict):
        return [Issue("error", "spec", "top level must be a mapping")]
    if spec.get("version") != SPEC_VERSION:
        err("spec", f"version must be {SPEC_VERSION}")
    if not _is_str(spec.get("project")):
        err("spec", "project name is missing")

    scripts = spec.get("scripts")
    if scripts is None:
        scripts = []  # a fresh project: nothing planned yet
    elif not isinstance(scripts, list):
        err("spec", "scripts must be a list")
        scripts = []

    seen_scripts: set[str] = set()
    for i, script in enumerate(scripts):
        if not isinstance(script, dict):
            err(f"scripts[{i}]", "must be a mapping")
            continue
        sid = script.get("id")
        where = sid if _is_str(sid) else f"scripts[{i}]"
        if not _is_str(sid):
            err(where, "id is missing")
        elif "." in sid:
            err(where, "script id must not contain '.'")
        elif sid in seen_scripts:
            err(where, "duplicate script id")
        seen_scripts.add(sid)
        if not _is_str(script.get("file")):
            err(where, "file is missing")

        nodes = script.get("nodes") or []
        if not isinstance(nodes, list):
            err(where, "nodes must be a list")
            continue
        if len(nodes) > SOFT_NODE_CAP:
            warn(where, f"{len(nodes)} nodes (soft cap is {SOFT_NODE_CAP}); move some to helpers")

        classes = {n.get("id") for n in nodes if isinstance(n, dict) and n.get("kind") == "class"}
        seen_nodes: set[str] = set()
        for j, node in enumerate(nodes):
            if not isinstance(node, dict):
                err(f"{where}.nodes[{j}]", "must be a mapping")
                continue
            nid = node.get("id")
            nwhere = f"{sid}.{nid}" if _is_str(nid) else f"{where}.nodes[{j}]"
            if not _is_str(nid):
                err(nwhere, "id is missing")
                continue
            if nid in seen_nodes:
                err(nwhere, "duplicate node id")
            seen_nodes.add(nid)

            kind, status = node.get("kind"), node.get("status")
            if kind not in KINDS:
                err(nwhere, f"kind must be one of {sorted(KINDS)}")
            if status not in STATUSES:
                err(nwhere, f"status must be one of {sorted(STATUSES)}")
            if not _is_str(node.get("purpose")):
                warn(nwhere, "purpose is empty")
            if "explain" in node and not isinstance(node["explain"], str):
                err(nwhere, "explain must be text")
            elif not _is_str(node.get("explain")):
                warn(nwhere, "explain is empty (2-4 plain sentences: in, what happens, out, why)")

            if kind == "method":
                cls, _, meth = nid.partition(".")
                if not meth or "." in meth:
                    err(nwhere, "method id must be 'Class.method'")
                elif cls not in classes:
                    err(nwhere, f"method's class '{cls}' has no class node in this script")
            elif "." in nid:
                err(nwhere, "only method ids may contain '.'")

            sig = node.get("signature")
            if sig is not None and not _is_str(sig):
                err(nwhere, "signature must be a string")
            if status in ("built", "changed") and kind in SIGNATURE_REQUIRED and not _is_str(sig):
                err(nwhere, f"signature is required once status is {status}")
            for field in ("helpers", "methods"):
                if field in node and not _is_str_list(node[field]):
                    err(nwhere, f"{field} must be a list of names")
            if "methods" in node and kind != "class":
                err(nwhere, "only class nodes may list methods")

    refs = node_refs(spec) if scripts else set()
    edges = spec.get("edges") or []
    if not isinstance(edges, list):
        err("edges", "must be a list")
        edges = []
    seen_edges: set[tuple[str, str]] = set()
    for k, edge in enumerate(edges):
        where = f"edges[{k}]"
        if not isinstance(edge, dict):
            err(where, "must be a mapping")
            continue
        src, dst = edge.get("from"), edge.get("to")
        where = f"edge {src} -> {dst}"
        for end, ref in (("from", src), ("to", dst)):
            if not _is_str(ref):
                err(where, f"'{end}' is missing")
            elif ref not in refs:
                err(where, f"'{end}' points to unknown node '{ref}'")
        if not _is_str(edge.get("data")):
            err(where, "data label is missing")
        if "shape" in edge and not _is_str(edge["shape"]):
            err(where, "shape must be a string")
        if src == dst and _is_str(src):
            err(where, "edge points to itself")
        if (src, dst) in seen_edges:
            warn(where, "duplicate edge")
        seen_edges.add((src, dst))

    return issues
