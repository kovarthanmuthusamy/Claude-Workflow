"""archcheck: compare architecture.yaml with the code and report drift.

Errors (exit code 1): invalid spec, missing built nodes, signature drift.
Warnings: unspecced public functions imported elsewhere, over the node cap,
missing helpers or listed methods.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import schema
from .schema import Issue

SKIP_DIRS = {"venv", "env", "__pycache__", "node_modules", "site-packages", "build", "dist"}


# ---------------------------------------------------------------- code index

@dataclass
class CodeIndex:
    """Definitions found in one Python file."""
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    all_defs: set[str] = field(default_factory=set)  # any def/class name at any depth

    def methods(self, cls: str) -> dict[str, ast.FunctionDef]:
        node = self.classes.get(cls)
        if node is None:
            return {}
        return {b.name: b for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def public_names(self) -> set[str]:
        return {n for n in (*self.functions, *self.classes) if not n.startswith("_")}


def index_file(tree: ast.Module) -> CodeIndex:
    idx = CodeIndex()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            idx.functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            idx.classes[node.name] = node
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            idx.all_defs.add(node.name)
    return idx


def find_def(idx: CodeIndex, node: dict) -> ast.AST | None:
    nid, kind = node["id"], node.get("kind")
    if kind == "function":
        return idx.functions.get(nid)
    if kind == "class":
        return idx.classes.get(nid)
    if kind == "method":
        cls, _, meth = nid.partition(".")
        return idx.methods(cls).get(meth)
    return None


# ---------------------------------------------------------------- signatures

@dataclass
class Sig:
    name: str
    params: list[tuple[str, str | None]]  # (name with * or ** prefix, annotation)
    returns: str | None

    def render(self) -> str:
        ps = ", ".join(f"{n}: {a}" if a else n for n, a in self.params)
        return f"{self.name}({ps})" + (f" -> {self.returns}" if self.returns else "")


def _ann(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:  # string annotation: "pd.DataFrame" == pd.DataFrame
            return ast.unparse(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return node.value
    return ast.unparse(node)


def sig_of(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str | None = None) -> Sig:
    a = fn.args
    params = [(p.arg, _ann(p.annotation)) for p in (*a.posonlyargs, *a.args)]
    if a.vararg:
        params.append(("*" + a.vararg.arg, _ann(a.vararg.annotation)))
    params += [(p.arg, _ann(p.annotation)) for p in a.kwonlyargs]
    if a.kwarg:
        params.append(("**" + a.kwarg.arg, _ann(a.kwarg.annotation)))
    return Sig(name or fn.name, params, _ann(fn.returns))


def parse_spec_sig(text: str) -> Sig:
    """Parse 'name(a: int, b) -> T' by treating it as a def header."""
    tree = ast.parse(f"def {text.strip()}:\n    pass")
    return sig_of(tree.body[0])


def code_sig(defn: ast.AST, kind: str) -> Sig:
    if kind == "class":  # a class signature describes its constructor
        init = next((b for b in defn.body if isinstance(b, ast.FunctionDef) and b.name == "__init__"), None)
        sig = sig_of(init, defn.name) if init else Sig(defn.name, [], None)
        sig.returns = None
        return sig
    return sig_of(defn)


def sig_drift(spec: Sig, code: Sig, kind: str) -> str | None:
    """Return a description of the mismatch, or None if they agree.

    Names must match exactly. Annotations are compared only where the spec
    gives one, so a terse spec does not drift against a typed implementation.
    """
    code_params = list(code.params)
    if kind in ("method", "class") and code_params and code_params[0][0] in ("self", "cls"):
        if not spec.params or spec.params[0][0] != code_params[0][0]:
            code_params = code_params[1:]

    problems = []
    if spec.name != code.name:
        problems.append(f"name '{spec.name}' vs '{code.name}'")
    spec_names, code_names = [n for n, _ in spec.params], [n for n, _ in code_params]
    if spec_names != code_names:
        problems.append(f"parameters ({', '.join(spec_names)}) vs ({', '.join(code_names)})")
    else:
        for (n, sa), (_, ca) in zip(spec.params, code_params):
            if sa is not None and sa != ca:
                problems.append(f"'{n}' annotated {sa} vs {ca or 'none'}")
    if spec.returns is not None and spec.returns != code.returns:
        problems.append(f"returns {spec.returns} vs {code.returns or 'none'}")
    if not problems:
        return None
    shown = Sig(code.name, code_params, code.returns).render()
    return "signature drift: " + "; ".join(problems) + f" (code: {shown})"


# ---------------------------------------------------------------- imports

def project_files(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel[:-1]):
            continue
        out.append(p)
    return out


def module_parts(path: Path, root: Path) -> list[str]:
    parts = list(path.relative_to(root).with_suffix("").parts)
    return parts[:-1] if parts and parts[-1] == "__init__" else parts


def _matches(dotted: str, target: str) -> bool:
    """'preprocess' or 'src.preprocess' both refer to module 'src.preprocess'."""
    return dotted == target or target.endswith("." + dotted)


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def imported_names(target_mod: str, tree: ast.Module, importer_parts: list[str], is_pkg: bool) -> set[str]:
    """Names from module `target_mod` that one file uses ('*' for star imports)."""
    names: set[str] = set()
    aliases: set[str] = set()  # local names bound to the target module itself
    package = importer_parts if is_pkg else importer_parts[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                mod = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                mod = node.module or ""
            for a in node.names:
                if mod and _matches(mod, target_mod):
                    names.add(a.name)
                elif _matches(f"{mod}.{a.name}".lstrip("."), target_mod):
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if _matches(a.name, target_mod):
                    aliases.add(a.asname or a.name)

    if aliases:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _dotted(node.value) in aliases:
                names.add(node.attr)
    return names


# ---------------------------------------------------------------- checker

def check(spec_path: str | Path, root: str | Path | None = None) -> list[Issue]:
    spec_path = Path(spec_path)
    # Resolve once so short (8.3) and long Windows paths compare equal.
    root = (Path(root) if root else spec_path.parent).resolve()
    try:
        spec = schema.load(spec_path)
    except Exception as e:  # noqa: BLE001 - any parse failure is a spec error
        return [Issue("error", "spec", f"cannot read {spec_path}: {e}")]

    issues = schema.validate(spec)
    if any(i.level == "error" and i.where == "spec" for i in issues):
        return issues

    trees: dict[Path, ast.Module] = {}
    for p in project_files(root):
        try:
            trees[p.resolve()] = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, UnicodeDecodeError):
            pass  # reported below only if it is a spec'd script

    for script in spec.get("scripts") or []:
        if not isinstance(script, dict) or not schema._is_str(script.get("file")):
            continue
        sid, nodes = script.get("id"), [n for n in script.get("nodes") or [] if isinstance(n, dict) and "id" in n]
        path = (root / script["file"]).resolve()
        needs_code = [n for n in nodes if n.get("status") in ("built", "changed") and n.get("kind") != "stage"]

        if not path.is_file():
            if needs_code:
                issues.append(Issue("error", sid, f"file {script['file']} not found"))
            continue
        tree = trees.get(path)
        if tree is None:
            issues.append(Issue("error", sid, f"{script['file']} has a syntax error"))
            continue
        idx = index_file(tree)

        for node in needs_code:
            where = f"{sid}.{node['id']}"
            defn = find_def(idx, node)
            if defn is None:
                issues.append(Issue("error", where, f"{node.get('kind')} not found in {script['file']}"))
                continue
            for h in node.get("helpers") or []:
                if h not in idx.all_defs:
                    issues.append(Issue("warning", where, f"helper '{h}' not found in {script['file']}"))
            if node.get("kind") == "class":
                have = idx.methods(node["id"])
                for m in node.get("methods") or []:
                    if m not in have:
                        issues.append(Issue("warning", where, f"listed method '{m}' not found"))
            if node.get("status") == "built" and schema._is_str(node.get("signature")):
                try:
                    spec_sig = parse_spec_sig(node["signature"])
                except SyntaxError:
                    issues.append(Issue("error", where, "signature is not a valid Python def header"))
                    continue
                expected = node["id"].rpartition(".")[2]
                drift = sig_drift(spec_sig, code_sig(defn, node["kind"]), node["kind"])
                if spec_sig.name != expected and drift is None:
                    drift = f"signature name '{spec_sig.name}' does not match node id '{expected}'"
                if drift:
                    issues.append(Issue("error", where, drift))

        # Public names used by other files but missing from the spec.
        specced = {n["id"].partition(".")[0] for n in nodes}
        helpers = {h for n in nodes for h in n.get("helpers") or []}
        target_mod = ".".join(module_parts(path, root))
        users: dict[str, list[str]] = {}
        for other, otree in trees.items():
            if other == path:
                continue
            used = imported_names(target_mod, otree, module_parts(other, root), other.name == "__init__.py")
            if "*" in used:
                used = idx.public_names()
            for name in used & idx.public_names():
                users.setdefault(name, []).append(other.relative_to(root).as_posix())
        for name in sorted(set(users) - specced):
            by = ", ".join(sorted(users[name]))
            hint = "listed as a helper, but " if name in helpers else ""
            issues.append(Issue("warning", f"{sid}.{name}", f"{hint}imported by {by} and has no node (node rule)"))

    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archcheck", description="Compare architecture.yaml with the code.")
    ap.add_argument("spec", nargs="?", default="architecture.yaml", help="path to the spec (default: ./architecture.yaml)")
    ap.add_argument("--root", help="project root (default: the spec's folder)")
    args = ap.parse_args(argv)

    if not Path(args.spec).is_file():
        print(f"archcheck: {args.spec} not found", file=sys.stderr)
        return 2
    issues = check(args.spec, args.root)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    for i in errors + warnings:
        print(i)
    if issues:
        print(f"archcheck: {len(errors)} error(s), {len(warnings)} warning(s)")
    else:
        print("archcheck: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
