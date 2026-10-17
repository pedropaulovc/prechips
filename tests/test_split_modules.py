"""scripts/split_modules.py: unit extraction, name analysis, refusals and a real apply.

Each split runs on a throwaway package under tmp_path; nothing here reads or writes the
repository's own sources.
"""

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "split_modules", ROOT / "scripts" / "split_modules.py"
)
split = importlib.util.module_from_spec(_spec)
sys.modules["split_modules"] = split  # dataclasses resolve the module by name
_spec.loader.exec_module(split)


def _names(source, **kwargs):
    return [(u.name, u.kind) for u in split.units(textwrap.dedent(source), **kwargs)]


def test_units_keep_comments_type_aliases_and_trailers_with_their_symbol():
    source = """\
        import math

        type Number = float | str
        # Stems one rule reads.
        STEMS = {"dia"}
        STEMS |= {"oal"}


        @staticmethod
        def f():
            return math.pi
        """
    units = split.units(textwrap.dedent(source))
    assert [(u.name, u.kind) for u in units] == [
        ("<import>", "import"),
        ("Number", "def"),
        ("STEMS", "def"),
        ("STEMS", "trailer"),
        ("f", "def"),
    ]
    assert units[2].start == 4  # the comment travels with STEMS
    assert units[4].start == 9  # and the decorator with f


def test_a_named_class_splits_into_its_head_and_members():
    source = """\
        class Big:
            LIMIT = 1

            def a(self):
                return self.b()

            def b(self):
                return 2
        """
    assert _names(source, classes={"Big"}) == [
        ("Big", "head"),
        ("Big.a", "method"),
        ("Big.b", "method"),
    ]


def test_free_names_follow_scopes_annotations_and_quoted_annotations():
    node = ast.parse(
        textwrap.dedent(
            """\
            def f(x: "Plan", y: Stock = DEFAULT) -> list[Hold]:
                LIMIT = 3
                total = [item for item in x if item > LIMIT]
                return helper(total, y)
            """
        )
    ).body[0]
    # Builtins stay in (only module-level bindings ever become imports); locals do not.
    assert split.free_names(node) == {"Plan", "Stock", "DEFAULT", "Hold", "helper", "list"}


def _package(tmp_path, source, spec):
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""pkg"""\n', encoding="utf-8")
    (package / "big.py").write_text(textwrap.dedent(source), encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    toml = tmp_path / "scripts" / "split_modules.toml"
    toml.write_text(textwrap.dedent(spec), encoding="utf-8")
    return toml


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setattr(split, "ROOT", tmp_path)
    monkeypatch.setattr(split, "SRC", tmp_path / "src")

    def make(source, spec):
        monkeypatch.setattr(split, "SPEC", _package(tmp_path, source, spec))
        return split.make_plan(split.module_spec("big"))

    return make


SPEC = """\
    [[module]]
    name = "big"
    source = "src/pkg/big.py"
    rest = "src/pkg/big.py"
    style = "package"
    classes = ["Engine"]
    [module.targets]
    "src/pkg/parts.py" = {targets}
    """


def _spec(targets):
    return SPEC.replace("{targets}", targets)


def test_module_state_written_under_global_and_read_elsewhere_is_refused(at):
    source = """\
        POOL = None

        def use():
            return POOL

        def main():
            global POOL
            POOL = 1
        """
    plan = at(source, _spec('["use"]'))
    assert any("module state POOL" in refusal for refusal in plan.refusals)


def test_a_mixin_method_using_zero_argument_super_is_refused(at):
    source = """\
        class Engine:
            def run(self):
                return super().run()
        """
    plan = at(source, _spec('["Engine.run"]'))
    assert any("zero-argument super()" in refusal for refusal in plan.refusals)


def test_an_import_cycle_names_the_symbols_on_each_edge(at):
    source = """\
        def a():
            return b()

        def b():
            return a()
        """
    plan = at(source, _spec('["a"]'))
    assert any("import cycle" in r and "a" in r and "b" in r for r in plan.refusals)


def test_a_monkeypatched_name_read_from_two_files_is_refused(at, tmp_path):
    source = """\
        def radius(x):
            return x

        def area(x):
            return radius(x) ** 2

        def volume(x):
            return radius(x) ** 3
        """
    at(source, _spec('["area"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n\ndef test(monkeypatch):\n"
        '    monkeypatch.setattr(big, "radius", abs)\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as stopped:
        split.main(["apply", "big"])
    assert stopped.value.code == 2
    assert not (tmp_path / "src" / "pkg" / "parts.py").exists()


def test_apply_moves_symbols_and_mixins_and_rewrites_importers_and_patches(at, tmp_path):
    source = '''\
        """Big."""

        from __future__ import annotations

        import math

        LIMIT = 2.0


        def radius(x: float) -> float:
            return math.sqrt(x) * LIMIT


        class Engine:
            def __init__(self):
                self.size = 4.0

            def run(self):
                return self.measure() + LIMIT

            def measure(self):
                return radius(self.size)
        '''
    at(source, _spec('["LIMIT", "radius", "Engine.measure"]'))
    test = tmp_path / "tests" / "test_big.py"
    test.write_text(
        textwrap.dedent(
            """\
            from pkg import big
            from pkg.big import Engine, radius


            def test_run(monkeypatch):
                assert Engine().run() == 6.0
                assert radius(4.0) == 4.0
                monkeypatch.setattr(big, "radius", lambda x: 1.0)
                assert Engine().run() == 3.0
            """
        ),
        encoding="utf-8",
    )
    split.main(["apply", "big"])
    parts = (tmp_path / "src" / "pkg" / "parts.py").read_text(encoding="utf-8")
    assert "class EngineParts:" in parts and "def measure(self):" in parts
    rest = (tmp_path / "src" / "pkg" / "big.py").read_text(encoding="utf-8")
    assert "class Engine(EngineParts):" in rest and "def radius" not in rest
    rewritten = test.read_text(encoding="utf-8")
    assert "from pkg.parts import radius" in rewritten
    assert 'monkeypatch.setattr(big_parts, "radius"' in rewritten
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test)],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def test_a_comprehension_target_never_hides_a_global_the_function_reads():
    node = ast.parse(
        textwrap.dedent(
            """\
            def f():
                values = [LIMIT for LIMIT in range(2)]
                return LIMIT, values, [(seen := item) for item in values], seen
            """
        )
    ).body[0]
    assert "LIMIT" in split.free_names(node)
    assert "seen" not in split.free_names(node)  # a walrus binds the function's scope


def _importer_case(at, tmp_path, source, targets, test_source):
    at(source, _spec(targets))
    test = tmp_path / "tests" / "test_big.py"
    test.write_text(textwrap.dedent(test_source), encoding="utf-8")
    split.main(["apply", "big"])
    return test.read_text(encoding="utf-8")


def test_a_lazy_module_import_stays_lazy_and_gets_its_replacement_beside_it(at, tmp_path):
    source = "def radius(x):\n    return x\n"
    rewritten = _importer_case(
        at,
        tmp_path,
        source,
        '["radius"]',
        """\
        def lazy():
            from pkg import big

            return big.radius(2)
        """,
    )
    assert rewritten.splitlines()[:4] == [
        "def lazy():",
        "    from pkg import big",
        "    from pkg import parts as big_parts",
        "",
    ]
    assert "return big_parts.radius(2)" in rewritten


def test_a_ruff_failure_fails_apply(at, tmp_path, monkeypatch):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    real = subprocess.run

    def failing_ruff(command, **kwargs):
        if command[1:3] == ["-m", "ruff"]:
            return subprocess.CompletedProcess(command, 2)
        return real(command, **kwargs)

    monkeypatch.setattr(split.subprocess, "run", failing_ruff)
    with pytest.raises(SystemExit, match="ruff check failed"):
        split.main(["apply", "big"])


def test_a_test_reading_the_split_modules_source_is_refused_until_listed(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    reader = tmp_path / "tests" / "test_reader.py"
    reader.write_text(
        'import ast\nfrom pathlib import Path\n\nTREE = ast.parse(Path("big.py").read_text())\n'
        'NAME = "big.py"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    assert (tmp_path / "src" / "pkg" / "big.py").read_text().startswith("def radius")


ENGINE_SPEC = """\
    [[module]]
    name = "big"
    source = "src/pkg/big.py"
    rest = "src/pkg/big.py"
    entry = "src/pkg/big.py"
    style = "engine"
    root = "src/pkg"
    [module.targets]
    "src/pkg/parts.py" = ["helper", "patched", "user"]
    """


def test_probes_are_found_by_their_loader_and_fragments_are_rewritten_too(at, tmp_path):
    source = """\
        def helper():
            return 1


        def patched():
            return 2


        def user():
            return patched()


        def run():
            return 0
        """
    at(source, ENGINE_SPEC)
    test = tmp_path / "tests" / "test_probe.py"
    test.write_text(
        textwrap.dedent(
            '''\
            _HEAD = r"""
            import importlib.util, os
            spec = importlib.util.spec_from_file_location("e", os.environ["OTHER_ENGINE"])
            engine = importlib.util.module_from_spec(spec)
            if True:
                spec.loader.exec_module(engine)
            engine.run()
            """
            _TAIL = r"""
            engine.patched = lambda: 3
            print(engine.helper(), engine.run())
            """
            PROBE = _HEAD + _TAIL
            '''
        ),
        encoding="utf-8",
    )
    split.main(["apply", "big"])
    rewritten = test.read_text(encoding="utf-8")
    assert "    spec.loader.exec_module(engine)\n    import parts as engine_parts\n" in rewritten
    assert "engine_parts.patched = lambda: 3" in rewritten  # patched where user reads it
    assert "print(engine_parts.helper(), engine.run())" in rewritten


def _fake_cli(outputs, exits):
    """A stand-in for ``uv run prechips VERB PLAN --out DIR`` writing ``outputs``."""

    def run(command, **kwargs):
        verb, plan, target = command[3], command[4], Path(command[6])
        target.mkdir(parents=True)
        for name, data in outputs[(plan, verb)].items():
            (target / name).write_bytes(data)
        return subprocess.CompletedProcess(command, exits[(plan, verb)], "", "")

    return run


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "report.json").write_bytes(b"{}")
    (expected / "traveler.html").write_bytes(b"<p>")
    monkeypatch.setattr(split, "ROOT", tmp_path)
    monkeypatch.setattr(split, "BUNDLES", {"plan.toml": ("expected", 0)})
    good = {
        ("plan.toml", "check"): {"report.json": b"{}"},
        ("plan.toml", "traveler"): {"report.json": b"{}", "traveler.html": b"<p>"},
    }
    return tmp_path, good


def _snapshot(monkeypatch, outputs, exits, *argv):
    monkeypatch.setattr(split.subprocess, "run", _fake_cli(outputs, exits))
    with pytest.raises(SystemExit) as stopped:
        split.main(["snapshot", *map(str, argv)])
    return stopped.value.code


def test_snapshot_passes_only_matching_outputs_at_the_documented_exit(bundle, monkeypatch):
    root, good = bundle
    clean = {("plan.toml", "check"): 0, ("plan.toml", "traveler"): 0}
    assert _snapshot(monkeypatch, good, clean, root / "a") == 0
    timed_out = {("plan.toml", "check"): 2, ("plan.toml", "traveler"): 0}
    assert _snapshot(monkeypatch, good, timed_out, root / "b") == 1
    missing = {**good, ("plan.toml", "traveler"): {"report.json": b"{}"}}
    assert _snapshot(monkeypatch, missing, clean, root / "c") == 1


def test_snapshot_refuses_a_used_directory_and_reads_its_baseline_first(bundle, monkeypatch):
    root, good = bundle
    clean = {("plan.toml", "check"): 0, ("plan.toml", "traveler"): 0}
    assert _snapshot(monkeypatch, good, clean, root / "base") == 0
    # An earlier run's files cannot stand in for this run's outputs.
    with pytest.raises(SystemExit, match="not empty"):
        split.main(["snapshot", str(root / "base")])
    baseline = root / "base" / "manifest.json"
    changed = {**good, ("plan.toml", "check"): {"report.json": b"{}", "extra.txt": b"x"}}
    assert _snapshot(monkeypatch, changed, clean, root / "new", "--against", baseline) == 1


def _repo(tmp_path, monkeypatch, versions):
    monkeypatch.setattr(split, "ROOT", tmp_path)
    split._UNITS.clear()
    commits = []
    for text in versions:
        (tmp_path / "big.py").write_text(textwrap.dedent(text), encoding="utf-8")
        if not commits:
            split.git("init", "-q")
        split.git("add", "big.py")
        split.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v")
        commits.append(split.git("rev-parse", "HEAD").strip())
    return commits


def test_churn_counts_a_deleted_symbol_against_the_file_it_lived_in(tmp_path, monkeypatch):
    base, head = _repo(
        tmp_path,
        monkeypatch,
        ["def a():\n    return 1\n\n\ndef b():\n    return 2\n", "def a():\n    return 1\n"],
    )
    names = {
        unit.name
        for version, hit in split.touched(base, head, "big.py")
        for i, unit in enumerate(version)
        if i in hit
    }
    assert "b" in names


BODY = "\n\ndef f():\n    return 1\n\n\ndef g():\n    return 2\n"


def test_churn_keeps_two_import_edits_paired_after_the_split(tmp_path, monkeypatch, capsys):
    _repo(
        tmp_path,
        monkeypatch,
        [
            imports + BODY
            for imports in ("import a\n", "import a\nimport b\n", "import a\nimport b\nimport c\n")
        ],
    )
    spec = tmp_path / "split.toml"
    spec.write_text(
        '[[module]]\nname = "big"\nsource = "big.py"\nrest = "big.py"\n'
        '[module.targets]\n"parts.py" = ["g"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(split, "SPEC", spec)
    split.main(["churn", "--by", "commit", "--since", "2000-01-01", "--json", str(tmp_path / "o")])
    report = json.loads((tmp_path / "o").read_text())["modules"]["big"]
    # The base commit adds every line (one change); the two import edits stay a pair.
    assert report["pairs_after"] == report["pairs_before"] == 3


def test_a_comprehension_iterable_is_read_before_its_target_binds():
    node = ast.parse("def moved():\n    return [LIMIT for LIMIT in LIMIT]\n").body[0]
    assert split.free_names(node) == {"LIMIT"}


def test_getattr_of_a_moved_name_reads_its_owner_and_a_computed_one_refuses(at, tmp_path):
    source = "def radius(x):\n    return x\n"
    rewritten = _importer_case(
        at,
        tmp_path,
        source,
        '["radius"]',
        """\
        from pkg import big


        def test():
            assert getattr(big, "radius")(1) == 1
        """,
    )
    assert 'getattr(big_parts, "radius")' in rewritten


def test_getattr_with_a_computed_name_on_the_split_module_refuses(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\nNAME = 'radius'\nFOUND = getattr(big, NAME)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    assert not (tmp_path / "src" / "pkg" / "parts.py").exists()


def test_importing_a_child_of_the_split_module_as_an_alias_is_not_refused(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "src" / "pkg" / "big_child.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_big.py").write_text(
        "import pkg.big.child as child\nfrom pkg.big import radius\n", encoding="utf-8"
    )
    split.main(["apply", "big"])
    assert (tmp_path / "src" / "pkg" / "parts.py").exists()


VALUE_SOURCE = "def evaluate(x):\n    return helper(x)\n\n\ndef helper(x):\n    return x\n"
VALUE_TEST = (
    "from pkg import big\n\nSCREENS = [big]\n\n\ndef test():\n"
    "    assert SCREENS[0].evaluate(3) == 3\n"
)


def test_a_module_alias_used_as_a_value_is_refused(at, tmp_path):
    at(VALUE_SOURCE, _spec('["helper"]'))
    (tmp_path / "tests" / "test_big.py").write_text(VALUE_TEST, encoding="utf-8")
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


def test_value_uses_rest_rebinds_a_value_alias_to_the_entry_points_file(at, tmp_path):
    spec = """\
        [[module]]
        name = "big"
        source = "src/pkg/big.py"
        rest = "src/pkg/big/rule.py"
        style = "package"
        value_uses = "rest"
        init = { "src/pkg/big/__init__.py" = "Big, split." }
        [module.targets]
        "src/pkg/big/parts.py" = ["helper"]
        """
    at(VALUE_SOURCE, spec)
    test = tmp_path / "tests" / "test_big.py"
    test.write_text(VALUE_TEST, encoding="utf-8")
    split.main(["apply", "big"])
    rewritten = test.read_text(encoding="utf-8")
    assert "SCREENS = [big_rule]" in rewritten
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test)],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def test_churn_never_counts_a_pure_deletion_against_the_symbol_after_it(tmp_path, monkeypatch):
    base, head = _repo(
        tmp_path,
        monkeypatch,
        [
            "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n",
            "def a():\n    return 1\n\n\ndef c():\n    return 3\n",
        ],
    )
    names = {
        unit.name
        for version, hit in split.touched(base, head, "big.py")
        for i, unit in enumerate(version)
        if i in hit
    }
    assert names == {"b"}


def test_builtin_setattr_lands_where_the_name_is_looked_up(at, tmp_path):
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    rewritten = _importer_case(
        at,
        tmp_path,
        source,
        '["radius", "area"]',
        'from pkg import big\n\nsetattr(big, "radius", abs)\n',
    )
    assert 'setattr(big_parts, "radius", abs)' in rewritten


def test_builtin_setattr_with_a_computed_name_refuses(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\nNAME = 'radius'\nsetattr(big, NAME, abs)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


def test_churn_keeps_a_symbol_history_dropped_in_rest(tmp_path, monkeypatch):
    _repo(
        tmp_path,
        monkeypatch,
        [
            "def f():\n    return 1\n\n\ndef old():\n    return 2\n\n\ndef g():\n    return 3\n",
            "def f():\n    return 1\n\n\ndef old():\n    return 4\n\n\ndef g():\n    return 3\n",
            "def f():\n    return 1\n\n\ndef g():\n    return 3\n",
        ],
    )
    spec = tmp_path / "split.toml"
    spec.write_text(
        '[[module]]\nname = "big"\nsource = "big.py"\nrest = "big.py"\n'
        '[module.targets]\n"parts.py" = ["f"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(split, "SPEC", spec)
    split.main(["churn", "--by", "commit", "--since", "2000-01-01", "--json", str(tmp_path / "o")])
    targets = json.loads((tmp_path / "o").read_text())["modules"]["big"]["targets"]
    # The edit to `old` (dropped since) stays with rest, never with f's parts.py.
    assert len(targets["parts.py"]["changes"]) == 1  # only the first commit adds f


def test_a_unit_reading_its_modules_name_never_moves_to_another_file(at):
    plan = at("def where():\n    return __name__\n", _spec('["where"]'))
    assert any("__name__" in refusal for refusal in plan.refusals)


def test_a_probe_compiling_the_source_is_a_source_reader(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_probe.py").write_text(
        'PROBE = r"""\ntext = open(path).read()\nexec(compile(text, path, "exec"), {})\n"""\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


@pytest.mark.parametrize(
    "use",
    [
        "def shadowed(big):\n    return big.radius(1)\n",
        "FOUND = [big.radius for big in []]\n",
        "def later(x=big.radius):\n    big = None\n    return big\n",
        "big = object()\nVALUE = big.radius\n",
    ],
)
def test_an_alias_name_bound_by_anything_but_its_import_refuses(at, tmp_path, use):
    # A parameter, comprehension target, local or reassignment named like the module
    # alias makes some loads mean something else; the script refuses rather than guess.
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n" + use, encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    assert not (tmp_path / "src" / "pkg" / "parts.py").exists()


def test_an_alias_imported_in_a_module_level_try_is_followed(at, tmp_path):
    rewritten = _importer_case(
        at,
        tmp_path,
        "def radius(x):\n    return x\n",
        '["radius"]',
        """\
        try:
            from pkg import big
        except ImportError:
            raise

        VALUE = big.radius(1)
        """,
    )
    assert "VALUE = big_parts.radius(1)" in rewritten


def test_a_direct_write_lands_where_the_name_is_looked_up(at, tmp_path):
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    rewritten = _importer_case(
        at, tmp_path, source, '["radius", "area"]', "from pkg import big\n\nbig.radius = abs\n"
    )
    assert "big_parts.radius = abs" in rewritten


@pytest.mark.parametrize(
    "use",
    [
        "delattr(big, 'radius')\n",
        "def test(monkeypatch):\n    monkeypatch.delattr(big, 'radius')\n",
    ],
)
def test_a_deletion_lands_where_the_name_is_looked_up(at, tmp_path, use):
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    rewritten = _importer_case(
        at, tmp_path, source, '["radius", "area"]', "from pkg import big\n\n" + use
    )
    assert "big_parts, " in rewritten or "big_parts," in rewritten


def test_an_alias_imported_in_a_class_body_refuses(at, tmp_path):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "class Holder:\n    from pkg import big\n\n    VALUE = big.radius(1)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


@pytest.mark.parametrize(
    "call",
    [
        "monkeypatch.setattr(big, name='radius', value=abs)",
        "monkeypatch.delattr(big, name='radius')",
    ],
)
def test_a_keyword_form_patch_of_the_split_module_refuses(at, tmp_path, call):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        f"from pkg import big\n\n\ndef test(monkeypatch):\n    {call}\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


def test_an_identity_attribute_stays_on_a_kept_module_and_refuses_on_a_package(at, tmp_path):
    rewritten = _importer_case(
        at,
        tmp_path,
        "def radius(x):\n    return x\n",
        '["radius"]',
        "from pkg import big\n\nNAME = big.__name__\n",
    )
    assert "NAME = big.__name__" in rewritten  # rest is big.py itself: same module object


def test_an_identity_attribute_of_a_package_conversion_refuses(at, tmp_path):
    spec = _spec('["radius"]').replace('rest = "src/pkg/big.py"', 'rest = "src/pkg/big/rule.py"')
    at("def radius(x):\n    return x\n\n\ndef other():\n    return 1\n", spec)
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\nNAME = big.__name__\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


@pytest.mark.parametrize(
    "importer",
    [
        "from pkg.big import *\n\nVALUE = radius(1)\n",
        (
            "try:\n    from pkg import big\nexcept ImportError:\n    import pkg.big as big\n\n"
            "VALUE = big.radius(1)\n"
        ),
    ],
    ids=["star", "conditional"],
)
def test_star_and_repeated_alias_imports_of_the_split_module_refuse(at, tmp_path, importer, capsys):
    # A star import binds whatever the rest exports; a second import of the alias would
    # not get the replacement import added beside the first.
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(importer, encoding="utf-8")
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    out = capsys.readouterr()
    assert "star import" in out.out + out.err or "more than once" in out.out + out.err


@pytest.mark.parametrize(
    ("member", "name"),
    [("def __hidden(self):\n        return 1", "__hidden"), ("__slot = 1", "__slot")],
)
def test_a_name_mangled_member_moved_to_a_mixin_is_refused(at, member, name):
    source = f"class Engine:\n    def run(self):\n        return 2\n\n    {member}\n"
    plan = at(source, _spec(f'["Engine.{name}"]'))
    assert any("name-mangled member" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize(
    "member",
    ["def moved(self, value=DEFAULT):\n        return value", "LIMIT = DEFAULT"],
)
def test_a_moved_member_reading_a_class_body_name_is_refused(at, member):
    # The class body runs the default (or the attribute's value); a mixin's body would
    # not see DEFAULT.
    source = (
        f"class Engine:\n    DEFAULT = 1\n\n    def run(self):\n        return 2\n\n    {member}\n"
    )
    name = "moved" if "def" in member else "LIMIT"
    plan = at(source, _spec(f'["Engine.{name}"]'))
    assert any("class-body name DEFAULT" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize(
    "importer",
    [
        "from pkg import big\n\nbig_parts = None\nVALUE = big.radius(1)\n",
        "from pkg import big\n\nVALUE = big.radius(1)\n\n\ndef f(big_parts):\n    return 1\n",
    ],
    ids=["earlier", "parameter"],
)
def test_a_generated_alias_name_already_bound_refuses(at, tmp_path, importer, capsys):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(importer, encoding="utf-8")
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    out = capsys.readouterr()
    assert "big_parts is already bound" in out.out + out.err


def test_an_all_keyword_patch_of_the_split_module_refuses(at, tmp_path, capsys):
    at("def radius(x):\n    return x\n", _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n\ndef test(monkeypatch):\n"
        "    monkeypatch.setattr(target=big, name='radius', value=abs)\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    out = capsys.readouterr()
    assert "by keyword" in out.out + out.err


def test_a_trailer_on_any_name_of_a_chained_assignment_moves_with_it(at):
    source = "A = B = 0\nB += 1\n\n\ndef use():\n    return A + B\n"
    plan = at(source, _spec('["A"]'))
    trailer = next(u for u, _ in plan.placed if u.kind == "trailer")
    assert (
        dict((u.name, t) for u, t in plan.placed)["A"]
        == dict((id(u), t) for u, t in plan.placed)[id(trailer)]
    )


def test_a_mixin_method_using_explicit_super_is_refused(at):
    source = """\
        class Engine:
            def run(self):
                return super(Engine, self).run()
        """
    plan = at(source, _spec('["Engine.run"]'))
    assert any("explicit super(...)" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize("binding", ["import math as DEFAULT", "if True:\n        DEFAULT = 1"])
def test_a_moved_member_reading_a_class_body_import_or_block_name_is_refused(at, binding):
    source = (
        f"class Engine:\n    {binding}\n\n    def run(self):\n        return 2\n\n"
        "    def moved(self, value=DEFAULT):\n        return value\n"
    )
    plan = at(source, _spec('["Engine.moved"]'))
    assert any("class-body name DEFAULT" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize(
    ("rest", "refused"), [("src/pkg/big.py", False), ("src/pkg/big/rule.py", True)]
)
def test_a_directly_imported_identity_attribute_stays_on_the_module(at, tmp_path, rest, refused):
    # `from pkg.big import __name__` reads the module object's identity, never a moved name.
    spec = _spec('["radius"]').replace('rest = "src/pkg/big.py"', f'rest = "{rest}"')
    at("def radius(x):\n    return x\n\n\ndef other():\n    return 1\n", spec)
    test = tmp_path / "tests" / "test_big.py"
    test.write_text("from pkg.big import __name__ as NAME, radius\n", encoding="utf-8")
    if refused:
        with pytest.raises(SystemExit):
            split.main(["apply", "big"])
        return
    split.main(["apply", "big"])
    rewritten = test.read_text(encoding="utf-8")
    assert "from pkg.big import __name__ as NAME" in rewritten
    assert "from pkg.parts import radius" in rewritten


def test_a_moved_name_rebound_in_module_level_control_flow_is_refused(at):
    source = "B = 1\nif ENABLED:\n    B = 2\n\n\ndef use():\n    return B\n"
    plan = at(source, _spec('["B"]'))
    assert any("B is rebound at module level" in refusal for refusal in plan.refusals)


def test_a_class_body_with_target_counts_as_a_class_name(at):
    source = (
        "class Engine:\n    with OPEN() as DEFAULT:\n        pass\n\n"
        "    def run(self):\n        return 2\n\n"
        "    def moved(self, value=DEFAULT):\n        return value\n"
    )
    plan = at(source, _spec('["Engine.moved"]'))
    assert any("class-body name DEFAULT" in refusal for refusal in plan.refusals)


def test_a_patch_and_a_read_of_the_same_name_in_two_files_refuses(at, tmp_path, capsys):
    # radius moves to parts.py, but only rest's area() looks it up: the patch would land
    # in rest while the test's own read of big.radius reads parts.
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    at(source, _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n\ndef test(monkeypatch):\n"
        "    monkeypatch.setattr(big, 'radius', abs)\n    assert big.radius(-1) == 1\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
    out = capsys.readouterr()
    assert "also read here" in out.out + out.err


def test_reading_the_original_before_patching_it_is_not_refused(at, tmp_path):
    # The common wrap: the read takes the original from its owner, the patch lands where
    # area() looks radius up; both stay right after the split.
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    at(source, _spec('["radius"]'))
    test = tmp_path / "tests" / "test_big.py"
    test.write_text(
        "from pkg import big\n\n\ndef test(monkeypatch):\n    original = big.radius\n"
        "    monkeypatch.setattr(big, 'radius', lambda x: original(x) + 1)\n"
        "    assert big.area(1) == 4\n",
        encoding="utf-8",
    )
    split.main(["apply", "big"])
    rewritten = test.read_text(encoding="utf-8")
    assert "original = big_parts.radius" in rewritten
    assert 'monkeypatch.setattr(big, "radius"' in rewritten


def test_a_class_body_match_case_binding_counts_as_a_class_name(at):
    source = (
        "class Engine:\n    match MODE:\n        case 1:\n            DEFAULT = 1\n\n"
        "    def run(self):\n        return 2\n\n"
        "    def moved(self, value=DEFAULT):\n        return value\n"
    )
    plan = at(source, _spec('["Engine.moved"]'))
    assert any("class-body name DEFAULT" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize(
    "use",
    [
        "NAMES = big.__dict__['radius']\n",
        "def test(monkeypatch):\n    monkeypatch.setattr(target='pkg.big.radius', value=abs)\n",
        (
            "def test(monkeypatch):\n    monkeypatch.setattr(big, 'radius', abs)\n\n"
            "    def later():\n        return big.radius(-1)\n\n    assert later() == 1\n"
        ),
    ],
    ids=["namespace-dunder", "keyword-dotted-string", "nested-read-after-patch"],
)
def test_namespace_dunders_keyword_strings_and_nested_reads_refuse(at, tmp_path, use):
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    at(source, _spec('["radius"]'))
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n\n" + use, encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])


def test_a_moved_name_captured_by_a_module_level_match_is_refused(at):
    source = "X = 0\nmatch VALUE:\n    case X:\n        pass\n\n\ndef use():\n    return X\n"
    plan = at(source, _spec('["X"]'))
    assert any("X is rebound at module level" in refusal for refusal in plan.refusals)


def test_a_unit_reading_its_loader_never_moves(at):
    plan = at("def loader():\n    return __loader__\n", _spec('["loader"]'))
    assert any("__loader__" in refusal for refusal in plan.refusals)


@pytest.mark.parametrize(
    ("helper", "test"),
    [
        (None, "    monkeypatch.setattr(big, 'radius', abs); assert big.radius(-1) == 1\n"),
        (
            "from pkg import big\n\n\ndef later():\n    return big.radius(-1)\n",
            "    monkeypatch.setattr(big, 'radius', abs)\n    assert helper.later() == 1\n",
        ),
    ],
    ids=["same-line", "helper-module"],
)
def test_a_read_after_a_retargeted_patch_on_one_line_or_in_a_helper_refuses(
    at, tmp_path, helper, test
):
    source = "def radius(x):\n    return x\n\n\ndef area(x):\n    return radius(x) ** 2\n"
    at(source, _spec('["radius"]'))
    if helper:
        (tmp_path / "tests" / "helper.py").write_text(helper, encoding="utf-8")
    (tmp_path / "tests" / "test_big.py").write_text(
        "from pkg import big\n\n\ndef test(monkeypatch):\n" + test, encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        split.main(["apply", "big"])
