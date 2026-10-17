"""The five TOML input schemas. Literal unknown is never a numeric default."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    model_serializer,
    model_validator,
)

type Unknown = Literal["unknown"]
UNKNOWN: Unknown = "unknown"
type Number = float | Unknown
type Vector = list[Number] | Unknown
type Citations = str | list[str]
TOLERANCE_REQUIREMENTS = frozenset(
    "dia nominal_dia position_dia angularity_dia finish_ra depth length width height radius "
    "thickness coaxiality_dia surface_profile "
    "height_above_pivot arc_len bottom_radius bottom_arc_len tip_land land_angle_deg station "
    "groove_width groove_depth separation".split()
)
# The BASIC dimensions a surface profile may govern: every recognised requirement the
# inspection rule reads as a dimension, never a zone (a position, coaxiality, angularity,
# roughness or the profile itself), whose scalar is already a zone width or a maximum.
PROFILE_GOVERNABLE = TOLERANCE_REQUIREMENTS - {
    "position_dia",
    "coaxiality_dia",
    "angularity_dia",
    "finish_ra",
    "surface_profile",
}
# The face extents a tilt is read across (``tilt_across``): every recognised linear dimension
# in manifest length units, never an angle, a roughness or a geometric zone.
LENGTH_REQUIREMENTS = frozenset(r for r in PROFILE_GOVERNABLE if not r.endswith("_deg"))
# The BASIC lengths read along the surface normal through a centre: a radius about it, a
# diameter across it. The normal is the reading direction at every point, so a profile
# entry never reads them at an obliquity (``obliquity_deg`` is for planar readings).
CENTRED = frozenset({"radius", "bottom_radius", "dia", "nominal_dia"})


def tolerance_requirements(feature: dict[str, Any]) -> list[str]:
    """Preserve unknown identities and every authored numeric requirement band."""
    requirements = feature.get("requirements", UNKNOWN)
    if requirements == UNKNOWN:
        return [UNKNOWN]
    result = []
    for requirement in requirements:
        value = feature.get(requirement)
        band = (
            isinstance(value, list)
            and len(value) == 2
            and all(
                item == UNKNOWN or isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in value
            )
        )
        if requirement == UNKNOWN or requirement in TOLERANCE_REQUIREMENTS or band:
            result.append(requirement)
    return sorted(result)


def profile_target(owner: str, key: str) -> tuple[str, str]:
    """``(feature, requirement)`` a ``surface_profile_governs`` key of feature ``owner``
    names: a bare ``requirement`` is the owner's own, ``"feature:requirement"`` another's."""
    feature, _, requirement = key.rpartition(":")
    return feature or owner, requirement


def reference_only(feature: dict[str, Any], requirement: str) -> bool:
    """A drawing's reference dimension (``<name>_ref``, such as a CUT TO FIT span): a number
    the drawing states with no limit, so no drawing band exists to hold inside."""
    value = feature.get(requirement)
    return (
        requirement.endswith("_ref")
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def record(name: str, fields: dict[str, Any], *, indexed: tuple[str, ...] = ()) -> type[InputModel]:
    """Optional unknown defaults; retain rule-indexed defaults in sparse dumps."""

    @model_serializer(mode="wrap")
    def include_indexed_defaults(self, handler):
        values = handler(self)
        for key in indexed:
            values[key] = getattr(self, key)
        return values

    return create_model(
        name,
        __base__=InputModel,
        __validators__={"include_indexed_defaults": include_indexed_defaults} if indexed else {},
        **{key: (annotation | Unknown, UNKNOWN) for key, annotation in fields.items()},
    )


def texts(names: str) -> dict[str, Any]:
    return {name: str for name in names.split()}


def numbers(names: str) -> dict[str, Any]:
    return {name: float for name in names.split()}


def flags(names: str) -> dict[str, Any]:
    return {name: bool for name in names.split()}


Drawing = record("Drawing", {**texts("number revision"), "cite": Citations})
Paths = record("Paths", texts("inventory policy cutting_data step"))
Direction = record("Direction", texts("x y z"))
Dro = record(
    "Dro",
    {
        **texts("controller manual manual_url mode units"),
        "radius_mode": bool,
        "direction": Direction,
    },
)


# A blank bought already profiled (laser-, waterjet- or plasma-cut): the supplied solid is
# the bundle-relative ``step``, authored in the part model's coordinates and bound by its
# ``step_sha256``; ``profile_tolerance_mm`` is the vendor's declared ± cut tolerance (a
# cited vendor value, never a measurement). See docs/plan.md "Profiled blank".
PROFILED_BLANK = "profiled_blank"
ProfiledBlank = record(
    "ProfiledBlank",
    {**texts("step step_sha256"), **numbers("profile_tolerance_mm"), "cite": Citations},
)
# The fields that size or place a box or round bar; a profiled blank's STEP does both.
BAR_ENVELOPE = ("section_mm", "dia_mm", "length_mm", "origin_mm", "axis", "section_axis")


def profiled(piece: Any) -> bool:
    """Whether a loaded stock or component table is a profiled blank: its form or an
    authored ``blank`` table (known or ``"unknown"``) says so. Every reader uses this one
    test, so a form-only blank is never mistaken for bar stock."""
    return isinstance(piece, dict) and ("blank" in piece or piece.get("form") == PROFILED_BLANK)


def profiled_blank_errors(stock: Any, where: str) -> list[str]:
    """Contradictions in one root stock or component that declares a profiled blank."""
    fields = getattr(stock, "model_fields_set", set())
    if "blank" not in fields and getattr(stock, "form", UNKNOWN) != PROFILED_BLANK:
        return []
    errors = []
    if "blank" in fields and stock.form != PROFILED_BLANK:
        errors.append(f"{where} declares a blank, so its form is {PROFILED_BLANK!r}")
    bar = [name for name in BAR_ENVELOPE if name in fields]
    if bar:
        errors.append(
            f"{where} is a profiled blank: its STEP is the envelope in model coordinates, "
            f"so it declares no {', '.join(bar)}"
        )
    blank = stock.blank if isinstance(stock.blank, InputModel) else None
    if blank is None:
        return errors
    if blank.step != UNKNOWN and not blank.step.strip():
        errors.append(f"{where}.blank.step names no file")
    digest = blank.step_sha256
    if digest != UNKNOWN and not re.fullmatch(r"[0-9a-f]{64}", digest):
        errors.append(f"{where}.blank.step_sha256 is not a lowercase SHA-256")
    tolerance = blank.profile_tolerance_mm
    if tolerance != UNKNOWN and tolerance <= 0:
        errors.append(f"{where}.blank.profile_tolerance_mm must be positive")
    return errors


class StockComponent(InputModel):
    id: Annotated[str, Field(min_length=1)]
    form: str | Unknown = UNKNOWN
    note: str | Unknown = UNKNOWN
    dia_mm: Number = UNKNOWN
    length_mm: Number = UNKNOWN
    section_mm: Vector = UNKNOWN
    origin_mm: Vector = UNKNOWN
    axis: Vector = UNKNOWN
    section_axis: Vector = UNKNOWN
    blank: ProfiledBlank | Unknown = UNKNOWN
    cite: Citations = UNKNOWN

    @model_validator(mode="after")
    def known_id(self) -> StockComponent:
        if not self.id.strip() or self.id == UNKNOWN:
            raise ValueError("Stock component id must be a known identifier.")
        return self


# The squared blank's acceptance checks: one gauge per size (``length``, ``section_0``,
# ``section_1``, read against size ± tolerance) and one per form check, each form check
# with its written method in ``methods`` and its limit in ``form_mm`` (the most, in mm,
# its method's gauge may move over the face; the gauge's resolution must read it).
PreparedChecks = record(
    "PreparedChecks",
    {**texts("length section_0 section_1 flat square parallel")},
)
PreparedMethods = record("PreparedMethods", {**texts("flat square parallel")})
PreparedForm = record("PreparedForm", numbers("flat square parallel"))
# The squared blank the route's first machining setup receives (docs/plan.md "Prepared
# blank"): a box on the root stock's own axes, made from the rectangular root stock by
# plan process end faces in the receiving setup's earlier stock lineage.
PreparedBlank = record(
    "PreparedBlank",
    {
        "setup": str,
        "origin_mm": Vector,
        "section_mm": Vector,
        "length_mm": float,
        "tolerance_mm": Vector,
        "checks": PreparedChecks,
        "methods": PreparedMethods,
        "form_mm": PreparedForm,
        "cite": Citations,
    },
)
Stock = record(
    "Stock",
    {
        **texts("form material drawing_material note supply_datum prerequisite"),
        **numbers("dia_mm length_mm north_allowance_mm south_grip_mm supply_length_mm"),
        **flags("material_verify form_verify on_hand"),
        "material_cite": Citations,
        "section_mm": Vector,
        "origin_mm": Vector,
        "axis": Vector,
        "section_axis": Vector,
        "as_is_faces": list[str],
        "components": list[StockComponent],
        "prepared": PreparedBlank,
        "blank": ProfiledBlank,
        "cite": Citations,
    },
)
StockState = record(
    "StockState",
    {
        **texts("top_feature bottom_feature note"),
        **numbers(
            "top_z bottom_z retained_rail_bottom_z od_mm north_end_z south_end_z plain_end_z"
        ),
        "bottom_z_cite": Citations,
        "local_thickness": dict[str, Number],
        "local_thickness_cite": dict[str, Citations],
        "entry_z": dict[str, Number],
    },
)
# A `hold.supports` table: follow rest {ref, ops, jaw_lead_mm[, jaw_side]} or steady rest
# {ref, ops, at_z_mm}. A follow rest's jaw_side is "turned" (behind the cutting point along
# the feed, on the diameter just cut; the default) or "uncut" (ahead of it); its
# engage_at_z_mm is the cut Z the tool passes before the jaws are set on the work.
Reference = record(
    "Reference",
    {
        **texts("ref orientation note jaw_side"),
        **numbers("height_mm jaw_lead_mm at_z_mm engage_at_z_mm"),
        "ops": list[int],
    },
)
# ``rotation = "continuous"``: a dividing head turned freely by its rotary ops, no plate.
Index = record(
    "Index",
    {
        "fixture": str,
        "feature": str,
        "angle_deg": Number,
        "positions": int,
        "rotation": Literal["continuous"],
    },
)
type Point3 = Annotated[list[Number], Field(min_length=3, max_length=3)]
# A fixture-local frame placed in the setup frame (mm): origin plus unit x and z axes.
Pose = record("Pose", {"origin_mm": Point3, "x": Point3, "z": Point3})
# ``restraint``: press holds stock down onto the fixture; locate only positions it.
# ``torque_nm``: the declared tightening torque the traveler prints in the clamp order.
# ``tighten = "hand"``: tightened by hand only, never with a wrench; the traveler's clamp
# order prints it, so a clamp note must not restate hand tightening (consistency).
ClampPlacement = record(
    "ClampPlacement",
    {
        **texts("ref note"),
        "pose": Pose,
        "restraint": Literal["press", "locate", "none"],
        "torque_nm": Number,
        "tighten": Literal["hand"],
    },
)
type PlanCentres = list[Annotated[list[Number], Field(min_length=2, max_length=2)]]
# A stickout set from a measured fit-up: the printed ``stickout_mm`` is the nominal
# ``nominal_mm + add_mm``; the operator sets the ``measure`` reading plus ``add_mm``.
StickoutFit = record("StickoutFit", {"measure": str, **numbers("nominal_mm add_mm")})
# The step that squares a mill vise's fixed jaw, or an angle plate's locating face (the
# fixture solid ``face`` names), to the table travel before the work goes in: the
# ``indicator`` (an inventory gauge) is swept ``over_mm`` along it and its reading may
# change by at most ``limit_mm``.
Align = record(
    "Align",
    {**texts("indicator face"), **numbers("limit_mm over_mm"), "cite": Citations},
)
Hold = record(
    "Hold",
    {
        **texts(
            "fixture jaws_along fixed_jaw parallels support support_orientation "
            "grip_on stop clamp note centre_lubrication riser method orientation locator "
            "release jaw_protection locate chuck riser_up riser_along parallels_along"
        ),
        "grip_mm": Number | Literal["not_applicable"],
        "jaw_above_parallels_mm": Number | Literal["not_applicable"],
        "stickout_mm": Number,
        "stickout_fit": StickoutFit,
        "jaw_center_along_mm": Number,
        "parallels_centres_mm": Annotated[PlanCentres, Field(min_length=2, max_length=2)],
        "riser_centres_mm": Annotated[PlanCentres, Field(min_length=1)],
        "supports": str | list[str | Reference],
        **flags("grip_mm_verify jaw_above_parallels_mm_verify"),
        "index": Index,
        "pose": Pose,
        "jaw_clock_deg": Number,
        "support_tip_mm": Point3,
        "quill_extension_mm": Number,
        # The countersink mouth of the work's centre hole at its end face: the dead centre
        # seats in a cone of its own point angle that opens to this diameter.
        "centre_hole_dia_mm": Number,
        # The plan.process_features centre_hole the dead or live centre rides in, made by an
        # op of an earlier setup in this setup's stock_in lineage (checked by centre_support).
        "centre_hole": str,
        "clamps": list[ClampPlacement],
        # Diagram annotations: action order references the 1-based clamps array.
        "clamp_order": list[Annotated[int, Field(gt=0)]],
        "preload_direction": Literal["clockwise", "counterclockwise"] | Unknown,
        "stop_fixture": str,
        # The face the work is set against: a feature already on the arriving stock, or
        # the stock's own end. Checked against the arriving stock by hold_fields.
        "stop_face": str,
        "stop_pose": Pose,
        # A vise's round bar between the work and the moving jaw (an inventory fixture of
        # kind round_bar with measured dia/length): the moving jaw closes on the bar, which
        # presses the work along one line so the fixed jaw seats its face square.
        "jaw_bar": str,
        # A vise's pair of jaw buttons (an inventory fixture of kind jaw_buttons with
        # measured dia, thickness, spigot_dia and spigot_length): one between each jaw and
        # the work, its spigot seated in the work's bore that opens on that jaw face.
        "jaw_buttons": str,
        # Required where a mill setup mounts or turns a vise or angle plate (hold_fields).
        "align": Align,
    },
)
# ``measure_before_hold``: a ``measure_then_set`` M read on the part before it is held (a
# span the hold then covers): the HOLD prints the reading before the clamping.
AxisZero = record(
    "AxisZero",
    {
        **texts("edge feature face method tool holder gauge measure"),
        "from": str,
        **numbers("edge_mm radius_mm paper_mm check_jog_mm offset_mm"),
        "retouch_after": list[int],
        "after_op": int,
        "measure_before_hold": bool,
    },
)
# ``keep_clamped``: the hold must not be loosened to realign the work (an indexed setup
# that keeps the earlier chucking); ``recovery`` is then the plan's sequence for a sweep
# that reads over the limit, printed in place of the loosen-and-tap advice.
Transfer = record(
    "Transfer",
    {
        "from": str,
        "indicate": str | list[str],
        "tool": str,
        "gauge": str,
        "runout_limit_mm": Number,
        "reindicate_after": list[int],
        "keep_clamped": bool,
        "recovery": str,
    },
)
# A lathe touch's X surface: ``x_face`` names the plan feature (or ``"x_zero"``, this
# setup's X-zero trial-cut land) whose measured diameter the tool touches, through
# ``x_paper_mm`` of paper; x_method keeps the operator's words.
ToolTouch = record(
    "ToolTouch",
    {
        **texts("tool x_method x_face gauge z_face method z_gauge z_measure"),
        **numbers("edge_mm paper_mm x_paper_mm z_offset_mm"),
        # The blade corner a grooving/parting blade's Z touch sets, where the touched
        # face's normal cannot give it (a scribe): docs/rules-coordinates.md.
        "corner": Literal["chuck_side", "tailstock_side"],
        "before_ops": list[int],
        "after_op": int,
    },
)
Zero = record(
    "Zero",
    {
        "x": AxisZero,
        "y": AxisZero,
        "z": AxisZero,
        "transfer": Transfer,
        "tool_touches": list[ToolTouch],
    },
)
Bounds = record("Bounds", {"x": Vector, "y": Vector, "z": Vector})
KeepOut = record("KeepOut", {"at": Vector, **numbers("dia_mm")})
# A ``guided_sweep`` contour's guide (docs/plan.md "Manual arcs"): the work rides
# ``fixture`` (an inventory swing arm on a ``pivot`` at the arc centre, or a sled whose
# ``rail`` bears on two table rollers) under a cutter touched off on the ``master`` gauge
# along ``touch_axis`` and locked; the fixture turns ``sweep_deg`` about the centre. A rail's
# ``rollers_deg`` and ``rail_deg`` (its ends) are degrees about the arc centre from the
# cutter's radial line, counterclockwise from above, with the cutter at the arc's middle.
GuidedSweep = record(
    "GuidedSweep",
    {
        "guide": Literal["pivot", "rail"],
        **texts("fixture master"),
        "touch_axis": Literal["+X", "-X", "+Y", "-Y"],
        **numbers("sweep_deg"),
        "rollers_deg": Vector,
        "rail_deg": Vector,
    },
)
# A manual-mill arc method (docs/plan.md): ``stairs`` and ``chain_drill`` rough outside the
# line, ``chords`` mill straight chords, ``rotary_table`` turns the work under the cutter,
# ``guided_sweep`` sweeps it under a locked cutter on a pivot or rail fixture (``sweep``).
Contour = record(
    "Contour",
    {
        **texts("method sweep_frame open_side centre_by centre_feature"),
        **numbers("step_deg step_mm start_deg end_deg pitch_mm cusp_mm"),
        "count": int,
        "sweep_bounds": Bounds,
        "keep_out": list[KeepOut],
        "sweep": GuidedSweep,
    },
)
# A layout or bench filing guide: ``buttons`` (an inventory ``fixtures`` kit of kind
# ``filing_buttons``) pinned through the plan feature ``bore``, or a radius ``template``
# (an inventory gauge); the ``gauge`` (an inventory radius or profile gauge) checks the arc.
Guide = record("Guide", texts("buttons bore template gauge"))
SawPlane = record(
    "SawPlane",
    {"axis": Literal["x", "y", "z"], "value": Number, "keep": Literal["below", "above"]},
)


class GoNoGo(InputModel):
    """The two limit-gauge sizes (mm) a go/no-go check uses: the GO size must pass the
    work (enter a hole, slip over a shaft) and the NO-GO size must not."""

    go: float
    no_go: float

    @model_validator(mode="after")
    def sized(self) -> GoNoGo:
        if not (self.go > 0 and self.no_go > 0):
            raise ValueError("GO and NO-GO gauge sizes must be positive.")
        if self.go == self.no_go:
            raise ValueError("GO and NO-GO gauge sizes must differ.")
        return self


def _requirement_pairs(value: dict) -> dict:
    """A feature's scoped table keys requirements: a malformed pair (``go`` / ``no_go``
    keys) must fail as a pair, never pass as a table of requirement entries."""
    if {"go", "no_go"} & set(value):
        raise ValueError("A GO / NO-GO pair needs two positive sizes, go and no_go.")
    return value


# One listed feature's GO / NO-GO pairs, requirement -> pair.
type ScopedGoNoGo = Annotated[dict[str, GoNoGo | Unknown], AfterValidator(_requirement_pairs)]


class ProcessHold(InputModel):
    """A shop limit inside one drawing requirement band, held for a stated process reason
    (a downstream fit, a clocking stop): printed as a process hold, never a drawing limit.

    On a reference-only dimension (``<name>_ref``, such as a CUT TO FIT span) the drawing
    sets no limit: the hold then names what its gauge reads (``measure``) and where its
    band comes from (``cite``)."""

    feature: str
    requirement: str
    band: Annotated[list[float], Field(min_length=2, max_length=2)]
    gauge: str
    reason: str
    # The GO / NO-GO sizes the hold's gauge reads the hold band with, when it is a limit check.
    go_no_go: GoNoGo | None = None
    measure: str | None = None
    cite: Citations | None = None

    @model_validator(mode="after")
    def stated(self) -> ProcessHold:
        for value, what in (
            (self.feature, "feature"),
            (self.requirement, "requirement"),
            (self.reason, "reason"),
            *(((self.measure, "measure"),) if self.measure is not None else ()),
        ):
            _known_text(value, f"A process hold {what}")
        cites = [self.cite] if isinstance(self.cite, str) else self.cite
        if cites is not None and (not cites or any(not c.strip() or c == UNKNOWN for c in cites)):
            raise ValueError("A process hold cite must name known, non-empty sources.")
        if not self.band[0] < self.band[1]:
            raise ValueError("A process hold band must be an ordered [lo, hi] band, lo < hi.")
        return self


# An inspection procedure: one string (blank-line paragraphs print as numbered steps), or a
# list of steps, each printed as one numbered step; a ``{name}`` in a step prints a labelled
# recording blank, and a step starting ``Calculate:`` prints as the calculation line.
type Procedure = str | Annotated[list[str], Field(min_length=1)]


class Aim(InputModel):
    """A drawing requirement held at a stated value inside its band: a process choice.

    Without ``face``, a located feature's DRO target moved off its drawing nominal so its
    height-like band from ``height_from`` (``height_above_pivot``, ``height`` or
    ``separation``) reads ``value_mm``, printed beside the target, never geometry. With
    ``face``, the faced length between the feature's ``lower_z`` and ``upper_z`` planes
    held at ``value_mm`` by moving that one faced plane: the kernel cuts the part with the
    face there."""

    requirement: str
    value_mm: float
    reason: str
    face: str | None = None

    @model_validator(mode="after")
    def stated(self) -> Aim:
        _known_text(self.requirement, "An aim requirement")
        _known_text(self.reason, "An aim reason")
        if self.face is not None:
            _known_text(self.face, "An aim face")
        return self


type KnownPoint3 = Annotated[list[float], Field(min_length=3, max_length=3)]
# Authored unit vectors carry trig residue; the kernel's pose tolerance applies.
UNIT_TOLERANCE = 1e-6


def _unit(vector: list[float], what: str) -> None:
    if abs(math.sqrt(sum(v * v for v in vector)) - 1.0) > UNIT_TOLERANCE:
        raise ValueError(f"{what} must be a unit vector.")


class InspectionAid(InputModel):
    """A gauge, block or holding an inspection sketch draws, in the part model's own
    coordinates (mm): a ``box`` from its least corner ``at_mm`` by ``size_mm`` along its
    edge directions ``axes`` (unit x then y, square; the model's X and Y when absent), or a
    ``cylinder`` (a gauge pin, a rod) from its base centre ``at_mm`` along the unit
    ``axis``, ``dia_mm`` across and ``length_mm`` long."""

    name: str
    shape: Literal["box", "cylinder"]
    at_mm: KnownPoint3
    size_mm: KnownPoint3 | None = None
    axes: Annotated[list[KnownPoint3], Field(min_length=2, max_length=2)] | None = None
    axis: KnownPoint3 | None = None
    dia_mm: float | None = None
    length_mm: float | None = None

    @model_validator(mode="after")
    def sized(self) -> InspectionAid:
        _known_text(self.name, "An inspection aid name")
        turned = (self.axis, self.dia_mm, self.length_mm)
        if self.shape == "box":
            if self.size_mm is None or any(v is not None for v in turned):
                raise ValueError(
                    f"Inspection aid {self.name!r}: a box states size_mm and its axes only."
                )
            if min(self.size_mm) <= 0:
                raise ValueError(f"Inspection aid {self.name!r}: a box size must be positive.")
            if self.axes is not None:
                x, y = self.axes
                _unit(x, f"Inspection aid {self.name!r} x axis")
                _unit(y, f"Inspection aid {self.name!r} y axis")
                if abs(sum(a * b for a, b in zip(x, y, strict=True))) > UNIT_TOLERANCE:
                    raise ValueError(f"Inspection aid {self.name!r}: its axes must be square.")
            return self
        if self.size_mm is not None or self.axes is not None or any(v is None for v in turned):
            raise ValueError(
                f"Inspection aid {self.name!r}: a cylinder states axis, dia_mm and length_mm."
            )
        _unit(self.axis, f"Inspection aid {self.name!r} axis")
        if self.dia_mm <= 0 or self.length_mm <= 0:
            raise ValueError(f"Inspection aid {self.name!r}: a cylinder size must be positive.")
        return self


class InspectionMark(InputModel):
    """A labelled point of an inspection sketch, in the part model's coordinates (mm): a
    datum contact, a stop, a gauge position. A ``reads`` mark is where a height reading is
    taken; the sketch draws its + arrow up off the plate (a higher contact reads +)."""

    label: str
    at_mm: KnownPoint3
    reads: bool = False

    @model_validator(mode="after")
    def named(self) -> InspectionMark:
        _known_text(self.label, "An inspection mark label")
        return self


class InspectionView(InputModel):
    """One labelled look at the part set up on the surface plate for an inspection: ``up``
    (a unit vector in the part model's axes) points up off the plate, the way a height
    reading rises, and ``toward`` points from the part to the viewer, square to ``up``.
    The sketch draws the part as the inspection's setup leaves it, the ``aids`` and the
    ``marks``."""

    title: str
    up: KnownPoint3
    toward: KnownPoint3
    aids: list[InspectionAid] = Field(default_factory=list)
    marks: Annotated[list[InspectionMark], Field(min_length=1)]

    @model_validator(mode="after")
    def square(self) -> InspectionView:
        _known_text(self.title, "An inspection view title")
        _unit(self.up, f"Inspection view {self.title!r} up")
        _unit(self.toward, f"Inspection view {self.title!r} toward")
        if abs(sum(a * b for a, b in zip(self.up, self.toward, strict=True))) > UNIT_TOLERANCE:
            raise ValueError(f"Inspection view {self.title!r}: toward must be square to up.")
        return self


Operation = record(
    "Operation",
    {
        "op": int,
        "do": str,
        # One manifest feature; an inspect op may name several (one drawing dimension
        # split across features is read once).
        "feature": str | Annotated[list[str], Field(min_length=2)],
        **texts("tool holder direction note layout"),
        "inspection_note": Procedure,
        # A coating op's process: an outside ``services`` entry or in-house ``consumables``.
        "process": str | Annotated[list[str], Field(min_length=1)],
        "process_holds": Annotated[list[ProcessHold], Field(min_length=1)],
        **numbers(
            "to_z depth_mm exit_mm rough_allowance_mm stock_to_leave_mm z_from z_to "
            "to_dia rpm feed_mm_min doc_mm feed_mm_rev approach_mm"
        ),
        "to_z_cite": Citations,
        "note_cite": Citations,
        "faces": Annotated[list[str], Field(min_length=1)],
        # Requirement -> gauge. A multi-feature inspect op may scope entries to one of its
        # listed features instead: feature -> {requirement -> gauge}.
        "checks": dict[str, str | dict[str, str]],
        # Requirement -> the GO / NO-GO sizes its `checks` gauge uses (a limit check), or
        # "unknown" when the pair is undecided; scoped per listed feature like `checks`.
        "go_no_go": dict[str, GoNoGo | Unknown | ScopedGoNoGo],
        "missing_requirements": dict[str, str],
        # Requirement -> procedure; scoped per listed feature like `checks`.
        "inspection_methods": dict[str, Procedure | dict[str, Procedure]],
        # Requirement -> the labelled sketches its flat inspection method's worksheet prints.
        "inspection_views": dict[str, Annotated[list[InspectionView], Field(min_length=1)]],
        "to_z_band": Vector,
        "contour": Contour,
        "guide": Guide,
        # Setup-frame volume (plan units) the op clears down to the finished part.
        "stock_removal_bounds": Bounds,
        # Mill op on a horizontal dividing head: each face sample turned under the spindle;
        # z_from/z_to are then head-axis positions and angle_window_deg its rotation span.
        "approach": Literal["rotary"],
        "angle_window_deg": Annotated[list[Number], Field(min_length=2, max_length=2)],
        # Blade centre plane in setup coordinates; kerf comes only from the selected blade.
        "cut_plane": SawPlane,
        # A saw cut that follows a scribed line instead: the earlier ``scribe`` op
        # (``"<setup>:<op>"``), the stock it leaves outside the line for the file, and its
        # ``stock_removal_bounds``, the region the blade and offcut take.
        "follows": str,
        "allowance_mm": float,
    },
    indexed=("do",),
)
# The schema cannot import the rules package: rules.resolution.SAW_OPS names the same actions.
SAW_ACTIONS = frozenset({"saw_cut", "cut_off"})
type KnownBand = Annotated[list[float], Field(min_length=2, max_length=2)]


def _cited(value: Any) -> bool:
    values = value if isinstance(value, list) else [value]
    return bool(values) and all(
        isinstance(item, str) and item.strip() and item.strip() != UNKNOWN for item in values
    )


def _known_text(value: str, what: str) -> None:
    if not value.strip() or value.strip() == UNKNOWN:
        raise ValueError(f"{what} must be known and non-empty.")


def _unit(vector: Any, what: str) -> None:
    if vector != UNKNOWN and abs(sum(v * v for v in vector) ** 0.5 - 1.0) > UNIT_TOLERANCE:
        raise ValueError(f"{what} must be a unit vector.")


def _ordered(band: Any, what: str, *, floor: float, inclusive: bool) -> None:
    if band == UNKNOWN:
        return
    low, high = band
    if not (low >= floor if inclusive else low > floor) or low > high:
        relation = ">=" if inclusive else ">"
        raise ValueError(f"{what} must be an ordered [lo, hi] band with lo {relation} {floor:g}.")


class JointFeature(InputModel):
    """A plan-owned transient cylinder on one stock component, never a finished surface.

    Unsuffixed lengths (``at``, ``dia``, ``nominal_dia``, ``depth``) are in manifest units
    in the model frame. Numeric literal unknown is joint-geometry debt; identities are strict.
    """

    kind: Literal["cylinder_bore", "cylinder_spigot"]
    component: str
    at: KnownPoint3 | Unknown
    axis: KnownPoint3 | Unknown
    dia: KnownBand | Unknown
    nominal_dia: float | Unknown
    depth: float | Unknown
    thru: bool
    cite: Citations
    requirements: list[Literal["dia"]] = Field(default_factory=lambda: ["dia"])
    precision: dict[str, int | Unknown] | Unknown = UNKNOWN
    note: str | Unknown = UNKNOWN

    @model_validator(mode="after")
    def known_geometry(self) -> JointFeature:
        _known_text(self.component, "A joint feature component")
        if not _cited(self.cite):
            raise ValueError("A joint feature must cite its author's geometry source.")
        _unit(self.axis, "A joint feature axis")
        _ordered(self.dia, "A joint feature dia", floor=0.0, inclusive=False)
        if self.dia != UNKNOWN and self.nominal_dia != UNKNOWN:
            if not self.dia[0] <= self.nominal_dia <= self.dia[1]:
                raise ValueError("A joint feature nominal_dia must lie within its dia band.")
        if self.depth != UNKNOWN and self.depth <= 0:
            raise ValueError("A joint feature depth must be positive, also when thru.")
        if len(set(self.requirements)) != len(self.requirements):
            raise ValueError("A joint feature lists a requirement twice.")
        return self


class ProcessFeature(InputModel):
    """A plan-owned transient feature the route makes on the stock, never a finished surface.

    ``at`` (manifest units, model frame) lies on the stock end the feature is made in and
    ``axis`` is that end's unit inward normal, pointing into the kept material. An
    ``end_face`` is the plane through ``at``; facing it removes the stock beyond it. A
    ``centre_hole`` is a combined drill and countersink centre whose mouth centre is ``at``:
    the countersink of ``countersink_angle_deg`` (included) opens to ``mouth_dia_mm`` on the
    face and the pilot (``drill_dia_mm``, ``drill_length_mm`` from the countersink to the
    tip, point included) runs on along ``axis``. Centre sizes are mm, cited to their source.
    """

    kind: Literal["end_face", "centre_hole"]
    at: KnownPoint3 | Unknown
    axis: KnownPoint3 | Unknown
    cite: Citations
    size: str | Unknown = UNKNOWN
    drill_dia_mm: float | Unknown = UNKNOWN
    drill_length_mm: float | Unknown = UNKNOWN
    mouth_dia_mm: float | Unknown = UNKNOWN
    countersink_angle_deg: float | Unknown = UNKNOWN
    note: str | Unknown = UNKNOWN

    @model_validator(mode="after")
    def known_geometry(self) -> ProcessFeature:
        if not _cited(self.cite):
            raise ValueError("A process feature must cite its author's geometry source.")
        _unit(self.axis, "A process feature axis")
        centre = ("size", "drill_dia_mm", "drill_length_mm", "mouth_dia_mm")
        centre += ("countersink_angle_deg",)
        if self.kind == "end_face":
            authored = sorted(key for key in centre if key in self.model_fields_set)
            if authored:
                raise ValueError(f"An end_face process feature has no {', '.join(authored)}.")
            return self
        missing = sorted(key for key in centre if key not in self.model_fields_set)
        if missing:
            raise ValueError(f"A centre_hole process feature needs {', '.join(missing)}.")
        for key in ("drill_dia_mm", "drill_length_mm", "mouth_dia_mm"):
            value = getattr(self, key)
            if value != UNKNOWN and value <= 0:
                raise ValueError(f"A centre_hole {key} must be positive.")
        angle = self.countersink_angle_deg
        if angle != UNKNOWN and not 0 < angle < 180:
            raise ValueError("A centre_hole countersink_angle_deg must lie between 0 and 180.")
        if UNKNOWN not in (self.drill_dia_mm, self.mouth_dia_mm):
            if self.mouth_dia_mm <= self.drill_dia_mm:
                raise ValueError("A centre_hole mouth_dia_mm must exceed its drill_dia_mm.")
        return self


class JointInterface(InputModel):
    """One planar rectangular contact patch: model-frame centre (manifest units)."""

    at: KnownPoint3 | Unknown
    normal: KnownPoint3 | Unknown
    x: KnownPoint3 | Unknown
    size_mm: KnownBand | Unknown
    cite: Citations

    @model_validator(mode="after")
    def known_geometry(self) -> JointInterface:
        if not _cited(self.cite):
            raise ValueError("A joint interface must cite its source.")
        _unit(self.normal, "A joint interface normal")
        _unit(self.x, "A joint interface x")
        if self.normal != UNKNOWN and self.x != UNKNOWN:
            if abs(sum(a * b for a, b in zip(self.normal, self.x, strict=True))) > UNIT_TOLERANCE:
                raise ValueError("A joint interface x must be orthogonal to its normal.")
        if self.size_mm != UNKNOWN and min(self.size_mm) <= 0:
            raise ValueError("A joint interface size_mm must be positive.")
        return self


_FIT_METHODS = {
    "clearance": {"silver_braze", "slip"},
    "interference": {"press"},
}
_COMPOUND_FORM = (
    'method = "slip" (clearance) or "press" (interference) with '
    "compound = { product, cure_time_min, surface_prep }"
)


class JointCompound(InputModel):
    """A retaining compound on a cylindrical joint's interface; the joint's cite covers
    its data sheet. Unknown prep or cure is debt that withholds the join."""

    product: str
    cure_time_min: float | Unknown
    surface_prep: str

    @model_validator(mode="after")
    def declared_compound(self) -> JointCompound:
        if self.product != UNKNOWN:
            _known_text(self.product, "A joint compound product")
        if self.cure_time_min != UNKNOWN and self.cure_time_min <= 0:
            raise ValueError("A joint compound cure_time_min must be positive.")
        if self.surface_prep != UNKNOWN:
            _known_text(self.surface_prep, "A joint compound surface_prep")
        return self


class CylindricalJoint(InputModel):
    """Socket/spigot join of exactly two branches; fit bands are diametral mm.

    ``method`` is the assembly action; a retaining ``compound`` on the interface bonds a
    slip fit and may back up a press fit.
    """

    kind: Literal["cylindrical"]
    socket: str
    spigot: str
    fit: Literal["clearance", "interference"]
    clearance_mm: KnownBand | Unknown | None = None
    interference_mm: KnownBand | Unknown | None = None
    method: Literal["silver_braze", "slip", "press"]
    process: str
    compound: JointCompound | None = None
    cite: Citations

    @model_validator(mode="before")
    @classmethod
    def current_compound_form(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        if values.get("method") == "retaining_compound":
            raise ValueError(
                f'A joint method is no longer "retaining_compound": write {_COMPOUND_FORM}.'
            )
        legacy = sorted(key for key in ("cure_time_min", "surface_prep") if key in values)
        if legacy:
            raise ValueError(
                f"A joint's {', '.join(legacy)} moved into its compound block: write "
                f"{_COMPOUND_FORM}."
            )
        return values

    @model_validator(mode="after")
    def declared_fit(self) -> CylindricalJoint:
        _known_text(self.process, "A joint process")
        if not _cited(self.cite):
            raise ValueError("A joint must cite its fit and process source.")
        if self.method not in _FIT_METHODS[self.fit]:
            raise ValueError(f"A {self.fit} joint cannot be made by {self.method}.")
        if self.method == "silver_braze" and self.compound is not None:
            raise ValueError("A silver_braze joint takes no compound: the braze is the bond.")
        if self.method == "slip" and self.compound is None:
            raise ValueError(
                "A slip joint must declare compound = { product, cure_time_min, surface_prep }: "
                "a slip fit with nothing bonding it is not a joint."
            )
        band, other = (
            (self.clearance_mm, self.interference_mm)
            if self.fit == "clearance"
            else (self.interference_mm, self.clearance_mm)
        )
        if band is None or other is not None:
            raise ValueError(
                f"A {self.fit} joint must declare {self.fit}_mm and no other fit band."
            )
        _ordered(band, f"{self.fit}_mm", floor=0.0, inclusive=self.fit == "clearance")
        return self


class SurfaceJoint(InputModel):
    """Planar butt join of exactly two branches through declared contact interfaces."""

    kind: Literal["surface"]
    method: Literal["weld", "silver_braze"]
    process: str
    cite: Citations
    interfaces: Annotated[list[JointInterface], Field(min_length=1)]

    @model_validator(mode="after")
    def declared_process(self) -> SurfaceJoint:
        _known_text(self.process, "A joint process")
        if not _cited(self.cite):
            raise ValueError("A joint must cite its interface and process source.")
        return self


Setup = record(
    "Setup",
    {
        **texts("id machine frame coolant note"),
        "stock_in": str | Annotated[list[str], Field(min_length=1)],
        "deburr_mm": Number,
        "deburr_cite": Citations,
        "stock_state": StockState,
        "hold": Hold,
        "zero": Zero,
        "ops": list[Operation],
        "joint": CylindricalJoint | SurfaceJoint,
    },
    indexed=("machine",),
)


def setup_lineage(plan: dict, sid: str) -> set[str]:
    """The setup and every earlier setup whose output material flows into it: the one
    workpiece its ops act on (omitted ``stock_in`` routing descends from none)."""
    setups = {setup["id"]: setup for setup in plan.get("setups", [])}
    seen, pending = set(), [sid]
    while pending:
        current = pending.pop()
        if current in seen or current not in setups:
            continue
        seen.add(current)
        refs = setups[current].get("stock_in")
        pending.extend(refs if isinstance(refs, list) else [refs] if isinstance(refs, str) else [])
    return seen


def stock_ancestry(routes: Any) -> dict[str, frozenset[str]]:
    """Root supplies behind each validated setup output; ``routes`` = (id, refs or None).

    A setup whose routing is omitted is its own root: its material is unexplained.
    """
    ancestry: dict[str, frozenset[str]] = {}
    for sid, refs in routes:
        roots = frozenset(
            root for ref in refs or () for root in ancestry.get(ref, frozenset((ref,)))
        )
        ancestry[sid] = roots or frozenset((sid,))
    return ancestry


class Plan(InputModel):
    part: str
    features: str
    construction: Literal["one_piece", "built_up"] | Unknown = UNKNOWN
    step: str | Unknown = UNKNOWN
    quantity: int | Unknown = UNKNOWN
    quantity_cite: Citations = UNKNOWN
    drawing: Drawing | Unknown = UNKNOWN
    paths: Paths | Unknown = UNKNOWN
    stock: Stock | Unknown = UNKNOWN
    dro: Dro | Unknown = UNKNOWN
    # Author-declared setup frames in model coordinates; never feature source frames.
    frames: dict[str, PlanFrame] | Unknown = UNKNOWN
    setups: list[Setup]
    # Plan-owned transient joint cylinders keyed by id; never exported finished features.
    joint_features: dict[str, JointFeature] = Field(default_factory=dict)
    # Plan-owned transient stock-preparation features (end faces, centre holes) keyed by id;
    # never exported finished features and never drawing coverage.
    process_features: dict[str, ProcessFeature] = Field(default_factory=dict)
    # Plan-owned DRO aims keyed by located feature; never a change to its geometry.
    aims: dict[str, Aim] = Field(default_factory=dict)

    @model_validator(mode="after")
    def named_frames(self) -> Plan:
        if isinstance(self.frames, dict) and any(
            not name.strip() or name == UNKNOWN for name in self.frames
        ):
            raise ValueError("Plan frame names must be known, non-empty names.")
        return self

    @model_validator(mode="after")
    def operation_fields(self) -> Plan:
        """A feature list is an inspect op's; a process is a coating op's."""
        for setup in self.setups:
            for op in setup.ops if isinstance(setup.ops, list) else ():
                where = f"Setup {setup.id} op {op.op}"
                if isinstance(op.feature, list):
                    if op.do != "inspect":
                        raise ValueError(f"{where}: only an inspect op may name a feature list.")
                    if len(set(op.feature)) != len(op.feature) or UNKNOWN in op.feature:
                        raise ValueError(f"{where}: a feature list names distinct known features.")
                if "process" in op.model_fields_set and op.do != "coating":
                    raise ValueError(f"{where}: only a coating op names a coating process.")
                if isinstance(op.inspection_views, dict):
                    if op.do != "inspect":
                        raise ValueError(f"{where}: only an inspect op declares inspection views.")
                    # Views are keyed by requirement alone: they illustrate a flat method.
                    methods = (
                        op.inspection_methods if isinstance(op.inspection_methods, dict) else {}
                    )
                    unmatched = [
                        requirement
                        for requirement in op.inspection_views
                        if requirement not in methods or isinstance(methods[requirement], dict)
                    ]
                    if unmatched:
                        raise ValueError(
                            f"{where}: inspection views for {', '.join(unmatched)} illustrate "
                            "no stated inspection method (views are keyed by requirement "
                            "alone, so they illustrate a flat inspection_methods entry)."
                        )
        return self

    @model_validator(mode="after")
    def profiled_blanks(self) -> Plan:
        """A profiled blank is one supply's whole envelope: never beside bar dimensions."""
        if not isinstance(self.stock, Stock):
            return self
        components = self.stock.components if isinstance(self.stock.components, list) else []
        errors = profiled_blank_errors(self.stock, "stock")
        profiled_root = "blank" in self.stock.model_fields_set or self.stock.form == PROFILED_BLANK
        if components and profiled_root:
            errors.append("stock declares components, so each profiled blank is a component's")
        for component in components:
            errors.extend(profiled_blank_errors(component, f"stock.components.{component.id}"))
        if errors:
            raise ValueError("; ".join(errors) + ".")
        return self

    @model_validator(mode="after")
    def saw_shapes(self) -> Plan:
        """A saw cut is planar (``cut_plane``) or follows an earlier scribe op's line
        (``follows``, ``allowance_mm``, ``stock_removal_bounds``): exactly one shape. The
        line must be on the saw's own workpiece: scribed earlier in the same setup or in a
        setup its ``stock_in`` routing descends from (omitted routing descends from none)."""
        scribes = {}
        # An ``ends`` layout scribes only an arc's two end marks (a guided sweep's stops): no
        # line for a saw to follow.
        end_marks = set()
        routes = {
            "setups": [
                {"id": setup.id, "stock_in": setup.stock_in}
                if "stock_in" in setup.model_fields_set
                else {"id": setup.id}
                for setup in self.setups
            ]
        }
        for setup in self.setups:
            lineage = setup_lineage(routes, setup.id)
            for op in setup.ops if isinstance(setup.ops, list) else ():
                where = f"Setup {setup.id} op {op.op}"
                declared = op.model_fields_set
                if op.do not in SAW_ACTIONS:
                    stray = sorted(declared & {"follows", "allowance_mm"})
                    if stray:
                        raise ValueError(f"{where}: only a saw cut declares {', '.join(stray)}.")
                    if op.do == "scribe" and op.layout == "ends":
                        end_marks.add(f"{setup.id}:{op.op}")
                    elif op.do == "scribe":
                        scribes[f"{setup.id}:{op.op}"] = setup.id
                    continue
                shapes = [field for field in ("cut_plane", "follows") if field in declared]
                if len(shapes) != 1:
                    raise ValueError(
                        f"{where}: a saw cut declares exactly one of cut_plane (a straight cut; "
                        '"unknown" while its plane is undecided) or follows (an earlier scribe '
                        "op's line)."
                    )
                if shapes == ["cut_plane"]:
                    stray = sorted(declared & {"allowance_mm", "stock_removal_bounds"})
                    if stray:
                        raise ValueError(
                            f"{where}: a straight saw cut is located by its cut_plane alone; "
                            f"{', '.join(stray)} belong to a cut that follows a scribed line."
                        )
                    continue
                if op.follows in end_marks:
                    raise ValueError(
                        f"{where}: follows {op.follows!r}, an ends layout: it scribes only the "
                        "arc's two end marks, no line for the saw to follow."
                    )
                if op.follows not in scribes:
                    raise ValueError(
                        f"{where}: follows {op.follows!r} names no earlier scribe op "
                        '("<setup>:<op>").'
                    )
                if scribes[op.follows] not in lineage:
                    raise ValueError(
                        f"{where}: follows {op.follows!r}, a line scribed on another "
                        "workpiece: the scribe's setup is not upstream of this setup's stock_in."
                    )
                if op.allowance_mm != UNKNOWN and op.allowance_mm <= 0:
                    raise ValueError(
                        f"{where}: allowance_mm, the stock left outside the line for the file, "
                        "must be positive."
                    )
        return self

    @model_validator(mode="after")
    def stock_routes(self) -> Plan:
        components = self.stock.components if isinstance(self.stock, Stock) else UNKNOWN
        component_ids = []
        if isinstance(components, list):
            component_ids = [component.id for component in components]
            if len(set(component_ids)) != len(component_ids):
                raise ValueError("Stock component ids must be unique.")
        setup_ids = [setup.id for setup in self.setups]
        known_ids = [sid for sid in setup_ids if sid != UNKNOWN]
        if len(set(known_ids)) != len(known_ids):
            raise ValueError("Setup ids must be unique.")
        if any(not sid.strip() or sid == "stock" or sid.startswith("stock.") for sid in known_ids):
            raise ValueError(
                "Setup ids must be non-empty and cannot use the reserved stock namespace."
            )
        earlier = set()
        ancestry = {"stock": {"stock"}}
        ancestry.update({f"stock.{cid}": {f"stock.{cid}"} for cid in component_ids})
        for setup in self.setups:
            consumed = {}
            # Omitted routing remains input debt, never an inferred linear route.
            if "stock_in" in setup.model_fields_set:
                refs = setup.stock_in if isinstance(setup.stock_in, list) else [setup.stock_in]
                for ref in refs:
                    where = f"Setup {setup.id} stock_in reference {ref!r}"
                    if ref == "stock":
                        if isinstance(components, list) and components:
                            raise ValueError(
                                f"{where} requires a single stock supply; use stock.<component id>."
                            )
                    elif ref.startswith("stock."):
                        if ref.removeprefix("stock.") not in component_ids:
                            raise ValueError(f"{where} names an unknown stock component.")
                    elif ref not in earlier:
                        reason = (
                            "is not an earlier setup"
                            if ref in known_ids
                            else "is an unknown stock reference"
                        )
                        raise ValueError(f"{where} {reason}.")
                    for ancestor in ancestry[ref]:
                        if ancestor in consumed:
                            raise ValueError(
                                f"{where} shares ancestor {ancestor!r} with "
                                f"{consumed[ancestor]!r}; an assembly cannot join the same "
                                "material twice."
                            )
                        consumed[ancestor] = ref
            if setup.id != UNKNOWN:
                earlier.add(setup.id)
                ancestry[setup.id] = set(consumed) if consumed else {setup.id}
        return self

    @model_validator(mode="after")
    def joints(self) -> Plan:
        """Exactly two-branch arrays declare one joint; transient cuts stay on their branch."""
        features = self.joint_features
        stock = self.stock if isinstance(self.stock, Stock) else None
        components = stock.components if stock is not None else UNKNOWN
        component_ids = (
            {component.id for component in components} if isinstance(components, list) else set()
        )
        for name, feature in features.items():
            _known_text(name, "A joint feature id")
            if feature.component not in component_ids:
                raise ValueError(
                    f"Joint feature {name!r} names component {feature.component!r}, which is "
                    "not a declared stock component."
                )
        ancestry = stock_ancestry(
            (
                setup.id,
                (setup.stock_in if isinstance(setup.stock_in, list) else [setup.stock_in])
                if "stock_in" in setup.model_fields_set
                else None,
            )
            for setup in self.setups
            if setup.id != UNKNOWN
        )
        joined: dict[str, str] = {}
        for setup in self.setups:
            where = f"Setup {setup.id}"
            refs = setup.stock_in if "stock_in" in setup.model_fields_set else UNKNOWN
            declared = "joint" in setup.model_fields_set
            if not isinstance(refs, list):
                if declared:
                    raise ValueError(f"{where} declares a joint but receives one stock_in.")
                continue
            if len(refs) != 2:
                raise ValueError(
                    f"{where} joins {len(refs)} stock_in references; a joint joins exactly two "
                    "branches."
                )
            branch_roots = [ancestry.get(ref, frozenset((ref,))) for ref in refs]
            if all(len(roots) > 1 for roots in branch_roots):
                raise ValueError(
                    f"{where} joins two already-joined assemblies; each joint may add only "
                    "one single component to an assembly."
                )
            joint = setup.joint
            if not declared or joint == UNKNOWN:
                raise ValueError(f"{where} stock_in array requires a declared joint.")
            if not isinstance(joint, CylindricalJoint):
                continue
            sides = {}
            for role, kind in (("socket", "cylinder_bore"), ("spigot", "cylinder_spigot")):
                name = getattr(joint, role)
                feature = features.get(name)
                if feature is None or feature.kind != kind:
                    raise ValueError(
                        f"{where} joint {role} {name!r} is not a plan joint feature of kind {kind}."
                    )
                if name in joined:
                    raise ValueError(
                        f"{where} joint {role} {name!r} is already joined in setup {joined[name]}."
                    )
                joined[name] = setup.id
                root = f"stock.{feature.component}"
                owners = [ref for ref in refs if root in ancestry.get(ref, {ref})]
                if not owners:
                    raise ValueError(
                        f"{where} joint {role} {name!r} belongs to component "
                        f"{feature.component!r}, which no consumed branch carries."
                    )
                sides[role] = owners[0]
            if sides["socket"] == sides["spigot"]:
                raise ValueError(
                    f"{where} joint socket and spigot must come from different stock_in branches."
                )
        for setup in self.setups:
            for op in setup.ops if isinstance(setup.ops, list) else ():
                feature = features.get(op.feature) if isinstance(op.feature, str) else None
                if feature is None:
                    continue
                root = f"stock.{feature.component}"
                if ancestry.get(setup.id) != {root}:
                    raise ValueError(
                        f"Setup {setup.id} op {op.op} claims joint feature {op.feature!r} "
                        f"outside the unjoined {root} branch; transient cuts precede the join."
                    )
        return self


type FrameVector = Annotated[list[Number], Field(min_length=3, max_length=3)] | Unknown


class Frame(InputModel):
    origin: FrameVector = UNKNOWN
    x: FrameVector = UNKNOWN
    y: FrameVector = UNKNOWN
    z: FrameVector = UNKNOWN
    note: str | Unknown = UNKNOWN
    binding: str | Unknown = UNKNOWN
    cite: Citations = UNKNOWN

    @model_validator(mode="after")
    def orthonormal_basis(self) -> Frame:
        axes = (self.x, self.y, self.z)
        if not all(isinstance(axis, list) and all(v != UNKNOWN for v in axis) for axis in axes):
            return self
        for i, left in enumerate(axes):
            for j, right in enumerate(axes):
                dot = sum(a * b for a, b in zip(left, right, strict=True))
                if abs(dot - (1.0 if i == j else 0.0)) > 1e-9:
                    raise ValueError("Frame axes must be an orthonormal basis.")
        x, y, z = axes
        cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
        if any(abs(a - b) > 1e-9 for a, b in zip(cross, z, strict=True)):
            raise ValueError("Frame axes must be right-handed.")
        return self


class PlanFrame(Frame):
    """A plan-owned setup frame: its owner and physical binding are never implied."""

    @model_validator(mode="after")
    def authored_provenance(self) -> PlanFrame:
        if "binding" not in self.model_fields_set:
            raise ValueError("A plan frame must state its binding, even if unknown.")
        if self.cite == UNKNOWN or not self.cite:
            raise ValueError("A plan frame must cite its author's choice and source geometry.")
        return self


Datum = record("Datum", {**texts("feature surface"), "cite": Citations})
MaterialSpec = record(
    "MaterialSpec", {**texts("spec name finish"), "thickness": Number, "cite": Citations}
)
GeneralTolerances = record(
    "GeneralTolerances",
    {
        **numbers(
            "linear_1pl linear_2pl linear_3pl angular_deg drilled_hole drilled_hole_plus "
            "drilled_hole_minus edge_break_r chamfer_max"
        ),
        "cite": Citations | dict[str, Citations],
    },
)
Plane = record("Plane", {**texts("frame axis"), "value": Number})
Notes = record(
    "Notes", {"manufacturing": list[str], **texts("process edge_break"), "cite": Citations}
)


class ProfileReading(InputModel):
    """A BASIC length read at ``obliquity_deg`` (0 <= θ < 90) to a planar governed surface's
    normal at a fixed transverse station: each zone offset reads ``1 / cos θ`` longer."""

    sense: Literal["increases", "decreases"]
    obliquity_deg: float


class ProfileTilt(InputModel):
    """A BASIC angle of a planar governed face, tilted by the zone across the face's least
    extent: a banded length requirement of the governed feature (its lower limit), or a
    number in manifest units."""

    tilt_across: str | float


# How a governed BASIC requirement reads in a profile zone (docs/features.md "Surface
# profiles"): how the length moves when material is added, or an angle's tilt.
type ProfileEntry = Literal["increases", "decreases", "unknown"] | ProfileReading | ProfileTilt
PROFILE_FIELDS = frozenset(
    {"surface_profile_u", "surface_profile_datums", "surface_profile_governs"}
)


Feature = record(
    "Feature",
    {
        **texts(
            "kind frame drill process datum coaxial_to height_from note binding dimension_type "
            "thread construction representation hole_spec arc parent hole top_edge_feature"
        ),
        "requirements": list[str],
        "faces": list[str],
        "cite": Citations | dict[str, Citations],
        "precision": dict[str, int | Unknown],
        "position_datums": list[str],
        "angularity_datums": list[str],
        "surface_profile_datums": list[str],
        "surface_profile_governs": dict[str, ProfileEntry],
        "tilt_across": dict[str, str | float],
        "surface_profile": float,
        "surface_profile_u": float,
        "thru": bool,
        "mirror_symmetric": bool,
        "at": Vector,
        "axis": Vector,
        "normal": Vector,
        "at_reference": Vector,
        "plane": Plane,
        "bounds": Bounds,
        "z_mm": Vector,
        "end": Vector,
        "arc_centre": Vector,
        "bottom_end": Vector,
        "angle_deg": Number,
        "angle_tol_deg": Number,
        "radial_tip_end": Vector,
        **{
            key: float | list[Number]
            for key in (
                "dia position_dia angularity_dia finish_ra depth length width height "
                "radius thickness "
                "coaxiality_dia height_above_pivot arc_len bottom_radius bottom_arc_len tip_land "
                "land_angle_deg land_angle_nominal_deg upper_z lower_z centre_from_pivot_ref "
                "depth_ref station nominal_dia nominal_width nominal_length nominal_height "
                "nominal_radius nominal_thickness length_ref dome_height groove_width groove_depth "
                "dia_nominal length_nominal width_nominal height_nominal thickness_nominal "
                "radius_nominal station_nominal through_thickness z_south_reference "
                "corner_radius_max_design apex_z base_z base_radius sphere_radius "
                "apex_z_reference base_z_reference length_reference cut_past_scribe "
                "end_past_scribe supply_length tap_drill_mm bottom_radius_nominal separation"
            ).split()
        },
    },
    indexed=("kind",),
)


class Features(InputModel):
    part: str
    units: Literal["mm", "in"] | Unknown = UNKNOWN
    precision: int | Unknown = UNKNOWN
    step_sha256: str = UNKNOWN
    step: str | Unknown = UNKNOWN
    construction: str | Unknown = UNKNOWN
    volume_mm3: Number = UNKNOWN
    volume_cite: Citations = UNKNOWN
    cite_root: str | Unknown = UNKNOWN
    cite: Citations | dict[str, Citations] = UNKNOWN
    notes: Notes | Unknown = UNKNOWN
    drawing: Drawing | Unknown = UNKNOWN
    material: MaterialSpec | Unknown = UNKNOWN
    general_tolerances: GeneralTolerances | Unknown = UNKNOWN
    frames: dict[str, Frame | Unknown] | Unknown
    datums: dict[str, Datum | Unknown] | Unknown = UNKNOWN
    features: dict[str, Feature]

    @model_validator(mode="after")
    def complete_requirements(self) -> Features:
        for name, feature in self.features.items():
            requirements = feature.requirements
            if requirements == UNKNOWN:
                continue
            if not isinstance(requirements, list):
                raise ValueError(f"{name}: requirements must enumerate drawing requirements")
            if len(set(requirements)) != len(requirements):
                raise ValueError(f"{name}: duplicate requirement")
            for requirement in requirements:
                if requirement == UNKNOWN:
                    continue
                if requirement not in feature.model_fields_set:
                    raise ValueError(f"{name}: missing required field {requirement}")
        return self

    @model_validator(mode="after")
    def surface_profiles(self) -> Features:
        """A profile zone 0 < t, 0 <= U <= t, listed in its feature's requirements, the datum
        labels of its frame declared, named once and never the profiled feature itself, and
        the BASIC scalars it governs, each once."""
        # The labels a frame may name: the datums table's and the features' own ``datum``. An
        # unknown datums table denies none; its labels resolve, or not, when rules run.
        declared = (
            None
            if self.datums == UNKNOWN
            else {*self.datums, *(feature.datum for feature in self.features.values())}
        )
        # The feature each label names, a feature's own ``datum`` first, as the rules
        # resolve it (``rules._profile.datum_features``).
        datum_feature = {
            label: datum.feature
            for label, datum in (self.datums.items() if isinstance(self.datums, dict) else ())
            if datum != UNKNOWN
        }
        datum_feature.update(
            {
                feature.datum: name
                for name, feature in self.features.items()
                if isinstance(feature.datum, str) and feature.datum != UNKNOWN
            }
        )
        for name, feature in self.features.items():
            given = feature.model_fields_set
            if "surface_profile" not in given:
                if dependants := sorted(given & PROFILE_FIELDS):
                    raise ValueError(f"{name}: {', '.join(dependants)} need a surface_profile zone")
                continue
            listed = feature.requirements
            if not isinstance(listed, list) or "surface_profile" not in listed:
                # Unlisted, the zone gets no inspection row while its derived bands pass.
                raise ValueError(
                    f"{name}: a surface_profile zone must be listed in its requirements"
                )
            zone, disposition = feature.surface_profile, feature.surface_profile_u
            if zone != UNKNOWN and zone <= 0:
                raise ValueError(f"{name}: surface_profile zone must be positive")
            most = math.inf if zone == UNKNOWN else zone
            if disposition != UNKNOWN and not 0 <= disposition <= most:
                raise ValueError(f"{name}: surface_profile_u must lie in [0, surface_profile]")
            labels = feature.surface_profile_datums
            named = (
                [label for label in labels if label != UNKNOWN] if isinstance(labels, list) else []
            )
            for index, label in enumerate(named):
                if declared is not None and label not in declared:
                    raise ValueError(
                        f"{name}: surface_profile_datums {label} is not a declared datum (a "
                        "datums table label or a feature's datum)"
                    )
                if datum_feature.get(label) == name:
                    raise ValueError(
                        f"{name}: surface_profile_datums {label} is {name}'s own datum: a "
                        "profile is never referenced to the feature it controls"
                    )
                if label in named[:index]:
                    raise ValueError(
                        f"{name}: surface_profile_datums {label} is named twice: a frame names "
                        "each datum once"
                    )
            governs = feature.surface_profile_governs
            targets: dict[tuple[str, str], str] = {}
            for key, entry in governs.items() if isinstance(governs, dict) else ():
                _governed(self.features, name, key, entry)
                target = profile_target(name, key)
                if target in targets:
                    raise ValueError(
                        f"{name}: surface_profile_governs {targets[target]} and {key} both "
                        f"govern {' '.join(target)}: a profile governs a requirement once"
                    )
                targets[target] = key
        return self

    @model_validator(mode="after")
    def drawn_angle_lengths(self) -> Features:
        """A drawn angle band read across a face (``tilt_across``) is a listed ``_deg`` band
        of its feature, a two-limit band (:func:`_two_limits`), and the face extent a listed
        length band or a positive number."""
        for name, feature in self.features.items():
            across = feature.tilt_across
            listed = feature.requirements if isinstance(feature.requirements, list) else []
            for requirement, extent in across.items() if isinstance(across, dict) else ():
                where = f"{name}: tilt_across {requirement}"
                if requirement not in listed or not requirement.endswith("_deg"):
                    raise ValueError(f"{where} is not a listed angle (_deg) requirement")
                band = getattr(feature, requirement)
                if not isinstance(band, list):
                    raise ValueError(
                        f"{where}: only a drawn angle band reads across a face; a BASIC "
                        "angle's tilt is its surface profile's"
                    )
                _two_limits(where, requirement, band)
                _face_extent(where, name, feature, listed, extent)
        return self


def _governed(features: dict[str, Any], owner: str, key: str, entry: ProfileEntry) -> None:
    """A ``surface_profile_governs`` entry names a listed BASIC scalar its form can read."""
    where = f"{owner}: surface_profile_governs {key}"
    name, requirement = profile_target(owner, key)
    feature = features.get(name)
    if feature is None:
        raise ValueError(f"{where} names no manifest feature {name}")
    listed = feature.requirements if isinstance(feature.requirements, list) else []
    if requirement in (UNKNOWN, "surface_profile") or requirement not in listed:
        raise ValueError(f"{where}: {requirement} is not a listed requirement of {name}")
    if requirement not in PROFILE_GOVERNABLE:
        # Inspection selects only recognised requirements (``tolerance_requirements``): a
        # band derived for anything else would never be read.
        raise ValueError(
            f"{where}: {requirement} is not a BASIC dimension the inspection rule reads"
        )
    value = getattr(feature, requirement)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            f"{where}: {name} {requirement} must be a BASIC scalar, not a band or unknown"
        )
    angle = requirement.endswith("_deg")
    if isinstance(entry, ProfileTilt):
        if not angle:
            raise ValueError(f"{where}: tilt_across bounds only an angle (a _deg requirement)")
        _face_extent(where, name, feature, listed, entry.tilt_across)
    elif angle and entry != UNKNOWN:
        raise ValueError(f"{where}: {requirement} is an angle: only tilt_across bounds it")
    if isinstance(entry, ProfileReading) and not 0 <= entry.obliquity_deg < 90:
        raise ValueError(f"{where}: obliquity_deg must lie in [0, 90)")
    if isinstance(entry, ProfileReading) and entry.obliquity_deg and requirement in CENTRED:
        raise ValueError(
            f"{where}: {requirement} is read along the normal through its centre, never "
            "obliquely: obliquity_deg must be 0"
        )


def _face_extent(where: str, name: str, feature: Any, listed: list, across: str | float) -> None:
    """A ``tilt_across`` face extent: a listed two-limit band (:func:`_two_limits`) of a
    recognised length dimension (``LENGTH_REQUIREMENTS``) of feature ``name``, or a number
    > 0."""
    if isinstance(across, str):
        length = across in listed and across in LENGTH_REQUIREMENTS
        band = getattr(feature, across) if length else None
        if not isinstance(band, list):
            raise ValueError(f"{where}: tilt_across {across} is not a listed length band of {name}")
        _two_limits(where, across, band)
    elif across <= 0:
        raise ValueError(f"{where}: tilt_across must be a positive face extent")


def _two_limits(where: str, requirement: str, band: list) -> None:
    """A band a tilt is read across is ``[lo, hi]``: exactly two limits, ``lo <= hi`` when
    both are known. An ``"unknown"`` limit is legal and leaves the reading unknown."""
    if len(band) != 2:
        raise ValueError(f"{where}: {requirement} must be a band of two limits [lo, hi]")
    if UNKNOWN not in band and band[0] > band[1]:
        raise ValueError(f"{where}: {requirement} must be an ordered band [lo, hi], lo <= hi")


Source = record("Source", {**texts("vendor by url note cite"), "sku": str | int, "verify": bool})


class Measurement(InputModel):
    # An omitted status never certifies a legacy record as a physical measurement.
    status: Literal["measured", "assumed", "illustrative"] = "assumed"
    by: str
    date: str
    instrument: str

    @model_validator(mode="after")
    def complete(self) -> Measurement:
        if any(
            not value.strip() or value.strip() == UNKNOWN
            for value in (self.by, self.date, self.instrument)
        ):
            raise ValueError("Measurement by, date and instrument must be complete.")
        if date.fromisoformat(self.date).isoformat() != self.date:
            raise ValueError("Measurement date must be an ISO YYYY-MM-DD calendar date.")
        return self


class LengthMeasurement(InputModel):
    """A fact-local value; only its own measured/verify qualify it (lengths or degrees)."""

    value: Number
    measured: Measurement | Unknown = UNKNOWN
    verify: bool | Unknown = UNKNOWN


type MeasuredLength = Number | LengthMeasurement
# A declared tolerance zone [least, greatest] (a filing-button kit's receipt limits): a
# plain pair, or one qualified only by its own measured/verify like a LengthMeasurement.
type LimitPair = Annotated[list[Number], Field(min_length=2, max_length=2)]


class LimitsMeasurement(InputModel):
    """A fact-local [least, greatest] pair; only its own measured/verify qualify it."""

    value: LimitPair
    measured: Measurement | Unknown = UNKNOWN
    verify: bool | Unknown = UNKNOWN


type MeasuredLimits = LimitPair | LimitsMeasurement
type MeasuredAngle = Number | LengthMeasurement
EnvelopeTravel = record("EnvelopeTravel", dict.fromkeys(("x", "y", "z"), MeasuredLength))
MachineEnvelope = record(
    "MachineEnvelope",
    {
        "travel_mm": EnvelopeTravel,
        "travel_in": EnvelopeTravel,
        **dict.fromkeys(
            (
                "spindle_to_table_max_mm",
                "spindle_to_table_max_in",
                "spindle_to_table_min_mm",
                "spindle_to_table_min_in",
            ),
            MeasuredLength,
        ),
        # Lathe envelope: swing diameters and the headstock-to-tailstock centre distance.
        **dict.fromkeys(
            (
                "swing_over_bed_mm",
                "swing_over_bed_in",
                "swing_over_cross_slide_mm",
                "swing_over_cross_slide_in",
                "between_centres_mm",
                "between_centres_in",
            ),
            MeasuredLength,
        ),
    },
)


class SpindleRotation(InputModel):
    """A labelled spindle rotation: only its own measured/verify qualify it."""

    value: Literal["cw", "ccw"]
    measured: Measurement | Unknown = UNKNOWN
    verify: bool | Unknown = UNKNOWN


Spindle = record(
    "Spindle",
    {
        **texts("taper drawbar drive mount"),
        **numbers("rpm_min rpm_max hp bore_in runout_in"),
        "two_ranges": bool,
        "ranges_rpm": list[list[Number]],
        # Cutting rotation viewed from above, looking down setup -Z (a right-hand cutter: cw).
        "rotation": Literal["cw", "ccw"] | SpindleRotation | Unknown,
    },
)
# Tool projection belongs to one (tool, holder) pair: full holder reference -> fact.
type ProjectionMap = dict[str, MeasuredLength]
LeadScrew = record("LeadScrew", {**numbers("tpi dial_in"), "cross_feed_ipr": Vector})
Capacity = record("Capacity", numbers("drill end_mill face_mill"))
Tailstock = record(
    "Tailstock",
    {
        "taper": str,
        "quill_travel_in": Number,
        **dict.fromkeys(("quill_dia_mm", "quill_dia_in"), MeasuredLength),
    },
)
Threads = record("Threads", {"inch_tpi": Vector, "metric_pitch_mm": Vector})
# ``centre_height`` / ``square_blade``: how each tool is set on spindle centre height and a
# blade squared to the spindle axis before its first touch-off (docs/inventory.md).
Toolpost = record(
    "Toolpost",
    {
        **texts("series type note centre_height square_blade"),
        "holders": int,
        "included": bool,
        "cite": Citations,
    },
)
DirectIndex = record("DirectIndex", numbers("positions step_deg"))
Tilt = record("Tilt", numbers("down up"))
Bars = record(
    "Bars",
    {"count": int, "type": str, "shank_in": Number, "min_bore_in": Vector, "depth_in": Vector},
)
# One primitive of a fixture body, in its owner's local frame (plain mm). Its own
# measured/verify qualify it, like a LengthMeasurement; nothing above it does. A ``void``
# primitive (bore, tapped hole, slot) is not drawn: it is cut from the owner's other
# primitives, or only from those named in ``cuts``. ``locates`` names the part face it
# locates or carries, ``bears`` how that locating solid bears on the work (its contact
# cylinder in a ``bore``, or a flat ``face``), ``fastener`` its thread / fastener, and
# ``shim`` marks an adjustable shim stack whose drawn thickness is the nominal (traveler
# fixture table).
# ``supply``: made with its owner (default), ``bought`` hardware, or ``existing`` in the
# shop (a machine's vise jaw drawn for clearance); only made solids are make-table rows.
# ``records``: values measured and written down when the part is made or received (a
# head-to-shoulder TIR, a squareness by reversal), printed as fill-ins under the table.
# A record says what is measured (``check``), optionally with which inventory ``gauge``
# and ``how``; ``max_mm`` is its spec (reject over), ``goal_mm`` a tighter aim, and
# ``over_mm`` the length the value is taken over. No spec: a characterisation, recorded only.
RecordBlank = record(
    "RecordBlank",
    {**texts("check gauge how"), **numbers("max_mm goal_mm over_mm")},
)
# One operation that makes a shop-made item or one of its primitives (docs/inventory.md
# "Shop-made fixtures"): how the piece is held, the ``tools`` key that cuts, the spindle
# speed (a number or a [low, high] range), the feed with its unit (``0.05 mm/rev``), the
# depth of cut per pass and the source of the cutting data. Each prints as one line.
MakeOp = record(
    "MakeOp",
    {**texts("hold tool feed cite"), "rpm": float | LimitPair, "doc_mm": float},
)
MakeOps = Annotated[list[MakeOp], Field(min_length=1)]
FixtureSolid = record(
    "FixtureSolid",
    {
        **texts("name shape note label locates fastener"),
        "at_mm": Point3,
        "size_mm": Point3,
        "axis": Point3,
        **numbers("dia_mm length_mm"),
        "void": bool,
        "shim": bool,
        "supply": Literal["made", "bought", "existing"],
        "bears": Literal["bore", "face"],
        "cuts": list[str],
        "records": list[RecordBlank],
        "make_ops": MakeOps,
        "measured": Measurement,
        "verify": bool,
    },
)
# One receipt check of a bought-finished item (docs/inventory.md "Purchased tooling"):
# ``check`` says what is checked, ``gauge`` names an inventory gauge (``"none"`` for a
# check by hand or eye, which then states its ``accept`` criterion), ``how`` the way the
# gauge is used. The limit is ``limits`` (the name of a limits pair or single-length field
# on the same item, printed lo–hi or ≤ value) or ``limits_mm`` [lo, hi], and/or ``accept``
# in words (a GO / NO-GO result).
AcceptanceCheck = record(
    "AcceptanceCheck",
    {**texts("check gauge how limits accept"), "limits_mm": LimitPair},
)
InventoryItem = record(
    "InventoryItem",
    {
        **texts(
            "name kind make control operation_mode note coating material coverage by standards "
            "shank drawbar insert arbor jaw_bolt mount fits stud t_slot_in hand "
            "standard series chart units taper"
        ),
        "sku": str | int,
        **flags("verify present center_cutting swivel_base scroll independent shop_made"),
        **texts("dial_increases"),
        # Edge finder (docs/inventory.md "Edge finder"): how its contact shows and the
        # spindle speed band it is run at (with ``tip_in``/``tip_mm``, the tip Ø).
        "finder_type": Literal["mechanical", "electronic"],
        "rpm_range": LimitPair,
        # Bought-finished tooling: what is bought, and its receipt checks.
        "purchase": str,
        "acceptance": Annotated[list[AcceptanceCheck], Field(min_length=1)],
        # A shop-made item's make operations, one cutting-data line each.
        "make_ops": MakeOps,
        **numbers(
            "headstock_tilt_deg swing_over_bed_in between_centres_in "
            "cross_slide_travel_in compound_travel_in weight_lb worm_ratio centre_height_in "
            "swing_in plates pieces angle_deg head_in max_offset_in "
            "dial_in min_bore_in tip_in "
            "diameter_in thickness_in runout_max_in "
            "max_shank_in sfm chip_load_mm_per_tooth feed_mm_rev capacity_mm "
            "t_slots graduation_deg vernier_deg"
        ),
        "point_angle": MeasuredAngle,
        "blade_speed_sfm": Annotated[list[Number], Field(min_length=2, max_length=2)],
        # A bandsaw's running modes: only a vertical one follows a scribed curve.
        "saw_modes": Annotated[list[Literal["horizontal", "vertical"]], Field(min_length=1)],
        **dict.fromkeys(
            (
                "dia",
                "dia_mm",
                "dia_in",
                "oal",
                "oal_mm",
                "oal_in",
                "grip_mm",
                "gauge_len_mm",
                "gauge_len_in",
                "lead_mm",
                "height_mm",
                "height_in",
                "bed_height_mm",
                "bed_height_in",
                "flute_len",
                "flute_len_mm",
                "flute_len_in",
                # Combined drill and countersink pilot length, countersink start to point
                # tip (Machinery's Handbook Table 6 drill length C).
                "pilot_len",
                "pilot_len_mm",
                "pilot_len_in",
                "gauge_dia",
                "gauge_dia_mm",
                "gauge_dia_in",
                "jaw_height_mm",
                "jaw_height_in",
                "jaw_width_mm",
                "jaw_width_in",
                "jaw_depth_mm",
                "jaw_depth_in",
                "opening_mm",
                "opening_in",
                "length_mm",
                "length_in",
                "width_mm",
                "width_in",
                "resolution_mm",
                "resolution_in",
                "kerf_mm",
                "kerf_in",
                # The tool body past its cutting length (docs/rules-geometry.md#reach).
                "shank_mm",
                "max_work_mm",
                "max_work_in",
                "t_slot_width_mm",
                "t_slot_width_in",
                # Jaw buttons (a vise hold's jaw_buttons): face Ø (dia), thickness, spigot.
                "thickness_mm",
                "spigot_dia_mm",
                "spigot_dia_in",
                "spigot_length_mm",
                "spigot_length_in",
            ),
            MeasuredLength,
        ),
        # Turning tools (insert holder) and toolpost holder bodies: docs/rules-lathe.md.
        **dict.fromkeys(
            (
                "nose_radius_mm",
                "nose_radius_in",
                "reach_mm",
                "reach_in",
                "edge_len_mm",
                "edge_len_in",
                "head_len_mm",
                "head_len_in",
                "shank_width_mm",
                "shank_width_in",
                "functional_width_mm",
                "functional_width_in",
                "body_width_mm",
                "body_width_in",
                "body_depth_mm",
                "body_depth_in",
            ),
            MeasuredLength,
        ),
        "insert_angle_deg": MeasuredAngle,
        "entering_angle_deg": MeasuredAngle,
        "projection_mm": ProjectionMap,
        "projection_in": ProjectionMap,
        "envelope": MachineEnvelope,
        # A tool's own shank, or an end-mill set's {shank: [sizes]} map.
        "shank_in": MeasuredLength | str | dict[str, list[str]],
        "flutes": int | list[int],
        "source": str | Source,
        "cite": Citations,
        "sizes": list[str | int | float],
        "sizes_in": list[str | float] | dict[str, list[str]],
        "sizes_mm": Vector,
        "styles": list[str],
        "heights_in": list[str | float],
        "shims_in": list[str | float],
        "ranges_in": list[str],
        "range_in": float | list[Number],
        "range_mm": float | list[Number],
        # Roughness capability of a roughness gauge/comparator/profilometer, Ra µm [lo, hi].
        "ra_range": Annotated[list[Number], Field(min_length=2, max_length=2)],
        "size_in": str | list[Number],
        "nominal_dia_mm": dict[str, Number],
        "nominal_dia_cite": dict[str, Citations],
        "candidates": dict[str, str],
        "holders": dict[str, int | Unknown],
        "standard_accessories": list[str],
        "included": list[str],
        "spindle": Spindle,
        "leadscrew": LeadScrew,
        "capacity_in": float | list[Number] | Capacity,
        "tailstock": Tailstock,
        "threads": Threads,
        "toolpost": Toolpost,
        "direct_index": DirectIndex,
        "tilt_deg": Tilt,
        "plate_holes": dict[str, Vector],
        "bars": Bars,
        "members": dict[str, "InventoryItem | Unknown"],
        "solids": list[FixtureSolid],
        # Chuck body dimensions (fixture solids).
        **dict.fromkeys(
            ("body_dia_mm", "body_dia_in", "body_length_mm", "body_length_in")
            + ("bore_dia_mm", "bore_dia_in"),
            MeasuredLength,
        ),
        # Follow/steady rest jaw capacity: the work diameters the rest can ride on.
        **dict.fromkeys(
            ("capacity_min_mm", "capacity_min_in", "capacity_max_mm", "capacity_max_in"),
            MeasuredLength,
        ),
        # Grooving/parting blade front-edge width (two-cornered blade): docs/rules-geometry.md.
        **dict.fromkeys(("blade_width_mm", "blade_width_in"), MeasuredLength),
        # Filing buttons' receipt limits: button OD, button bore and pin diameters, and the
        # button OD's runout about its bore (docs/inventory.md, docs/rules-coordinates.md).
        **dict.fromkeys(
            ("button_dia_limits_mm", "button_dia_limits_in")
            + ("button_bore_limits_mm", "button_bore_limits_in")
            + ("pin_dia_limits_mm", "pin_dia_limits_in"),
            MeasuredLimits,
        ),
        **dict.fromkeys(("button_runout_mm", "button_runout_in"), MeasuredLength),
        # Guided-sweep fixtures and masters (docs/inventory.md "Guided-sweep fixtures"): a
        # swing arm's pivot play, an arc sled's rail radius, form error and roller runout,
        # and the radius limits a setting bar or master arc sets about the guide's centre.
        **dict.fromkeys(
            ("pivot_play_mm", "pivot_play_in", "rail_radius_mm", "rail_radius_in")
            + ("rail_form_error_mm", "rail_form_error_in")
            + ("roller_runout_mm", "roller_runout_in"),
            MeasuredLength,
        ),
        **dict.fromkeys(("radius_limits_mm", "radius_limits_in"), MeasuredLimits),
        # An arc sled's guide rollers: which edge of the sled the rail is (the rollers bear
        # on it from outside the arc, or from the arc centre's side), and their diameter,
        # which sets how far an inside roller's centre orbits.
        **dict.fromkeys(("roller_dia_mm", "roller_dia_in"), MeasuredLength),
        "rail_side": Literal["outer", "inner"],
        # Follow rest jaw directions about the spindle axis, degrees from the cutting tool.
        "jaw_angles_deg": list[Number],
    },
)
InventoryItem.model_rebuild()


# Single-length facts consumed by rules; size/range lists are independent collections.
_INVENTORY_LENGTH_STEMS = frozenset(
    "dia oal grip gauge_len gauge_dia lead height bed_height projection flute_len "
    "jaw_height jaw_width jaw_depth opening width shank capacity max_shank "
    "nose_radius reach tip length resolution edge_len head_len shank_width functional_width "
    "body_width body_depth kerf".split()
)
_ENVELOPE_LENGTH_STEMS = frozenset(
    (
        "spindle_to_table_max",
        "spindle_to_table_min",
        "travel",
        "swing_over_bed",
        "swing_over_cross_slide",
        "between_centres",
    )
)
_TRAVEL_LENGTH_STEMS = frozenset(("x", "y", "z"))

# Chuck body dimensions (fixture solids).
_INVENTORY_LENGTH_STEMS |= {"body_dia", "body_length", "bore_dia"}
# Follow/steady rest jaw capacity.
_INVENTORY_LENGTH_STEMS |= {"capacity_min", "capacity_max"}
# Grooving/parting blade front-edge width.
_INVENTORY_LENGTH_STEMS |= {"blade_width"}
# Filing buttons' runout and receipt limits: one fact each, in mm or in, never both.
_INVENTORY_LENGTH_STEMS |= {"button_runout", "button_dia_limits", "button_bore_limits"}
_INVENTORY_LENGTH_STEMS |= {"pin_dia_limits"}
# Rotary table work capacity and T-slot width.
_INVENTORY_LENGTH_STEMS |= {"max_work", "t_slot_width"}
# Combined drill and countersink pilot length (Table 6 C).
_INVENTORY_LENGTH_STEMS |= {"pilot_len"}
# Jaw button thickness and spigot (a vise hold's jaw_buttons).
_INVENTORY_LENGTH_STEMS |= {"thickness", "spigot_dia", "spigot_length"}
# Guided-sweep fixtures and masters: one fact each, in mm or in, never both.
_INVENTORY_LENGTH_STEMS |= {"pivot_play", "rail_radius", "rail_form_error", "roller_runout"}
_INVENTORY_LENGTH_STEMS |= {"radius_limits", "roller_dia"}


def _inventory_lengths(
    item: Any,
    where: str,
    *,
    tool: bool,
    unit: str | None = None,
    stems: frozenset[str] = _INVENTORY_LENGTH_STEMS,
) -> None:
    """Reject duplicate single-length facts, not independently authored size lists."""
    from prechips.measurements import length_keys

    if not isinstance(item, dict):
        return
    if item.get("units") in {"mm", "in", "inch"}:
        unit = "in" if item["units"] == "inch" else item["units"]
    if not tool and {"projection_mm", "projection_in"} & item.keys():
        raise ValueError(f"{where}: projection is a tool-owned map keyed by full holder reference.")
    for stem in sorted(stems):
        keys = length_keys(item, stem, unit)
        if len(keys) > 1:
            raise ValueError(f"{where}: {' and '.join(keys)} author one length twice.")
    members = item.get("members")
    for name, member in members.items() if isinstance(members, dict) else ():
        _inventory_lengths(member, f"{where}/{name}", tool=tool)
    for key in ("envelope", "travel_mm", "travel_in"):
        child_unit = "mm" if key.endswith("_mm") else "in" if key.endswith("_in") else unit
        _inventory_lengths(
            item.get(key),
            f"{where}.{key}",
            tool=tool,
            unit=child_unit,
            stems=_ENVELOPE_LENGTH_STEMS if key == "envelope" else _TRAVEL_LENGTH_STEMS,
        )


def _inventory_checks(item: Any, where: str) -> None:
    """Receipt checks belong to bought items and make operations to shop-made ones, and an
    edge finder's speed band is ordered (docs/inventory.md "Purchased tooling", "Shop-made
    fixtures", "Edge finder")."""
    if not isinstance(item, dict):
        return
    band = item.get("rpm_range")
    if _numeric_pair(band):
        _ordered(band, f"{where}: rpm_range", floor=0.0, inclusive=False)
    checks = item.get("acceptance")
    if isinstance(checks, list):
        if item.get("shop_made") is True or item.get("kind") == "custom":
            raise ValueError(f"{where}: acceptance is a bought item's receipt check.")
        for index, check in enumerate(checks):
            if isinstance(check, dict):
                _acceptance_check(check, f"{where}.acceptance[{index}]")
    _make_ops_checks(item, where)
    solids = item.get("solids")
    for solid in solids if isinstance(solids, list) else ():
        if not isinstance(solid, dict):
            continue
        name = solid.get("name", "?")
        if "records" not in solid:
            continue
        records = solid["records"]
        if not isinstance(records, list):
            raise ValueError(
                f"{where} solid {name}: records must list what is measured (omit it for none)."
            )
        for index, blank in enumerate(records):
            if isinstance(blank, dict):
                _record_blank(blank, f"{where} solid {name}.records[{index}]")
    members = item.get("members")
    for name, member in members.items() if isinstance(members, dict) else ():
        if _declares_make_ops(member):
            # A member is its set's record with its own keys over it: its make operations
            # would replace the set's, or print nowhere when the set is held whole.
            raise ValueError(f"{where}/{name}: a set member has no make_ops of its own.")
        _inventory_checks(member, f"{where}/{name}")
        if isinstance(member, dict) and _declares_make_ops({**item, "members": {}}):
            # The member as the traveler reads it (the set's keys, its own over them) keeps
            # the set's make operations: they must still be made here and print.
            try:
                _make_ops_checks({**item, **member}, f"{where}/{name}")
            except ValueError as error:
                kept = f"{error} (the make_ops are {where}'s, kept by its member)"
                raise ValueError(kept) from None


def _make_ops_checks(item: dict, where: str) -> None:
    """Make operations only where a make table prints them: on a shop-made item with a
    solid made here (or none drawn), and on a made primitive."""
    made_here = item.get("shop_made") is True or item.get("kind") == "custom"
    solids = item.get("solids")
    shapes = [s for s in solids if isinstance(s, dict)] if isinstance(solids, list) else []
    if "make_ops" in item:
        _make_ops(item["make_ops"], f"{where}.make_ops", made_here)
        # The traveler prints make operations on the item's make table, and an item none
        # of whose solids is made here has none: never accepted, then left off.
        if shapes and not any(s.get("supply", "made") == "made" for s in shapes):
            raise ValueError(
                f"{where}.make_ops: every solid is bought or existing, so nothing is made "
                "here; state what is made, or drop make_ops."
            )
    for solid in shapes:
        if "make_ops" in solid:
            name = solid.get("name", "?")
            supply = solid.get("supply", "made")
            if supply != "made":
                raise ValueError(
                    f"{where} solid {name}: a {supply} primitive is not made here; give the "
                    "make_ops to the hole made in it, or to the item."
                )
            _make_ops(solid["make_ops"], f"{where} solid {name}.make_ops", made_here)


# The categories whose shop-made items print a make table, so their make operations: the
# items a hold or an op's holder holds the work with.
_MADE_CATEGORIES = ("fixtures", "holders", "machines")


def _declares_make_ops(item: Any) -> bool:
    """Whether ``item`` states ``make_ops``: its own, a solid's or a member's."""
    if not isinstance(item, dict):
        return False
    solids = item.get("solids") if isinstance(item.get("solids"), list) else []
    members = item.get("members") if isinstance(item.get("members"), dict) else {}
    return (
        "make_ops" in item
        or any(isinstance(s, dict) and "make_ops" in s for s in solids)
        or any(map(_declares_make_ops, members.values()))
    )


# A make operation's feed: a number or a low-high range, then its unit.
_FEED_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
_MAKE_FEED = re.compile(
    rf"{_FEED_NUMBER}(?:\s*[-–]\s*{_FEED_NUMBER})?\s*(?:mm|in)/(?:rev|min|tooth)"
)
_MAKE_OP_FIELDS = ("hold", "tool", "rpm", "feed", "doc_mm", "cite")


def _make_ops(ops: Any, where: str, made_here: bool) -> None:
    """Make operations belong to a shop-made item (``kind = "custom"`` or ``shop_made``).
    Each states all six facts its line prints: its hold and ``tools`` key as text, its
    speed (a number or an ordered range) and depth of cut as numbers > 0, its feed as a
    number with its unit and the source of its cutting data. A fact not yet known is
    ``unknown`` (the traveler prints ``?`` and a STOP), never omitted or blank."""
    if not made_here:
        raise ValueError(
            f'{where}: only a shop-made item (kind = "custom" or shop_made = true) is made.'
        )
    for index, op in enumerate(ops if isinstance(ops, list) else ()):
        if not isinstance(op, dict):
            continue
        at = f"{where}[{index}]"
        for key in _MAKE_OP_FIELDS:
            if key not in op:
                raise ValueError(f"{at}: {key} must be stated, or be unknown.")
        for key in ("hold", "tool", "feed", "cite"):
            if isinstance(op[key], str) and not op[key].strip():
                raise ValueError(f"{at}: {key} must be stated, or be unknown.")
        feed = op["feed"]
        if isinstance(feed, str) and feed != UNKNOWN and not _MAKE_FEED.fullmatch(feed.strip()):
            raise ValueError(
                f"{at}: feed {feed!r} must be a number with its unit: mm/rev, mm/min, "
                "mm/tooth, in/rev, in/min or in/tooth."
            )
        if _numeric_pair(op["rpm"]):
            _ordered(op["rpm"], f"{at}: rpm", floor=0.0, inclusive=False)
        for key in ("rpm", "doc_mm"):
            value = op[key]
            if isinstance(value, int | float) and not isinstance(value, bool) and value <= 0:
                raise ValueError(f"{at}: {key} must be > 0, or be unknown.")


def _record_blank(blank: dict, where: str) -> None:
    """A record blank says what is measured, and how and with which gauge when it says so
    at all (a stated unknown would be dropped from the fill-in); its spec, goal and span
    are known lengths (an unknown spec would print a fill-in nobody can judge), the goal
    inside the spec. An unknown gauge stays allowed: tool_resolves reports it unknown."""
    check = blank.get("check")
    if not isinstance(check, str) or check.strip() in ("", UNKNOWN):
        raise ValueError(f"{where}: check must say what is measured and recorded.")
    how = blank.get("how")
    if "how" in blank and (not isinstance(how, str) or how.strip() in ("", UNKNOWN)):
        raise ValueError(f"{where}: how must say how it is measured, or be omitted.")
    gauge = blank.get("gauge")
    if "gauge" in blank and (not isinstance(gauge, str) or not gauge.strip()):
        raise ValueError(f"{where}: gauge must name an inventory gauge, or be omitted.")
    for key in ("max_mm", "goal_mm", "over_mm"):
        value = blank.get(key)
        if key in blank and (
            not isinstance(value, int | float) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"{where}: {key} must be a known length >= 0, or omitted.")
    if "goal_mm" in blank and "max_mm" in blank and blank["goal_mm"] > blank["max_mm"]:
        raise ValueError(f"{where}: goal_mm must lie inside the max_mm spec.")
    if blank.get("over_mm") == 0:
        raise ValueError(f"{where}: over_mm must be a length > 0.")


def _acceptance_check(check: dict, where: str) -> None:
    """A receipt check states what it checks, with a gauge (or ``none``) and a limit."""
    for key in ("check", "gauge"):
        value = check.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}: {key} must be stated (gauge may be unknown or none).")
    numeric = [key for key in ("limits", "limits_mm") if key in check]
    if len(numeric) > 1:
        raise ValueError(f"{where}: state the limit once, as limits or limits_mm.")
    if not numeric and "accept" not in check:
        raise ValueError(f"{where}: a receipt check needs a limit or an accept criterion.")
    if check["gauge"] == "none" and numeric:
        raise ValueError(f"{where}: a numeric limit is read with a gauge, not by hand.")
    band = check.get("limits_mm")
    if _numeric_pair(band):
        _ordered(band, f"{where}: limits_mm", floor=0.0, inclusive=True)


def _numeric_pair(band: Any) -> bool:
    return (
        isinstance(band, list)
        and len(band) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in band)
    )


# An in-house consumable a coating op names: the shop's display name for the traveler and
# the products on the shelf; an unknown, empty or blank product list leaves it unresolved.
Consumable = record("Consumable", {"name": str, "products": list[str]})


class Inventory(InputModel):
    machines: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    tools: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    holders: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    fixtures: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    gauges: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    # Outside processes the shop sends work to (a coating vendor): not shop-owned kit.
    services: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    consumables: dict[str, Consumable | Unknown] | Unknown = UNKNOWN
    stock: list[Stock] | Unknown = UNKNOWN

    @model_validator(mode="after")
    def bar_stock(self) -> Inventory:
        """A profiled blank is one part's supply, bound to a STEP in that part's bundle."""
        for index, stock in enumerate(self.stock if isinstance(self.stock, list) else ()):
            pieces = [stock, *(stock.components if isinstance(stock.components, list) else ())]
            if any(
                "blank" in piece.model_fields_set or piece.form == PROFILED_BLANK
                for piece in pieces
            ):
                raise ValueError(
                    f"inventory stock[{index}] is a profiled blank; declare it as the plan's "
                    "stock, where its STEP is read and hashed."
                )
        return self

    @model_validator(mode="before")
    @classmethod
    def unambiguous_lengths(cls, values: Any) -> Any:
        if isinstance(values, dict):
            for category in ("machines", "tools", "holders", "fixtures", "gauges", "services"):
                items = values.get(category)
                if isinstance(items, dict):
                    for identity, item in items.items():
                        where = f"{category}.{identity}"
                        _inventory_lengths(item, where, tool=category == "tools")
                        _inventory_checks(item, where)
                        if category not in _MADE_CATEGORIES and _declares_make_ops(item):
                            raise ValueError(
                                f"{where}: make_ops print on a holding item's make table; "
                                f"only {', '.join(_MADE_CATEGORIES)} items have one."
                            )
        return values


class Policy(InputModel):
    revision: int | Unknown = UNKNOWN
    required: dict[str, str | list[str]] | Unknown = UNKNOWN
    numbers: dict[str, Number] | Unknown = UNKNOWN
    numbers_cite: dict[str, Citations] | Unknown = UNKNOWN
    numbers_verify: dict[str, bool | Unknown] | Unknown = UNKNOWN


Cut = record(
    "Cut",
    {
        **texts("material_class tool_material operation"),
        "diameter_range": Vector,
        **numbers("sfm chip_load_mm_per_tooth feed_mm_rev feed_mm_min"),
        "cite": Citations,
    },
)
CutMaterial = record(
    "CutMaterial", {"material_class": str, **numbers("kc_n_per_mm2 e_gpa"), "cite": Citations}
)
DeepHole = record(
    "DeepHole",
    {"operation": str, **numbers("depth_over_dia sfm_factor"), "cite": Citations},
)
# An end mill fed straight down its own axis into the stock: feed per spindle revolution,
# selected like a cut row by material class, tool material and tool diameter.
Plunge = record(
    "Plunge",
    {
        **texts("material_class tool_material"),
        "diameter_range": Vector,
        "feed_mm_rev": float,
        "cite": Citations,
    },
)


class CuttingData(InputModel):
    revision: int | Unknown = UNKNOWN
    aliases: dict[str, str] | Unknown = UNKNOWN
    cut: list[Cut] | Unknown = UNKNOWN
    material: list[CutMaterial] | Unknown = UNKNOWN
    deep_hole: list[DeepHole] | Unknown = UNKNOWN
    plunge: list[Plunge] | Unknown = UNKNOWN
