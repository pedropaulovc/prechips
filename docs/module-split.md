# Module split plan

Status: **design only**. Nothing is moved by the PR that adds this page. Each split
below is its own later PR, made by re-running `scripts/split_modules.py` on the latest
`main` after the in-flight feature PRs (#251, #253, #254, #258, #263) land and the
coordinator says go.

Seven modules are touched by almost every feature PR:

| Module | Lines | Largest unit |
|---|---:|---|
| `src/prechips/kernel/freecad_job.py` | 14,323 | `class _Setup`, 9,897 lines (226 methods) |
| `src/prechips/sheet.py` | 10,249 | `class _Traveler`, 7,266 lines (218 methods) |
| `src/prechips/rules/coordinates.py` | 4,730 | `evaluate`, 638 lines |
| `src/prechips/kernel/render_diagram.py` | 4,029 | `class _Diagram`, 1,796 lines |
| `src/prechips/rules/zero_recipe.py` | 2,956 | `evaluate`, 453 lines |
| `src/prechips/model.py` | 2,103 | `InventoryItem`, 177 lines |
| `src/prechips/kernel/__init__.py` | 2,074 | `op_inputs`, 190 lines |

`rules/manual_arc.py` (407 lines) is also named in the collision list. Of the five
in-flight PRs, only #254 changes it, so it is not split (see
[What is not split](#what-is-not-split)).

## Evidence

All numbers below come from `uv run scripts/split_modules.py churn` on `main` at
`f5c7414`, so anyone can re-run them. The analysis:

* maps every hunk of every change to the top-level symbol it touches. Classes of 300 or
  more lines are mapped per method (`_Setup._render`). A change is either a merged PR
  (first-parent history since 2026-09-01: 28 changes) or a non-merge commit (673), plus
  the five in-flight branches diffed against their merge base;
* sets *sweeps* aside: changes that touch more than half of a module's symbols
  (formatting, renames, the initial integrations #8/#22/#120). There are 39–41 per
  module at commit level, which would otherwise make every symbol look equally hot;
* counts the **pairs of changes that edit the same file**, before the split and after the
  split the spec describes. Two changes that share no file cannot conflict textually.

### Where the in-flight PRs collide today

| PR | `model.py` | `sheet.py` | `freecad_job.py` | `kernel/__init__.py` |
|---|---|---|---|---|
| #251 joint compound | `CylindricalJoint`, new `JointCompound` | `operations`, `joint_text`, `compound_*` | `_Job._held`, `_Job._cylindrical_join` | – |
| #253 profiled blank | `Plan`, `Stock`, `StockComponent`, `Inventory`, new `ProfiledBlank` | `stock_line`, `_STOCK_FORMS` | `_Job.run`, `_Job._supplies`, `_envelope`, new `_profiled*` | `run_geometries`, `stock_inputs`, `_stock_envelope` |
| #254 bench saw | `Plan`, `Operation`, `SAW_ACTIONS` | `operations`, `speeds`, new `saw_*` | `_Setup._saw_*`, `_Setup._render_tool` | `op_inputs`, `_ENGINE_OP` |
| #258 guided sweep | `InventoryItem`, `Contour`, new `GuidedSweep` | `operations`, `contours`, `dro`, `__init__` | – | – |
| #263 build job once | – | – | – | `run_geometries` |

Most collisions are between *different* symbols of the same file. Only a few are real
same-symbol overlaps: `Plan` (#253, #254), `_Traveler.operations` (#251, #254, #258) and
`run_geometries` (#253, #263). No split removes those.

### Hot symbols (non-sweep commits since 2026-09-01)

| Module | Commits | Hottest symbols (commits) |
|---|---:|---|
| `freecad_job` | 125 | `_Setup._render` 25, `_Setup.__init__` 23, `_Setup._sample_facts` 21, `_Setup.run` 12, `_Setup._bounded` 11, `_Culled` 10 |
| `sheet` | 153 | `_Traveler.contours` 32, `_CSS` 27, `_Traveler.dro` 27, `_DUPLEX_JS` 21, `_Traveler.operations` 21, `shop_made_table` 15 |
| `coordinates` | 49 | `evaluate` 30, `_arc` 12, `_dome` 6 |
| `render_diagram` | 46 | `_Diagram.__init__` 20, `_labels` 13, `_measurements` 12 |
| `zero_recipe` | 54 | `evaluate` 39, `axis_recipe` 25, `DIRECTIONS` 22, `gauge_ready` 21 |
| `model` | 62 | `InventoryItem` 16, `Plan` 12, `Features` 9, `Operation` 9, `Hold` 7 |
| `kernel` | 51 | `op_inputs` 19, `_ENGINE_OP` 13, `build_job` 9 |

### Call graph and cycles

* The repository has **no import cycle between modules at top level**. It has 233
  function-level imports that keep it that way (`zero_recipe` 53, `tip_endpoints` 41,
  `kernel` 30, `cli` 22, `coordinates` 19). The split keeps every such import where it
  is and rewrites the ones that name a moved symbol.
* Inside each module the symbols are tightly coupled. `plan` reports the references that
  would cross files: 305 for `model`, 438 for `sheet` (plus 276 `self.` calls between
  `_Traveler` mixins) and 1,276 for `freecad_job` (plus 184 between `_Setup`/`_Job`
  mixins). Every split is a DAG of imports: shared helpers sink to a `common` file and
  nothing imports upward. The script refuses a cycle and names the symbols that cause
  it. Getting each spec below to "no refusal" took that loop: for example `_stadium`
  moved into `engine/sections.py`, and `_text` moved into `sheet/common.py`.

## Options evaluated

Each row is a spec entry in `scripts/split_modules.toml`; alternatives are
`[[variant]]` entries. "PR pairs" counts merged PRs since 2026-09-01; "commit pairs"
counts non-merge commits; "open pairs" counts the five in-flight PRs. Each is shown as
before → after.

| Module / option | Files | Largest file (lines) | PR pairs | Commit pairs | Open pairs |
|---|---:|---:|---|---|---|
| **model: per input family, plan by concern** | 12 | 608 | 55 → 33 | 1,891 → 692 | 6 → 3 |
| model: per input family only (task's sketch) | 5 | 830 | 55 → 43 | 1,891 → 993 | 6 → 6 |
| **sheet: per traveler card (mixins)** | 18 | 1,516 | 91 → 52 | 11,628 → 4,526 | 6 → 3 |
| sheet: helpers and literals only, `_Traveler` whole | 9 | 7,078 | 91 → 91 | 11,628 → 10,231 | 6 → 6 |
| **freecad_job: per job stage and op kind (mixins)** | 21 | 1,474 | 36 → 17 | 7,750 → 2,867 | 3 → 1 |
| freecad_job: helpers only, `_Job`/`_Setup` whole | 15 | 9,653 | 36 → 17 | 7,750 → 6,252 | 3 → 1 |
| **coordinates: per printed-coordinate family** | 11 | 877 | 10 → 6 | 1,176 → 581 | 0 → 0 |
| **kernel: job-input families beside the run seam** | 5 | 609 | 21 → 16 | 1,275 → 710 | 3 → 2 |
| render_diagram: per picture | 7 | 1,834 | 1 → 1 | 1,035 → 836 | 0 → 0 |
| zero_recipe: per zero source | 5 | 1,157 | 10 → 10 | 1,431 → 999 | 0 → 0 |

What the numbers say:

* **Splitting the two giant classes is what pays.** Moving helpers out of `sheet.py`
  and leaving `_Traveler` whole changes nothing (91 → 91). Splitting its methods into
  card mixins removes 61% of commit pairs. For `freecad_job`, the PR-level numbers tie
  (the 28 merged PRs are too coarse), but at commit level the mixin split removes 63%
  of pairs where helpers-only removes 19%.
* **`model` per input family alone is not enough.** Most feature PRs edit the plan
  schema, so that file stays shared by every open pair. Splitting the plan by concern
  (stock, holding, zero, operation, inspection, joints) halves the open pairs. The
  family-only variant also has an import cycle (`features` needs `Bounds` from the plan).
* **A split cannot help a hot dispatch function.** The open pairs that remain all run
  through one function: `_Traveler.operations`, `Plan` (its cross-field validators),
  `run_geometries`, `coordinates.evaluate` and `zero_recipe.evaluate`. Those need a
  per-op registry refactor by hand (see [Beyond the mechanical split](#beyond-the-mechanical-split)).
  That is also why `zero_recipe` (10 → 10) and `render_diagram` (1 → 1) gain little.

## Recommended layout

New features should land in new or small files: a new op adds a card mixin, an engine
mixin, a schema module and an op-inputs entry, not a hunk in a 10k-line file.

```
src/prechips/model/              plan.py (Plan, Setup) · common.py · stock.py · holding.py · zero.py
  (__init__: docstring only)     operation.py · inspection.py · joints.py · features.py
                                 inventory.py · policy.py · cutting_data.py
src/prechips/sheet/              traveler.py (_Traveler head, render_traveler) · common.py · html.py
  (__init__: docstring only)     styles.py (_CSS) · duplex.py (_DUPLEX_JS) · labels.py · solids.py
                                 card mixins: measurements · holding · clearance · dro · tools
                                 inspection · joints · stock · saw · contours · operations
src/prechips/rules/coordinates/  rule.py (evaluate) · frames · bands · grid · chains · stairs
                                 raster · lathe · checkpoints · manual · rotary
src/prechips/kernel/             __init__.py keeps discovery, cache and run (the patched seam)
                                 job_debts.py · job_ops.py · job_holds.py · job_engine.py
src/prechips/kernel/engine/      runs only inside freecadcmd; freecad_job.py keeps sys.path,
                                 pool wiring and main()
                                 common · pool · sections · faces · cull · tools · material
                                 job (_Job, run) · setup (_Setup head, run)
                                 _Setup/_Job mixins: joints · fixtures · render · checkpoints
                                 saw · removal · sweeps · holes · milling · turning · rotary
```

The full symbol-to-file mapping is the spec, not this page.

Package choices:

* `model`, `sheet` and `coordinates` become packages. Their `__init__.py` holds only a
  docstring; no re-exports, so a new schema class or card never edits a shared import
  list. The script rewrites every importer to the owning module, relative imports
  (`from .model import X` → `from .model.stock import X`) included. `rest` is a leaf
  module (`model/plan.py`, `sheet/traveler.py`, `coordinates/rule.py`), never
  `__init__`: an `__init__` that imports its own submodules, which import it back,
  would be a cycle.
* The `kernel/__init__.py` split keeps its new files as flat siblings: they are host
  code, already inside today's `kernel/*.py` digest.
* `render_diagram` is imported by the host (`prechips.kernel.render_diagram`) and by
  freecadcmd (`render_diagram`), so its split uses the dual import it already uses for
  `render_png` (`try: from .x import …` / `except ImportError: from x import …`).

## Hard constraints and how each is verified

### 1. `freecad_job.py` stays a single script path inside freecadcmd

`kernel/__init__.py::_execute` runs `freecadcmd <kernel>/freecad_job.py -- IN OUT`, and
`freecad_job._pool` starts workers with the same path. Both stay as they are: the entry
script keeps its name, its `sys.path.insert(0, <kernel dir>)`, `main()`, `_pool()` and
`_POOL_FUNCTIONS`. Everything else moves into `kernel/engine/`, which the entry imports
by absolute name (`from engine.job import run`) because the kernel directory is on
`sys.path`. Inside the package, modules import each other the same way
(`from engine.common import LIFT`).

Prototyped against the pinned FreeCAD 1.1.0 AppImage (SHA-256 `ef85f171…e2f0`,
extracted, `freecadcmd` → `AppRun freecadcmd`):

* a probe with a flat sibling, a subpackage with absolute and relative imports, and a
  mixin across subpackage files ran under freecadcmd and made `Part` solids in each;
* freecadcmd 1.1 on Linux runs the script with **`__name__` equal to its stem**
  (`entry`, not `__main__`) and registers it in `sys.modules` under both. That is why
  `freecad_job.py` ends with `if __name__ in {"__main__", "freecad_job"}`. One
  consequence: an engine module that imported `freecad_job` would get the
  *half-initialised* entry. The script refuses any import from a split file to the
  entry (and the DAG rule refuses it as a cycle anyway);
* none of the candidate names (`engine`, `job`, `setup`, `common`, `fixtures`, …)
  matches any of the 1,358 modules the AppImage's interpreter can import, so the
  subpackage shadows nothing there;
* the real split (below) ran the full kernel-required test suite under that AppImage.

Not exercised: Windows FreeCAD 1.1 (`C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe`),
which may bundle other packages. The first `freecad_job` split PR adds a
kernel-required test that runs under the discovered freecadcmd, so it also runs on
Windows wherever the suite runs there:

```python
def test_engine_imports_shadow_nothing_in_freecad(freecad_kernel, tmp_path):
    # inside freecadcmd: drop the kernel dir from sys.path, then for each top-level
    # module or package in kernel/ (freecad_job, boolean_pool, engine, …) assert
    # importlib.util.find_spec(name) is None; also record __name__ of the script.
```

There is also a static host test: no file under `kernel/engine/` imports `freecad_job`,
and every module the entry imports, transitively, resolves to a file under `kernel/`,
the stdlib, `FreeCAD` or `Part`.

### 2. Every engine source file stays in both digests

`_engine_digest` hashes `Path(__file__).parent.glob("*.py")`, and CI keys the geometry
cache on `hashFiles('src/prechips/kernel/*.py')`. Neither covers `kernel/engine/`. The
first PR that adds a kernel subpackage makes both recursive in the same commit as the
move:

```diff
-def _engine_digest():
+def _engine_digest(root=Path(__file__).parent):
     digest = hashlib.sha256()
-    for path in sorted(Path(__file__).parent.glob("*.py")):
-        digest.update(path.name.encode())
+    for path in sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
+        digest.update(path.relative_to(root).as_posix().encode())
         digest.update(path.read_bytes())
```

```diff
-hashFiles('src/prechips/kernel/*.py')
+hashFiles('src/prechips/kernel/**/*.py')
```

For top-level files the posix relative name is the bare file name, so the digest of
today's flat tree does not change; only the split's own moves invalidate the cache
(once, cold). The tests that ship with it:

* **every engine source is digested**: copy `kernel/` to `tmp_path`, then for each
  `*.py` found by an independent `os.walk`, append a byte and assert
  `_engine_digest(copy)` changes;
* **the engine's import closure is digested**: resolve `freecad_job.py`'s imports
  transitively (ast) and assert every local file is in that set (this catches an
  engine module importing `prechips.trig` from outside `kernel/`);
* **CI keys match the digest**: every `kernel-…` cache key and restore key in
  `.github/workflows/ci.yml` uses `hashFiles('src/prechips/kernel/**/*.py')`.

This change is not in the design PR: `kernel/__init__.py` is being edited by #253, #254
and #263 right now, and the digest change would cold-start the cache for nothing.

### 3. Reports and travelers stay byte-identical

`uv run scripts/split_modules.py snapshot OUT` runs `prechips check` and
`prechips traveler` on all four bundles. It records each exit code and the SHA-256 of
every output file in `OUT/manifest.json`, compares each traveler directory byte for byte
with the bundle's `expected/`, and with `--against` compares against an earlier
manifest (the one from `main`). Every split PR records both manifests, using a
persistent `PRECHIPS_KERNEL_CACHE`. A split that touches `kernel/` has to run cold,
because the engine digest changes. That cold run is what makes the geometry check
meaningful: the engine itself recomputes every fact.

Observed on `main` (`f5c7414`): pivot-shaft, rocker-arm and pivot-bracket exit 0 and the
cone exits 4 (its documented proof stop, see
[expected consumer CLI exits](../examples/README.md#expected-consumer-cli-exits)), for
both verbs; all four traveler outputs match `expected/` exactly.

Byte identity covers the checker's outputs, not timing facts or un-pooled booleans. The
`_POOL` case below shows why the script also needs static guards.

The traveler's printed content is byte-identical, so the blind machinist review in
AGENTS.md (required "after a change to what the traveler prints") is not triggered. A
split PR whose traveler bytes differ is wrong by definition and is not shipped.

### 4. Public CLI, schema and LF endings

The CLI (`cli.py`, entry point `prechips.cli:main`) is not split; only its imports are
rewritten. The schema is the TOML each input accepts. The pydantic classes keep their
names, fields and validators and only change module, and pydantic resolves postponed
annotations in the *defining* module. So the script's free-name analysis counts
annotation names, including quoted ones: a moved model imports every type its fields
name. The snapshot and the suite's schema tests cover acceptance and error text. The
script writes files with `newline="\n"`, and `ruff format` then normalises blank lines.

### 5. Wheel and sdist ship the new packages

`uv_build` packages all of `src/prechips/`, subpackages included. The split PR extends
`tests/test_cli.py::test_installed_artifact_console_script_matches_module`, which the CI
`build` job runs on both the wheel and the sdist, to compare the installed
distribution's `prechips/**` file list (`importlib.metadata.distribution("prechips").files`)
with `src/prechips/**` (`*.py` and `tokens.css`). A missing `model/stock.py` or
`kernel/engine/setup.py` then fails packaging CI, not a user's first run.

### 6. Seams that tests patch or probe

* **`monkeypatch.setattr`** (103 calls; for example `kernel._execute`,
  `coordinates._printed`, `"prechips.sheet.stock_states"`) patches the module the code
  *looks the name up in*. The script rewrites each patch to the single split file that
  reads the name. It refuses when two files read it: the `sheet` prototype first found
  `stock_states` read by both `_Traveler` and `dro`, and that turned out to be a scope
  bug in the script. The rewritten patch reads `"prechips.sheet.dro.stock_states"`.
* **In-kernel probes** (seven test files load `freecad_job.py` through `KERNEL_SOURCE`
  and read `job._Setup`, `kernel._grown`, …): the script rewrites `alias.name` for a
  moved name to `alias_<file>.name` and adds `import engine.<file> as alias_<file>`
  right after the probe's `exec_module(alias)`. It edits the literal's source text, so
  raw strings keep their backslashes.

## The split script

`scripts/split_modules.py` with the spec in `scripts/split_modules.toml`. The spec lists,
per module, the target files and fnmatch patterns over symbol names (`Class.method`
for methods of a split class); anything no pattern names stays in `rest`.

```
uv run scripts/split_modules.py churn [--by pr|commit] [--ref BRANCH ...] [--json OUT]
uv run scripts/split_modules.py plan NAME [--variant V]     # files, import edges, refusals
uv run scripts/split_modules.py apply NAME                  # writes the split
uv run scripts/split_modules.py snapshot OUT [--against M]  # byte-identity check
```

What `apply` does:

1. It parses the module into units: each top-level statement with its leading comments
   and decorators, and the methods of every class of 300 or more lines. Trailers such
   as `X |= {...}` or `InventoryItem.model_rebuild()` move with `X`.
2. For each file, it computes the module-level names each unit reads: scope-aware, with
   annotations, quoted annotations and decorators included.
3. It refuses, before writing anything:
   * an import cycle between the new files (it names the symbols on each edge);
   * a star import;
   * module state written under `global` and read from another file;
   * a moved method that uses zero-argument `super()`, `__class__` or a name-mangled
     `self.__x` (mixins would change their meaning);
   * a symbol that reads `__file__` and would move to another directory;
   * a name bound twice that would land in two files;
   * a monkeypatched name read from two files;
   * a plain `import prechips.<module>` it cannot rewrite;
   * a `file:line` citation of the module in docs or example data (AGENTS.md cites
     Python by line).
4. It writes each target: a docstring from the spec, `from __future__ import annotations`
   when the source has it, each source import reduced to the names this file reads,
   imports from sibling files, then the units in source order. Moved methods go into a
   `class <Class><File>:` mixin, and the class head inherits the mixins. Relative
   imports are re-levelled when the package depth changes.
5. It rewrites importers in `src/`, `tests/` and `scripts/` (module-level and
   function-level `from … import`, module-alias attribute uses, monkeypatch targets
   and in-kernel probes), then runs `ruff check --select I --fix` and `ruff format` on
   the files it wrote. It prints the prose mentions of the old path (for example
   `docs/plan.md` naming `src/prechips/model.py`) as `UPDATE BY HAND` lines.

### Prototype results

Each split ran in a throwaway worktree on `main` at `f5c7414`. Nothing was committed.

| Split | Result |
|---|---|
| `model` (the small module) | `apply`: 12 files, 27 importers rewritten. Ruff and format clean. Full suite (`-n 2 --dist loadscope`, `PRECHIPS_KERNEL_WORKERS=1`, `PRECHIPS_REQUIRE_KERNEL=1`, pinned AppImage): 9,423 passed, 83 skipped (82 for no print browser here, 1 packaging-only), 0 failed. Snapshot manifest identical to `main`'s, all four travelers equal to `expected/`. `uv build`: the wheel and sdist both contain all 78 files under `src/prechips/`, `model/` included. |
| `sheet` (mixins) | `apply`: 18 files, 10 `_Traveler` mixins, the `stock_states` monkeypatches retargeted to `sheet.dro`. Ruff clean. The pivot-shaft traveler is byte-identical to `expected/`. |
| `freecad_job` (FreeCAD) | `apply` after one hand prep commit (`_POOL` holder, below): 21 engine files, 14 mixins, 6 probe test files rewritten. **See PR body** for the kernel suite and cold snapshot. |

Gaps the prototypes found, to close in the split PRs:

* **`_POOL` (freecad_job)**: `main()` assigns it under `global` and `_ahead()`/`run`
  read it. Split naively, the readers would see `None` forever and every boolean would
  run un-pooled with byte-identical output. Only the `pool_answers` timing fact would
  show it. The script refuses this. A hand prep commit, first in that PR, replaces the
  global with a mutable holder in `engine/pool.py` (`_POOL["pool"]`) that `main` fills.
* **Dead duplicate (model)**: `model.py` defines `_unit` twice (lines 489 and 636); the
  first is shadowed and never runs. The split keeps both in `model/common.py` in order
  (the script refuses to separate them). Deleting the dead one is a separate fix.
* **Probe line length**: rewritten probe lines can pass 100 columns (two lines in
  `test_kernel_guard_frames.py`). Ruff does not reflow strings, so they are wrapped by
  hand in that PR.
* **Prose paths**: `AGENTS.md`, `examples/README.md` and five `docs/` pages name
  `src/prechips/model.py`; `examples/geometry/README.md` and `docs/rules-geometry.md`
  name `freecad_job.py`. These are updated by hand in each split PR, as AGENTS.md
  requires.

### Re-running at merge time

A split PR is one **mechanical commit**: the output of `apply` on its base, with no hand
edits. It is preceded by any hand **prep** commits (like `_POOL`) and followed by a hand
**docs** commit. When `main` moves, the split PR is never conflict-resolved. Instead:

```sh
git fetch origin main && git checkout -B refactor/split-model origin/main
git cherry-pick <prep commits>           # small, hand-made, re-checked
uv run scripts/split_modules.py apply model
uv run ruff check . && uv run ruff format --check . && uv run pytest -n 2 --dist loadscope
uv run scripts/split_modules.py snapshot out/split --against out/main/manifest.json
git commit -am "model: split per input family (mechanical, scripts/split_modules.py)"
git cherry-pick <docs commit>
```

If `apply` refuses (for example a new feature added a cycle or a `global`), the spec or
a prep commit changes; the moved code is never edited by hand. A new symbol that no
pattern names stays in `rest`, so `plan` after a rebase lists what to classify.

A feature branch opened before a split lands can port its change without hand-merging
the moved code:

1. Commit `apply` on the branch's merge base (S₀) and on the branch tip (S₁).
2. `git rebase --onto origin/main S₀ S₁`.

The branch's diff then arrives already in the split layout, and the only conflicts
left are real same-symbol ones.

## Sequence and estimates

One module per PR, lowest risk first. All of them start after #251, #253, #254, #258 and
#263 land.

| # | Split | Risk | Why here | Estimate |
|---|---|---|---|---|
| 1 | `model` → `model/` | Low: host only, no kernel digest, pydantic covered by the suite | All four feature PRs collide here; open pairs 6 → 3 | 0.5 day |
| 2 | `kernel/__init__.py` → `job_*.py` | Low–medium: host only but digested, so cache goes cold once | Ships the digest/CI-key change and its tests alone, before any FreeCAD code moves | 1 day |
| 3 | `rules/coordinates.py` → `coordinates/` | Medium: four monkeypatches, 19 lazy imports | 1,176 → 581 commit pairs | 1 day |
| 4 | `sheet.py` → `sheet/` | Medium: 10 mixins, 276 cross-mixin calls | Largest commit churn (153); open pairs 6 → 3 | 1.5 days |
| 5 | `kernel/freecad_job.py` → `kernel/engine/` | High: runs in freecadcmd, `_POOL` prep, probes, cold geometry | 7,750 → 2,867 commit pairs; open pairs 3 → 1 | 2.5 days |
| 6 | `render_diagram`, `zero_recipe` (optional) | Medium (dual host/FreeCAD imports) / Low | Little gain (1 → 1 and 10 → 10 PR pairs); revisit with fresh `churn` data | 1 day each |

Each estimate covers running the script on fresh `main` and reaching the clean `plan`.
It also covers one full suite run (cold when the kernel digest changes), the snapshot
against `main`, the prose updates and review rounds.

## Beyond the mechanical split

The remaining shared files are dispatch points that every new op edits:
`_Traveler.operations` (270 lines), `_Setup.__init__`/`run`, `Plan` validators,
`coordinates.evaluate`, `zero_recipe.evaluate`, `op_inputs` and `_ENGINE_OP`. A split
moves them intact. Turning each into a per-op registry (an op kind maps to its card
method, engine handler and input builder) is a behaviour-preserving refactor, but not a
mechanical one, so it is proposed separately, after the splits, one dispatcher per PR,
verified by the same snapshot.

## What is not split

`rules/manual_arc.py` (407 lines, 15 commits since 2026-09-01, one of the five open PRs)
is small and cohesive. Splitting it would add files without removing a collision.
