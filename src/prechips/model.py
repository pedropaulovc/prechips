"""The five TOML input schemas. Literal unknown is never a numeric default."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_serializer, model_validator

type Unknown = Literal["unknown"]
UNKNOWN: Unknown = "unknown"
type Number = float | Unknown
type Vector = list[Number] | Unknown
type Citations = str | list[str]
TOLERANCE_REQUIREMENTS = frozenset(
    "dia position_dia angularity_dia finish_ra depth length width height radius thickness "
    "coaxiality_dia "
    "height_above_pivot arc_len bottom_radius bottom_arc_len tip_land land_angle_deg station "
    "groove_width groove_depth separation".split()
)


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


class StockComponent(InputModel):
    id: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]
    form: str | Unknown = UNKNOWN
    note: str | Unknown = UNKNOWN
    dia_mm: Number = UNKNOWN
    length_mm: Number = UNKNOWN
    section_mm: Vector = UNKNOWN
    origin_mm: Vector = UNKNOWN
    axis: Vector = UNKNOWN
    section_axis: Vector = UNKNOWN
    cite: Citations = UNKNOWN

    @model_validator(mode="after")
    def known_id(self) -> StockComponent:
        if self.id == UNKNOWN:
            raise ValueError("Stock component id must be a known identifier.")
        return self


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
        "cite": Citations,
    },
)
StockState = record(
    "StockState",
    {
        **texts("top_feature note"),
        **numbers(
            "top_z bottom_z retained_rail_bottom_z od_mm north_end_z south_end_z plain_end_z"
        ),
        "bottom_z_cite": Citations,
        "local_thickness": dict[str, Number],
        "local_thickness_cite": dict[str, Citations],
        "entry_z": dict[str, Number],
    },
)
Reference = record("Reference", {**texts("ref orientation note"), **numbers("height_mm")})
Index = record("Index", {"fixture": str, "feature": str, "angle_deg": Number, "positions": int})
Hold = record(
    "Hold",
    {
        **texts(
            "fixture jaws_along fixed_jaw parallels support support_orientation "
            "grip_on stop clamp note centre_lubrication riser method orientation locator "
            "release jaw_protection locate"
        ),
        "grip_mm": Number | Literal["not_applicable"],
        "jaw_above_parallels_mm": Number | Literal["not_applicable"],
        "stickout_mm": Number,
        "jaw_center_along_mm": Number,
        "parallels_centres_mm": Annotated[
            list[Annotated[list[Number], Field(min_length=2, max_length=2)]],
            Field(min_length=2, max_length=2),
        ],
        "supports": str | list[str | Reference],
        **flags("grip_mm_verify jaw_above_parallels_mm_verify"),
        "index": Index,
    },
)
AxisZero = record(
    "AxisZero",
    {
        **texts("edge feature face method tool holder gauge"),
        "from": str,
        **numbers("edge_mm radius_mm paper_mm check_jog_mm"),
        "retouch_after": list[int],
        "after_op": int,
    },
)
Transfer = record(
    "Transfer",
    {
        "from": str,
        "indicate": str | list[str],
        "tool": str,
        "gauge": str,
        "runout_limit_mm": Number,
        "reindicate_after": list[int],
    },
)
ToolTouch = record(
    "ToolTouch",
    {
        **texts("tool x_method gauge z_face method"),
        **numbers("edge_mm paper_mm"),
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
Contour = record(
    "Contour",
    {
        **texts("method sweep_frame open_side"),
        **numbers("step_deg step_mm start_deg end_deg"),
        "sweep_bounds": Bounds,
    },
)
Operation = record(
    "Operation",
    {
        "op": int,
        **texts("do feature tool holder direction note inspection_note"),
        **numbers(
            "to_z depth_mm exit_mm rough_allowance_mm stock_to_leave_mm z_from z_to "
            "to_dia rpm feed_mm_min doc_mm feed_mm_rev approach_mm"
        ),
        "to_z_cite": Citations,
        "note_cite": Citations,
        "faces": Annotated[list[str], Field(min_length=1)],
        "checks": dict[str, str],
        "missing_requirements": dict[str, str],
        "inspection_methods": dict[str, str],
        "to_z_band": Vector,
        "contour": Contour,
        # Setup-frame volume (plan units) the op clears down to the finished part.
        "stock_removal_bounds": Bounds,
    },
    indexed=("do",),
)
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
    },
    indexed=("machine",),
)


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

    @model_validator(mode="after")
    def named_frames(self) -> Plan:
        if isinstance(self.frames, dict) and any(
            not name.strip() or name == UNKNOWN for name in self.frames
        ):
            raise ValueError("Plan frame names must be known, non-empty names.")
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
        for setup in self.setups:
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
            if setup.id != UNKNOWN:
                earlier.add(setup.id)
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


Source = record("Source", {**texts("vendor by url note cite"), "sku": str | int, "verify": bool})


class Measurement(InputModel):
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
    },
)
Spindle = record(
    "Spindle",
    {
        **texts("taper drawbar drive mount"),
        **numbers("rpm_min rpm_max hp bore_in runout_in"),
        "two_ranges": bool,
        "ranges_rpm": list[list[Number]],
    },
)
# Tool projection belongs to one (tool, holder) pair: full holder reference -> fact.
type ProjectionMap = dict[str, MeasuredLength]
LeadScrew = record("LeadScrew", {**numbers("tpi dial_in"), "cross_feed_ipr": Vector})
Capacity = record("Capacity", numbers("drill end_mill face_mill"))
Tailstock = record("Tailstock", {"taper": str, "quill_travel_in": Number})
Threads = record("Threads", {"inch_tpi": Vector, "metric_pitch_mm": Vector})
Toolpost = record("Toolpost", {**texts("series type note"), "holders": int, "included": bool})
DirectIndex = record("DirectIndex", numbers("positions step_deg"))
Tilt = record("Tilt", numbers("down up"))
Bars = record(
    "Bars",
    {"count": int, "type": str, "shank_in": Number, "min_bore_in": Vector, "depth_in": Vector},
)
InventoryItem = record(
    "InventoryItem",
    {
        **texts(
            "kind make control operation_mode note coating material coverage by standards "
            "shank drawbar insert arbor jaw_bolt mount fits stud t_slot_in "
            "standard series chart units taper"
        ),
        "sku": str | int,
        **flags("verify present center_cutting swivel_base scroll independent"),
        **numbers(
            "headstock_tilt_deg swing_over_bed_in between_centres_in "
            "cross_slide_travel_in compound_travel_in weight_lb worm_ratio centre_height_in "
            "swing_in plates pieces angle_deg head_in max_offset_in "
            "dial_in min_bore_in tip_in "
            "diameter_in thickness_in resolution_in runout_max_in "
            "max_shank_in sfm chip_load_mm_per_tooth "
            "shank_mm capacity_mm nose_radius_mm reach_mm"
        ),
        "point_angle": MeasuredAngle,
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
            ),
            MeasuredLength,
        ),
        "projection_mm": ProjectionMap,
        "projection_in": ProjectionMap,
        "envelope": MachineEnvelope,
        "shank_in": float | str | dict[str, list[str]],
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
        "resolution_mm": Number,
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
    },
)
InventoryItem.model_rebuild()


# Single-length facts consumed by rules; size/range lists are independent collections.
_INVENTORY_LENGTH_STEMS = frozenset(
    "dia oal grip gauge_len gauge_dia lead height bed_height projection flute_len "
    "jaw_height jaw_width jaw_depth opening width shank capacity max_shank "
    "nose_radius reach tip length resolution".split()
)
_ENVELOPE_LENGTH_STEMS = frozenset(("spindle_to_table_max", "spindle_to_table_min", "travel"))
_TRAVEL_LENGTH_STEMS = frozenset(("x", "y", "z"))


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


class Inventory(InputModel):
    machines: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    tools: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    holders: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    fixtures: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    gauges: dict[str, InventoryItem | Unknown] | Unknown = UNKNOWN
    consumables: dict[str, list[str] | Unknown] | Unknown = UNKNOWN
    stock: list[Stock] | Unknown = UNKNOWN

    @model_validator(mode="before")
    @classmethod
    def unambiguous_lengths(cls, values: Any) -> Any:
        if isinstance(values, dict):
            for category in ("machines", "tools", "holders", "fixtures", "gauges"):
                items = values.get(category)
                if isinstance(items, dict):
                    for identity, item in items.items():
                        where = f"{category}.{identity}"
                        _inventory_lengths(item, where, tool=category == "tools")
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
        **numbers("sfm chip_load_mm_per_tooth"),
        "cite": Citations,
    },
)
CutMaterial = record(
    "CutMaterial", {"material_class": str, **numbers("kc_n_per_mm2 e_gpa"), "cite": Citations}
)


class CuttingData(InputModel):
    revision: int | Unknown = UNKNOWN
    aliases: dict[str, str] | Unknown = UNKNOWN
    cut: list[Cut] | Unknown = UNKNOWN
    material: list[CutMaterial] | Unknown = UNKNOWN
