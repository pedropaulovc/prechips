"""scripts/split_modules.py: unit extraction, name analysis, refusals and a real apply.

Each split runs on a throwaway package under tmp_path; nothing here reads or writes the
repository's own sources.
"""

import ast
import importlib.util
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
