"""Read the small process-plan format and render a self-contained print sheet."""

import base64
import re
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from functools import cache
from html import escape
from importlib import metadata
from math import floor, isfinite
from pathlib import Path
from xml.etree import ElementTree

from prechips import indexing, milling, palette, speeds
from prechips.cad import Agreed, CadData, CadError, bind_data, bind_text, load_cad
from prechips.checks import CheckError, positive_mm
from prechips.checks import fields as check_fields
from prechips.profiles import PRO, Profile
from prechips.shop import STATUSES


class PlanError(ValueError):
    """An authored plan has a missing or unusable field."""


# The only parameters that are lists of names, not numbers: flat_bar's blank
# groups. Every other parameter stays a finite number.
_NAME_LISTS = re.compile(r"blank_groups|[a-z][a-z0-9_]*_blank_(features|size_fields)")


def _keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise PlanError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def _text(table: dict, key: str, where: str, *, optional: bool = False) -> str:
    if optional and key not in table:
        return ""
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{where}.{key}: expected a nonempty string")
    return value


def _tables(table: dict, key: str, where: str) -> list[dict]:
    value = table.get(key)
    if not isinstance(value, list) or not value:
        raise PlanError(f"{where}.{key}: expected a nonempty array of tables")
    if any(not isinstance(item, dict) for item in value):
        raise PlanError(f"{where}.{key}: expected an array of tables")
    return value


def _shop_record(shop: dict, section: str, key: str, where: str) -> dict:
    records = shop.get(section, {})
    if not isinstance(records, dict):
        raise PlanError(f"shop.{section}: expected a table")
    if key not in records:
        raise PlanError(f"{where}: unknown shared {section} reference {key!r}")
    record = records[key]
    if not isinstance(record, dict):
        raise PlanError(f"shop.{section}.{key}: expected a table")
    return record


NOTE_KINDS = {"stop"}


def _note_block(block: dict, where: str) -> None:
    """A titled block at the sheet's head: a list of ``items`` or two-column
    ``rows`` (label, text), exactly one; ``kind = "stop"`` sets it apart."""
    _keys(block, {"title", "kind", "items", "rows"}, where)
    _text(block, "title", where)
    _choice(block, "kind", NOTE_KINDS, where)
    if ("items" in block) == ("rows" in block):
        raise PlanError(f"{where}: declare items or rows, not both or neither")
    if "items" in block:
        items = block["items"]
        if (
            not isinstance(items, list)
            or not items
            or any(not isinstance(item, str) or not item.strip() for item in items)
        ):
            raise PlanError(f"{where}.items: expected a nonempty array of strings")
        return
    rows = block["rows"]
    if (
        not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(row, list)
            or len(row) != 2
            or any(not isinstance(cell, str) or not cell.strip() for cell in row)
            for row in rows
        )
    ):
        raise PlanError(f"{where}.rows: expected a nonempty array of [label, text]")


def _notes(plan: dict, shop: dict, shop_path: Path | None) -> list[dict]:
    """The plan's ``notes`` in order, each shop ``ref`` replaced by its record."""
    notes = []
    refs: list[str] = []
    for index, block in enumerate(_tables(plan, "notes", "plan"), 1):
        where = f"notes[{index}]"
        if "ref" not in block:
            _note_block(block, where)
            notes.append(block)
            continue
        _keys(block, {"ref"}, where)
        ref = _text(block, "ref", where)
        if shop_path is None:
            raise PlanError(f"{where}.ref: requires plan.shop")
        if ref in refs:
            raise PlanError(f"{where}: duplicate notes reference {ref!r}")
        refs.append(ref)
        shared = _shop_record(shop, "notes", ref, where)
        _note_block(shared, f"shop.notes.{ref}")
        notes.append(shared)
    return notes


def _standing(shop: dict, where: str) -> dict:
    """The shop's ``[standing]`` page: its title, optional ``intro``, the
    ``pointer`` a sheet opting in prints, an optional full picture ``legend``
    and its ``notes`` (keys of shop ``[notes.<key>]`` blocks, in order),
    returned with each key replaced by its block."""
    page = shop.get("standing")
    if not isinstance(page, dict):
        raise PlanError(f"{where}: the shop has no [standing] table")
    _keys(page, {"title", "intro", "pointer", "legend", "notes"}, "shop.standing")
    _text(page, "title", "shop.standing")
    _text(page, "intro", "shop.standing", optional=True)
    _text(page, "pointer", "shop.standing")
    if not isinstance(page.get("legend", False), bool):
        raise PlanError("shop.standing.legend: expected true or false")
    keys = page.get("notes")
    if (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) or not key.strip() for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise PlanError(
            "shop.standing.notes: expected a nonempty array of distinct keys"
        )
    blocks = []
    for key in keys:
        block = _shop_record(shop, "notes", key, "shop.standing.notes")
        _note_block(block, f"shop.notes.{key}")
        blocks.append(block)
    return page | {"notes": blocks}


def load_standing(path: Path) -> tuple[dict, list[Path]]:
    """The standing page of the shop file or directory at ``path``, and the
    shop files it was read from."""
    shop, files = load_shop(path)
    return _standing(shop, f"shop {path}") | {"project": _project(shop)}, files


def _project(shop: dict) -> str:
    """The shop's ``[sheet] project``: the project title every printed page
    carries in its running header, as the drawings' title block prints it."""
    sheet = shop.get("sheet")
    if sheet is None:
        return ""
    if not isinstance(sheet, dict):
        raise PlanError("shop.sheet: expected a table")
    _keys(sheet, {"project"}, "shop.sheet")
    return _text(sheet, "project", "shop.sheet")


@cache
def _version() -> str:
    try:
        return metadata.version("prechips")
    except metadata.PackageNotFoundError:
        return "unknown"


def _css_string(text: str) -> str:
    """A CSS string inside ``<style>``: whitespace runs made one space, ``\\``
    and ``"`` escaped, and ``<`` as the CSS escape ``\\3c`` so no ``</style``
    closes the element early. A hex escape swallows one whitespace character
    after it (CSS Syntax 3, 4.3.7), so it always ends in its own space and a
    space that followed the ``<`` survives."""
    escaped = " ".join(text.split()).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("<", "\\3c ") + '"'


# An SVG root's width or height that gives it a natural size: a positive
# number, optionally in an absolute unit ("100%", "auto", "" or 0 give none).
_ABSOLUTE_LENGTH = re.compile(
    r"\s*(\d+\.?\d*|\.\d+)\s*(px|pt|pc|mm|cm|in)?\s*", re.IGNORECASE
)


def _natural_size(value: str | None) -> bool:
    match = _ABSOLUTE_LENGTH.fullmatch(value or "")
    return match is not None and float(match[1]) > 0


def _running(top_left: str, top_right: str, bottom_left: str) -> str:
    """A running header and footer in the page margin, one line each, on
    every printed page: the project, the sheet's identity, what printed it,
    and ``SHEET n OF N``. They cost no body lines."""
    box = "font-family: Arial, Helvetica, sans-serif; font-size: 7.5pt; color: #000;"
    rules = "".join(
        f"@{name} {{ content: {_css_string(text)}; {box} }}"
        for name, text in (
            ("top-left", top_left),
            ("top-right", top_right),
            ("bottom-left", bottom_left),
        )
        if text
    )
    sheet = 'content: "SHEET " counter(page) " OF " counter(pages);'
    return f"@page {{ {rules}@bottom-right {{ {sheet} {box} }} }}\n"


def _identity(loaded: "LoadedPlan", part: str | None = None) -> str:
    """Each part's slug and drawing number, then the revision, from the feature
    manifests; the plan's own part and revision lines without CAD data."""
    plan = loaded.data
    if part is not None:
        cads = [loaded.parts[part][0]]
    elif loaded.parts:
        cads = [cad for cad, _ in loaded.parts.values()]
    else:
        cads = [loaded.cad] if loaded.cad is not None else []
    values = [cad.values for cad in cads]
    if not values or any(
        not {"part", "drawing_number", "revision"} <= value.keys() for value in values
    ):
        return f"{plan['part']} · REV {plan['revision']}"
    revisions = dict.fromkeys(v["revision"] for v in values)
    if len(revisions) == 1:
        parts = " · ".join(f"{v['part']} {v['drawing_number']}" for v in values)
        return f"{parts} · REV {next(iter(revisions))}"
    # Parts at different revisions: each carries its own.
    return " · ".join(
        f"{v['part']} {v['drawing_number']} REV {v['revision']}" for v in values
    )


def _cutting_settings(table: dict, where: str) -> None:
    _text(table, "feed", where, optional=True)
    if "rpm" in table:
        rpm = table["rpm"]
        if type(rpm) is not int or rpm <= 0:
            raise PlanError(f"{where}.rpm: expected a positive integer")


def _names(table: dict, key: str, where: str) -> None:
    """An optional nonempty array of distinct nonempty strings."""
    if key not in table:
        return
    names = table[key]
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(set(names)) != len(names)
    ):
        raise PlanError(f"{where}.{key}: expected a nonempty array of distinct names")


def _choice(table: dict, key: str, choices: set[str], where: str) -> None:
    if key in table and (not isinstance(table[key], str) or table[key] not in choices):
        raise PlanError(f"{where}.{key}: expected {' or '.join(sorted(choices))}")


STEP_KINDS = {"action", "check", "stop"}


def _steps(operation: dict, key: str, where: str) -> None:
    if key not in operation:
        return
    for index, step in enumerate(_tables(operation, key, where), 1):
        step_where = f"{where}.{key}[{index}]"
        _keys(step, {"text", "kind"}, step_where)
        _text(step, "text", step_where)
        if "kind" not in step:
            raise PlanError(f"{step_where}.kind: required")
        _choice(step, "kind", STEP_KINDS, step_where)


def _work(operation: dict, where: str) -> None:
    """Each slot, compact and detailed, holds instruction text or steps."""
    if "instruction" in operation and "steps" in operation:
        raise PlanError(f"{where}: declare instruction or steps, not both")
    if "instruction_detailed" in operation and "steps_detailed" in operation:
        raise PlanError(
            f"{where}: declare instruction_detailed or steps_detailed, not both"
        )
    if "instruction" not in operation and "steps" not in operation:
        raise PlanError(f"{where}: expected instruction or steps")
    if "instruction" in operation:
        _text(operation, "instruction", where)
    _text(operation, "instruction_detailed", where, optional=True)
    _steps(operation, "steps", where)
    _steps(operation, "steps_detailed", where)


def _diagram(table: dict, where: str) -> None:
    """A setup's or an operation's picture: an SVG file and its alt text."""
    if "diagram" not in table:
        return
    diagram = table["diagram"]
    where = f"{where}.diagram"
    if not isinstance(diagram, dict):
        raise PlanError(f"{where}: expected a table")
    _keys(diagram, {"file", "alt", "part"}, where)
    _text(diagram, "file", where)
    _text(diagram, "alt", where)


def _turning_numbers(table: dict, keys: set[str], where: str) -> None:
    for key in keys & table.keys():
        value = table[key]
        if type(value) not in (int, float) or not isfinite(value):
            raise PlanError(f"{where}.{key}: expected a finite number")


def _turning_support(setup: dict, where: str) -> None:
    if "turning_support" not in setup:
        return
    support = setup["turning_support"]
    where = f"{where}.turning_support"
    if not isinstance(support, dict):
        raise PlanError(f"{where}: expected a table")
    numbers = {
        "chuck_z_mm",
        "centre_z_mm",
        "engage_z_mm",
        "offset_mm",
        "pad_width_mm",
    }
    _keys(support, {"kind"} | numbers, where)
    _choice(support, "kind", {"chuck_only", "tailstock", "follower"}, where)
    _turning_numbers(support, numbers, where)


def _turning_cuts(operation: dict, where: str) -> None:
    if "turning_cuts" not in operation:
        return
    numbers = {
        "start_z_mm",
        "end_z_mm",
        "start_diameter_mm",
        "end_diameter_mm",
        "max_radial_doc_mm",
        "feed_mm_rev",
        "minimum_diameter_mm",
        "max_deflection_mm",
        "kept_start_z_mm",
        "kept_end_z_mm",
    }
    for index, cut in enumerate(_tables(operation, "turning_cuts", where), 1):
        cut_where = f"{where}.turning_cuts[{index}]"
        _keys(cut, {"name", "phase"} | numbers, cut_where)
        _text(cut, "name", cut_where)
        _choice(cut, "phase", {"rough", "finish"}, cut_where)
        _turning_numbers(cut, numbers, cut_where)


def _turning_step(operation: dict, where: str) -> None:
    if "turning_step" not in operation:
        return
    step = operation["turning_step"]
    where = f"{where}.turning_step"
    if not isinstance(step, dict):
        raise PlanError(f"{where}: expected a table")
    numbers = {"length_mm", "load_diameter_mm"}
    _keys(step, numbers, where)
    for key in sorted(numbers):
        try:
            positive_mm(step.get(key), f"{where}.{key}")
        except CheckError as error:
            raise PlanError(str(error)) from error


def _turning_step_html(length_mm: float) -> str:
    """The step length the turning screen used, as the machinist's limit.

    Rounded down, so the printed limit never exceeds the screened one.
    """
    millimetres = floor(length_mm * 100 + 1e-9) / 100
    inches = f"{floor(length_mm / 25.4 * 1000 + 1e-9) / 1000:.3f}".removeprefix("0")
    return (
        f'<div class="text"><strong>Steps:</strong> at most {millimetres:.2f} mm '
        f"({inches} in), toward the chuck; rough and finish each step before "
        "the next.</div>"
    )


def _shop_toml(file: Path) -> dict:
    try:
        with file.open("rb") as source:
            return tomllib.load(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise PlanError(f"shop {file}: {error}") from error


def load_shop(path: Path) -> tuple[dict, list[Path]]:
    """Read one shop file, or merge a directory's files; return data and files.

    A directory merges every ``*.toml`` directly in it, skipping names that
    start with ``.``, by section. A record key, a ``limits`` key or a top-level
    value defined in two files is refused; everything else is used as one file
    would be.
    """
    if not path.is_dir():
        return _shop_toml(path), [path]
    files = sorted(
        file
        for file in path.glob("*.toml")
        if file.is_file() and not file.name.startswith(".")
    )
    if not files:
        raise PlanError(f"shop {path}: no .toml files in the directory")
    shop: dict = {}
    first: dict[tuple, Path] = {}

    def define(name: tuple, file: Path) -> None:
        if name in first:
            raise PlanError(
                f"shop.{'.'.join(name)}: defined in both "
                f"{first[name].name} and {file.name}"
            )
        first[name] = file

    for file in files:
        for section, value in _shop_toml(file).items():
            merging = isinstance(value, dict) and isinstance(
                shop.get(section, {}), dict
            )
            if not merging:
                # A non-table value is checked where it is read, as in one file.
                define((section,), file)
                shop[section] = value
                continue
            first.setdefault((section,), file)
            merged = shop.setdefault(section, {})
            for key, record in value.items():
                define((section, key), file)
                merged[key] = record
    return shop, files


@dataclass
class LoadedPlan:
    data: dict
    path: Path
    cad: CadData | None
    parameters: dict
    shop: Path | None
    shop_data: dict
    # The files read for ``shop``: the file itself, or a directory's files.
    shop_files: list[Path] = field(default_factory=list)
    # A family plan's parts, by id: each one's CAD data and its parameters
    # (the plan's with the part's own over them). Empty for a one-part plan.
    parts: dict[str, tuple[CadData, dict]] = field(default_factory=dict)
    # The parts' optional printed names, by id.
    labels: dict[str, str] = field(default_factory=dict)
    # The parts' optional titles, by id: what a part's placeholder is headed.
    titles: dict[str, str] = field(default_factory=dict)

    def scopes(self, *tables: dict) -> list[tuple[CadData | None, dict]]:
        """The CAD data and parameters a picture is drawn from: the part the
        first of ``tables`` (innermost first) names, else every part's."""
        for table in tables:
            if "part" in table:
                return [self.parts[table["part"]]]
        return list(self.parts.values()) or [(self.cad, self.parameters)]


_PART_ID = re.compile(r"[a-z][a-z0-9_]*")


def _parameters(parameters: object, where: str) -> None:
    if not isinstance(parameters, dict):
        raise PlanError(f"{where}: expected a table")
    for key, value in parameters.items():
        if key == "quantity" and (type(value) is not int or value < 1):
            raise PlanError(f"{where}.quantity: expected a positive integer")
        # A list of names configures flat_bar's blank groups.
        if _NAME_LISTS.fullmatch(key) and isinstance(value, list):
            if not value or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise PlanError(f"{where}.{key}: expected a nonempty list of names")
            continue
        if type(value) not in (int, float):
            raise PlanError(f"{where}.{key}: expected a finite number")
        if not isfinite(value):
            raise PlanError(f"{where}.{key}: expected a finite number")
        if (
            key
            in {
                "blank_length_in",
                "blank_width_in",
                "blank_thickness_in",
            }
            and value <= 0
        ):
            raise PlanError(f"{where}.{key}: expected a positive number")


def _load_parts(
    family: object, path: Path, parameters: dict
) -> tuple[dict, dict, dict]:
    """A family plan's ``[[parts]]``: each part's manifest through its adapter,
    read with the plan's parameters and the part's own over them, and the
    parts' labels and titles."""
    if not isinstance(family, list) or len(family) < 2:
        raise PlanError("parts: expected two or more [[parts]] tables")
    parts: dict[str, tuple[CadData, dict]] = {}
    labels: dict[str, str] = {}
    titles: dict[str, str] = {}
    for index, entry in enumerate(family, 1):
        where = f"parts[{index}]"
        if not isinstance(entry, dict):
            raise PlanError(f"{where}: expected a table")
        _keys(
            entry,
            {"id", "label", "title", "file", "adapter", "part", "parameters"},
            where,
        )
        part_id = _text(entry, "id", where)
        if not _PART_ID.fullmatch(part_id):
            raise PlanError(
                f"{where}.id: expected a lower-case name of letters, digits and _"
            )
        if part_id in parts:
            raise PlanError(f"{where}.id: duplicate part {part_id!r}")
        own = entry.get("parameters", {})
        _parameters(own, f"{where}.parameters")
        merged = parameters | own
        try:
            cad = load_cad(
                path.parent / _text(entry, "file", where),
                merged,
                _text(entry, "adapter", where),
                _text(entry, "part", where),
            )
        except CadError as error:
            raise PlanError(f"{where} ({part_id}): {error}") from error
        parts[part_id] = (cad, merged)
    # A label or title binds its own part's values; a qualified token names
    # any part's, so every part is loaded first.
    for index, entry in enumerate(family, 1):
        where = f"parts[{index}]"
        for key, bound in (("label", labels), ("title", titles)):
            if key in entry:
                bound[entry["id"]] = bind_text(
                    _text(entry, key, where), *parts[entry["id"]], parts=parts
                )
    return parts, labels, titles


def load_plan(path: Path) -> LoadedPlan:
    with path.open("rb") as source:
        plan = tomllib.load(source)
    parameters = plan.pop("parameters", {})
    _parameters(parameters, "parameters")
    cad = None
    config = plan.pop("cad", None)
    family = plan.pop("parts", None)
    parts: dict[str, tuple[CadData, dict]] = {}
    labels: dict[str, str] = {}
    titles: dict[str, str] = {}
    try:
        if config is not None:
            if family is not None:
                raise PlanError("plan: expected [cad] or [[parts]], not both")
            if not isinstance(config, dict):
                raise PlanError("cad: expected a table")
            _keys(config, {"file", "adapter", "part"}, "cad")
            cad = load_cad(
                path.parent / _text(config, "file", "cad"),
                parameters,
                _text(config, "adapter", "cad"),
                _text(config, "part", "cad"),
            )
        if family is not None:
            parts, labels, titles = _load_parts(family, path, parameters)
            # Text that names no part binds only what every part gives alike.
            shared = (
                CadData(
                    Agreed(
                        "cad", {key: part.values for key, (part, _) in parts.items()}
                    ),
                    stock_requirement=None,
                    source=path.resolve(),
                ),
                Agreed("process", {key: own for key, (_, own) in parts.items()}),
            )
        else:
            # Literal-only plans can also bind authored process parameters.
            shared = (
                cad or CadData({}, stock_requirement=None, source=path.resolve()),
                parameters,
            )
        # Analysis inputs retain full-precision numeric tokens. Printed fields
        # keep the existing text binding semantics.
        native = {
            "tools": check_fields("tool"),
            "setups": {"turning_support"} | check_fields("setup"),
            "operations": {"turning_cuts", "turning_step"} | check_fields("operation"),
        }
        named = parts or None

        def scope(table: dict, where: str, outer: tuple) -> tuple:
            """The part a setup, operation or picture names, else ``outer``."""
            if "part" not in table:
                return outer
            if not parts:
                raise PlanError(f"{where}.part: requires [[parts]]")
            if not isinstance(table["part"], str) or table["part"] not in parts:
                raise PlanError(f"{where}.part: unknown part {table['part']!r}")
            return parts[table["part"]]

        def bound(table: dict, kind: str, where: str, at: tuple) -> dict:
            """``table`` bound in the scope ``at``, its operations left as they are."""
            # A picture that names a part binds its file and alt text there.
            picture = at
            if isinstance(table.get("diagram"), dict):
                picture = scope(table["diagram"], f"{where}.diagram", at)
            for key in native[kind] & table.keys():
                table[key] = bind_data(
                    table[key], *at, scalar_mode="native", parts=named
                )
            return {
                key: value
                if key == "operations"
                else bind_data(
                    value, *(picture if key == "diagram" else at), parts=named
                )
                for key, value in table.items()
            }

        tools = [
            bound(tool, "tools", f"tools[{index}]", shared)
            for index, tool in enumerate(_tables(plan, "tools", "plan"), 1)
        ]
        setups = []
        for index, setup in enumerate(_tables(plan, "setups", "plan"), 1):
            where = f"setups[{index}]"
            at = scope(setup, where, shared)
            operations = [
                bound(
                    operation,
                    "operations",
                    f"{where}.operations[{op_index}]",
                    scope(operation, f"{where}.operations[{op_index}]", at),
                )
                for op_index, operation in enumerate(
                    _tables(setup, "operations", "setup"), 1
                )
            ]
            setup = bound(setup, "setups", where, at)
            setup["operations"] = operations
            setups.append(setup)
        plan = {
            key: tools
            if key == "tools"
            else setups
            if key == "setups"
            else bind_data(value, *shared, parts=named)
            for key, value in plan.items()
        }
    except CadError as error:
        raise PlanError(str(error)) from error
    shop_path = None
    shop = {}
    shop_files = []
    if "shop" in plan:
        shop_path = (path.parent / _text(plan, "shop", "plan")).resolve()
        shop, shop_files = load_shop(shop_path)
        _project(shop)
        plan.pop("shop")
    material_key = _text(plan, "material_key", "plan", optional=True)
    plan.pop("material_key", None)
    _keys(
        plan,
        {
            "title",
            "part",
            "revision",
            "material",
            "stock",
            "stock_refs",
            "note",
            "notes",
            "standing",
            "tools",
            "setups",
            "turning_material",
            "milling_material",
        },
        "plan",
    )
    for key in ("title", "part", "revision", "material", "stock"):
        _text(plan, key, "plan")
    _text(plan, "note", "plan", optional=True)
    _text(plan, "turning_material", "plan", optional=True)
    _text(plan, "milling_material", "plan", optional=True)
    if "stock_refs" in plan:
        refs = plan["stock_refs"]
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
        ):
            raise PlanError("plan.stock_refs: expected a nonempty array of strings")
        if shop_path is None:
            raise PlanError("plan.stock_refs: requires plan.shop")
        stock = []
        for index, ref in enumerate(refs, 1):
            where = f"stock_refs[{index}]"
            if ref in refs[: index - 1]:
                raise PlanError(f"{where}: duplicate stock reference {ref!r}")
            shared = _shop_record(shop, "stock", ref, where)
            shared_where = f"shop.stock.{ref}"
            _keys(shared, {"name", "description", "status"}, shared_where)
            _text(shared, "description", shared_where)
            _text(shared, "name", shared_where, optional=True)
            _choice(shared, "status", set(STATUSES), shared_where)
            stock.append(shared)
        # The printed stock text stays the authority; the records add marks.
        plan["stock_refs"] = stock
    if "notes" in plan:
        plan["notes"] = _notes(plan, shop, shop_path)
    if "standing" in plan:
        if plan["standing"] is not True:
            raise PlanError("plan.standing: expected true (or leave it out)")
        if shop_path is None:
            raise PlanError("plan.standing: requires plan.shop")
        # The sheet prints only the pointer; the page is rendered on its own.
        plan["standing"] = _standing(shop, "plan.standing")["pointer"]

    tool_ids = set()
    tool_refs = {}
    # The T numbers the plan's NC programs call its tools by.
    tool_numbers: dict[int, str] = {}
    for index, tool in enumerate(_tables(plan, "tools", "plan"), 1):
        where = f"tools[{index}]"
        _keys(
            tool,
            {"id", "name", "description", "status", "ref", "number"}
            | check_fields("tool"),
            where,
        )
        tool_id = _text(tool, "id", where)
        if "number" in tool:
            number = tool["number"]
            if type(number) is not int or number < 1:
                raise PlanError(f"{where}.number: expected a positive integer")
            if number in tool_numbers:
                raise PlanError(
                    f"{where}.number: T{number} is already tool "
                    f"{tool_numbers[number]!r}; one number names one tool"
                )
            tool_numbers[number] = tool_id
        if "ref" in tool:
            ref = _text(tool, "ref", where)
            if shop_path is None:
                raise PlanError(f"{where}.ref: requires plan.shop")
            shared = _shop_record(shop, "tools", ref, f"{where}.ref")
            shared_where = f"shop.tools.{ref}"
            _keys(
                shared,
                {"name", "description", "status"} | check_fields("tool"),
                shared_where,
            )
            _choice(shared, "status", set(STATUSES), shared_where)
            _text(shared, "description", shared_where)
            _text(shared, "name", shared_where, optional=True)
            for key in shared:
                if key not in tool:
                    tool[key] = shared[key]
            tool_refs[tool_id] = tool.pop("ref")
        _text(tool, "name", where, optional=True)
        _text(tool, "description", where)
        _choice(tool, "status", set(STATUSES), where)
        if tool_id in tool_ids:
            raise PlanError(f"{where}.id: duplicate tool {tool_id!r}")
        tool_ids.add(tool_id)

    for index, setup in enumerate(_tables(plan, "setups", "plan"), 1):
        where = f"setups[{index}]"
        _keys(
            setup,
            {
                "title",
                "machine",
                "machine_ref",
                "holding",
                "datum",
                "diagram",
                "operations",
                "inspection",
                "machine_kind",
                "part",
                "programs",
                "serves",
                "turning_support",
            }
            | check_fields("setup"),
            where,
        )
        for key in ("title", "machine"):
            _text(setup, key, where)
        _names(setup, "programs", where)
        if "serves" in setup:
            if not parts:
                raise PlanError(f"{where}.serves: requires [[parts]]")
            _names(setup, "serves", where)
            unknown = [name for name in setup["serves"] if name not in parts]
            if unknown:
                raise PlanError(f"{where}.serves: unknown part {unknown[0]!r}")
            if "part" in setup and setup["part"] not in setup["serves"]:
                raise PlanError(
                    f"{where}.serves: expected to include its part {setup['part']!r}"
                )
        if "machine_ref" in setup:
            ref = _text(setup, "machine_ref", where)
            if shop_path is None:
                raise PlanError(f"{where}.machine_ref: requires plan.shop")
            _shop_record(shop, "machines", ref, f"{where}.machine_ref")
        _choice(setup, "machine_kind", {"lathe", "other"}, where)
        _turning_support(setup, where)
        for key in ("holding", "datum"):
            _text(setup, key, where, optional=True)
        _diagram(setup, where)
        checks = setup.get("inspection", [])
        if not isinstance(checks, list) or any(
            not isinstance(check, str) or not check.strip() for check in checks
        ):
            raise PlanError(
                f"{where}.inspection: expected an array of nonempty strings"
            )
        for op_index, operation in enumerate(_tables(setup, "operations", where), 1):
            op_where = f"{where}.operations[{op_index}]"
            _keys(
                operation,
                {
                    "tool",
                    "settings",
                    "instruction",
                    "instruction_detailed",
                    "steps",
                    "steps_detailed",
                    "rpm",
                    "feed",
                    "inspection",
                    "table",
                    "diagram",
                    "cut_kind",
                    "turning_cuts",
                    "turning_step",
                    "part",
                }
                | check_fields("operation"),
                op_where,
            )
            _choice(operation, "cut_kind", {"longitudinal_turning", "other"}, op_where)
            _turning_cuts(operation, op_where)
            _turning_step(operation, op_where)
            _cutting_settings(operation, op_where)
            _diagram(operation, op_where)
            tool_id = _text(operation, "tool", op_where, optional=True)
            if tool_id and tool_id not in tool_ids:
                raise PlanError(f"{op_where}.tool: unknown tool {tool_id!r}")
            if "settings" in operation:
                ref = _text(operation, "settings", op_where)
                if shop_path is None:
                    raise PlanError(f"{op_where}.settings: requires plan.shop")
                shared = _shop_record(shop, "settings", ref, f"{op_where}.settings")
                shared_where = f"shop.settings.{ref}"
                _keys(
                    shared,
                    {"tool", "material", "rpm", "feed"} | speeds.SETTING_FIELDS,
                    shared_where,
                )
                shared_tool = _text(shared, "tool", shared_where)
                shared_material = _text(shared, "material", shared_where)
                _cutting_settings(shared, shared_where)
                if (
                    not {
                        "rpm",
                        "sfm",
                        "feed",
                        "feed_mm_rev",
                        "chip_load_mm_per_tooth",
                    }
                    & shared.keys()
                ):
                    raise PlanError(f"{shared_where}: expected rpm or feed")
                if not tool_id or tool_refs.get(tool_id) != shared_tool:
                    raise PlanError(
                        f"{op_where}.settings: {ref!r} requires tool ref {shared_tool!r}"
                    )
                if not material_key or material_key != shared_material:
                    raise PlanError(
                        f"{op_where}.settings: {ref!r} requires "
                        f"material_key {shared_material!r}"
                    )
                try:
                    values = speeds.setting_values(
                        shared,
                        shared_where,
                        operation,
                        op_where,
                        setup.get("machine_ref"),
                        shop,
                    )
                except CheckError as error:
                    raise PlanError(str(error)) from error
                authored_feed = "feed" in operation
                for key, value in values.items():
                    if key not in operation:
                        operation[key] = value
                # milling_deflection reads the chip load behind a calculated
                # feed and the feed as printed; an authored feed has neither.
                if "chip_load_mm_per_tooth" in shared and not authored_feed:
                    operation["chip_load_mm_per_tooth"] = shared[
                        "chip_load_mm_per_tooth"
                    ]
                    operation["flutes"] = shared["flutes"]
                    operation["feed_mm_min"] = speeds.chip_load_feed(
                        shared, operation["rpm"]
                    )[1]
                operation.pop("settings")
            _work(operation, op_where)
            _text(operation, "inspection", op_where, optional=True)
            if "table" in operation:
                data = operation["table"]
                table_where = f"{op_where}.table"
                if not isinstance(data, dict):
                    raise PlanError(f"{table_where}: expected a table")
                _keys(data, {"columns", "rows"}, table_where)
                columns = data.get("columns")
                if (
                    not isinstance(columns, list)
                    or not columns
                    or any(
                        not isinstance(column, str) or not column.strip()
                        for column in columns
                    )
                ):
                    raise PlanError(
                        f"{table_where}.columns: expected nonempty column names"
                    )
                rows = data.get("rows")
                if (
                    not isinstance(rows, list)
                    or not rows
                    or any(
                        not isinstance(row, list)
                        or len(row) != len(columns)
                        or any(not isinstance(cell, str) for cell in row)
                        for row in rows
                    )
                ):
                    raise PlanError(
                        f"{table_where}.rows: expected nonempty rows matching the columns"
                    )
    return LoadedPlan(
        plan,
        path.resolve(),
        cad,
        parameters,
        shop_path,
        shop,
        shop_files,
        parts,
        labels,
        titles,
    )


CSS = """
:root {
  --ink: #000;
  --paper: #fff;
  --rule: #ccc;
  --font: Arial, Helvetica, sans-serif;
  --body-size: 10.5pt;
  --title-size: 17pt;
  --heading-size: 12pt;
}
@page { size: Letter; margin: 0.5in; }
* { box-sizing: border-box; }
html, body { overflow-x: clip; }
body {
  color: var(--ink); background: var(--paper);
  font-family: var(--font); font-size: var(--body-size);
  line-height: 1.2; max-width: 7.5in; margin: 0 auto;
}
h1 { font-size: var(--title-size); margin: 0 0 0.08in; }
h2 { font-size: var(--heading-size); margin: 0.12in 0 0.04in; }
h1, h2 { overflow-wrap: break-word; min-width: 0; }
h1, h2, dt { break-after: avoid; }
p { margin: 0.05in 0; }
.meta { margin-bottom: 0.06in; }
dl { display: grid; grid-template-columns: 0.6in 1fr; gap: 0.02in 0.04in; margin: 0.04in 0; }
dt { font-weight: bold; }
dd { margin: 0; white-space: pre-wrap; }
table { width: 100%; border-collapse: collapse; margin: 0.06in 0; }
thead { display: table-header-group; break-after: avoid; }
tr { break-inside: avoid; }
th, td { text-align: left; vertical-align: top; padding: 0.015in 0.05in; }
th { border-bottom: 1px solid var(--ink); }
td { border-bottom: 1px solid var(--rule); }
th:first-child, td:first-child { padding-left: 0; }
th:last-child, td:last-child { padding-right: 0; }
.tools { table-layout: fixed; }
.tools td { width: 50%; }
.tools td:nth-child(2) { padding-left: 0.1in; }
.setup-heading { break-inside: avoid; break-after: avoid; }
.setup-heading.pictured { break-after: auto; }
.setup-heading h2 { display: flex; justify-content: space-between; gap: 0.12in; }
.machine { font-size: var(--body-size); font-weight: normal; text-align: right; }
.setup-diagram { margin: 0.08in 0; break-inside: avoid; }
.setup-diagram img { display: block; width: 100%; max-height: 4in; object-fit: contain; }
.setup-top { display: flex; flex-wrap: wrap; align-items: flex-start; column-gap: 0.15in; }
.setup-top > dl { flex: 1 1 2.8in; }
.setup-top > .setup-diagram { flex: 0 0 auto; max-width: 100%; }
.setup-top > .setup-diagram img { width: auto; max-width: 100%; }
.setup-top > .setup-diagram[data-wide] { flex: 1 1 100%; }
.setup-top > .setup-diagram[data-wide] img { width: 100%; }
.op-feed { float: right; max-width: 50%; margin-left: 0.15in; }
.operations { table-layout: fixed; }
.setup-heading:not(.pictured) + .operations { break-before: avoid; }
.op-column { width: 6%; }
.work-column { width: 65%; }
.settings-column { width: 29%; }
.op-number { white-space: nowrap; font-variant-numeric: tabular-nums; }
.tool { font-weight: bold; }
.setting-value { font-variant-numeric: tabular-nums; }
.data-row { break-inside: auto; }
.data-row > td { padding: 0; border-bottom: 0; }
.data { margin: 0; }
.data th, .data td { font-variant-numeric: tabular-nums; }
.text { white-space: pre-wrap; }
ul { padding-left: 0.2in; margin: 0.06in 0; }
li { break-inside: avoid; }
@media screen { body { padding: 0.25in 0; } }
"""


def _html(value: str | int) -> str:
    return escape(str(value), quote=True)


# Printed only on sheets that use markup or steps, so plain sheets keep their
# exact bytes.
RICH_CSS = """\
.text ol, .text ul { margin: 0; padding-left: 0.22in; }
.text .gap { height: 1.2em; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.95em; }
.steps { margin: 0; padding-left: 0.22in; white-space: pre-wrap; }
.steps-spaced > li + li { margin-top: 0.04in; }
.step-check, .step-stop { padding-left: 0.05in; }
.step-check { border-left: 1px solid var(--ink); }
.step-stop { border-left: 3px solid var(--ink); font-weight: bold; }
"""

_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*")
# Emphasis opens before a word character and never closes after "(", so
# footnote marks such as "(*)" stay literal; it may close after other
# punctuation ("*Note:*").
_EM = re.compile(r"(?<![*\w])\*(?=\w)(.+?)(?<=[^\s*(])\*(?![*\w])")
# Bullets use "* " (asterisk, space), which emphasis cannot open. "- " never
# makes a list, so a minus-sign tolerance line always prints as typed.
_ITEM = re.compile(r"(\d+)\. (.*)|\* (.*)")
# A blank line beside a list: the list's block edges would swallow it.
_GAP = '<div class="gap"></div>'


def _inline(value: str) -> str:
    """Escape, then apply **bold**, *em* and `code`; code spans stay literal."""
    parts = _CODE.split(_html(value))
    for index, part in enumerate(parts):
        if index % 2:
            parts[index] = f"<code>{part}</code>"
            continue
        parts[index] = _EM.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", part))
    return "".join(parts)


def _rich(value: str) -> str:
    """Inline markup plus `1.`/`*` line lists; plain text renders as `_html`."""
    lines = value.split("\n")
    found = [_ITEM.fullmatch(line) for line in lines]
    if not any(found):
        return _inline(value)
    blocks: list[str] = []
    plain: list[str] = []
    items: list[str] = []
    tag = start = number = None

    def close_list() -> None:
        nonlocal tag
        if tag is None:
            return
        begin = f'<ol start="{start}">' if tag == "ol" and start != 1 else f"<{tag}>"
        blocks.append(begin + "".join(items) + f"</{tag}>")
        items.clear()
        tag = None

    def flush_plain() -> int:
        """Print the plain run; return its trailing blank lines, which print
        as gaps only if a list follows (none at the start or end)."""
        filled = [index for index, line in enumerate(plain) if line]
        if not filled:
            trailing = len(plain) if blocks else 0
            plain.clear()
            return trailing
        first, final = filled[0], filled[-1]
        if blocks:
            blocks.append(_GAP * first)
        blocks.append(_inline("\n".join(plain[first : final + 1])))
        trailing = len(plain) - 1 - final
        plain.clear()
        return trailing

    for line, item in zip(lines, found, strict=True):
        if item is None:
            close_list()
            plain.append(line)
            continue
        kind = "ol" if item[1] else "ul"
        if kind != tag:
            close_list()
            if plain:
                blocks.append(_GAP * flush_plain())
            tag, start = kind, int(item[1]) if item[1] else None
            number = start - 1 if start is not None else None
        text = _inline(item[2] if item[1] else item[3])
        if kind == "ul":
            items.append(f"<li>{text}</li>")
            continue
        # Numbers count on from the previous item; an authored number that
        # jumps ahead prints as written, and a repeated or lower one ("1.",
        # "1.", "1.") counts on, as in markdown.
        authored = int(item[1])
        if authored <= number:
            number += 1
            items.append(f"<li>{text}</li>")
            continue
        jump = f' value="{authored}"' if authored != number + 1 else ""
        number = authored
        items.append(f"<li{jump}>{text}</li>")
    close_list()
    if plain:
        flush_plain()
    return "".join(blocks)


STEP_LABELS = {"check": "Check:", "stop": "Stop:"}


class StepLayout(Enum):
    """How a step list prints; the value is its CSS class."""

    COMPACT = "steps"
    SPACED = "steps steps-spaced"


def _steps_html(steps: list[dict], layout: StepLayout) -> str:
    """Numbered steps; check and stop lines carry a label, rule and weight."""
    rows = []
    for step in steps:
        text = _inline(step["text"])
        label = STEP_LABELS.get(step["kind"])
        if label is None:
            rows.append(f"<li>{text}</li>")
            continue
        rows.append(
            f'<li class="step-{step["kind"]}"><strong>{label}</strong> {text}</li>'
        )
    return f'<ol class="{layout.value}">' + "".join(rows) + "</ol>"


# Printed only on sheets with an operation picture. The picture and its
# operation's row share one tbody so a page break cannot separate them; the
# row-level break-after backs that up in engines that ignore break-inside
# on row groups.
OP_DIAGRAM_CSS = """\
.op-group { break-inside: avoid; }
.op-diagram { break-after: avoid; }
.op-diagram > td { padding: 0; border-bottom: 0; }
"""


# Printed only on sheets with head notes. A stop block is boxed and its title
# bold, distinct in greyscale; a rows block is a label column and its text.
NOTES_CSS = """\
.note-block { margin: 0.06in 0; break-inside: avoid; }
.note-block h3 { font-size: var(--body-size); margin: 0 0 0.02in; break-after: avoid; }
.note-block ul { margin: 0; }
.note-stop { border: 2px solid var(--ink); padding: 0.04in 0.08in; }
.note-rows { margin: 0; table-layout: fixed; }
.note-rows th { width: 1.6in; font-weight: bold; border-bottom: 1px solid var(--rule); }
"""


def _note_html(block: dict) -> str:
    """One head note block: its title, then its items or its rows."""
    kind = " note-stop" if block.get("kind") == "stop" else ""
    parts = [f'<div class="note-block{kind}"><h3>{_html(block["title"])}</h3>']
    if "items" in block:
        parts.append(
            "<ul>"
            + "".join(f"<li>{_inline(item)}</li>" for item in block["items"])
            + "</ul>"
        )
    else:
        parts.append('<table class="note-rows"><tbody>')
        parts += [
            f'<tr><th scope="row">{_inline(label)}</th><td>{_inline(text)}</td></tr>'
            for label, text in block["rows"]
        ]
        parts.append("</tbody></table>")
    parts.append("</div>")
    return "".join(parts)


def used_diagrams(setup: dict, profile: Profile) -> dict[int, dict]:
    """The pictures a render of this setup opens: 0 is the setup's own, n its
    nth operation's. The CLI's output guard reads the same lookup."""
    if "setup_diagrams" not in profile.features:
        return {}
    tables = (setup, *setup["operations"])
    return {
        index: table["diagram"]
        for index, table in enumerate(tables)
        if "diagram" in table
    }


def _diagram_html(
    diagram: dict,
    where: str,
    figure_class: str,
    source_dir: Path,
    scopes: list[tuple[CadData | None, dict]],
    caption: str | None = None,
    parts: dict | None = None,
) -> tuple[str, set[str]]:
    """Return a setup's or operation's picture figure and the roles it draws.

    ``scopes`` holds the CAD data and parameters to draw it from: one, or in a
    family plan every part's when the picture names none, which must then all
    draw the same picture."""
    path = source_dir / diagram["file"]
    try:
        content = path.read_bytes()
        if scopes[0][0] is not None:
            from prechips.cad_diagrams import render_cad_svg

            drawings = {
                render_cad_svg(content, *scope, parts=parts) for scope in scopes
            }
            if len(drawings) > 1:
                raise ValueError(
                    "the parts draw it differently: give the picture, its "
                    "operation or its setup a part"
                )
            content = drawings.pop()
        root = ElementTree.fromstring(content)
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise ValueError("expected an SVG root element")
        drawn = palette.paint(root)
        if drawn:
            content = ElementTree.tostring(root, encoding="utf-8")
    except (OSError, ElementTree.ParseError, ValueError) as error:
        raise PlanError(
            f"{where}: cannot use SVG {diagram['file']!r}: {error}"
        ) from error
    image = base64.b64encode(content).decode("ascii")
    alt = _html(diagram["alt"])
    # A picture that names its own part says which, where the part has a label.
    named = (
        f'<figcaption style="font-weight: 700">{_html(caption)}</figcaption>'
        if caption
        else ""
    )
    # A captioned operation picture is one unbreakable box. Observed
    # 2026-11-24 printing a consumer's family traveler with headless Chromium
    # (--print-to-pdf): the caption of a picture in an operations-table cell
    # stayed at a page's foot, its image on the next page, twice in 21 pages,
    # despite break-inside: avoid on the figure and its row group. A setup
    # picture stands outside the table, where break-inside holds.
    boxed = caption and "op-picture" in figure_class.split()
    whole = ' style="display: inline-block; width: 100%"' if boxed else ""
    # A setup picture whose SVG has no width and height of its own (a viewBox
    # only) has no natural size to stand beside the setup's facts at: it
    # spans the column below them, as every picture did before they stood
    # side by side.
    unsized = not all(_natural_size(root.get(side)) for side in ("width", "height"))
    if unsized and "op-picture" not in figure_class.split():
        whole += " data-wide"
    figure = (
        f'<figure class="{figure_class}"{whole}>{named}'
        f'<img src="data:image/svg+xml;base64,{image}" alt="{alt}">'
        "</figure>"
    )
    return figure, drawn


def _status_mark(item: dict) -> str:
    """A shop item not in hand prints its status ("to order"); "on_hand" and an
    unrecorded status print nothing."""
    status = item.get("status", "on_hand")
    return "" if status == "on_hand" else status.replace("_", " ")


def _stock_html(plan: dict) -> str:
    marks = [
        f" <strong>({_status_mark(record)}: "
        f"{_html(record.get('name') or record['description'])})</strong>"
        for record in plan.get("stock_refs", [])
        if _status_mark(record)
    ]
    return f"{_html(plan['stock'])}{''.join(marks)}"


def _tool_number(tool: dict) -> str:
    """``T3 ``, the number the plan's NC programs call the tool by, if it has one."""
    return f"T{tool['number']} " if "number" in tool else ""


def _tool_html(tool: dict) -> str:
    mark = _status_mark(tool)
    status = f" <strong>({mark})</strong>" if mark else ""
    return f"{_tool_number(tool)}{_html(tool['description'])}{status}"


def setups_serving(loaded: LoadedPlan, part: str) -> list[tuple[int, dict]]:
    """The numbered setups a family's part goes through: those listing it in
    ``serves``, else the ones naming it or naming no part."""
    return [
        (number, setup)
        for number, setup in enumerate(loaded.data["setups"], 1)
        if part in setup.get("serves", [setup.get("part", part)])
    ]


def render_placeholder(
    loaded: LoadedPlan, part: str, *, shared_file: str | None = None
) -> str:
    """A pointer sheet for one part of a family plan: it points to the shared
    traveler and lists every setup (and its NC programs) the part goes
    through, so it is one page for a plan of ordinary length and runs on
    where the list is longer. The part has no sheet of its own to drift from
    the shared one."""
    if part not in loaded.parts:
        known = ", ".join(loaded.parts) or "none: the plan has no [[parts]]"
        raise PlanError(f"placeholder: unknown part {part!r} (parts: {known})")
    plan = loaded.data

    def name(part_id: str) -> str:
        return loaded.titles.get(part_id) or loaded.labels.get(part_id) or part_id

    others = [name(other) for other in loaded.parts if other != part]
    file = f" (file {_html(shared_file)})" if shared_file else ""
    running = _running(
        _project(loaded.shop_data),
        _identity(loaded, part),
        f"{name(part)} · placeholder, prechips {_version()}",
    )
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(name(part))}</title>",
        f"<style>{CSS}{running}</style></head><body>",
        f"<h1>{_html(name(part))}</h1>",
        '<div class="meta">',
        f"<p>{_html(plan['revision'])}</p>",
        f"<p><strong>{_html(plan['material'])}.</strong></p>",
        "</div>",
        (
            '<p class="text">This part has no traveler of its own. It is made on the '
            f"shared traveler <strong>{_html(plan['title'])}</strong>{file}, "
            f"together with {_html(', '.join(others))}. "
            "Work from that sheet: this page only points to it.</p>"
        ),
        (
            '<table class="data"><thead><tr><th scope="col">Shared traveler setup</th>'
            '<th scope="col">Machine</th><th scope="col">NC programs</th></tr></thead>'
            "<tbody>"
        ),
    ]
    for number, setup in setups_serving(loaded, part):
        programs = ", ".join(setup.get("programs", [])) or "none"
        lines.append(
            f'<tr><td class="text">Setup {number} — {_html(setup["title"])}</td>'
            f'<td class="text">{_html(setup["machine"])}</td>'
            f'<td class="text">{_html(programs)}</td></tr>'
        )
    lines += ["</tbody></table>", "</body></html>\n"]
    return "\n".join(lines)


# The standing page is one sheet (a consumer's owner-approved design): its
# blocks sit closer than a traveler's head notes, and the picture key keeps a
# small margin, so a row can grow by a line without pushing the key onto a
# second sheet. The text is unchanged.
STANDING_CSS = """\
h1 { margin: 0 0 0.04in; }
p { margin: 0.03in 0; }
.note-block { margin: 0.03in 0; }
.note-block h3 { margin: 0; }
.picture-key { margin: 0.04in 0 0; }
"""


def render_standing(page: dict) -> str:
    """The shop's standing page (``load_standing``): its title and intro, its
    note blocks in order, and the full picture key when ``legend`` is set. One
    document for every sheet, with the travelers' stylesheet."""
    running = _running(page.get("project", ""), page["title"], f"prechips {_version()}")
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(page['title'])}</title>",
        f"<style>{CSS}{RICH_CSS}{NOTES_CSS}{STANDING_CSS}{running}</style></head><body>",
        f"<h1>{_html(page['title'])}</h1>",
    ]
    if "intro" in page:
        lines.append(f'<p class="text">{_html(page["intro"])}</p>')
    lines += [_note_html(block) for block in page["notes"]]
    if page.get("legend"):
        key = base64.b64encode(palette.legend_svg(palette.LEGEND)).decode("ascii")
        alt = _html("Picture key: " + "; ".join(text for _, text in palette.LEGEND))
        # At 90 % of the column the full key (six rows since the work stop's
        # rod has its own entry) still fits under a page of standing rows;
        # at full width it alone spilled onto a second sheet (a consumer's
        # one-page standing page, 2026-11-25).
        lines.append(
            '<figure class="picture-key">'
            f'<img src="data:image/svg+xml;base64,{key}" alt="{alt}"'
            ' style="display: block; width: 90%">'
            "</figure>"
        )
    lines.append("</body></html>\n")
    return "\n".join(lines)


def render_traveler(loaded: LoadedPlan, *, profile: Profile = PRO) -> str:
    """Render a loaded plan; source paths remain relative to its TOML file."""
    plan = loaded.data
    source_dir = loaded.path.parent
    tools = {tool["id"]: tool for tool in plan["tools"]}
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(plan['title'])}</title>",
    ]
    running = _running(
        _project(loaded.shop_data),
        _identity(loaded),
        f"{plan['title']} · traveler, prechips {_version()}",
    )
    # Sheets using markup, steps or operation pictures get their extra CSS
    # spliced in here at the end.
    style_at = len(lines)
    lines += [
        f"<style>{CSS}{running}</style></head><body>",
        f"<h1>{_html(plan['title'])}</h1>",
        '<div class="meta">',
        (f"<p>{_html(plan['part'])}; {_html(plan['revision'])}</p>"),
        (f"<p><strong>{_html(plan['material'])}.</strong> {_stock_html(plan)}</p>"),
        "</div>",
    ]
    if "standing" in plan:
        lines.append(
            f'<p class="text standing"><strong>{_html(plan["standing"])}</strong></p>'
        )
    if "note" in plan:
        lines.append(f'<p class="text">{_html(plan["note"])}</p>')
    for block in plan.get("notes", []):
        lines.append(_note_html(block))
    lines.append(
        '<table class="tools"><thead><tr><th colspan="2">Tools</th></tr></thead><tbody>'
    )
    tool_list = list(tools.values())
    for start in range(0, len(tool_list), 2):
        lines.append("<tr>")
        for tool in tool_list[start : start + 2]:
            lines.append(f'<td class="text">{_tool_html(tool)}</td>')
        if len(tool_list[start : start + 2]) == 1:
            lines.append("<td></td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    # The palette's key prints here, once, listing the roles the pictures draw.
    key_at = len(lines)
    drawn: set[str] = set()
    rich = op_diagrams = False
    detailed = "detailed_instructions" in profile.features
    layout = StepLayout.SPACED if detailed else StepLayout.COMPACT
    pictures_on = "setup_diagrams" in profile.features
    operation_number = 0
    for setup_number, setup in enumerate(plan["setups"], 1):
        heading = (
            f"<h2>Setup {setup_number} — {_html(setup['title'])}"
            f'<span class="machine">{_html(setup["machine"])}</span></h2>'
        )
        index = indexing.setting(
            loaded, setup, f"setup {setup_number} ({setup['title']})"
        )
        # Accepted figures print only while the check that holds the cuts to
        # them is enforced: an unchecked figure is not put on the sheet.
        bonds = []
        if "milling_deflection" in profile.enforce:
            bonds = milling.accepted_bonds(
                setup, f"setup {setup_number} ({setup['title']})"
            )
        programs = setup.get("programs")
        facts = []
        if (
            "holding" in setup
            or "datum" in setup
            or index is not None
            or bonds
            or programs
        ):
            facts.append("<dl>")
            for key in ("holding", "datum"):
                if key in setup:
                    facts.append(f"<dt>{key.title()}:</dt><dd>{_html(setup[key])}</dd>")
            if programs:
                facts.append(f"<dt>NC:</dt><dd>{_html(', '.join(programs))}</dd>")
            for bond in bonds:
                facts.append(f"<dt>Bond:</dt><dd>{_html(bond)}</dd>")
            if index is not None:
                facts.append(
                    f"<dt>Index:</dt><dd>{_html(indexing.describe(index))}</dd>"
                )
            facts.append("</dl>")
        # Profiles require the setup's picture only; operation pictures are
        # optional additions under the same feature.
        pictures = used_diagrams(setup, profile)
        where = f"setup {setup['title']!r}.diagram"
        if 0 in pictures:
            diagram, roles = _diagram_html(
                pictures[0],
                where,
                "setup-diagram",
                source_dir,
                loaded.scopes(pictures[0], setup),
                loaded.labels.get(pictures[0].get("part")),
                loaded.parts or None,
            )
            drawn |= roles
            # The picture stands beside the setup's facts at its own width
            # (it wraps below them when both do not fit), and the operations
            # may start on the next page: a picture that does not fit no
            # longer drags the table's first row along.
            lines.append(
                f'<section><div class="setup-heading pictured">{heading}'
                '<div class="setup-top">'
            )
            lines += [*facts, diagram, "</div></div>"]
        else:
            if pictures_on and "setup_diagrams" in profile.enforce:
                raise PlanError(f"{where}: required by profile {profile.name!r}")
            lines.append(f'<section><div class="setup-heading">{heading}')
            lines += [*facts, "</div>"]
        lines.append(
            '<table class="operations"><colgroup><col class="op-column">'
            '<col class="work-column"><col class="settings-column"></colgroup>'
            '<thead><tr><th scope="col">Op</th>'
            f'<th scope="col">Setup {setup_number} — Work</th>'
            '<th scope="col">Tool / settings</th></tr></thead><tbody>'
        )
        # The plain tbody just opened has no rows. An op picture and its row
        # get a tbody of their own ("closed" leaves none open), and no empty
        # tbody is left between the header and a group: that break point
        # would carry no break-avoid and could strand the heading.
        body = "empty"
        for op_index, operation in enumerate(setup["operations"], 1):
            operation_number += 10
            tool = tools[operation["tool"]] if "tool" in operation else None
            grouped = op_index in pictures
            if grouped:
                # Setup-picture styling, plus a class of its own so setup
                # pictures can still be counted apart.
                diagram, roles = _diagram_html(
                    pictures[op_index],
                    f"setup {setup_number} ({setup['title']}), Op {operation_number}"
                    " diagram",
                    "setup-diagram op-picture",
                    source_dir,
                    loaded.scopes(pictures[op_index], operation, setup),
                    loaded.labels.get(pictures[op_index].get("part")),
                    loaded.parts or None,
                )
                drawn |= roles
                op_diagrams = True
                if body == "empty":
                    lines[-1] = lines[-1].removesuffix("<tbody>")
                lines.append(
                    ("</tbody>" if body == "rows" else "") + '<tbody class="op-group">'
                    f'<tr class="op-diagram"><td colspan="3">{diagram}</td></tr>'
                )
            # The detailed slot, when selected and authored, replaces the
            # compact one; either slot holds instruction text or steps.
            slots = [("instruction", "steps")]
            if detailed:
                slots.insert(0, ("instruction_detailed", "steps_detailed"))
            text_key, steps_key = next(
                pair for pair in slots if pair[0] in operation or pair[1] in operation
            )
            # Validation leaves exactly one of the two keys.
            if steps_key in operation:
                work = _steps_html(operation[steps_key], layout)
                rich = True
            if text_key in operation:
                text = _rich(operation[text_key])
                rich |= text != _html(operation[text_key])
                work = f'<div class="text">{text}</div>'
            reopen = "<tbody>" if body == "closed" and not grouped else ""
            # An operation with no tool and no speed has nothing for the
            # Tool / settings column but its feed text: its work spans that
            # column, the feed printed at the cell's top right.
            spans = tool is None and "rpm" not in operation
            cell = '<td colspan="2">' if spans else "<td>"
            if spans and "feed" in operation:
                cell += (
                    '<div class="text setting-value op-feed">'
                    f"{_html(operation['feed'])}</div>"
                )
            lines.append(
                f'{reopen}<tr><td class="op-number">{operation_number}</td>{cell}{work}'
            )
            body = "rows"
            if "turning_step" in operation:
                lines.append(_turning_step_html(operation["turning_step"]["length_mm"]))
            if "inspection" in operation:
                lines.append(
                    '<div class="text"><strong>Check:</strong> '
                    f"{_html(operation['inspection'])}</div>"
                )
            if not spans:
                lines.append("</td><td>")
                if tool is not None:
                    lines.append(
                        f'<div class="text tool">{_tool_number(tool)}'
                        f"{_html(tool.get('name', tool['description']))}</div>"
                    )
                settings = []
                if "rpm" in operation:
                    settings.append(f"{_html(operation['rpm'])} rpm")
                if "feed" in operation:
                    settings.append(_html(operation["feed"]))
                if settings:
                    lines.append(
                        '<div class="text setting-value">'
                        + "; ".join(settings)
                        + "</div>"
                    )
            lines.append("</td></tr>")
            if grouped:
                lines.append("</tbody>")
                body = "closed"
            if "table" in operation:
                data = operation["table"]
                lines.append(
                    ("<tbody>" if body == "closed" else "")
                    + '<tr class="data-row"><td colspan="3">'
                    f'<table class="data" aria-label="Op {operation_number} data">'
                    "<thead><tr>"
                    + "".join(
                        f'<th scope="col">{_html(column)}</th>'
                        for column in data["columns"]
                    )
                    + "</tr></thead><tbody>"
                )
                for row in data["rows"]:
                    lines.append(
                        "<tr>"
                        + "".join(
                            f'<td class="text">{_html(cell)}</td>' for cell in row
                        )
                        + "</tr>"
                    )
                lines.append("</tbody></table></td></tr>")
                body = "rows"
        lines.append("</table>" if body == "closed" else "</tbody></table>")
        checks = setup.get("inspection", [])
        if len(checks) == 1:
            lines.append(
                f'<p class="text"><strong>Inspection:</strong> {_html(checks[0])}</p>'
            )
        elif checks:
            lines.append("<p><strong>Inspection</strong></p><ul>")
            for check in checks:
                lines.append(f'<li class="text">{_html(check)}</li>')
            lines.append("</ul>")
        lines.append("</section>")
    entries = [(role, text) for role, text in palette.LEGEND if role in drawn]
    if entries:
        key = base64.b64encode(palette.legend_svg(entries)).decode("ascii")
        alt = _html("Picture key: " + "; ".join(text for _, text in entries))
        lines.insert(
            key_at,
            '<figure class="picture-key" style="margin: 0.08in 0">'
            f'<img src="data:image/svg+xml;base64,{key}" alt="{alt}"'
            ' style="display: block; width: 100%">'
            "</figure>",
        )
    notes = "notes" in plan
    extra = (
        (RICH_CSS if rich or notes else "")
        + (OP_DIAGRAM_CSS if op_diagrams else "")
        + (NOTES_CSS if notes else "")
    )
    if extra:
        lines[style_at] = f"<style>{CSS}{extra}{running}</style></head><body>"
    lines.append("</body></html>\n")
    return "\n".join(lines)
