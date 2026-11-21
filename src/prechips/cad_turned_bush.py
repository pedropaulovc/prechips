"""Bindings for a short turned part: a bush, spacer, ring, washer, collar,
cup or plug, made on the lathe from round bar or a squared blank.

Every feature lies on one model axis. ``datum_end`` is the end face the
turned stations run from: its ``plane`` names the axis and its ``outward``
normal points out of the part, so a station is its distance from that face
into the part. ``far_end`` is the other end face, with a ``length`` band (or a
supply ``length_min``) from the datum end. Optional features:

- ``shoulder``: a step face, a ``station`` band from the datum end;
- ``outer``, ``step`` and member ``outer_<member>``: kind ``diameter``, each
  with a ``span`` along the axis and one acceptance: a ``dia`` band, a
  ``stock`` diameter left as bought (``dia_ref``), or a ``dia_ref`` turned to
  a measured mate with a ``diametral_clearance`` (a ``dia`` band may add a
  ``diametral_interference``);
- ``bore``: a ``hole`` through, a ``dia`` band and its ``process``;
- ``pocket``: a ``counterbore`` from the datum end, a ``dia_ref`` bored to a
  measured mate's ``diametral_clearance`` under ``dia_max``, a ``depth`` band
  and a floor ``corner_radius_max``;
- ``tap``: a ``threaded_hole`` from the datum end, its drill ``dia`` and its
  ``drill_depth`` and ``thread_depth`` bands;
- ``chamfer_*``: kind ``chamfer``, a ``leg`` band.

Bands bind in inches as ``<key>_in``/``_min_in``/``_max_in``/``_band_mm``,
nominal sizes as ``<key>_mm``, stations as ``<feature>_z0_mm``/``_z1_mm``.

With the plan's round-bar parameters the adapter binds the bar-fed cycle
(the pitch one part takes off the bar, the stickout for a pull of parts and
the parts one bar makes); with the squared-blank parameters it binds the
blank a 4-jaw chuck turns the part from.
"""

import math
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _all_or_none,
    _band,
    _edge_breaks,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _required,
    _string,
)

_AXES = "xyz"
_DIAMETERS = ("outer", "step")
_OPTIONAL = {"shoulder", "bore", "pocket", "tap"}
_BAR = ("stock_dia_in", "face_allowance_in", "part_kerf_in")
_BAR_LENGTH = ("bar_length_in", "chuck_grip_in")
_BLOCK = ("blank_side_in", "blank_axial_in")
_TOLERANCE = 1e-6


def _frame(features: dict) -> tuple[int, float, float]:
    """The datum end's axis index, plane value and inward sign."""
    datum = features.get("datum_end")
    if not isinstance(datum, dict) or datum.get("kind") != "face":
        raise CadError("datum_end: expected a model-frame face")
    plane = datum.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") not in _AXES:
        raise CadError("datum_end.plane: expected a plane on x, y or z")
    index = _AXES.index(plane["axis"])
    value = _number(plane.get("value"), "datum_end.plane.value")
    outward = datum.get("outward")
    expected = [[float(i == index) * sign for i in range(3)] for sign in (1, -1)]
    if outward not in expected:
        raise CadError(
            "datum_end.outward: expected a unit normal along its plane's axis"
        )
    return index, value, -float(outward[index])


def _station(frame: tuple[int, float, float], coordinate: float) -> float:
    """A model coordinate along the axis as a distance into the part."""
    _, datum, inward = frame
    return (coordinate - datum) * inward + 0.0


def _on_axis(item: dict, name: str, index: int) -> None:
    axis, at = item.get("axis"), item.get("at")
    if not isinstance(axis, list) or [
        abs(_number(v, f"{name}.axis")) for v in axis
    ] != [float(i == index) for i in range(3)]:
        raise CadError(f"{name}.axis: expected the turning axis")
    if not isinstance(at, list) or len(at) != 3:
        raise CadError(f"{name}.at: expected a point on the turning axis")
    if any(_number(v, f"{name}.at") != 0 for i, v in enumerate(at) if i != index):
        raise CadError(f"{name}.at: expected a point on the turning axis")


def _span(item: dict, name: str, frame: tuple, values: dict) -> tuple[float, float]:
    span = item.get("span")
    if not isinstance(span, list) or len(span) != 2:
        raise CadError(f"{name}.span: expected two stations along the axis")
    low, high = sorted(_station(frame, _number(v, f"{name}.span")) for v in span)
    if low < -_TOLERANCE or high - low <= 0:
        raise CadError(f"{name}.span: expected a run inside the part")
    values[f"{name}_z0_mm"], values[f"{name}_z1_mm"] = low, high
    return low, high


def _limits(
    item: dict, field: str, name: str, key: str, values: dict
) -> tuple[float, float]:
    band = _band(item, field, name)
    _inch_limits(values, key, band)
    return band


def _nominal(item: dict, field: str, band: tuple[float, float], name: str) -> float:
    value = _positive(item.get(field), f"{name}.{field}")
    if not band[0] - _TOLERANCE <= value <= band[1] + _TOLERANCE:
        raise CadError(f"{name}.{field}: outside its band")
    return value


def _length(features: dict, frame: tuple, values: dict) -> float:
    far = features.get("far_end")
    if not isinstance(far, dict) or far.get("kind") != "face":
        raise CadError("far_end: expected a model-frame face")
    plane = far.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") != _AXES[frame[0]]:
        raise CadError("far_end.plane: expected a plane on the datum end's axis")
    if far.get("length_from") != "datum_end":
        raise CadError("far_end.length_from: expected datum_end")
    station = _station(frame, _number(plane.get("value"), "far_end.plane.value"))
    if "length_min" in far.get("requirements", []):
        low = _positive(far.get("length_min"), "far_end.length_min")
        values["length_min_mm"], values["length_min_in"] = low, low / 25.4
        values["length_supply"] = True
        nominal = _positive(far.get("length_nominal"), "far_end.length_nominal")
        if nominal < low - _TOLERANCE:
            raise CadError("far_end.length_nominal: under its minimum")
    else:
        band = _limits(far, "length", "far_end", "length", values)
        nominal = _nominal(far, "length_nominal", band, "far_end")
        values["length_supply"] = False
    if abs(station - nominal) > _TOLERANCE:
        raise CadError("far_end.plane: not the nominal length from the datum end")
    values["length_mm"] = nominal
    values["length_nominal_in"] = nominal / 25.4
    return nominal


def _shoulder(item: dict, frame: tuple, values: dict) -> None:
    if item.get("kind") != "face" or item.get("station_from") != "datum_end":
        raise CadError("shoulder: expected a face stationed from datum_end")
    band = _limits(item, "station", "shoulder", "shoulder", values)
    nominal = _nominal(item, "station_nominal", band, "shoulder")
    plane = item.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") != _AXES[frame[0]]:
        raise CadError("shoulder.plane: expected a plane on the datum end's axis")
    if (
        abs(
            _station(frame, _number(plane.get("value"), "shoulder.plane.value"))
            - nominal
        )
        > _TOLERANCE
    ):
        raise CadError("shoulder.plane: not the nominal station from the datum end")
    values["shoulder_mm"] = nominal


def _diameter(item: dict, name: str, frame: tuple, values: dict) -> float:
    """Bind one turned diameter; return the largest size it can be."""
    if item.get("kind") != "diameter":
        raise CadError(f"{name}: expected a model-frame diameter")
    _on_axis(item, name, frame[0])
    _span(item, name, frame, values)
    requirements = item.get("requirements", [])
    largest = 0.0
    if "dia" in requirements:
        band = _limits(item, "dia", name, f"{name}_dia", values)
        values[f"{name}_dia_mm"] = _nominal(item, "dia_nominal", band, name)
        largest = band[1]
    elif "stock" in requirements or "diametral_clearance" in requirements:
        ref = _positive(item.get("dia_ref"), f"{name}.dia_ref")
        values[f"{name}_dia_mm"], values[f"{name}_ref_in"] = ref, ref / 25.4
        largest = ref
    else:
        raise CadError(f"{name}: expected a dia band, a stock size or a matched fit")
    values[f"{name}_stock"] = "stock" in requirements
    if "stock" in requirements:
        values[f"{name}_stock_text"] = _string(item.get("stock"), f"{name}.stock")
    for fit in ("diametral_clearance", "diametral_interference"):
        if fit in requirements:
            _limits(item, fit, name, f"{name}_{fit.split('_')[1]}", values)
            values[f"{name}_mate"] = _string(item.get("mate"), f"{name}.mate")
            if fit == "diametral_clearance":
                # Turned under the measured mate: the largest it can be is
                # the mate less the least clearance; bound by the REF here.
                largest = max(largest, values[f"{name}_dia_mm"])
    if "diametral_clearance_ref" in item:
        _inch_limits(
            values,
            f"{name}_clearance_ref",
            tuple(
                _positive(v, f"{name}.diametral_clearance_ref")
                for v in item["diametral_clearance_ref"]
            ),
        )
    return largest


def _bore(item: dict, frame: tuple, values: dict) -> None:
    if item.get("kind") != "hole":
        raise CadError("bore: expected a model-frame hole")
    _on_axis(item, "bore", frame[0])
    _span(item, "bore", frame, values)
    _required(item, "thru", "bore")
    if item.get("thru") is not True:
        raise CadError("bore.thru: expected a through hole")
    band = _limits(item, "dia", "bore", "bore_dia", values)
    values["bore_dia_mm"] = _nominal(item, "nominal_dia", band, "bore")
    values["bore_process"] = _string(item.get("process"), "bore.process")
    if "wall_min" in item:
        values["bore_wall_min_in"] = _positive(item["wall_min"], "bore.wall_min") / 25.4
    if "diametral_clearance_ref" in item:
        low, high = (
            _positive(v, "bore.diametral_clearance_ref")
            for v in item["diametral_clearance_ref"]
        )
        _inch_limits(values, "bore_clearance_ref", (low, high))
        values["bore_mate"] = _string(item.get("mate"), "bore.mate")


def _pocket(item: dict, frame: tuple, values: dict) -> None:
    if item.get("kind") != "counterbore" or item.get("depth_from") != "datum_end":
        raise CadError("pocket: expected a counterbore from datum_end")
    _on_axis(item, "pocket", frame[0])
    low, _ = _span(item, "pocket", frame, values)
    if abs(low) > _TOLERANCE:
        raise CadError("pocket.span: expected to open on the datum end")
    ref = _positive(item.get("dia_ref"), "pocket.dia_ref")
    values["pocket_dia_mm"], values["pocket_ref_in"] = ref, ref / 25.4
    _required(item, "dia_max", "pocket")
    values["pocket_dia_max_in"] = (
        _positive(item.get("dia_max"), "pocket.dia_max") / 25.4
    )
    _limits(item, "diametral_clearance", "pocket", "pocket_clearance", values)
    values["pocket_mate"] = _string(item.get("mate"), "pocket.mate")
    band = _limits(item, "depth", "pocket", "pocket_depth", values)
    values["pocket_depth_mm"] = _nominal(item, "depth_nominal", band, "pocket")
    _required(item, "corner_radius_max", "pocket")
    values["pocket_corner_r_max_in"] = (
        _positive(item.get("corner_radius_max"), "pocket.corner_radius_max") / 25.4
    )
    if "wall_min" in item:
        values["pocket_wall_min_in"] = (
            _positive(item["wall_min"], "pocket.wall_min") / 25.4
        )


def _tap(item: dict, frame: tuple, values: dict) -> None:
    if item.get("kind") != "threaded_hole" or item.get("depth_from") != "datum_end":
        raise CadError("tap: expected a threaded hole from datum_end")
    _on_axis(item, "tap", frame[0])
    _required(item, "thread", "tap")
    values["tap_thread"] = _string(item.get("thread"), "tap.thread")
    band = _limits(item, "dia", "tap", "tap_drill_dia", values)
    values["tap_drill_dia_mm"] = _nominal(item, "nominal_dia", band, "tap")
    drill = _limits(item, "drill_depth", "tap", "tap_drill_depth", values)
    thread = _limits(item, "thread_depth", "tap", "tap_thread_depth", values)
    values["tap_drill_depth_mm"] = _nominal(item, "drill_depth_nominal", drill, "tap")
    values["tap_thread_depth_mm"] = _nominal(
        item, "thread_depth_nominal", thread, "tap"
    )
    if thread[1] >= drill[0]:
        raise CadError("tap: the deepest thread reaches the shallowest drilled depth")
    if "engagement_min" in item:
        values["tap_engagement_min_in"] = (
            _positive(item["engagement_min"], "tap.engagement_min") / 25.4
        )


def _chamfer(item: dict, name: str, features: dict, values: dict) -> None:
    if item.get("kind") != "chamfer":
        raise CadError(f"{name}: expected a model-frame chamfer")
    band = _limits(item, "leg", name, f"{name}_leg", values)
    values[f"{name}_leg_mm"] = _nominal(item, "leg_nominal", band, name)
    for key in ("edge_of", "at_end"):
        if item.get(key) not in features:
            raise CadError(f"{name}.{key}: expected a feature of this part")


def _bar(
    values: dict, parameters: dict, largest: float, turned: list[str]
) -> list[StockAxis]:
    """The round bar the part is turned and parted from.

    A member's outside diameter left as bought comes off its own bar,
    ``stock_dia_<member>_in``; every other diameter off ``stock_dia_in``.
    """
    stock, face, kerf = (_positive(parameters[key], f"process.{key}") for key in _BAR)
    stock_mm = stock * 25.4
    values["stock_dia_mm"] = stock_mm
    axes = [StockAxis("diameter", "stock_dia_in", largest)]
    for name in turned:
        bar_mm, key = stock_mm, "stock_dia_in"
        if name.startswith("outer_"):
            key = f"stock_dia_{name.removeprefix('outer_').lower()}_in"
            bar_mm = _positive(parameters.get(key), f"process.{key}") * 25.4
            values[f"{name}_stock_dia_mm"] = bar_mm
            axes.append(StockAxis(f"{name} diameter", key, values[f"{name}_dia_mm"]))
        if values[f"{name}_stock"]:
            if abs(bar_mm - values[f"{name}_dia_mm"]) > 0.0254:
                raise CadError(
                    f"process.{key}: {name} is left as bought at "
                    f"{values[f'{name}_ref_in']:.4f} in, not this bar"
                )
            continue
        if f"{name}_dia_band_mm" in values:
            low, high = values[f"{name}_dia_band_mm"]
            # A bar inside the band is the finished diameter as bought.
            values[f"{name}_from_bar"] = low <= bar_mm <= high
            values[f"{name}_turn_off_in"] = max(bar_mm - high, 0.0) / 25.4 / 2
    values["pitch_in"] = values["length_nominal_in"] + face + kerf
    values["pitch_mm"] = values["pitch_in"] * 25.4
    values["face_allowance_mm"] = face * 25.4
    for name in turned:
        # Turned round and gripped on this diameter: what stands out of the
        # jaws, with the facing allowance still on the out end.
        values[f"{name}_stickout_datum_mm"] = values[f"{name}_z0_mm"] + face * 25.4
        values[f"{name}_stickout_far_mm"] = (
            values["length_mm"] - values[f"{name}_z1_mm"] + face * 25.4
        )
    if "parts_per_pull" in parameters:
        pull = _positive(parameters["parts_per_pull"], "process.parts_per_pull")
        if pull != int(pull):
            raise CadError("process.parts_per_pull: expected a whole number")
        values["stickout_in"] = pull * values["pitch_in"] + face
        values["stickout_mm"] = values["stickout_in"] * 25.4
        cut = [
            values[f"{name}_dia_mm"] for name in turned if not values[f"{name}_stock"]
        ]
        values["stickout_ratio"] = values["stickout_in"] * 25.4 / min(cut or [stock_mm])
    if _all_or_none(parameters, _BAR_LENGTH, "the bar's parts count"):
        bar, grip = (
            _positive(parameters[key], f"process.{key}") for key in _BAR_LENGTH
        )
        values["parts_per_bar"] = math.floor((bar - grip) / values["pitch_in"])
        if values["parts_per_bar"] < 1:
            raise CadError("process.bar_length_in: no part fits past the chuck grip")
        if "quantity" in parameters:
            quantity = _positive(parameters["quantity"], "process.quantity")
            if quantity > values["parts_per_bar"]:
                raise CadError(
                    f"process.bar_length_in: one bar makes {values['parts_per_bar']} "
                    f"parts, under the quantity {quantity:g}"
                )
            values["bar_used_in"] = grip + quantity * values["pitch_in"]
        axes.append(
            StockAxis("length", "bar_length_in", (grip + values["pitch_in"]) * 25.4)
        )
    return axes


def _block(values: dict, parameters: dict, largest: float) -> list[StockAxis]:
    """A squared blank turned round in the 4-jaw chuck."""
    side, axial = (_positive(parameters[key], f"process.{key}") for key in _BLOCK)
    values["blank_side_mm"], values["blank_axial_mm"] = side * 25.4, axial * 25.4
    values["face_stock_in"] = axial - values["length_nominal_in"]
    if values["face_stock_in"] < 0:
        raise CadError("process.blank_axial_in: shorter than the finished length")
    values["blank_corner_in"] = side * math.sqrt(2)
    return [
        StockAxis("square side", "blank_side_in", largest),
        StockAxis("along the axis", "blank_axial_in", values["length_mm"]),
    ]


def load_turned_bush(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the part's length, diameters, bore, pocket, tap and chamfers."""
    raw, values, features = _read_manifest(path, part, "turned_bush")
    _model_frame(raw)
    frame = _frame(features)
    values["axis"] = _AXES[frame[0]]
    _length(features, frame, values)
    members = [
        name.removeprefix("outer_") for name in features if name.startswith("outer_")
    ]
    known = {"datum_end", "far_end", *_DIAMETERS, *_OPTIONAL}
    known |= {f"outer_{member}" for member in members}
    known |= {name for name in features if name.startswith("chamfer_")}
    if set(features) - known:
        raise CadError(
            f"cad.features: unsupported {', '.join(sorted(set(features) - known))}"
        )
    if "outer" not in features:
        raise CadError("outer: a turned part needs its outside diameter")
    turned = [
        name
        for name in (*_DIAMETERS, *(f"outer_{m}" for m in members))
        if name in features
    ]
    largest = max(_diameter(features[name], name, frame, values) for name in turned)
    members_found = []
    for name in turned:
        configuration = features[name].get("configuration")
        if name.startswith("outer_"):
            if (
                not isinstance(configuration, str)
                or configuration.lower() != name.removeprefix("outer_").lower()
            ):
                raise CadError(f"{name}.configuration: expected its member's name")
            members_found.append(configuration)
        elif configuration is not None:
            raise CadError(f"{name}.configuration: the default member owns it")
        if "quantity" in features[name]:
            values[f"{name}_quantity"] = int(
                _positive(features[name]["quantity"], f"{name}.quantity")
            )
    values["members"] = (
        [_string(features["outer"].get("member"), "outer.member"), *members_found]
        if members_found
        else []
    )
    values["largest_dia_mm"] = largest
    if "shoulder" in features:
        _shoulder(features["shoulder"], frame, values)
    if "bore" in features:
        _bore(features["bore"], frame, values)
    if "pocket" in features:
        _pocket(features["pocket"], frame, values)
    if "tap" in features:
        _tap(features["tap"], frame, values)
    for name in sorted(features):
        if name.startswith("chamfer_"):
            _chamfer(features[name], name, features, values)
    _edge_breaks(raw, values)
    axes: list[StockAxis] = []
    if _all_or_none(parameters, _BAR, "round bar"):
        axes = _bar(values, parameters, largest, turned)
    if _all_or_none(parameters, _BLOCK, "the squared blank"):
        if axes:
            raise CadError("process: round bar and a squared blank are exclusive")
        axes = _block(values, parameters, largest)
    requirement = StockRequirement("in", tuple(axes)) if axes else None
    return CadData(values, requirement, path.resolve())
