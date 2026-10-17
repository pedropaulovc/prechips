"""Split prechips' large modules by symbol, re-runnably, from a committed spec.

Development tool only: the checker never imports it and it touches no network.

    uv run scripts/split_modules.py churn [--since DATE] [--by pr|commit] [--ref REF ...]
    uv run scripts/split_modules.py plan NAME
    uv run scripts/split_modules.py apply NAME
    uv run scripts/split_modules.py snapshot OUT [--against MANIFEST]

``churn`` measures which symbols of every spec'd module each merged PR (``--by pr``,
first-parent history) or each non-merge commit (``--by commit``) since ``--since`` and
each in-flight ``--ref`` touched, and how many pairs of changes would still share a file
after the split each spec variant describes. Changes rewriting more than half of a
module's symbols (formatting and rename sweeps) are counted apart.

``plan`` prints a split's files, the imports between them and every refusal, without
writing. ``apply`` performs it on the working tree: each selected symbol's exact source
text (with its leading comments and decorators) moves to its target, methods of a split
class move to a mixin the class then inherits, each file gets exactly the imports its
code names, and every importer, module-attribute use and ``monkeypatch.setattr`` in
``src/``, ``tests/`` and ``scripts/`` is rewritten to the new owner. It refuses, before
writing anything, a split it cannot prove keeps every name lookup the same: an import
cycle between the new files, a star import, module state written under ``global`` and
read from another file, a moved method using zero-argument ``super()``, ``__class__`` or
a name-mangled attribute, a symbol reading ``__file__`` moving to another directory,
a name bound twice landing in two files, a monkeypatched name looked up from more than
one file, and a plain ``import prechips.<module>`` it cannot rewrite.

``snapshot`` runs ``prechips check`` and ``prechips traveler`` on every example bundle,
records exit codes and output digests, and compares travelers byte for byte with each
bundle's ``expected/`` (and with an earlier snapshot given ``--against``).

The spec is ``scripts/split_modules.toml``; the design is docs/module-split.md.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import fnmatch
import hashlib
import itertools
import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SPEC = Path(__file__).with_suffix(".toml")
EXPAND_LINES = 300  # a class this long is analysed per method (and split into mixins)
SWEEP = 0.5  # a change touching more than this share of a module's symbols is a sweep
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# Module attributes naming the module object itself, which a kept module keeps.
IDENTITY = {"__name__", "__file__", "__doc__", "__spec__", "__package__", "__loader__"}
BUILTINS = set(dir(builtins)) | IDENTITY
REWRITE_ROOTS = ("src", "tests", "scripts")


class Refused(Exception):
    """The split cannot be proved to keep every name lookup unchanged."""


# --- symbols ---------------------------------------------------------------------------


@dataclass
class Unit:
    """A movable piece of a module.

    ``kind`` is ``def`` (a top-level def, class or assignment), ``head`` (an expanded
    class's line and the class-level statements before its first method), ``method``
    (each later member: a method, or a class attribute after the first method),
    ``trailer`` (a later top-level statement mutating a ``def``: ``X |= ...``,
    ``X.model_rebuild()``), ``import``, or ``module`` (any other top-level statement;
    imports and these never move)."""

    name: str
    kind: str
    start: int  # 1-based, including leading comments and decorators
    end: int  # 1-based, inclusive
    node: ast.AST = field(repr=False)
    cls: str | None = None

    @property
    def binds(self):
        """Every name the unit binds at module level (``A = B = 1``, ``A, B = ...``)."""
        if self.kind not in ("def", "head"):
            return set()
        if isinstance(self.node, ast.Assign):
            found = set()
            for target in self.node.targets:
                _targets(target, found)
            return found
        return {self.name}


def _bound_name(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.TypeAlias):
        return node.name.id
    if isinstance(node, ast.Assign):
        names = set()
        for target in node.targets:
            _targets(target, names)
        plain = all(isinstance(n, (ast.Name, ast.Tuple, ast.Starred)) for n in node.targets)
        if plain and names:
            first = node.targets[0]
            return first.id if isinstance(first, ast.Name) else sorted(names)[0]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _root(node):
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _trailer_root(node):
    if isinstance(node, ast.AugAssign):
        return _root(node.target)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return _root(node.value.func) if isinstance(node.value.func, ast.Attribute) else None
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        return _root(target) if isinstance(target, (ast.Attribute, ast.Subscript)) else None
    return None


def _is_import(node):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, (ast.Try, ast.If)):
        body = list(ast.walk(node))[1:]
        statements = [n for n in body if isinstance(n, ast.stmt)]
        return bool(statements) and all(
            isinstance(n, (ast.Import, ast.ImportFrom, ast.Pass)) for n in statements
        )
    return False


def _first_line(node, lines, floor):
    """The node's first line, extended up over its decorators and contiguous comments."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    while start - 1 > floor and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    return start


def units(source, expand=EXPAND_LINES, classes=()):
    """The module's units in source order; a class of ``expand`` lines or more, or one
    named in ``classes``, is a ``head`` followed by its ``method`` units."""
    tree = ast.parse(source)
    lines = source.splitlines()
    found = []
    defined = set()
    floor = 0
    for node in tree.body:
        name = _bound_name(node)
        if _is_import(node):
            found.append(Unit("<import>", "import", node.lineno, node.end_lineno, node))
            floor = node.end_lineno
            continue
        root = _trailer_root(node) if name is None else None
        if name is None and root not in defined:
            found.append(Unit("<module>", "module", node.lineno, node.end_lineno, node))
            floor = node.end_lineno
            continue
        start, end = _first_line(node, lines, floor), node.end_lineno
        floor = end
        if root is not None:
            found.append(Unit(root, "trailer", start, end, node))
            continue
        defined.add(name)
        for target in getattr(node, "targets", []):
            _targets(target, defined)  # A = B = ...: a trailer on B follows it too
        big = end - start + 1 >= expand or name in classes
        if not (isinstance(node, ast.ClassDef) and big):
            found.append(Unit(name, "def", start, end, node))
            continue
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        head_end = (_first_line(methods[0], lines, node.lineno) - 1) if methods else end
        found.append(Unit(name, "head", start, head_end, node))
        inner = head_end
        for member in [n for n in node.body if n.lineno > head_end]:
            first = _first_line(member, lines, inner)
            label = f"{name}.{_bound_name(member) or member.lineno}"
            found.append(Unit(label, "method", first, member.end_lineno, member, name))
            inner = member.end_lineno
    return found


# --- names -----------------------------------------------------------------------------


def _targets(node, out):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.Starred) and isinstance(n.value, ast.Name):
            out.add(n.value.id)


def _local_bindings(function):
    """Names a function (or lambda) binds locally, minus its ``global`` declarations."""
    bound, declared = set(), set()
    arguments = function.args
    for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
        bound.add(arg.arg)
    for arg in (arguments.vararg, arguments.kwarg):
        if arg:
            bound.add(arg.arg)
    body = function.body if isinstance(function.body, list) else [function.body]
    stack = list(body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
            continue
        if isinstance(n, ast.Lambda):
            continue
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # Its loop targets are its own scope's; only a walrus inside binds here.
            parts = [getattr(n, key) for key in ("elt", "key", "value") if hasattr(n, key)]
            for generator in n.generators:
                parts += [generator.iter, *generator.ifs]
            stack.extend(parts)
            continue
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            declared.update(n.names)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            bound.add(n.name)
        stack.extend(ast.iter_child_nodes(n))
    return bound - declared


def free_names(node):
    """Names ``node`` reads that no function scope inside it binds: its module-level
    dependencies. Annotations count, quoted ones included, because pydantic resolves
    them in the defining module."""
    out = set()

    def annotation(n, bound):
        if n is None:
            return
        for sub in ast.walk(n):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                try:
                    visit(ast.parse(sub.value, mode="eval").body, bound)
                except SyntaxError:
                    pass
        visit(n, bound)

    def visit(n, bound):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for d in getattr(n, "decorator_list", []):
                visit(d, bound)
            for d in [*n.args.defaults, *[d for d in n.args.kw_defaults if d]]:
                visit(d, bound)
            if not isinstance(n, ast.Lambda):
                arguments = [*n.args.posonlyargs, *n.args.args, *n.args.kwonlyargs]
                arguments += [a for a in (n.args.vararg, n.args.kwarg) if a]
                for arg in arguments:
                    annotation(arg.annotation, bound)
                annotation(n.returns, bound)
            inner = bound | _local_bindings(n)
            for statement in n.body if isinstance(n.body, list) else [n.body]:
                visit(statement, inner)
            return
        if isinstance(n, ast.ClassDef):
            for d in [*n.decorator_list, *n.bases, *[k.value for k in n.keywords]]:
                visit(d, bound)
            for statement in n.body:
                visit(statement, bound)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # Each iterable is read before its own targets bind (the first one in the
            # enclosing scope); conditions and the element see every target bound so far.
            inner = set(bound)
            for generator in n.generators:
                visit(generator.iter, inner)
                _targets(generator.target, inner)
                for condition in generator.ifs:
                    visit(condition, inner)
            for key in ("elt", "key", "value"):
                if hasattr(n, key):
                    visit(getattr(n, key), inner)
            return
        if isinstance(n, ast.AnnAssign):
            annotation(n.annotation, bound)
            for child in (n.target, n.value):
                if child is not None:
                    visit(child, bound)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound:
            out.add(n.id)
        for child in ast.iter_child_nodes(n):
            visit(child, bound)

    visit(node, set())
    return out


def _written_globals(node):
    return {name for n in ast.walk(node) if isinstance(n, ast.Global) for name in n.names}


def _self_calls(node):
    return {
        n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"
    }


def _mixin_hazards(node):
    found = []
    for name in _defined_names(node):
        if name.startswith("__") and not name.endswith("__"):
            found.append(f"name-mangled member {name}")
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "super":
            # super(Cls, self) would start its search at the mixin, inside Cls's MRO.
            found.append("explicit super(...)" if n.args else "zero-argument super()")
        elif isinstance(n, ast.Name) and n.id == "__class__":
            found.append("__class__")
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__") and not n.attr.endswith("__"):
            found.append(f"name-mangled {n.attr}")
    return found


def _class_reads(member, cls):
    """Class-body names a member's definition reads while the class body runs: its
    decorators, defaults and annotations, or an attribute's value. A mixin body lacks
    them."""
    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = member.args
        parts = [*member.decorator_list, *args.defaults, *filter(None, args.kw_defaults)]
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        parts += [a.annotation for a in every if a is not None and a.annotation is not None]
        parts += [member.returns] if member.returns else []
    elif isinstance(member, ast.ClassDef):
        parts = [*member.decorator_list, *member.bases, *member.keywords]
    else:
        parts = [member]
    read = {
        n.id
        for part in parts
        for n in ast.walk(part)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    bound = {name for n in cls.body if n is not member for name in _defined_names(n)}
    return read & bound


def _defined_names(node):
    """Names a class-body statement binds in the class scope, however nested in blocks
    (``if``, ``try``, ``with``, ``for``, ``match``…); function, class and lambda bodies
    and comprehensions have scopes of their own."""
    found, stack = [], [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append(n.name)  # its decorators run here, but only read
            continue
        if isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            continue
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            found += [(a.asname or a.name).split(".")[0] for a in n.names]
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            found.append(n.id)
        elif isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and n.name:
            found.append(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            found.append(n.rest)
        stack.extend(ast.iter_child_nodes(n))
    return found


def _import_bindings(node):
    """``{bound name: alias}`` for an import statement (or try/if block of imports)."""
    found = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Import):
            for alias in n.names:
                found[alias.asname or alias.name.split(".")[0]] = alias
        elif isinstance(n, ast.ImportFrom):
            for alias in n.names:
                if alias.name == "*":
                    raise Refused(f"star import from {n.module} at line {n.lineno}")
                found[alias.asname or alias.name] = alias
    return found


# --- spec ------------------------------------------------------------------------------


def load_spec():
    """Every ``[[module]]``; a ``[[variant]]`` is its ``base`` module with ``merge``
    folding target files into others and ``whole_classes`` dropping method patterns."""
    data = tomllib.loads(SPEC.read_text(encoding="utf-8"))
    modules = data["module"]
    for module in modules:
        module["_parses_source"] = data.get("parses_source", {})
    for variant in data.get("variant", []):
        base = next(m for m in modules if m["name"] == variant["base"])
        merge = variant.get("merge", {})
        targets = {}
        for target, patterns in base["targets"].items():
            if variant.get("whole_classes"):
                patterns = [p for p in patterns if "." not in p]
            into = merge.get(target, target)
            if into == base["rest"]:
                continue
            targets.setdefault(into, []).extend(patterns)
        modules.append({**base, "variant": variant["name"], "targets": targets})
    return modules


def module_spec(key, variant=None):
    for module in load_spec():
        if key == module["name"] and module.get("variant") == variant:
            return module
    raise SystemExit(f"no module {key!r} (variant {variant!r}) in {SPEC.name}")


def dotted(module, path):
    """The import name of ``path``: under ``src/`` for ``style = "package"``, under the
    module's ``root`` directory (on ``sys.path`` inside freecadcmd) for ``"engine"``."""
    base = ROOT / module.get("root", "src")
    parts = list((ROOT / path).relative_to(base).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def assign(module, source_units):
    """``[(unit, target path)]``: patterns choose a ``def`` or ``head`` target (else
    ``rest``) and a ``method`` target (else its class's); trailers follow their name;
    imports and other module statements stay in ``rest``. A name new since HEAD that no
    pattern names follows the unit before it (``churn`` on an in-flight branch)."""
    targets = module["targets"]
    known = module.get("_known")

    def match(name):
        # A method ("Class.method") matches only a pattern naming a class, and back.
        for target, patterns in targets.items():
            for pattern in patterns:
                if ("." in pattern) == ("." in name) and fnmatch.fnmatchcase(name, pattern):
                    return target
        return None

    placed = {}
    result = []
    previous = module["rest"]
    for unit in source_units:
        if unit.kind in ("import", "module"):
            target = module["rest"]
        elif unit.kind == "trailer":
            target = placed.get(unit.name, module["rest"])
        elif unit.kind == "method":
            target = match(unit.name) or placed[unit.cls]
        else:
            target = match(unit.name)
            if target is None:
                new = known is not None and unit.name not in known
                target = previous if new else module["rest"]
            for name in unit.binds or [unit.name]:
                placed[name] = target
        if unit.kind != "import" and unit.kind != "module":
            previous = target
        result.append((unit, target))
    return result


# --- plan ------------------------------------------------------------------------------


@dataclass
class Plan:
    module: dict
    source: str
    placed: list  # [(Unit, target)]
    provider: dict  # name -> target path, or ("import", Unit)
    needs: dict  # target -> {name}
    edges: dict  # target -> {target: {name}}
    mixins: dict  # (class, target) -> mixin class name
    refusals: list
    coupling: dict  # "names"/"self_calls" -> cross-file reference count

    def files(self):
        seen = []
        for _, target in self.placed:
            if target not in seen:
                seen.append(target)
        return seen


def _mixin_name(cls, target):
    stem = Path(target).stem.replace("job_", "")
    return cls + "".join(part.title() for part in stem.split("_"))


def _cycles(edges, nodes):
    index, low, stack, on, found = {}, {}, [], set(), []

    def connect(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in edges.get(v, {}):
            if w not in index:
                connect(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    sys.setrecursionlimit(10000)
    for v in nodes:
        if v not in index:
            connect(v)
    return found


def make_plan(module):
    path = ROOT / module["source"]
    source = path.read_text(encoding="utf-8")
    classes = set(module.get("classes", ()))
    placed = assign(module, units(source, classes=classes))
    refusals = []
    provider = {}
    for unit, target in placed:
        if unit.kind == "import":
            for name in _import_bindings(unit.node):
                provider[name] = ("import", unit)
        elif unit.kind in ("def", "head"):
            for name in unit.binds:
                provider[name] = target
    bound_in = defaultdict(set)
    for unit, target in placed:
        if unit.kind == "def":
            for name in unit.binds:
                bound_in[name].add(target)
    for name, files in bound_in.items():
        if len(files) > 1:
            refusals.append(f"{name} is bound more than once, across {sorted(files)}")
    for unit, target in placed:
        # Each file has its own __file__, __name__, __spec__, __package__ and __doc__.
        located = set(IDENTITY)
        located &= _unit_free(unit)
        if located and target != module["source"] and unit.kind != "import":
            refusals.append(f"{unit.name} reads {sorted(located)}, which differ in {target}")
    placed_at = {n: t for u, t in placed if u.kind in ("def", "head") for n in u.binds}
    for unit, target in placed:
        if unit.kind != "module":
            continue
        rebound = _module_bindings(ast.Module(body=[unit.node], type_ignores=[]))
        for name in sorted(rebound):
            if placed_at.get(name, target) != target:
                refusals.append(
                    f"line {unit.start}: {name} is rebound at module level outside its "
                    f"definition, which moves to {placed_at[name]}"
                )
    mixins = {}
    for unit, target in placed:
        if unit.kind != "method":
            continue
        heads = {u.name: u for u, _ in placed if u.kind == "head"}
        head_target = dict((u.name, t) for u, t in placed if u.kind == "head")[unit.cls]
        if target != head_target:
            mixins[(unit.cls, target)] = _mixin_name(unit.cls, target)
            for hazard in _mixin_hazards(unit.node):
                refusals.append(f"{unit.name} -> {target}: {hazard}")
            for name in sorted(_class_reads(unit.node, heads[unit.cls].node)):
                refusals.append(
                    f"{unit.name} -> {target}: its definition reads class-body name {name}, "
                    "which the mixin does not bind"
                )
    needs = defaultdict(set)
    uses = defaultdict(set)  # name -> {target reading it}
    writes = defaultdict(set)
    for unit, target in placed:
        if unit.kind == "import":
            continue
        names = _unit_free(unit)
        for name in names:
            if name in provider and provider[name] != target:
                needs[target].add(name)
            if name in provider:
                uses[name].add(target)
        for name in _written_globals(unit.node):
            writes[name].add(target)
    for (cls, target), mixin in mixins.items():
        head_target = provider[cls]
        needs[head_target].add(mixin)
        provider[mixin] = target
    edges = defaultdict(lambda: defaultdict(set))
    for target, names in needs.items():
        for name in names:
            owner = provider[name]
            if not isinstance(owner, tuple):
                edges[target][owner].add(name)
    for name, written in writes.items():
        files = written | uses[name] | ({provider[name]} if name in provider else set())
        files = {f for f in files if not isinstance(f, tuple)}
        if len(files) > 1:
            refusals.append(f"module state {name} (global) is written and read in {sorted(files)}")
    files = [t for t in dict.fromkeys(t for _, t in placed)]
    for cycle in _cycles(edges, files):
        detail = "; ".join(
            f"{Path(a).name}->{Path(b).name}: {', '.join(sorted(edges[a][b])[:6])}"
            for a in cycle
            for b in cycle
            if b in edges.get(a, {})
        )
        refusals.append(f"import cycle {[Path(c).name for c in cycle]}: {detail}")
    entry = module.get("entry")
    for target in files:
        if entry and target != entry and entry in edges.get(target, {}):
            refusals.append(f"{target} imports the entry script {entry}")
    for target in files:
        exists = (ROOT / target).exists()
        if exists and target != module["source"]:
            refusals.append(f"target {target} already exists")
    coupling = {"names": 0, "self_calls": 0}
    method_target = {u.name.split(".", 1)[1]: t for u, t in placed if u.kind == "method"}
    for unit, target in placed:
        if unit.kind == "import":
            continue
        for name in _unit_free(unit):
            owner = provider.get(name)
            if owner is not None and not isinstance(owner, tuple) and owner != target:
                coupling["names"] += 1
        if unit.kind == "method":
            for call in _self_calls(unit.node):
                if method_target.get(call, target) != target:
                    coupling["self_calls"] += 1
    return Plan(module, source, placed, provider, needs, edges, mixins, refusals, coupling)


def _unit_free(unit):
    return _head_free(unit.node) if unit.kind == "head" else free_names(unit.node)


def _head_free(node):
    """Free names of a class's header: decorators, bases, keywords, class-level statements."""
    out = set()
    for d in [*node.decorator_list, *node.bases, *[k.value for k in node.keywords]]:
        out |= free_names(d)
    for statement in node.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out |= free_names(statement)
    return out


def show_plan(plan):
    lines_by = defaultdict(int)
    units_by = defaultdict(int)
    for unit, target in plan.placed:
        if unit.kind in ("import",):
            continue
        lines_by[target] += unit.end - unit.start + 1
        units_by[target] += 1
    for target in plan.files():
        imports = {Path(t).name: len(n) for t, n in sorted(plan.edges.get(target, {}).items())}
        print(f"{target:52s} {lines_by[target]:6d} lines {units_by[target]:4d} units  <- {imports}")
    for (_, target), mixin in sorted(plan.mixins.items()):
        print(f"  mixin {mixin} in {target}")
    print(
        f"cross-file name references {plan.coupling['names']}, "
        f"cross-mixin self calls {plan.coupling['self_calls']}"
    )
    for refusal in plan.refusals:
        print(f"REFUSED: {refusal}")


def plan_command(args):
    plan = make_plan(module_spec(args.name, args.variant))
    show_plan(plan)
    raise SystemExit(2 if plan.refusals else 0)


# --- apply -----------------------------------------------------------------------------


def _depth(path):
    return len((ROOT / path).relative_to(SRC).parent.parts)


def _lines_for(plan, target):
    """The source's lines with each relative import's dots moved by the change in package
    depth from the source to ``target`` (``from . import trig`` in ``prechips/sheet.py``
    is ``from .. import trig`` in ``prechips/sheet/holding.py``)."""
    lines = plan.source.splitlines()
    delta = _depth(target) - _depth(plan.module["source"])
    if not delta:
        return lines, 0
    lines = list(lines)
    for node in ast.walk(ast.parse(plan.source)):
        if isinstance(node, ast.ImportFrom) and node.level:
            line = lines[node.lineno - 1]
            at = line.index("from", node.col_offset) + len("from ")
            if line[at : at + node.level] != "." * node.level:
                raise Refused(f"line {node.lineno}: relative import spelled across lines")
            lines[node.lineno - 1] = (
                line[:at] + "." * (node.level + delta) + line[at + node.level :]
            )
    return lines, delta


def _segment(lines, unit):
    return "\n".join(lines[unit.start - 1 : unit.end])


def _reduced_import(source_lines, unit, wanted, delta=0):
    """The import statement ``unit`` cut down to the names in ``wanted`` (a try/if block
    of imports verbatim), or ``None`` when it binds none of them."""
    node = unit.node
    if isinstance(node, ast.ImportFrom) and node.module == "__future__":
        return _segment(source_lines, unit)
    bound = _import_bindings(node)
    if not (set(bound) & wanted):
        return None
    if not isinstance(node, (ast.Import, ast.ImportFrom)):
        return _segment(source_lines, unit)
    tail = ""
    text = _segment(source_lines, unit)
    comment = re.search(r"#.*$", text.splitlines()[-1]) if "\n" not in text else None
    if comment:
        tail = "  " + comment.group(0)
    aliases = [a for name, a in bound.items() if name in wanted]
    spelled = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in aliases)
    if isinstance(node, ast.Import):
        return f"import {spelled}{tail}"
    level = node.level + delta if node.level else 0
    return f"from {'.' * level}{node.module or ''} import {spelled}{tail}"


def _render(plan, target, header_lines):
    """The new file ``target``: docstring, imports, then its units in source order with
    each mixin class holding its moved methods."""
    module = plan.module
    lines, delta = _lines_for(plan, target)
    wanted = plan.needs.get(target, set())
    out = list(header_lines)
    for unit, _ in plan.placed:
        if unit.kind == "import":
            reduced = _reduced_import(lines, unit, wanted, delta)
            if reduced:
                out.append(reduced.replace("  # noqa: E402", ""))
    by_owner = defaultdict(set)
    for name in wanted:
        owner = plan.provider[name]
        if not isinstance(owner, tuple):
            by_owner[owner].add(name)
    for owner, names in sorted(by_owner.items()):
        out.append(_intra(module, owner, names))
    body = []
    mixin_bodies = defaultdict(list)
    for unit, owner in plan.placed:
        if owner != target or unit.kind in ("import",):
            continue
        if unit.kind == "method" and (unit.cls, target) in plan.mixins:
            mixin_bodies[(unit.cls, target)].append(_segment(lines, unit))
            continue
        text = _segment(lines, unit)
        if unit.kind == "head":
            text = _with_mixins(plan, unit, text)
        body.append((unit, text))
    text = "\n".join(out) + "\n\n\n"
    previous = None
    for unit, chunk in body:
        if previous is not None:
            text += "\n" if previous.kind == "method" and unit.kind == "method" else "\n\n\n"
        text += chunk + "\n"
        previous = unit
    for (cls, owner), methods in mixin_bodies.items():
        mixin = plan.mixins[(cls, owner)]
        text += f"\n\nclass {mixin}:\n"
        text += f'    """{cls} methods split from {Path(module["source"]).name}."""\n\n'
        text += "\n\n".join(methods) + "\n"
    return text


def _with_mixins(plan, unit, text):
    names = [m for (cls, _), m in sorted(plan.mixins.items()) if cls == unit.name]
    if not names:
        return text
    node = unit.node
    first = node.lineno - unit.start  # the class line within the segment
    lines = text.split("\n")
    line = lines[first]
    if node.bases or node.keywords:
        line = line.replace(f"class {node.name}(", f"class {node.name}({', '.join(names)}, ", 1)
    else:
        line = line.replace(f"class {node.name}:", f"class {node.name}({', '.join(names)}):", 1)
    lines[first] = line
    return "\n".join(lines)


def _intra(module, owner, names, entry=False):
    """The import of ``names`` from the split's file ``owner``, as its style spells it:
    ``package`` absolute; ``engine`` by name under the kernel directory (after the entry's
    ``sys.path`` insert, so E402 there); ``dual`` relative on the host with the flat
    fallback freecadcmd needs, like render_diagram's own import of render_png."""
    spelled = ", ".join(sorted(names))
    style = module.get("style", "package")
    if style == "dual":
        stem = Path(owner).stem
        return (
            f"try:\n    from .{stem} import {spelled}\n"
            "except ImportError:  # FreeCAD runs the kernel helpers as standalone modules.\n"
            f"    from {stem} import {spelled}"
        )
    tail = "  # noqa: E402" if style == "engine" and entry else ""
    return f"from {dotted(module, owner)} import {spelled}{tail}"


def _rest(plan):
    """The ``rest`` file: the source with every moved unit cut out, each import reduced
    to the names still read there, imports of the moved names
    added after the last import, and split classes inheriting their mixins."""
    module = plan.module
    rest = module["rest"]
    lines, delta = _lines_for(plan, rest)
    wanted = plan.needs.get(rest, set())
    own = {n for u, t in plan.placed if t == rest for n in u.binds}
    for unit, target in plan.placed:
        if target == rest and unit.kind not in ("import",):
            wanted |= _unit_free(unit) - own
    pieces = []
    cursor = 1
    last_import = None
    for unit, target in plan.placed:
        if unit.kind == "method" and target == rest and (unit.cls, rest) in plan.mixins:
            target = None  # a method of a class whose head moved elsewhere
        gap = "\n".join(lines[cursor - 1 : unit.start - 1])
        cursor = unit.end + 1
        if unit.kind == "import":
            reduced = _reduced_import(lines, unit, wanted, delta)
            pieces.append(gap)
            if reduced:
                pieces.append(reduced)
                last_import = len(pieces) - 1
            continue
        if target != rest:
            continue
        text = _segment(lines, unit)
        if unit.kind == "head":
            text = _with_mixins(plan, unit, text)
        pieces.extend([gap, text])
    pieces.append("\n".join(lines[cursor - 1 :]))
    by_owner = defaultdict(set)
    for name in wanted:
        owner = plan.provider.get(name)
        if owner is not None and not isinstance(owner, tuple) and owner != rest:
            by_owner[owner].add(name)
    added = [_intra(module, owner, names, entry=True) for owner, names in sorted(by_owner.items())]
    if added:
        at = last_import if last_import is not None else 0
        pieces[at] = pieces[at] + "\n" + "\n".join(added)
    text = "\n".join(p for p in pieces if p is not None)
    return re.sub(r"\n{4,}", "\n\n\n", text).rstrip("\n") + "\n"


def _header(plan, target):
    module = plan.module
    doc = module.get("docs", {}).get(target)
    if doc is None:
        doc = f"Split from {Path(module['source']).name} by scripts/split_modules.py."
    header = [f'"""{doc}"""', ""]
    tree = ast.parse(plan.source)
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    if future:
        header += ["from __future__ import annotations", ""]
    return header


# --- importer rewriting ----------------------------------------------------------------


def _module_of(path):
    relative = path.relative_to(ROOT)
    if relative.parts[0] == "src":
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts), path.name == "__init__.py"
    return None, False


def _absolute(path, node):
    if not node.level:
        return node.module
    name, package = _module_of(path)
    if name is None:
        return None
    parts = name.split(".") if package else name.split(".")[:-1]
    parts = parts[: len(parts) - (node.level - 1)]
    return ".".join(parts + ([node.module] if node.module else []))


def _spelled(path, node, module):
    """``module`` spelled as ``node`` spells its own: relative from ``path`` when the
    original import was relative and ``module`` is inside the same base package."""
    if not node.level:
        return module
    name, package = _module_of(path)
    parts = name.split(".") if package else name.split(".")[:-1]
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    if module == base:
        return "." * node.level
    if module.startswith(base + "."):
        return "." * node.level + module[len(base) + 1 :]
    return module


class Rewriter:
    """Rewrites code outside the split that names the source module's symbols."""

    def __init__(self, plan):
        self.plan = plan
        self.module = plan.module
        self.source = dotted(self.module, self.module["source"])
        self.rest = self.module["rest"]
        self.owner = {}
        for name, provider in plan.provider.items():
            if not isinstance(provider, tuple):
                self.owner[name] = provider
        self.lookups = defaultdict(set)
        for unit, target in plan.placed:
            if unit.kind != "import":
                for name in _unit_free(unit):
                    self.lookups[name].add(target)
        self.refusals = []
        self.hand = []
        self.flat = Path(self.module["source"]).stem
        self.readers = defaultdict(set)  # name -> importer files reading it directly
        self._path = None
        self._file_reads = {}  # name -> direct reads (node) in the file being rewritten
        self._tree = None

    def new_module(self, name):
        target = self.owner.get(name, self.rest)
        return dotted(self.module, target)

    def patched_module(self, name, site=None):
        """Where a monkeypatch of ``name`` must land: the one file that looks it up. A
        direct read of the name after the patch at ``site``, in the same function, would
        reach the owner instead, so that refuses."""
        files = self.lookups.get(name, set())
        if len(files) > 1:
            names = sorted(Path(f).name for f in files)
            self.refusals.append(f"monkeypatched {name} is looked up from {names}")
            return None
        if files:
            looked = next(iter(files))
            elsewhere = self.readers.get(name, set()) - {self._path}
            if (self._read_after(name, site) or (site is not None and elsewhere)) and (
                looked != self.owner.get(name, self.rest)
            ):
                # The patch lands in the looking file, the later read in the owner.
                self.refusals.append(
                    f"monkeypatched {name} is also read here, so the patch and the read "
                    "would reach different files"
                )
                return None
            return dotted(self.module, looked)
        return self.new_module(name)

    def collect_reads(self, paths):
        """Which importer files read each name of the split module directly: a patch
        retargeted away from the name's owner would miss those reads. A ``test_*.py``
        file's reads run only in its own tests, after any other test's patch is undone,
        so only code a test can call (``src/``, ``scripts/``, test helpers) counts."""
        for path in paths:
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            if self.source.rsplit(".", 1)[-1] not in text:
                continue
            for name in _direct_reads(ast.parse(text), path, self.source):
                self.readers[name].add(path)

    def _read_after(self, name, site):
        if site is None:
            return False
        scope = _scope_of(self._tree, site)
        inside = {id(n) for n in ast.walk(scope)}
        for read in self._file_reads.get(name, []):
            if id(read) not in inside:
                continue
            # A nested helper may run after the patch whatever its line.
            after = (read.lineno, read.col_offset) > (site.lineno, site.col_offset)
            if after or _scope_of(self._tree, read) is not scope:
                return True
        return False

    def rewrite(self, path):
        text = path.read_text(encoding="utf-8")
        probe = self.module.get("entry") and "module_from_spec" in text
        probe = probe or any(word in text for word in ("parse(", "getsource(", "compile(", "exec("))
        mentioned = Path(self.module["source"]).stem in text or self.source.rsplit(".")[-1] in text
        if not (probe or mentioned):
            return None
        tree = ast.parse(text)
        before = len(self.refusals)
        try:
            return self._rewrite(path, text, tree)
        finally:
            where = path.relative_to(ROOT).as_posix()
            self.refusals[before:] = [
                r if r.startswith(where) else f"{where}: {r}" for r in self.refusals[before:]
            ]

    def _rewrite(self, path, text, tree):
        self._consumed = defaultdict(int)  # alias loads an edit replaced, per alias import
        self._file_reads = _direct_reads(tree, path, self.source)
        self._tree = tree
        self._path = path
        lines = text.splitlines(keepends=True)
        edits = []  # (start offset, end offset, replacement)
        offsets = list(itertools.accumulate([0] + [len(line) for line in lines]))

        def at(lineno, col):  # ast columns count UTF-8 bytes
            line = lines[lineno - 1].encode("utf-8")
            return offsets[lineno - 1] + len(line[:col].decode("utf-8"))

        flat = self.flat if path.parent == ROOT / self.module.get("flat_root", "-") else None
        aliases = {}  # id(import node) -> {local name bound there to the source module}
        imports = {}  # id(import node) -> import node
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                absolute = _absolute(path, node)
                if flat and not node.level and node.module == flat:
                    edits.append(self._from_import(path, node, at, flat=True))
                elif absolute == self.source:
                    edits.append(self._from_import(path, node, at))
                from_source = absolute == self.source or (
                    flat and not node.level and node.module == flat
                )
                if from_source and any(a.name == "*" for a in node.names):
                    self.refusals.append(
                        f"{path}:{node.lineno} star import of the split module; "
                        "import its names explicitly"
                    )
                elif absolute:
                    for a in node.names:
                        if f"{absolute}.{a.name}" == self.source:
                            aliases.setdefault(id(node), set()).add(a.asname or a.name)
                            imports[id(node)] = node
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == self.source and a.asname:
                        aliases.setdefault(id(node), set()).add(a.asname)
                        imports[id(node)] = node
                    elif a.name == self.source or (
                        a.name.startswith(self.source + ".") and not a.asname
                    ):
                        # Binds the top package, so code reaches the split module as
                        # prechips.<...>.<name>; `import <child> as x` binds only the child.
                        self.refusals.append(f"{path}:{node.lineno} plain `import {a.name}`")
        for node in imports.values():
            if _in_class_body(tree, node):
                self.refusals.append(
                    f"line {node.lineno}: the split module is imported in a class body; "
                    "move the import out of the class"
                )
        bound_by = defaultdict(list)  # (scope, alias name) -> alias import lines
        for key, names in aliases.items():
            for name in names:
                bound_by[(id(_scope_of(tree, imports[key])), name)].append(imports[key].lineno)
        for (_, name), lines_at in bound_by.items():
            if len(lines_at) > 1:
                self.refusals.append(
                    f"lines {', '.join(map(str, sorted(lines_at)))}: {name} imports the split "
                    "module more than once in one scope; keep one import"
                )
        for key, names in aliases.items():
            scope = _scope_of(tree, imports[key])
            for name, line in _other_bindings(scope, names, imports[key]):
                self.refusals.append(
                    f"line {line}: {name} names the split module and is also bound here; "
                    "rename one so every use of it means the module"
                )
        added = defaultdict(set)  # id(import node) -> import lines to add beside it
        parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        alias_names = set().union(*aliases.values()) if aliases else set()
        for node in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            # target=alias or target="pkg.big.name" leaves no positional module argument
            # for the resolver to see; any keyword form naming the split module refuses.
            values = [*node.args, *(k.value for k in node.keywords)]
            names_it = any(
                (isinstance(v, ast.Name) and v.id in alias_names)
                or (
                    isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                    and (v.value == self.source or v.value.startswith(self.source + "."))
                )
                for v in values
            )
            if _keyword_form(node) and names_it:
                self.refusals.append(
                    f"line {node.lineno}: {ast.unparse(node.func)} on the split module names "
                    "its target by keyword; pass the module and name positionally"
                )
        for node, binding in _resolved_uses(tree, aliases):
            if binding is not None and _keyword_form(node):
                self.refusals.append(
                    f"line {node.lineno}: {ast.unparse(node.func)} on the split module names "
                    "its target by keyword; pass the module and name positionally"
                )
                continue
            if binding is not None and isinstance(node, ast.Name) and not _reached(node, parents):
                edits.append(self._value_use(node, binding, at, added))
                continue
            edit = self._patch(node, binding, at, added)
            edit = edit or self._lookup(node, binding, at, added)
            edit = edit or self._attribute(node, binding, at, added)
            if edit:
                edits.append(edit)
        for line in set().union(*added.values()) if added else ():
            self._generated_alias_free(tree, line)
        for key, lines_ in added.items():
            node = imports[key]
            indent = " " * node.col_offset
            offset = offsets[node.end_lineno]  # start of the line after the alias import
            edits.append((offset, offset, "".join(f"{indent}{line}\n" for line in sorted(lines_))))
        if self.module.get("entry"):
            edits.extend(self._probes(text, tree, at, path))
        relative = path.relative_to(ROOT).as_posix()
        parsers = self.module.get("_parses_source", {})
        if self._reads_source(text):
            if relative not in parsers:
                self.refusals.append(
                    f"{relative} parses source: list it in the spec's [parses_source] "
                    "with the modules whose source it reads"
                )
            elif self.module["source"] in parsers[relative]:
                self.hand.append(f"{relative} reads {self.module['source']}'s source")
        edits = [e for e in edits if e is not None]
        if not edits:
            return None
        for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def _reads_source(self, text):
        """A file that parses, compiles or executes source text (``ast.parse``,
        ``inspect.getsource``, built-in ``compile``/``exec``) may depend on where a split
        module's code lives, which the script cannot port. Each such file is listed once
        in the spec's ``[parses_source]`` with the modules it reads."""
        return _parses_source(ast.parse(text))

    def _probes(self, text, tree, at, path):
        """Rewrite in-kernel probe scripts: test string literals that load the entry with
        ``importlib.util.module_from_spec`` (whatever variable names its path), plus every
        other literal of that file (probe fragments joined to a loader). A read of a moved
        name, ``alias.name``, reads its owning engine module, imported after the loader's
        ``exec_module(alias)`` at that line's indentation; a write, ``alias.name = ...``,
        lands in the one file that looks the name up (else it refuses, as for
        ``monkeypatch``). Edits the literals' source text, so raw strings stay as written."""
        loader = r"^[ \t]*(\w+) = importlib\.util\.module_from_spec"
        literals = [
            n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        aliases = set()
        for node in literals:
            aliases.update(re.findall(loader, node.value, re.M))
        if not aliases:
            return []
        used = defaultdict(dict)  # alias -> {stem: dotted module}
        edits = []
        for node in literals:
            start = at(node.lineno, node.col_offset)
            end = at(node.end_lineno, node.end_col_offset)
            literal = original = text[start:end]
            for alias in sorted(aliases):

                def written(match, alias=alias):
                    if self.owner.get(match[2]) in (None, self.rest):
                        return match[0]
                    module = self.patched_module(match[2])
                    if module is None or module == dotted(self.module, self.rest):
                        return match[0]
                    stem = module.rsplit(".", 1)[-1]
                    used[alias][stem] = module
                    return f"{match[1]}{alias}_{stem}.{match[2]}{match[3]}"

                def read(match, alias=alias):
                    owner = self.owner.get(match[1])
                    if owner is None or owner == self.rest:
                        return match[0]
                    stem = Path(owner).stem
                    used[alias][stem] = dotted(self.module, owner)
                    return f"{alias}_{stem}.{match[1]}"

                write = rf"(^[ \t]*){alias}\.(\w+)(\s*=(?!=))"
                literal = re.sub(write, written, literal, flags=re.M)
                literal = re.sub(rf"(?<![\w.]){alias}\.(\w+)", read, literal)
            if literal != original:
                edits.append([start, end, literal, node])
        for alias, stems in used.items():
            exec_line = rf"^([ \t]*)spec\.loader\.exec_module\({alias}\)\n"
            for edit in edits + [[at(n.lineno, n.col_offset), None, None, n] for n in literals]:
                body = (
                    edit[2]
                    if edit[2] is not None
                    else text[edit[0] : at(edit[3].end_lineno, edit[3].end_col_offset)]
                )
                match = re.search(exec_line, body, re.M)
                if not match:
                    continue
                imports = "".join(
                    f"{match[1]}import {name} as {alias}_{stem}\n"
                    for stem, name in sorted(stems.items())
                )
                body = body[: match.end()] + imports + body[match.end() :]
                if edit[2] is None:
                    end = at(edit[3].end_lineno, edit[3].end_col_offset)
                    edits.append([edit[0], end, body, edit[3]])
                else:
                    edit[2] = body
                break
            else:
                raise Refused(f"{path.name}: no spec.loader.exec_module({alias}) line")
        return [(start, end, literal) for start, end, literal, _ in edits]

    def _from_import(self, path, node, at, flat=False):
        groups = defaultdict(list)
        for a in node.names:
            if _dunder(a.name):  # an identity attribute stays on the module object
                self._identity(a.name, node.lineno)
                groups[self.source].append(a)
                continue
            groups[self.new_module(a.name)].append(a)
        if list(groups) == [self.source]:
            return None
        indent = " " * node.col_offset
        statements = [
            f"from {module.rsplit('.', 1)[-1] if flat else _spelled(path, node, module)} import "
            + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in names)
            for module, names in sorted(groups.items())
        ]
        replacement = ("\n" + indent).join(statements)
        span = at(node.lineno, node.col_offset), at(node.end_lineno, node.end_col_offset)
        return *span, replacement

    def _value_use(self, node, binding, at, added):
        """The alias as a value (in a list, passed to a function, compared with ``is``):
        what it is later asked for cannot be followed. The spec's ``value_uses = "rest"``
        says such a value stands for the module's entry point, which stays in ``rest``
        (a rule's ``evaluate``); the suite then checks that claim. Otherwise it refuses."""
        if self.module.get("value_uses") != "rest":
            self.refusals.append(
                f'line {node.lineno}: {node.id} is used as a value; set value_uses = "rest" '
                "if it stands for the entry point the rest file keeps"
            )
            return None
        module = dotted(self.module, self.rest)
        if module == self.source:
            return None
        local = self._alias_for(node.id, module, added, binding)
        return at(node.lineno, node.col_offset), at(node.end_lineno, node.end_col_offset), local

    def _generated_alias_free(self, tree, line):
        """A generated ``from A import B as N`` must not meet another binding of ``N`` in
        the file: an earlier one would be overwritten, a later one would hijack the
        rewritten uses. Only the same import may already bind it."""
        wanted = ast.parse(line).body[0]
        name = wanted.names[0].asname
        same = ast.dump(wanted)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                (a.asname or a.name) == name for a in node.names
            ):
                kept = [a for a in node.names if (a.asname or a.name) == name]
                if all(
                    ast.dump(ast.ImportFrom(node.module, [a], node.level)) == same for a in kept
                ):
                    continue
                self.refusals.append(f"line {node.lineno}: {name} is already bound; rename it")
            elif name in _bound_here(node):
                self.refusals.append(
                    f"line {getattr(node, 'lineno', 0)}: {name} is already bound; rename it"
                )

    def _alias_for(self, local, module, added, binding):
        """The local name of ``module``, imported beside the alias import ``binding``
        (same scope and indentation, so a function-level import stays lazy)."""
        if module == self.source:
            return local
        short = module.rsplit(".", 1)
        name = f"{local}_{short[-1]}"
        added[id(binding)].add(f"from {short[0]} import {short[-1]} as {name}")
        return name

    def _builtin_setattr(self, node, binding, at, added):
        """``setattr``/``delattr(alias, "name", ...)`` and ``monkeypatch.delattr(alias,
        "name")`` land where the name is looked up, as a monkeypatch does; a computed name
        or several looking files refuse."""
        first, second = node.args[0], node.args[1]
        if not (isinstance(first, ast.Name) and binding is not None):
            return None
        call = ast.unparse(node.func)
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            self.refusals.append(f"line {node.lineno}: {call}({first.id}, <computed name>)")
            return None
        if _dunder(second.value):
            self._identity(second.value, node.lineno)
            return None
        module = self.patched_module(second.value, node)
        if module is None or module == self.source:
            if module is None:
                self._consumed[id(binding)] += 1  # refused; keep the alias count whole
            return None
        local = self._alias_for(first.id, module, added, binding)
        self._consumed[id(binding)] += 1
        return at(first.lineno, first.col_offset), at(first.end_lineno, first.end_col_offset), local

    def _dotted_delattr(self, node, at):
        """``monkeypatch.delattr("prechips.<module>.name")``: the one looking file, or refuse."""
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return None
        prefix, _, name = first.value.rpartition(".")
        if prefix != self.source:
            return None
        if _dunder(name):
            self._identity(name, node.lineno)
            return None
        module = self.patched_module(name, node)
        if module is None or module == self.source:
            return None
        span = at(first.lineno, first.col_offset), at(first.end_lineno, first.end_col_offset)
        return *span, repr(f"{module}.{name}")

    def _lookup(self, node, binding, at, added):
        """``getattr(alias, "name")`` / ``hasattr(alias, "name")`` of a moved name reads
        the owning module; a computed name cannot be resolved, so it refuses."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            return None
        if node.func.id not in ("getattr", "hasattr") or len(node.args) < 2:
            return None
        first, second = node.args[0], node.args[1]
        if not (isinstance(first, ast.Name) and binding is not None):
            return None
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            self.refusals.append(
                f"line {node.lineno}: {node.func.id}({first.id}, <computed name>) on the split "
                "module cannot be resolved"
            )
            return None
        if _dunder(second.value):
            self._identity(second.value, node.lineno)
            return None
        module = self.new_module(second.value)
        if module == self.source:
            return None
        local = self._alias_for(first.id, module, added, binding)
        return at(first.lineno, first.col_offset), at(first.end_lineno, first.end_col_offset), local

    def _patch(self, node, binding, at, added):
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "delattr" and len(node.args) == 1:
            return self._dotted_delattr(node, at)
        if len(node.args) < 2:
            return None
        if isinstance(node.func, ast.Name) and node.func.id in ("setattr", "delattr"):
            return self._builtin_setattr(node, binding, at, added)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "delattr":
            return self._builtin_setattr(node, binding, at, added)  # monkeypatch.delattr
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "setattr"):
            return None
        first, second = node.args[0], node.args[1]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            prefix, _, name = first.value.rpartition(".")
            if prefix != self.source:
                return None
            if _dunder(name):
                self._identity(name, node.lineno)
                return None
            module = self.patched_module(name, node)
            if module is None or module == self.source:
                return None
            span = at(first.lineno, first.col_offset), at(first.end_lineno, first.end_col_offset)
            return *span, repr(f"{module}.{name}")
        if not (isinstance(first, ast.Name) and binding is not None):
            return None
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            self.refusals.append(f"monkeypatch of {first.id} with a computed name")
            return None
        if _dunder(second.value):
            self._identity(second.value, node.lineno)
            return None
        module = self.patched_module(second.value, node)
        if module is None or module == self.source:
            return None
        local = self._alias_for(first.id, module, added, binding)
        return at(first.lineno, first.col_offset), at(first.end_lineno, first.end_col_offset), local

    def _identity(self, name, line):
        """A module identity attribute (``__name__``, ``__file__``, ``__doc__``…) stays on
        the module object when the split keeps that object (rest is the source file);
        a package conversion changes it, so the script refuses."""
        if name not in IDENTITY:
            # __dict__, __all__…: the module's namespace, which loses the moved names.
            self.refusals.append(f"line {line}: {name} of the split module changes with the split")
            return True
        if self.rest == self.module["source"]:
            return True
        self.refusals.append(f"line {line}: {name} of the split module changes with the split")
        return True

    def _attribute(self, node, binding, at, added):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            return None
        if binding is None:
            return None
        if _dunder(node.attr):
            self._identity(node.attr, node.lineno)
            return None
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            # A write lands where the name is looked up, as setattr does.
            if self.owner.get(node.attr) in (None, self.rest) and node.attr not in self.lookups:
                return None
            module = self.patched_module(node.attr, node)
            if module is None:
                return None
        else:
            module = self.new_module(node.attr)
        if module == self.source:
            return None
        local = self._alias_for(node.value.id, module, added, binding)
        value = node.value
        return at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset), local


def _in_class_body(tree, node):
    """Whether ``node``'s nearest enclosing scope is a class body."""
    nearest = None
    for scope in ast.walk(tree):
        kinds = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        if isinstance(scope, kinds) and any(n is node for n in ast.walk(scope)):
            if nearest is None or any(n is scope for n in ast.walk(nearest)):
                nearest = scope
    return isinstance(nearest, ast.ClassDef)


def _scope_of(tree, node):
    """The innermost module or function whose own scope holds ``node``: the region where
    the name it binds is visible."""
    best = tree
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if any(n is node for n in ast.walk(scope)):
            if best is tree or any(n is scope for n in ast.walk(best)):
                best = scope
    return best


def _other_bindings(tree, names, alias_import):
    """``(name, line)`` for each binding of a module-alias name in the file that is not an
    import of the split module itself (a parameter, local, loop or comprehension target,
    assignment, def, except name). With none, every load of the name means the module, so
    no scope rule can make a rewrite wrong."""
    found = []
    for node in ast.walk(tree):
        bound = []
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound = [node.id]
        elif isinstance(node, ast.arg):
            bound = [node.arg]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = [node.name]
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            bound = [node.name] if node.name else []
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound = list(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = [
                (a.asname or a.name).split(".")[0]
                for a in node.names
                if not _imports_alias(node, a, alias_import)
            ]
        found += [(name, getattr(node, "lineno", 0)) for name in bound if name in names]
    return found


def _direct_reads(tree, path, source):
    """``{name: [read node]}`` for names a file reads from ``source`` itself: uses of a
    ``from source import name`` binding and ``alias.name`` loads through a module alias
    of ``source``."""
    aliases, imported, found = set(), {}, defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            absolute = _absolute(path, node)
            if absolute == source:
                imported.update({a.asname or a.name: a.name for a in node.names})
            for a in node.names:
                if absolute and f"{absolute}.{a.name}" == source:
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            aliases.update(a.asname for a in node.names if a.name == source and a.asname)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            found[node.attr].append(node)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in imported:
            found[imported[node.id]].append(node)
    return found


def _bound_here(node):
    """Names ``node`` itself binds (an import is checked by the caller)."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [node.id]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return [node.name] if node.name else []
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.Import):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    return []


def _imports_alias(node, alias, alias_import):
    """Whether ``alias`` in ``node`` imports the same module object ``alias_import`` does."""
    if node is alias_import:
        return True
    same = [a for a in alias_import.names if (a.asname or a.name) == (alias.asname or alias.name)]
    if not same or type(node) is not type(alias_import):
        return False
    if isinstance(node, ast.ImportFrom):
        spelled = (node.level, node.module, alias.name)
        return spelled == (alias_import.level, alias_import.module, same[0].name)
    return alias.name == same[0].name


def _parses_source(tree):
    """Whether code in ``tree``, or in a probe script held in one of its string literals
    (run inside freecadcmd), parses, compiles or executes source text."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "\n" in node.value and ("compile(" in node.value or "exec(" in node.value):
                try:
                    if _parses_source(ast.parse(node.value)):
                        return True
                except SyntaxError:
                    pass
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("compile", "exec"):
            return True
        if isinstance(func, ast.Attribute) and func.attr in ("parse", "getsource"):
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id in ("ast", "inspect"):
                return True
    return False


def _dunder(name):
    return name.startswith("__") and name.endswith("__")


def _keyword_form(node):
    """A setattr/delattr/getattr/hasattr call (built-in or monkeypatch) that names its
    target, attribute or value by keyword, a shape the rewriter does not follow."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if called not in ("setattr", "delattr", "getattr", "hasattr"):
        return False
    return any(k.arg in ("target", "name", "value") for k in node.keywords)


def _reached(name, parents):
    """Whether this load of a module alias is one the rewriter follows: ``alias.attr``,
    or the module argument of ``setattr``/``delattr``/``getattr``/``hasattr``."""
    parent = parents.get(id(name))
    if isinstance(parent, ast.Attribute) and parent.value is name:
        return True
    if isinstance(parent, ast.Call) and parent.args and parent.args[0] is name:
        func = parent.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        return called in ("setattr", "delattr", "getattr", "hasattr")
    return False


def _module_bindings(tree):
    """Names the module scope binds, including imports and assignments nested in
    module-level ``try``/``if``/``with``/``for`` blocks (not inside functions,
    classes or comprehensions, which have scopes of their own)."""
    bound = set()
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            continue
        if isinstance(
            node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        stack.extend(ast.iter_child_nodes(node))
    return bound


def _resolved_uses(tree, aliases):
    """``(node, alias import or None)`` for every node, the import being the one the
    node's leading name resolves to lexically: a function's own parameter or local
    named like a module alias hides that alias, as Python's scoping does."""
    scope_of = {}  # id(import node) -> id(scope node)
    names_of = {}
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        body = scope.body if isinstance(scope.body, list) else [scope.body]
        stack = list(body)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if id(n) in aliases:
                scope_of[id(n)] = id(scope)
                for name in aliases[id(n)]:
                    names_of[(id(scope), name)] = n
            stack.extend(ast.iter_child_nodes(n))
    found = []

    def visit(n, chain):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # Its targets hide an alias inside it; each iterable is read before its
            # own targets bind, the first one in the enclosing scope.
            found.append((n, None))
            bound = set()
            for generator in n.generators:
                visit(generator.iter, [*chain, (id(n), set(bound))])
                _targets(generator.target, bound)
                for condition in generator.ifs:
                    visit(condition, [*chain, (id(n), set(bound))])
            for key in ("elt", "key", "value"):
                if hasattr(n, key):
                    visit(getattr(n, key), [*chain, (id(n), set(bound))])
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            chain = [*chain, (id(n), _local_bindings(n))]
        name = None
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            name = n.value.id
        elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Name):
            name = n.args[0].id
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            name = n.id
        binding = None
        if name is not None:
            for scope, bound in reversed(chain):
                if name in bound:
                    binding = names_of.get((scope, name))
                    break
        found.append((n, binding))
        for child in ast.iter_child_nodes(n):
            visit(child, chain)

    visit(tree, [(id(tree), _module_bindings(tree))])
    return found


def _citations(source):
    """``(line citations, other mentions)`` of ``source`` in the repository's prose and
    example data: a ``file:line`` citation would point at moved code, so it refuses."""
    cited, mentioned = [], []
    pattern = re.compile(re.escape(source) + r"(:\d+)?")
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in (".md", ".toml", ".yml", ".yaml", ".txt") or ".venv" in path.parts:
            continue
        if path == SPEC:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in pattern.finditer(line):
                where = f"{path.relative_to(ROOT)}:{number}"
                (cited if match[1] else mentioned).append(where)
    return cited, mentioned


def apply(args):
    module = module_spec(args.name, args.variant)
    plan = make_plan(module)
    rewriter = Rewriter(plan)
    rewritten = {}
    moved = {ROOT / f for f in plan.files()} | {ROOT / module["source"]}
    importers = [
        path
        for root in REWRITE_ROOTS
        for path in sorted((ROOT / root).rglob("*.py"))
        if path not in moved and "__pycache__" not in path.parts
    ]
    rewriter.collect_reads(importers)
    for path in importers:
        text = rewriter.rewrite(path)
        if text is not None:
            rewritten[path] = text
    cited, mentioned = _citations(module["source"])
    rewriter.refusals += [f"{where} cites {module['source']} by line" for where in cited]
    refusals = plan.refusals + rewriter.refusals
    if refusals:
        show_plan(plan)
        for refusal in rewriter.refusals:
            print(f"REFUSED: {refusal}")
        raise SystemExit(2)
    files = {}
    for target in plan.files():
        if target == module["rest"]:
            files[ROOT / target] = _rest(plan)
        else:
            files[ROOT / target] = _render(plan, target, _header(plan, target))
    source = ROOT / module["source"]
    if module["rest"] != module["source"]:
        source.unlink()
    for init, doc in module.get("init", {}).items():
        files[ROOT / init] = f'"""{doc}"""\n'
    for path, text in {**files, **rewritten}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    changed = [str(p) for p in {**files, **rewritten}]
    ruff = [sys.executable, "-m", "ruff"]
    for step in (["check", "--quiet", "--fix", "--select", "I"], ["format", "--quiet"]):
        process = subprocess.run([*ruff, *step, *changed], cwd=ROOT)
        if process.returncode:
            raise SystemExit(f"ruff {step[0]} failed ({process.returncode}) on the written files")
    for path in sorted(changed):
        print(f"wrote {Path(path).relative_to(ROOT)}")
    for where in mentioned:
        print(f"UPDATE BY HAND: {where} names {module['source']}")
    for note in rewriter.hand:
        print(f"UPDATE BY HAND: {note}")


# --- churn -----------------------------------------------------------------------------


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


_UNITS = {}


def _units_at(commit, path):
    """``(blob, units)`` of ``path`` at ``commit``; ``(None, [])`` where it is absent."""
    try:
        blob = git("rev-parse", f"{commit}:{path}").strip()
    except subprocess.CalledProcessError:
        return None, []
    if blob not in _UNITS:
        try:
            _UNITS[blob] = units(git("cat-file", "blob", blob))
        except (SyntaxError, Refused):
            _UNITS[blob] = []
    return blob, _UNITS[blob]


def _hits(found, spans):
    owner = {}
    for index, unit in enumerate(found):
        for line in range(unit.start, unit.end + 1):
            owner[line] = index
    return {
        owner[line]
        for first, count in spans
        for line in range(first, first + count)
        if line in owner
    }


def touched(base, head, path):
    """``[(units, {indices touched})]`` for both sides of ``base..head``: at ``head`` the
    units whose lines were added or changed (a pure deletion counts against the unit at
    its position), and at ``base`` the units whose lines were removed or changed, so a
    deleted symbol still counts against the file it lived in."""
    diff = git("diff", "-U0", "--no-color", base, head, "--", path)
    if not diff:
        return []
    old, new = [], []
    for match in HUNK.finditer(diff):
        old_count = 1 if match[2] is None else int(match[2])
        new_count = 1 if match[4] is None else int(match[4])
        if old_count:
            old.append((int(match[1]), old_count))
        if new_count:  # a pure deletion has no head-side lines; its old side counts
            new.append((int(match[3]), new_count))
    sides = []
    for commit, spans in ((head, new), (base, old)):
        blob, found = _units_at(commit, path) if commit != EMPTY_TREE else (None, [])
        if blob is not None and spans:
            sides.append((found, _hits(found, spans)))
    return sides


def changes(since, refs, paths, by):
    """``{change: {path: (units, touched indices)}}`` for each merged PR (first parent)
    or non-merge commit since ``since`` and each in-flight ``ref`` since its merge base."""
    found = {}
    walk = ["--first-parent"] if by == "pr" else ["--no-merges"]
    for line in git("log", *walk, f"--since={since}", "--format=%H %P|%s").splitlines():
        hashes, subject = line.split("|", 1)
        commit, *parents = hashes.split()
        parent = parents[0] if parents else EMPTY_TREE
        numbers = re.findall(r"\(#(\d+)\)", subject) if by == "pr" else []
        label = f"#{numbers[-1]}" if numbers else commit[:9]
        found[label] = {p: touched(parent, commit, p) for p in paths}
    for ref in refs:
        base = git("merge-base", "HEAD", ref).strip()
        label = "open:" + ref.split("/", 1)[-1]
        found[label] = {p: touched(base, ref, p) for p in paths}
    return {
        k: {p: v for p, v in files.items() if any(hit for _, hit in v)}
        for k, files in found.items()
    }


def churn(args):
    spec = load_spec()
    paths = sorted({m["source"] for m in spec})
    found = changes(args.since, args.ref, paths, args.by)
    report = {"since": args.since, "by": args.by, "changes": sorted(found), "modules": {}}
    for module in spec:
        path = module["source"]
        source = (ROOT / path).read_text(encoding="utf-8")
        head_units = units(source)
        plain = module
        module = {**module, "_known": {u.name for u in head_units}}
        per_target = defaultdict(set)
        per_unit = defaultdict(set)
        sweeps = []
        touching = []
        for change, files in found.items():
            if path not in files:
                continue
            sides = files[path]
            version, hit = sides[0]
            movable = [i for i, u in enumerate(version) if u.kind not in ("import", "module")]
            hit_movable = [i for i in hit if version[i].kind not in ("import", "module")]
            if len(movable) > 8 and len(hit_movable) > SWEEP * len(movable):
                sweeps.append(change)
                continue
            touching.append(change)
            targets, imports = set(), False
            for version, hit in sides:
                # Only an in-flight branch's symbols that HEAD lacks are new; one that
                # merged history had and HEAD dropped since falls back to rest.
                placed = assign(module if change.startswith("open:") else plain, version)
                for index, (unit, target) in enumerate(placed):
                    if index not in hit:
                        continue
                    if unit.kind in ("import", "module"):
                        per_unit[f"<{unit.kind}>"].add(change)
                        imports = True
                        continue
                    targets.add(target)
                    per_unit[unit.name].add(change)
            # An import edit serves the change's own symbols, so it lands in their files;
            # a change that edits only imports keeps the rest file.
            if imports and not targets:
                targets.add(module["rest"])
            for target in targets:
                per_target[target].add(change)
        pairs = list(itertools.combinations(touching, 2))
        shared = [p for p in pairs if any(p[0] in s and p[1] in s for s in per_target.values())]
        open_ = [c for c in touching if c.startswith("open:")]
        open_pairs = list(itertools.combinations(open_, 2))
        open_shared = [
            p for p in open_pairs if any(p[0] in s and p[1] in s for s in per_target.values())
        ]
        sizes = defaultdict(int)
        for unit, target in assign(module, head_units):
            if unit.kind not in ("import",):
                sizes[target] += unit.end - unit.start + 1
        largest = max(sizes.values()) if sizes else 0
        key = module["name"] + (f"[{module['variant']}]" if module.get("variant") else "")
        report["modules"][key] = {
            "changes": len(touching),
            "sweeps": sweeps,
            "pairs_before": len(pairs),
            "pairs_after": len(shared),
            "open_pairs_before": len(open_pairs),
            "open_pairs_after": len(open_shared),
            "open_shared": [list(p) for p in open_shared],
            "files": len(sizes),
            "largest_file_lines": largest,
            "targets": {
                t: {"lines": sizes[t], "changes": sorted(per_target[t])}
                for t in sorted(set(sizes) | set(per_target))
            },
            "units": {
                n: sorted(c) for n, c in sorted(per_unit.items(), key=lambda i: (-len(i[1]), i[0]))
            },
        }
        print(
            f"{key:28s} files={len(sizes):3d} largest={largest:6d}  changes={len(touching):3d} "
            f"(+{len(sweeps)} sweeps)  pairs {len(pairs):5d} -> {len(shared):5d}  "
            f"open pairs {len(open_pairs)} -> {len(open_shared)}"
        )
        if args.verbose:
            for target, data in report["modules"][key]["targets"].items():
                count = len(data["changes"])
                print(f"    {target:56s} {data['lines']:6d} lines {count:4d} changes")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


# --- byte identity ---------------------------------------------------------------------

# plan -> (its expected traveler directory, the exit examples/README.md documents for it)
BUNDLES = {
    "examples/pivot-shaft/plan.toml": ("examples/pivot-shaft/expected", 0),
    "examples/rocker-arm/plan.toml": ("examples/rocker-arm/expected", 0),
    "examples/pivot-bracket/plan.toml": ("examples/pivot-bracket/expected", 0),
    "examples/cone-pivot-post/built-up.toml": ("examples/cone-pivot-post/expected/built-up", 4),
}


def _digests(directory):
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def snapshot(args):
    """Fails on any of: a non-empty OUT (an earlier run's file could stand in for a missing
    output), an exit other than the bundle's documented one, a traveler directory or a
    check's report.json differing from ``expected/``, or any difference from the
    ``--against`` manifest (read before anything is written)."""
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; snapshot needs a fresh output directory")
    before = json.loads(Path(args.against).read_text()) if args.against else None
    manifest = {}
    failed = []
    for plan, (expected, exit_code) in BUNDLES.items():
        stem = Path(plan).parent.name
        reference = _digests(ROOT / expected)
        for verb in ("check", "traveler"):
            target = out / stem / verb
            process = subprocess.run(
                ["uv", "run", "prechips", verb, plan, "--out", str(target)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            files = _digests(target) if target.exists() else {}
            wanted = reference if verb == "traveler" else {"report.json": reference["report.json"]}
            entry = {
                "exit": process.returncode,
                "files": files,
                "matches_expected": files == wanted,
            }
            manifest[f"{stem}/{verb}"] = entry
            if process.returncode != exit_code:
                failed.append(f"{stem}/{verb}: exit {process.returncode}, documented {exit_code}")
            if not entry["matches_expected"]:
                failed.append(f"{stem}/{verb}: outputs differ from {expected}")
            print(f"{stem:16s} {verb:9s} exit={process.returncode}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if before is not None:
        keys = sorted(set(before) | set(manifest))
        failed += [f"{k}: differs from --against" for k in keys if before.get(k) != manifest.get(k)]
    for reason in failed:
        print(f"DIFFERS: {reason}")
    raise SystemExit(1 if failed else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("churn")
    p.add_argument("--since", default="2026-09-01")
    p.add_argument("--by", choices=("pr", "commit"), default="pr")
    p.add_argument("--ref", action="append", default=[])
    p.add_argument("--json")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(run=churn)
    for verb, run in (("plan", plan_command), ("apply", apply)):
        p = sub.add_parser(verb)
        p.add_argument("name")
        p.add_argument("--variant")
        p.set_defaults(run=run)
    p = sub.add_parser("snapshot")
    p.add_argument("out")
    p.add_argument("--against", help="an earlier snapshot's manifest.json")
    p.set_defaults(run=snapshot)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
