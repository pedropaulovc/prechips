# Module split plan

This internal design records the evidence and constraints for splitting large modules
without changing their behavior. It is partly implemented:
[`rules/zero_recipe/`](../src/prechips/rules/zero_recipe/) is already a package.
The other layouts below remain proposals, not a map of the current source tree.

Use [architecture](internals/architecture.md) for current module ownership and
[development](internals/development.md) for contributor checks. The
[CLI catalog](reference/cli.md) and [Python catalog](reference/python-api.md) describe
the interfaces consumers can use.

The measurements, collision list, prototypes and scheduling estimates below are a
historical snapshot at `f5c7414`, unless a section explicitly identifies a later
change. They are not fresh counts or current PR status. Before another split,
rerun the read-only `churn` and `plan` modes of `scripts/split_modules.py`
against the intended base and review the spec. `apply` writes source; use it
only in the isolated refactor workflow described below.

## Current status and navigation

- [Evidence](#evidence) records why the split was proposed.
- [Recommended layout](#recommended-layout) describes the target, not the current tree.
- [Hard constraints](#hard-constraints-and-how-each-is-verified) define behavior preservation.
- [The split script](#the-split-script) covers rewriting, refusals and known seams.
- [Sequence and estimates](#sequence-and-estimates) retains the original scheduling rationale.
- [Open review notes](#open-review-notes) retains unresolved design constraints.

The original analysis identified seven frequently edited modules:

| Module | Lines | Largest unit |
|---|---:|---|
| `src/prechips/kernel/freecad_job.py` | 14,323 | `class _Setup`, 9,897 lines (226 methods) |
| `src/prechips/sheet.py` | 10,249 | `class _Traveler`, 7,266 lines (218 methods) |
| `src/prechips/rules/coordinates.py` | 4,730 | `evaluate`, 638 lines |
| `src/prechips/kernel/render_diagram.py` | 4,029 | `class _Diagram`, 1,796 lines |
| `src/prechips/rules/zero_recipe.py` (split since: `rules/zero_recipe/`) | 2,956 | `evaluate`, 453 lines |
| `src/prechips/model.py` | 2,103 | `InventoryItem`, 177 lines |
| `src/prechips/kernel/__init__.py` | 2,074 | `op_inputs`, 190 lines |

The snapshot also named `rules/manual_arc.py` (407 lines). Only #254 among the five
then-open PRs changed it, so the proposed split excluded it
(see [What is not split](#what-is-not-split)).

## Evidence

The evidence came from `uv run scripts/split_modules.py churn` on `main` at
`f5c7414`. Reproducing that snapshot requires that revision; running the command on
current code produces a new analysis. The script:

* maps each changed hunk to its top-level symbol, or to a method for classes of 300
  or more lines (`_Setup._render`). The population was first-parent history since
  2026-09-01: 28 merged PRs and 673 non-merge commits, plus the five then-open
  branches diffed against their merge bases;
* excludes sweeps that touch more than half a module's symbols, such as formatting,
  renames and initial integrations #8/#22/#120. There were 39 to 41 sweeps per module
  at commit level; including them would make most symbols appear equally hot;
* counts pairs of changes that edit the same file before and after the proposed
  split. Changes that share no file cannot conflict textually.

### Where the in-flight PRs collide today

| PR | `model.py` | `sheet.py` | `freecad_job.py` | `kernel/__init__.py` |
|---|---|---|---|---|
| #251 joint compound | `CylindricalJoint`, new `JointCompound` | `operations`, `joint_text`, `compound_*` | `_Job._held`, `_Job._cylindrical_join` | none |
| #253 profiled blank | `Plan`, `Stock`, `StockComponent`, `Inventory`, new `ProfiledBlank` | `stock_line`, `_STOCK_FORMS` | `_Job.run`, `_Job._supplies`, `_envelope`, new `_profiled*` | `run_geometries`, `stock_inputs`, `_stock_envelope` |
| #254 bench saw | `Plan`, `Operation`, `SAW_ACTIONS` | `operations`, `speeds`, new `saw_*` | `_Setup._saw_*`, `_Setup._render_tool` | `op_inputs`, `_ENGINE_OP` |
| #258 guided sweep | `InventoryItem`, `Contour`, new `GuidedSweep` | `operations`, `contours`, `dro`, `__init__` | none | none |
| #263 build job once | none | none | none | `run_geometries` |

Most snapshot collisions involved different symbols in one file. The same-symbol
overlaps were `Plan` (#253, #254), `_Traveler.operations` (#251, #254, #258) and
`run_geometries` (#253, #263). Moving files cannot remove those overlaps.

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

* The snapshot had no top-level import cycle between modules. Its 233
  function-level imports helped avoid cycles (`zero_recipe` 53, `tip_endpoints` 41,
  `kernel` 30, `cli` 22, `coordinates` 19). A split must preserve those import
  locations and rewrite references to moved symbols.
* The proposed boundaries crossed 305 references in `model`, 438 in `sheet`
  (plus 276 `self.` calls between `_Traveler` mixins), and 1,276 in `freecad_job`
  (plus 184 between `_Setup`/`_Job` mixins). Each split must remain an import DAG:
  shared helpers belong in a lower-level `common` module, with no upward import.
  The script refuses cycles and names the responsible symbols. During prototype
  design, that check moved `_stadium` to `engine/sections.py` and `_text` to
  `sheet/common.py`.

## Options evaluated

Each option was a spec entry in `scripts/split_modules.toml`; alternatives used
`[[variant]]` entries. "PR pairs" counts merged PRs since 2026-09-01, "commit pairs"
counts non-merge commits, and "open pairs" counts the five then-open PRs. Each cell
shows before → after. These are snapshot comparisons, not current forecasts.

| Module / option | Files | Largest file (lines) | PR pairs | Commit pairs | Open pairs |
|---|---:|---:|---|---|---|
| model: per input family, plan by concern (selected) | 12 | 608 | 55 → 33 | 1,891 → 692 | 6 → 3 |
| model: per input family only (task's sketch) | 5 | 830 | 55 → 43 | 1,891 → 993 | 6 → 6 |
| sheet: per traveler card, mixins (selected) | 18 | 1,516 | 91 → 52 | 11,628 → 4,526 | 6 → 3 |
| sheet: helpers and literals only, `_Traveler` whole | 9 | 7,078 | 91 → 91 | 11,628 → 10,231 | 6 → 6 |
| freecad_job: per job stage and op kind, mixins (selected) | 21 | 1,474 | 36 → 17 | 7,750 → 2,867 | 3 → 1 |
| freecad_job: helpers only, `_Job`/`_Setup` whole | 15 | 9,653 | 36 → 17 | 7,750 → 6,252 | 3 → 1 |
| coordinates: per printed-coordinate family (selected) | 11 | 877 | 10 → 6 | 1,176 → 581 | 0 → 0 |
| kernel: job-input families beside the run seam (selected) | 5 | 609 | 21 → 16 | 1,275 → 710 | 3 → 2 |
| render_diagram: per picture | 7 | 1,834 | 1 → 1 | 1,035 → 836 | 0 → 0 |
| zero_recipe: per zero source | 5 | 1,157 | 10 → 10 | 1,431 → 999 | 0 → 0 |

The snapshot supported these choices:

* Splitting `_Traveler` into card mixins removed 61% of commit pairs. Moving only
  helpers left all 91 PR pairs. For `freecad_job`, both options tied at PR level,
  where the 28 merged PRs were too coarse to distinguish them. At commit level,
  mixins removed 63% of pairs and helpers alone removed 19%.
* Splitting `model` only by input family left the plan schema shared by every open
  pair. Splitting the plan by concern (stock, holding, zero, operation, inspection,
  joints) halved the open pairs. The family-only variant also introduced a cycle:
  `features` needed `Bounds` from the plan.
* Shared dispatch functions remained shared: `_Traveler.operations`, `Plan`
  cross-field validators, `run_geometries`, `coordinates.evaluate` and
  `zero_recipe.evaluate`. They need a separate
  [registry refactor](#beyond-the-mechanical-split). This also explains the small
  PR-pair gains for `zero_recipe` (10 → 10) and `render_diagram` (1 → 1).

## Recommended layout

The proposed layout gives a new operation a card mixin, an engine mixin, a schema
module and an op-inputs entry, reducing edits to the large shared files. This is a
target layout fragment, not an executable command or a current directory listing:

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

The spec owns the complete symbol-to-file mapping.

The package design has three constraints:

* Proposed `model`, `sheet` and `coordinates` packages have docstring-only
  `__init__.py` files, with no re-exports. Adding a class or card therefore does
  not edit a shared import list. The script rewrites every importer to the owning
  module, including relative imports
  (`from .model import X` → `from .model.stock import X`). `rest` is a leaf
  (`model/plan.py`, `sheet/traveler.py`, `coordinates/rule.py`), never `__init__`.
  An `__init__` that imports submodules which import it back would create a cycle.
* Proposed `job_*.py` siblings of `kernel/__init__.py` are host code. Under the
  current explicit `ENGINE_SOURCES` contract they must stay out of the engine
  digest; changes they make to job content are covered by the job key.
* `render_diagram` runs on the host (`prechips.kernel.render_diagram`) and in
  freecadcmd (`render_diagram`). Its proposed split must retain the existing dual
  import pattern used for `render_png`
  (`try: from .x import …` / `except ImportError: from x import …`).

## Hard constraints and how each is verified

### 1. `freecad_job.py` stays a single script path inside freecadcmd

`kernel/__init__.py::_execute` runs
`freecadcmd <kernel>/freecad_job.py -- IN OUT`, and `freecad_job._pool` starts
workers through that same path. A split must preserve the
entry script's name, `sys.path.insert(0, <kernel dir>)`, `main()`, `_pool()` and
`_POOL_FUNCTIONS`. The proposed `kernel/engine/` package holds the remaining code.
The entry imports it by absolute name (`from engine.job import run`), with the kernel
directory on `sys.path`; package modules use imports such as
`from engine.common import LIFT`.

The historical prototype used the pinned FreeCAD 1.1.0 AppImage
(SHA-256 `ef85f171…e2f0`, extracted, `freecadcmd` → `AppRun freecadcmd`):

* a probe with a flat sibling, a subpackage with absolute and relative imports, and a
  mixin across subpackage files ran under freecadcmd and made `Part` solids in each;
* freecadcmd 1.1 on Linux ran the script with `__name__` equal to its stem
  (`entry`, not `__main__`) and registered both names in `sys.modules`. This is why
  `freecad_job.py` ends with `if __name__ in {"__main__", "freecad_job"}`. An engine
  module importing `freecad_job` would receive the half-initialized entry.
  The split script must refuse imports back to the entry; the DAG check also
  rejects that cycle;
* none of the candidate names (`engine`, `job`, `setup`, `common`, `fixtures`, …)
  matches any of the 1,358 modules the AppImage's interpreter can import, so the
  subpackage shadows nothing there;
* the split prototype below exercised the kernel-required test suite under that
  AppImage. Its recorded failures remain part of the evidence.

That prototype did not exercise Windows FreeCAD 1.1 at the illustrative path
`C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe`; this path is not an automatic
discovery claim. Windows may bundle different packages. The proposed engine split
therefore requires a kernel test under the discovered launcher. This Python fragment
specifies the test's intent; it has no implementation body and is not runnable:

```python
def test_engine_imports_shadow_nothing_in_freecad(freecad_kernel, tmp_path):
    # inside freecadcmd: drop the kernel dir from sys.path, then for each top-level
    # module or package in kernel/ (freecad_job, boolean_pool, engine, …) assert
    # importlib.util.find_spec(name) is None; also record __name__ of the script.
```

The split also requires a static host test: no `kernel/engine/` file may import
`freecad_job`, and every transitive entry import must resolve under `kernel/`, in the
stdlib, or to `FreeCAD` or `Part`.

### 2. Every engine source file stays in both digests

The current engine digest contract, introduced by #285 after the original analysis,
is explicit. `kernel/__init__.py` hashes the names and bytes in `ENGINE_SOURCES`:
`freecad_job.py` and its five transitive local imports. CI keys the geometry cache
with the resulting `PRECHIPS_ENGINE_DIGEST`. `tests/test_engine_digest.py` pins the
boundary. The listed set must match all local files reachable from the entry,
including future nested names such as `engine.job`. Editing a listed file must
change the digest; editing host-only kernel code must not.

Future splits must preserve that boundary:

* A `freecad_job` split must add every new `kernel/engine/*.py` file and
  `engine/__init__.py` to `ENGINE_SOURCES` in the same mechanical commit, using the
  spec's file list. Missing files must fail
  `test_engine_sources_cover_every_module_the_engine_imports`.
* A `kernel/__init__.py` split must keep host-only `job_*.py` files outside
  `ENGINE_SOURCES`, as pinned by
  `test_host_only_kernel_edits_keep_the_engine_digest`. The proposed spec leaves
  `ENGINE_SOURCES` and `_engine_digest` in `__init__.py`.
* A `render_diagram` split must add its engine-imported files in the same commit.
* Splits outside `kernel/` (`zero_recipe`, `coordinates`, `model`, `sheet`) do not
  change the engine digest.

### 3. Reports and travelers stay byte-identical

`uv run scripts/split_modules.py snapshot OUT` runs `prechips check` and
`prechips traveler` on all four bundles. It records exits and output-file SHA-256
values in `OUT/manifest.json`, compares each traveler directory byte for byte with
the bundle's `expected/`, and uses `--against` to compare with an earlier manifest.
Each split PR must retain both manifests and use a persistent
`PRECHIPS_KERNEL_CACHE`. An engine-source split changes the digest, so its cold
snapshot must recompute geometry rather than reuse the old engine's cache.

At `f5c7414`, pivot-shaft, rocker-arm and pivot-bracket exited 0 and the cone
exited 4 for both verbs. The cone's stop was documented under
[expected consumer CLI exits](../examples/README.md#expected-consumer-cli-exits).
All four traveler outputs matched `expected/` exactly. These are historical results,
not the expected exits of every current checkout.

Output identity does not establish unchanged timing or pooled boolean execution.
The `_POOL` case below requires a static guard as well.

A mechanical split must not change printed bytes. AGENTS.md requires blind
machinist review "after a change to what the traveler prints"; byte-identical
output does not trigger that requirement. A split PR whose traveler bytes differ
violates this contract and MUST NOT SHIP. Investigation or a completed review
does not waive byte identity for a mechanical split.

### 4. Public CLI, schema and LF endings

The proposed splits leave the CLI (`cli.py`, entry point `prechips.cli:main`) intact
apart from imports. Accepted TOML is the schema contract. Pydantic classes retain
their names, fields and validators while changing modules. Because Pydantic resolves
postponed annotations in the defining module, the script's free-name analysis must
include quoted annotations and import every field type in its new owner. Snapshot
and schema checks cover acceptance and error text. The script writes LF with
`newline="\n"`; `ruff format` normalizes blank lines.

### 5. Wheel and sdist ship the new packages

`uv_build` includes `src/prechips/` subpackages. A split PR must extend
`tests/test_cli.py::test_installed_artifact_console_script_matches_module` so CI's
wheel and sdist checks compare
`importlib.metadata.distribution("prechips").files` with the source `prechips/**`
file list (`*.py` and `tokens.css`). A missing proposed `model/stock.py` or
`kernel/engine/setup.py` must fail packaging checks before distribution.

### 6. Seams that tests patch or probe

* The snapshot contained 103 `monkeypatch.setattr` calls, including
  `kernel._execute`, `coordinates._printed` and `"prechips.sheet.stock_states"`.
  A patch must target the module where the caller looks up the name. The script
  rewrites to that file and refuses an ambiguous target. In the sheet prototype,
  `stock_states` appeared to have two readers because of a scope-analysis bug;
  after correction its target was `"prechips.sheet.dro.stock_states"`.
* In-kernel probes are test string literals that load `freecad_job.py` with
  `importlib.util.module_from_spec`. The path comes from whatever variable the test
  uses: `KERNEL_SOURCE`, `ENGINE`, `CULLED_ENGINE`, `POOL_PROBE_ENGINE`, or a fixture.
  The script finds probes by that loader, not by the variable. It rewrites a read
  `alias.name` of a moved name, in the loader literal and in every other literal of the
  file (probe fragments joined to a loader), to `alias_<file>.name`. It adds
  `import engine.<file> as alias_<file>` after the loader's `exec_module(alias)`, at
  that line's indentation. A write `alias.name = ...` is rewritten like a monkeypatch,
  to the one file that looks the name up, and refused if more than one file does. It
  edits the literal's source text, so raw strings keep their backslashes.
* Tests using `ast.parse`, `inspect.getsource`, built-in `compile` or `exec`
  (including probe scripts) may reconstruct functions from module source.
  `test_kernel_checkpoints.py` and `test_render_png.py` did this for
  `freecad_job.py`. The script cannot port those readers automatically.
  The spec must classify every such file in `[parses_source]` and name its source
  modules. Unlisted readers are refused; affected classified readers are reported
  as `UPDATE BY HAND` for a separate hand edit in the split PR.

## The split script

`scripts/split_modules.py` reads `scripts/split_modules.toml`. For each module the
spec names target files and fnmatch patterns over symbols (`Class.method` for split
classes). Unmatched symbols stay in `rest`. Command syntax:

```
uv run scripts/split_modules.py churn [--by pr|commit] [--ref BRANCH ...] [--json OUT]
uv run scripts/split_modules.py plan NAME [--variant V]     # files, import edges, refusals
uv run scripts/split_modules.py apply NAME                  # writes the split
uv run scripts/split_modules.py snapshot OUT [--against M]  # byte-identity check
```

The `apply` operation follows this sequence:

1. It parses the module into units: each top-level statement with its leading comments
   and decorators, and the methods of every class of 300 or more lines. Trailers such
   as `X |= {...}` or `InventoryItem.model_rebuild()` move with `X`.
2. For each file, it computes the module-level names each unit reads: scope-aware, with
   annotations, quoted annotations and decorators included.
3. It refuses, before writing anything:
   * an import cycle between the new files (it names the symbols on each edge);
   * a star import, in the module or of it in an importer;
   * module state written under `global` and read from another file;
   * a moved member that uses `super()` or `super(Cls, self)`, `__class__`, a name-mangled
     `self.__x`, or is itself named `__x`, or whose decorators, defaults, annotations
     or value read a name the class body binds (mixins would change their meaning);
   * a symbol that reads `__file__`, `__name__`, `__spec__`, `__package__` or `__doc__`
     and would move to another file (each file has its own);
   * a name bound twice that would land in two files;
   * a probe's `alias.name = ...` of a name read from two files; and, outside
     `tests/`, a monkeypatched name read from two files, or a monkeypatch whose landing
     file differs from the name's owner while the same function (or one nested in it)
     reads the name after patching it. In `tests/` those monkeypatches become
     `patch_split` calls (below);
   * a namespace dunder of the split module (`__dict__`, `__all__`…), which loses the
     moved names; identity attributes such as `__name__` stay on a kept module;
   * a moved name rebound by a module-level `if`/`try`/`for`/`with` block that stays in
     `rest`;
   * a `setattr`, `getattr` or `hasattr` on the split module with a computed name;
   * such a call (or a monkeypatch) naming its target, name or value by keyword, the
     target being a module alias or a dotted `"prechips.<module>.name"` string;
   * a generated `<alias>_<file>` import name that the importer already binds;
   * the module alias used as a value (in a list, passed on, compared with `is`), unless
     the spec says `value_uses = "rest"`. That setting means such a value stands for the
     module's entry point that `rest` keeps, such as a rule's `evaluate`, and the value
     is rebound to `rest`. The suite checks the claim;
   * a file that parses, compiles or executes source and that the spec has not
     classified (section 6);
   * a plain `import prechips.<module>` it cannot rewrite, or a module alias imported
     twice in one scope (as in `try`/`except`), since the replacement import goes beside
     only one of them;
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
   the files it wrote, failing if either Ruff step fails. It prints the prose mentions of
   the old path (for example `docs/plan.md` naming `src/prechips/model.py`) and the
   `[parses_source]` readers to port as `UPDATE BY HAND` lines.
6. It never stages anything: new files are untracked until `git add -A`.

### Prototype results

The following results were recorded in throwaway worktrees at `f5c7414`; no split
was committed by those prototype runs. They do not establish current validation.

| Split | Result |
|---|---|
| `model` (the small module) | `apply`: 12 files, 27 importers rewritten. Ruff and format clean. Full suite (`-n 2 --dist loadscope`, `PRECHIPS_KERNEL_WORKERS=1`, `PRECHIPS_REQUIRE_KERNEL=1`, pinned AppImage): 9,423 passed, 83 skipped (82 for no print browser here, 1 packaging-only), 0 failed. Snapshot manifest identical to `main`'s, all four travelers equal to `expected/`. `uv build`: the wheel and sdist both contain all 78 files under `src/prechips/`, `model/` included. |
| `sheet` (mixins) | `apply`: 18 files, 10 `_Traveler` mixins, the `stock_states` monkeypatches retargeted to `sheet.dro`. Ruff clean. The pivot-shaft traveler is byte-identical to `expected/`. |
| `freecad_job` (FreeCAD) | `apply` after one hand prep commit (`_POOL` holder, below): 21 engine files, 14 mixins, 6 probe test files rewritten. Under the pinned AppImage with a fresh `PRECHIPS_KERNEL_CACHE` that only the split engine filled, the snapshot manifest is identical to `main`'s and all four travelers equal `expected/`. Cold rocker-arm `check`: `main` 537 s, split 501 s, reports byte-identical. Full suite of that first prototype: 9,115 passed, 11 failed, 297 errors, 83 skipped. Every failure traced to a test seam the first script did not handle: probes loading the entry through `ENGINE`/`CULLED_ENGINE`/a fixture, probe fragments, two tests that rebuild code from `freecad_job.py`'s AST, and probes that patch `_culled_common`/`_face_samples`. The fixed script now rewrites the first two and refuses the rest: `_culled_common` is read from 2 files and `_face_samples` from 8. So the engine split needs hand prep before `apply` (below); it is not mechanical yet. |

The prototypes identified these preparation and hand-edit requirements:

* `_POOL` in `freecad_job`: `main()` assigns it under `global`, and `_ahead()`/`run`
  read it. Split naively, the readers would see `None` forever and every boolean would
  run un-pooled with byte-identical output. Only the `pool_answers` timing fact would
  show it. The script refuses this. A hand prep commit, first in that PR and still inside
  `freecad_job.py`, replaces the global with a mutable holder (`_POOL = {"pool": None}`,
  set by `main` as `_POOL["pool"] = ...`). The spec then moves `_POOL` and `_ahead` into
  `engine/pool.py`, which therefore does not exist before `apply` (it refuses an
  existing target).
* Shared engine probe patches: `test_kernel_pose_reuse.py`
  replaces `engine._culled_common`, read after the split by `engine/cull.py` and the
  entry's `_POOL_FUNCTIONS`. `test_kernel_region_geometry.py` replaces
  `engine._face_samples`, read by 8 engine files. A hand prep commit makes those probes
  patch each reading module (or makes the callers read the function through one
  module) before `apply`.
* AST-reading tests: `pure_chain_regeneration` and `stock_dispatch` in
  `test_kernel_checkpoints.py`, and `test_render_png.py`, rebuild functions from
  `freecad_job.py`'s AST. In that PR they read the engine files that now hold those
  functions (a hand commit after the mechanical one).
* Historical duplicate in `model`: the snapshot's `model.py` defined `_unit` twice
  (lines 489 and 636). The first definition was shadowed and never ran. The prototype
  kept both in `model/common.py` in source order; the script refused to separate
  them. Deleting the dead definition was outside the mechanical move.
* Probe line length: rewritten probe lines can pass 100 columns (two lines in
  `test_kernel_guard_frames.py`). Ruff does not reflow strings, so they are wrapped by
  hand in that PR.
* Computed-name patches in `zero_recipe`: `tests/test_validate_examples.py`
  patches and reads carry helpers through `forge_carry(monkeypatch, target)`
  (`getattr`/`setattr(zero_recipe, target)`), and patches `_position`, which four
  split files read. No hand prep: a patch the script cannot land in one file (a
  computed name, a name several split files look up, or a patch followed by a read
  that would reach another file) is rewritten in tests to
  `patch_split(monkeypatch, "<module>", name, value)` from the generated
  `tests/split_patch.py`. It patches the name in every split file that binds it, which
  is what one patch of the unsplit module did; `split_attr` reads it the same way.
  Outside `tests/` such a patch still refuses.
* Cold kernel deadline: the first cold engine snapshot gave rocker-arm exit 2
  because its kernel job hit the 600 s deadline. Timed alone, the job takes about 500 s
  cold with `PRECHIPS_KERNEL_WORKERS=1` on 4 vCPUs, on `main` as well as on the split.
  So a split PR runs its cold snapshot with nothing else on the machine, and checks
  any timeout against `main` cold before calling it a regression.
* Prose paths: snapshot references in `AGENTS.md`, `examples/README.md` and five
  `docs/` pages named `src/prechips/model.py`; `examples/geometry/README.md` and
  `docs/rules-geometry.md` named `freecad_job.py`. Each future split must find and
  update affected prose references by hand, as AGENTS.md requires.

### Re-running at merge time

Keep the generated move in one mechanical commit, with no hand edits. Put hand
preparation such as `_POOL` before it and documentation changes after it. When the
base advances, regenerate the split instead of resolving conflicts in moved code.
The historical shell recipe below is schematic: placeholders must be replaced and
branch-changing commands belong only in a disposable or otherwise safe worktree.

```sh
git fetch origin main && git checkout -B refactor/split-model origin/main
git cherry-pick <prep commits>           # small, hand-made, re-checked
uv run scripts/split_modules.py apply model
uv run ruff check . && uv run ruff format --check . && uv run pytest -n 2 --dist loadscope
uv run scripts/split_modules.py snapshot out/split --against out/main/manifest.json  # fresh dir
git add -A    # apply's new files are untracked until staged
git commit -m "model: split per input family (mechanical, scripts/split_modules.py)"
git cherry-pick <docs commit>
```

If `apply` refuses a cycle, `global` or another unsupported shape, change the spec or
add a preparation commit. Do not hand-edit the generated move. Unmatched new symbols
stay in `rest`; inspect `plan` after updating the base to classify them.

A feature branch opened before the split can be transformed in the same layout
before replaying its change. This historical shell fragment also changes branches
and creates commits; it is not a command to run in an active shared checkout:

```sh
base=$(git merge-base origin/main feature)
git checkout --detach "$base" && uv run scripts/split_modules.py apply model
git add -A && git commit -qm "split at base" && s0=$(git rev-parse HEAD)
git checkout --detach feature && uv run scripts/split_modules.py apply model
git add -A && tree=$(git write-tree)
s1=$(git commit-tree "$tree" -p "$s0" -m "feature, in the split layout")
git checkout -B feature-split "$s1" && git rebase --onto origin/main "$s0"
```

S₁ is a child of S₀, so S₀..S₁ contains only the feature's change in the split
layout. The rebase replays that change, not the unsplit feature commits; remaining
conflicts are same-symbol overlaps. Use the script and spec revision from main's
split commit. In the recorded throwaway-clone experiment, editing `Policy` in
`model.py` produced a 2-line change to `model/policy.py` above the split base.

## Sequence and estimates

The original schedule used one module per PR, rerunning the script on the latest
`origin/main` after feature work stopped editing that module. By its 2026-10-17
schedule update, #251, #253, #254 and #263 had landed; it still listed #258/#267/#278
(guided sweep: `sheet.py`, `freecad_job.py`, `model.py`, `coordinates.py`,
`render_diagram.py`), #279 (`freecad_job.py`), #280 (`coordinates.py`) and #285
(`kernel/__init__.py` and engine digest) as scheduling constraints. These are
historical branch states. `zero_recipe` was chosen first because no listed open PR
edited it, despite its small measured gain; that split has since shipped.

The original estimates below are retained for rationale, not as delivery promises.
Row 3 predates the explicit digest boundary: a host-only split now stays outside
`ENGINE_SOURCES` and does not by itself make the geometry cache cold.

| # | Split | Risk | Why here | Estimate |
|---|---|---|---|---|
| 1 | `rules/zero_recipe.py` → `zero_recipe/` (shipped) | Low: host only, no kernel digest | Chosen first because no then-open PR edited it; small gain (10 → 10 PR pairs here, re-measured in its PR) | 1 day |
| 2 | `model` → `model/` | Low: host only, no kernel digest, pydantic covered by the suite | All four feature PRs collide here; open pairs 6 → 3 | 0.5 day |
| 3 | `kernel/__init__.py` → `job_*.py` | Low to medium: host-only; keep outside `ENGINE_SOURCES` | Originally paired with the digest/CI-key change; that explicit boundary has since shipped | 1 day |
| 4 | `rules/coordinates.py` → `coordinates/` | Medium: four monkeypatches, 19 lazy imports | 1,176 → 581 commit pairs | 1 day |
| 5 | `sheet.py` → `sheet/` | Medium: 10 mixins, 276 cross-mixin calls | Largest commit churn (153); open pairs 6 → 3 | 1.5 days |
| 6 | `kernel/freecad_job.py` → `kernel/engine/` | High: runs in freecadcmd, `_POOL` prep, probes, cold geometry | 7,750 → 2,867 commit pairs; open pairs 3 → 1 | 2.5 days |
| 7 | `render_diagram` (optional) | Medium: dual host/FreeCAD imports | Little gain (1 → 1 PR pairs); revisit with fresh `churn` data | 1 day |

Each historical estimate included regenerating on fresh `main`, resolving `plan`
refusals, a full suite run (cold for engine-source changes), a snapshot against the
base, prose updates and review rounds.

## Beyond the mechanical split

The snapshot's dispatch points were `_Traveler.operations` (270 lines),
`_Setup.__init__`/`run`, `Plan` validators, `coordinates.evaluate`,
`zero_recipe.evaluate`, `op_inputs` and `_ENGINE_OP`. Mechanical movement leaves
their shared edits intact. A per-operation registry could map an operation kind to
its card method, engine handler and input builder, but that is a separate
behavior-preserving refactor. Reassess the current owners first; change one
dispatcher per PR and require the same output snapshot.

## What is not split

The snapshot's `rules/manual_arc.py` was cohesive: 407 lines, 15 commits since
2026-09-01 and one of the five open PRs. A split would add files without removing
a collision in that population. Revisit only with new evidence.

## Open review notes

Review of the original plan stopped after 15 Codex rounds at the owner's request.
Reported cases that could generate a broken tree received refusal handling and
tests in `tests/test_split_modules.py`. The remaining constraints are:

* The rewriter can refuse only shapes it models. Review added refusals for match
  captures, keyword-only patch calls, nested-helper reads and namespace dunders.
  The recorded non-engine dry runs found none beyond the documented preparation.
  An unrecognized shape could still pass, so every split needs its own byte-identical
  snapshot, kernel-enabled suite and example validator. Add a refusal and regression
  test when a new shape is found; do not hand-fix generated movement.
* The compared `model[family-only]` option has a cycle because `features` needs
  `Bounds` from the plan. It was not the selected layout.
* The engine prototype refused `_POOL`; its proposed split still requires the
  preparation described above. Prototype results do not mean the engine split shipped.
* The package design keeps `__init__.py` docstring-only, as the shipped
  [`zero_recipe/__init__.py`](../src/prechips/rules/zero_recipe/__init__.py) does.
  Re-exporting a moved entry point, such as the former `zero_recipe.evaluate`,
  would preserve old external paths but widen the namespace and shared import
  surface. The supported interface is the `prechips` CLI. Whether to add
  re-exports remains the owner's call, raised on #311; this plan does not
  authorize compatibility shims. Consult the
  [Python support boundary](reference/python-api.md) for current consumer guidance.
