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
  a measured mate with a ``diametral_clearance`` or a press fit's
  ``diametral_interference`` (a ``dia`` band may add a
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
_PULL = ("parts_per_pull", "jaw_clearance_in")
_BLOCK = ("blank_side_in", "blank_axial_in")
_TOLERANCE = 1e-6
# A 118° twist drill's point beyond its full diameter, per mm of diameter.
_DRILL_POINT = 0.5 / math.tan(math.radians(59))


def _least_length(values: dict) -> float:
    """The shortest the part may be: its length band's low end, supply minimum
    or, for a REF length, the length itself."""
    if "length_band_mm" in values:
        return values["length_band_mm"][0]
    return values.get("length_min_mm", values["length_mm"])


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
    if high > values["length_mm"] + _TOLERANCE:
        raise CadError(f"{name}.span: runs past the far end")
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
    station = _station(frame, _number(plane.get("value"), "shoulder.plane.value"))
    if abs(station - nominal) > _TOLERANCE:
        raise CadError("shoulder.plane: not the nominal station from the datum end")
    if band[1] >= _least_length(values):
        raise CadError("shoulder.station: reaches the far end of the shortest part")
    values["shoulder_mm"] = nominal


_FITS = frozenset({"diametral_clearance", "diametral_interference"})


def _diameter(
    item: dict, name: str, frame: tuple, values: dict, *, press_ref: bool = False
) -> float:
    """Bind one turned diameter; return the least bar that makes it.

    ``press_ref`` admits a REF turned over its measured mate for a
    ``diametral_interference`` (turned_bush's matched press); other callers
    keep refusing it."""
    if item.get("kind") != "diameter":
        raise CadError(f"{name}: expected a model-frame diameter")
    _on_axis(item, name, frame[0])
    _span(item, name, frame, values)
    requirements = set(item.get("requirements", []))
    # One acceptance per diameter: a dia band (with an optional fit on its
    # mate, printed beside it), a stock size, or a REF turned to a mate.
    if "stock" in requirements and ({"dia"} | _FITS) & requirements:
        raise CadError(f"{name}: a stock size takes no dia band or fit")
    if _FITS <= requirements:
        raise CadError(f"{name}: a fit is a clearance or a press, not both")
    press = "dia" not in requirements and "diametral_interference" in requirements
    if press and not press_ref:
        raise CadError(f"{name}: expected a dia band, a stock size or a matched fit")
    for fit in _FITS & requirements:
        _limits(item, fit, name, f"{name}_{fit.split('_')[1]}", values)
        values[f"{name}_mate"] = _string(item.get("mate"), f"{name}.mate")
    if "dia" in requirements:
        band = _limits(item, "dia", name, f"{name}_dia", values)
        nominal = _positive(item.get("dia_nominal"), f"{name}.dia_nominal")
        if "diametral_interference" not in requirements:
            nominal = _nominal(item, "dia_nominal", band, name)
        # A press fit's band sits above its mate's nominal size: the turned
        # size is the band's middle, the nominal is bound beside it.
        values[f"{name}_dia_mm"] = (band[0] + band[1]) / 2
        values[f"{name}_nominal_mm"] = nominal
        values[f"{name}_turn_min_mm"] = band[0]
        # A bar over the band is turned down to it; one left as supplied
        # inside the band (``as_supplied``) is admitted in load_turned_bush.
        least_bar = band[1]
    elif "stock" in requirements or _FITS & requirements:
        ref = _positive(item.get("dia_ref"), f"{name}.dia_ref")
        values[f"{name}_dia_mm"], values[f"{name}_ref_in"] = ref, ref / 25.4
        least_bar = ref
        if "diametral_clearance" in requirements:
            # Turned under a measured mate: the smallest it is turned is the
            # mate at its REF less the most clearance (the turning screen's
            # stiffness size). The screen assumes the mate measures at or
            # over its REF; a smaller mate turns the part smaller than
            # screened.
            least = ref - values[f"{name}_clearance_band_mm"][1]
            values[f"{name}_turn_min_mm"] = least
        elif press:
            # A press turned over its measured mate: the smallest it is
            # turned is the mate at its REF plus the least interference (the
            # screen assumes the mate at or over its REF, as above). The bar
            # must reach the REF plus the most; a mate measuring over its REF
            # needs that much more, which the bar chosen must allow.
            interference = values[f"{name}_interference_band_mm"]
            values[f"{name}_turn_min_mm"] = ref + interference[0]
            least_bar = ref + interference[1]
    else:
        raise CadError(f"{name}: expected a dia band, a stock size or a matched fit")
    values[f"{name}_stock"] = "stock" in requirements
    if "stock" in requirements and "stock_dia_min" in item:
        # The least bar the drawing accepts as supplied.
        least = _positive(item["stock_dia_min"], f"{name}.stock_dia_min")
        values[f"{name}_stock_dia_min_in"] = least / 25.4
        values[f"{name}_stock_dia_min_mm"] = least
    return least_bar


def _tiles(values: dict, names: list[str]) -> None:
    """The diameters run end to end along the part, no gap and no overlap."""
    spans = sorted((values[f"{n}_z0_mm"], values[f"{n}_z1_mm"], n) for n in names)
    reach = 0.0
    for low, high, name in spans:
        if abs(low - reach) > _TOLERANCE:
            raise CadError(
                f"{name}.span: the diameters must run end to end along the part"
            )
        reach = high
    if abs(reach - values["length_mm"]) > _TOLERANCE:
        raise CadError("cad.features: the diameters stop short of the far end")


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
    # The drawing's least wall and a bonded bore's clearance on its mate
    # are printed acceptances the traveler states.
    if "wall_min" in item:
        values["bore_wall_min_in"] = _positive(item["wall_min"], "bore.wall_min") / 25.4
    if "diametral_clearance_ref" in item:
        clearance = item["diametral_clearance_ref"]
        if not isinstance(clearance, list) or len(clearance) != 2:
            raise CadError("bore.diametral_clearance_ref: expected a band")
        low, high = (_positive(v, "bore.diametral_clearance_ref") for v in clearance)
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
    if band[1] >= _least_length(values):
        raise CadError("pocket.depth: reaches the far end of the shortest part")
    _required(item, "corner_radius_max", "pocket")
    values["pocket_corner_r_max_in"] = (
        _positive(item.get("corner_radius_max"), "pocket.corner_radius_max") / 25.4
    )


def _tap(item: dict, frame: tuple, values: dict, parameters: dict) -> None:
    """A blind tapped hole from the datum end.

    With the plan's ``tap_lead_in`` (the finishing tap's lead, its point past
    full thread) it binds the tap point's reach, full thread plus the lead,
    capped at the least drilled depth so a tap run to it cannot bottom.
    """
    if item.get("kind") != "threaded_hole" or item.get("depth_from") != "datum_end":
        raise CadError("tap: expected a threaded hole from datum_end")
    _on_axis(item, "tap", frame[0])
    if abs(_station(frame, _number(item["at"][frame[0]], "tap.at"))) > _TOLERANCE:
        raise CadError("tap.at: expected to enter on the datum end")
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
    # The blind drill's point runs past its full-diameter depth.
    if drill[1] + _DRILL_POINT * band[1] >= _least_length(values):
        raise CadError(
            "tap.drill_depth: the drill's point reaches the far end of the shortest part"
        )
    if thread[1] >= drill[0]:
        raise CadError("tap: the deepest thread reaches the shallowest drilled depth")
    if "tap_lead_in" in parameters:
        lead = _positive(parameters["tap_lead_in"], "process.tap_lead_in") * 25.4
        if thread[0] + lead > drill[0]:
            raise CadError(
                f"process.tap_lead_in: full thread {thread[0]:.3f} mm plus the "
                f"{lead:.3f} mm lead passes the {drill[0]:.3f} mm least drilled depth"
            )
        _inch_limits(
            values, "tap_reach", (thread[0] + lead, min(thread[1] + lead, drill[0]))
        )


def _chamfer(item: dict, name: str, features: dict, values: dict) -> None:
    if item.get("kind") != "chamfer":
        raise CadError(f"{name}: expected a model-frame chamfer")
    band = _limits(item, "leg", name, f"{name}_leg", values)
    values[f"{name}_leg_mm"] = _nominal(item, "leg_nominal", band, name)
    for key in ("edge_of", "at_end"):
        if item.get(key) not in features:
            raise CadError(f"{name}.{key}: expected a feature of this part")


def _bar_size(values: dict, name: str, bar_mm: float, key: str) -> None:
    """Check a diameter left as bought or as supplied against its bar."""
    if values[f"{name}_stock"] and abs(bar_mm - values[f"{name}_dia_mm"]) > 0.0254:
        raise CadError(
            f"process.{key}: {name} is left as bought at "
            f"{values[f'{name}_ref_in']:.4f} in, not this bar"
        )
    if values.get(f"{name}_as_supplied"):
        low, high = values[f"{name}_dia_band_mm"]
        # The slack absorbs inch-to-mm conversion noise at the edges.
        if not low - _TOLERANCE <= bar_mm <= high + _TOLERANCE:
            raise CadError(
                f"process.{key}: {name} is left as supplied, so its bar must "
                f"lie inside its band {low / 25.4:.4f}-{high / 25.4:.4f} in"
            )
        # Not turned: the diameter, and the least it is cut, are the bar's.
        values[f"{name}_dia_mm"] = bar_mm
        values[f"{name}_turn_min_mm"] = bar_mm


def _lathe_z(values: dict, name: str) -> None:
    """The diameter's run in the bar's Z frame (Z0 the end faced first, Z+
    away from the chuck), with either end of the part out."""
    z0, z1, length = (
        values[f"{name}_z0_mm"],
        values[f"{name}_z1_mm"],
        values["length_mm"],
    )
    values[f"{name}_datum_out_near_z_mm"] = -z0
    values[f"{name}_datum_out_far_z_mm"] = -z1
    values[f"{name}_far_out_near_z_mm"] = z1 - length
    values[f"{name}_far_out_far_z_mm"] = z0 - length


def _as_supplied(parameters: dict, sizes: dict, values: dict) -> list[str]:
    """``as_supplied_<name> = 1``: a banded diameter the bar already lies
    inside, left as supplied, so the bar need reach only the band's low end
    (checked in _bar_size). Plan parameters are numbers, hence the 0/1 flag."""
    supplied = []
    for key in sorted(k for k in parameters if k.startswith("as_supplied_")):
        name = key.removeprefix("as_supplied_")
        if parameters[key] not in (0, 1) or isinstance(parameters[key], bool):
            raise CadError(f"process.{key}: expected 0 or 1")
        if name not in sizes or f"{name}_dia_band_mm" not in values:
            raise CadError(f"process.{key}: {name!r} is not a banded diameter")
        if parameters[key]:
            supplied.append(name)
            values[f"{name}_as_supplied"] = True
            sizes[name] = values[f"{name}_dia_band_mm"][0]
    return supplied


def _rough_sizes(
    parameters: dict, values: dict, sizes: dict, turned: list[str], supplied: list
) -> None:
    """With ``finish_allowance_in``, each turned diameter's rough size."""
    if "finish_allowance_in" not in parameters:
        return
    allowance = _positive(
        parameters["finish_allowance_in"], "process.finish_allowance_in"
    )
    for name in turned:
        if f"{name}_turn_min_mm" in values and name not in supplied:
            # Roughed to this, a side's allowance over its smallest size.
            values[f"{name}_rough_dia_mm"] = (
                values[f"{name}_turn_min_mm"] + 2 * allowance * 25.4
            )
            # The bar must also reach the rough size it is roughed to.
            sizes[name] = max(sizes[name], values[f"{name}_rough_dia_mm"])


def _count(parameters: dict, key: str) -> int:
    value = _positive(parameters[key], f"process.{key}")
    if value != int(value):
        raise CadError(f"process.{key}: expected a whole number")
    return int(value)


def _bar(
    values: dict, parameters: dict, sizes: dict, least_bar: float, turned: list[str]
) -> list:
    """The round bar the part is turned and parted from.

    Each part takes, from its bar end: the facing allowance, the part, the
    regrip allowance (``regrip_allowance_in``, left on the parted end to face
    in a second chucking; none by default) and the parting kerf. A member's
    outside diameter left as bought comes off its own bar,
    ``stock_dia_<member>_in``; every other diameter off ``stock_dia_in``.
    """
    stock, face, kerf = (_positive(parameters[key], f"process.{key}") for key in _BAR)
    regrip = 0.0
    if "regrip_allowance_in" in parameters:
        regrip = _positive(
            parameters["regrip_allowance_in"], "process.regrip_allowance_in"
        )
    stock_mm = stock * 25.4
    values["stock_dia_mm"] = stock_mm
    axes = [StockAxis("diameter", "stock_dia_in", least_bar)]
    for name in turned:
        bar_mm, key = stock_mm, "stock_dia_in"
        if name.startswith("outer_"):
            key = f"stock_dia_{name.removeprefix('outer_').lower()}_in"
            bar_mm = _positive(parameters.get(key), f"process.{key}") * 25.4
            values[f"{name}_stock_dia_mm"] = bar_mm
            axes.append(StockAxis(f"{name} diameter", key, sizes[name]))
        # The plan parameter naming this diameter's bar, for its pictures.
        values[f"{name}_stock_key"] = key
        _bar_size(values, name, bar_mm, key)
    length = values["length_mm"]
    values["face_allowance_mm"] = face * 25.4
    values["regrip_allowance_mm"] = regrip * 25.4
    values["part_off_in"] = values["length_nominal_in"] + regrip
    values["part_off_mm"] = values["part_off_in"] * 25.4
    values["pitch_in"] = face + values["part_off_in"] + kerf
    values["pitch_mm"] = values["pitch_in"] * 25.4
    grip_mm = math.inf
    if "regrip_grip_in" in parameters:
        # How much of the gripped diameter the regrip's jaws take, from its
        # chuck-side end; the whole diameter when not stated.
        grip_mm = (
            _positive(parameters["regrip_grip_in"], "process.regrip_grip_in") * 25.4
        )
        values["regrip_grip_mm"] = grip_mm
    for name in turned:
        z0, z1 = values[f"{name}_z0_mm"], values[f"{name}_z1_mm"]
        # Turned round and gripped on this diameter after parting: what
        # stands out of the jaws, the regrip allowance still on the out end.
        values[f"{name}_stickout_datum_mm"] = max(z0, z1 - grip_mm) + regrip * 25.4
        values[f"{name}_stickout_far_mm"] = (
            length - min(z1, z0 + grip_mm) + regrip * 25.4
        )
        # The regrip's jaw fronts in its Z frame, Z0 on the out end once it
        # is faced (Z+ away from the chuck): a turning_support chuck_z_mm.
        values[f"{name}_regrip_jaw_z_datum_mm"] = -max(z0, z1 - grip_mm)
        values[f"{name}_regrip_jaw_z_far_mm"] = min(z1, z0 + grip_mm) - length
        _lathe_z(values, name)
    clear = 0.0
    if _all_or_none(parameters, _PULL, "the parts out of the jaws"):
        pull = _count(parameters, "parts_per_pull")
        clear = _positive(parameters["jaw_clearance_in"], "process.jaw_clearance_in")
        # The arriving end stands the facing allowance out at Z+; part k runs
        # back from -k × pitch; the last part's kerf ends one facing
        # allowance short of a whole number of pitches, and the jaws stand
        # the clearance beyond.
        run = pull * values["pitch_in"] - face
        values["stickout_in"] = run + clear + face
        values["stickout_mm"] = values["stickout_in"] * 25.4
        # From the faced end through the last parting line: a drill through
        # the pull reaches this deep.
        values["run_in"] = run
        values["run_mm"] = run * 25.4
        values["run_end_z_mm"] = -run * 25.4
        values["jaw_z_mm"] = -(run + clear) * 25.4
        values["kept_end_z_mm"] = -(
            (pull - 1) * values["pitch_mm"] + values["part_off_mm"]
        )
    if _all_or_none(parameters, _BAR_LENGTH, "the bar's parts count"):
        bar, grip = (
            _positive(parameters[key], f"process.{key}") for key in _BAR_LENGTH
        )
        # The last part's kerf stands the jaw clearance off the jaws.
        values["parts_per_bar"] = math.floor((bar - grip - clear) / values["pitch_in"])
        quantity = _count(parameters, "quantity") if "quantity" in parameters else 1
        if quantity > values["parts_per_bar"]:
            raise CadError(
                f"process.bar_length_in: one bar makes {values['parts_per_bar']} "
                f"parts, under the quantity {quantity}"
            )
        axes.append(
            StockAxis(
                "length",
                "bar_length_in",
                (grip + clear + quantity * values["pitch_in"]) * 25.4,
            )
        )
    return axes


def _block(values: dict, parameters: dict, least_bar: float) -> list:
    """A squared blank turned round in the 4-jaw chuck."""
    side, axial = (_positive(parameters[key], f"process.{key}") for key in _BLOCK)
    values["blank_side_mm"], values["blank_axial_mm"] = side * 25.4, axial * 25.4
    values["face_stock_in"] = axial - values["length_nominal_in"]
    if values["face_stock_in"] < 0:
        raise CadError("process.blank_axial_in: shorter than the finished length")
    return [
        StockAxis("square side", "blank_side_in", least_bar),
        StockAxis("along the axis", "blank_axial_in", values["length_mm"]),
    ]


def load_turned_bush(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the part's length, diameters, bore, pocket, tap and chamfers."""
    raw, values, features = _read_manifest(path, part, "turned_bush")
    _model_frame(raw)
    for name, item in features.items():
        if not isinstance(item, dict) or item.get("frame") != "model":
            raise CadError(f"{name}: expected a model-frame feature")
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
    sizes = {
        name: _diameter(features[name], name, frame, values, press_ref=True)
        for name in turned
    }
    _tiles(values, [name for name in _DIAMETERS if name in sizes])
    for name in turned:
        if name.startswith("outer_"):
            _tiles(values, [name, *(["step"] if "step" in sizes else [])])
    supplied = _as_supplied(parameters, sizes, values)
    members_found, members_outer = [], []
    for name in turned:
        configuration = features[name].get("configuration")
        if name.startswith("outer_"):
            if (
                not isinstance(configuration, str)
                or configuration.lower() != name.removeprefix("outer_").lower()
            ):
                raise CadError(f"{name}.configuration: expected its member's name")
            members_found.append(configuration)
            members_outer.append(name)
        elif configuration is not None:
            raise CadError(f"{name}.configuration: the default member owns it")
    values["members"] = (
        [_string(features["outer"].get("member"), "outer.member"), *members_found]
        if members_found
        else []
    )
    if len({m.lower() for m in values["members"]}) != len(values["members"]):
        raise CadError("cad.features: member names must differ in more than case")
    # Each member's outer feature, for pictures that draw one member.
    values["member_outers"] = (
        dict(zip(values["members"], ["outer", *members_outer], strict=True))
        if members_found
        else {}
    )
    if "shoulder" in features:
        _shoulder(features["shoulder"], frame, values)
    if "bore" in features:
        _bore(features["bore"], frame, values)
    if "pocket" in features:
        _pocket(features["pocket"], frame, values)
    if "tap" in features:
        _tap(features["tap"], frame, values, parameters)
    for name in sorted(features):
        if name.startswith("chamfer_"):
            _chamfer(features[name], name, features, values)
    _edge_breaks(raw, values)
    _rough_sizes(parameters, values, sizes, turned, supplied)
    # The default member's bar or blank: the other members bring their own.
    least_bar = max(sizes[name] for name in _DIAMETERS if name in sizes)
    axes: list[StockAxis] = []
    # Round bar is named by its diameter; the facing allowance and kerf may
    # also serve a squared blank's pictures.
    if "stock_dia_in" in parameters and _all_or_none(parameters, _BAR, "round bar"):
        axes = _bar(values, parameters, sizes, least_bar, turned)
    elif "regrip_grip_in" in parameters:
        raise CadError("process.regrip_grip_in: binds only with round bar")
    if _all_or_none(parameters, _BLOCK, "the squared blank"):
        if axes:
            raise CadError("process: round bar and a squared blank are exclusive")
        if supplied:
            raise CadError("process.as_supplied: a squared blank is always turned")
        axes = _block(values, parameters, least_bar)
    if supplied and "stock_dia_mm" not in values:
        raise CadError("process.as_supplied: needs round bar")
    requirement = StockRequirement("in", tuple(axes)) if axes else None
    return CadData(values, requirement, path.resolve())
