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
    id: Annotated[str, Field(min_length=1)]
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
        if not self.id.strip() or self.id == UNKNOWN:
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
ClampPlacement = record(
    "ClampPlacement",
    {
        **texts("ref note"),
        "pose": Pose,
        "restraint": Literal["press", "locate", "none"],
        "torque_nm": Number,
    },
)
type PlanCentres = list[Annotated[list[Number], Field(min_length=2, max_length=2)]]
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
        "clamps": list[ClampPlacement],
        # Diagram annotations: action order references the 1-based clamps array.
        "clamp_order": list[Annotated[int, Field(gt=0)]],
        "preload_direction": Literal["clockwise", "counterclockwise"] | Unknown,
        "stop_fixture": str,
        # The face the work is set against: a feature already on the arriving stock, or
        # the stock's own end. Checked against the arriving stock by hold_fields.
        "stop_face": str,
        "stop_pose": Pose,
    },
)
AxisZero = record(
    "AxisZero",
    {
        **texts("edge feature face method tool holder gauge measure"),
        "from": str,
        **numbers("edge_mm radius_mm paper_mm check_jog_mm offset_mm"),
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
        **texts("tool x_method gauge z_face method z_gauge z_measure"),
        **numbers("edge_mm paper_mm z_offset_mm"),
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
SawPlane = record(
    "SawPlane",
    {"axis": Literal["x", "y", "z"], "value": Number, "keep": Literal["below", "above"]},
)


class ProcessHold(InputModel):
    """A shop limit inside one drawing requirement band, held for a stated process reason
    (a downstream fit, a clocking stop): printed as a process hold, never a drawing limit."""

    feature: str
    requirement: str
    band: Annotated[list[float], Field(min_length=2, max_length=2)]
    gauge: str
    reason: str

    @model_validator(mode="after")
    def stated(self) -> ProcessHold:
        for value, what in (
            (self.feature, "feature"),
            (self.requirement, "requirement"),
            (self.reason, "reason"),
        ):
            _known_text(value, f"A process hold {what}")
        if not self.band[0] < self.band[1]:
            raise ValueError("A process hold band must be an ordered [lo, hi] band, lo < hi.")
        return self


# An inspection procedure: one string (blank-line paragraphs print as numbered steps), or a
# list of steps, each printed as one numbered step; a ``{name}`` in a step prints a labelled
# recording blank, and a step starting ``Calculate:`` prints as the calculation line.
type Procedure = str | Annotated[list[str], Field(min_length=1)]
Operation = record(
    "Operation",
    {
        "op": int,
        "do": str,
        # One manifest feature; an inspect op may name several (one drawing dimension
        # split across features is read once).
        "feature": str | Annotated[list[str], Field(min_length=2)],
        **texts("tool holder direction note"),
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
        "checks": dict[str, str],
        "missing_requirements": dict[str, str],
        "inspection_methods": dict[str, Procedure],
        "to_z_band": Vector,
        "contour": Contour,
        # Setup-frame volume (plan units) the op clears down to the finished part.
        "stock_removal_bounds": Bounds,
        # Mill op on a horizontal dividing head: each face sample turned under the spindle;
        # z_from/z_to are then head-axis positions and angle_window_deg its rotation span.
        "approach": Literal["rotary"],
        "angle_window_deg": Annotated[list[Number], Field(min_length=2, max_length=2)],
        # Blade centre plane in setup coordinates; kerf comes only from the selected blade.
        "cut_plane": SawPlane,
    },
    indexed=("do",),
)
type KnownPoint3 = Annotated[list[float], Field(min_length=3, max_length=3)]
type KnownBand = Annotated[list[float], Field(min_length=2, max_length=2)]
# Authored unit vectors carry trig residue; the kernel's pose tolerance applies.
UNIT_TOLERANCE = 1e-6


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
    "clearance": {"silver_braze", "retaining_compound"},
    "interference": {"press"},
}


class CylindricalJoint(InputModel):
    """Socket/spigot join of exactly two branches; fit bands are diametral mm."""

    kind: Literal["cylindrical"]
    socket: str
    spigot: str
    fit: Literal["clearance", "interference"]
    clearance_mm: KnownBand | Unknown | None = None
    interference_mm: KnownBand | Unknown | None = None
    method: Literal["silver_braze", "retaining_compound", "press"]
    process: str
    cure_time_min: float | Unknown | None = None
    surface_prep: str | None = None
    cite: Citations

    @model_validator(mode="after")
    def declared_fit(self) -> CylindricalJoint:
        _known_text(self.process, "A joint process")
        if not _cited(self.cite):
            raise ValueError("A joint must cite its fit and process source.")
        if self.method not in _FIT_METHODS[self.fit]:
            raise ValueError(f"A {self.fit} joint cannot be made by {self.method}.")
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
        if self.method == "retaining_compound":
            if self.cure_time_min is None or self.surface_prep is None:
                raise ValueError(
                    "A retaining_compound joint must declare cure_time_min and surface_prep."
                )
            if self.cure_time_min != UNKNOWN and self.cure_time_min <= 0:
                raise ValueError("A retaining_compound cure_time_min must be positive.")
            if self.surface_prep != UNKNOWN:
                _known_text(self.surface_prep, "A retaining_compound surface_prep")
        elif self.cure_time_min is not None or self.surface_prep is not None:
            raise ValueError("Cure time and surface prep are retaining_compound process facts.")
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


class Contouring(InputModel):
    """A labelled contouring capability: only its own measured/verify qualify it."""

    value: Literal["mdi", "jog"]
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
Toolpost = record("Toolpost", {**texts("series type note"), "holders": int, "included": bool})
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
# locates or carries, ``fastener`` its thread / fastener, and ``shim`` marks an
# adjustable shim stack whose drawn thickness is the nominal (traveler fixture table).
# ``supply``: made with its owner (default), ``bought`` hardware, or ``existing`` in the
# shop (a machine's vise jaw drawn for clearance); only made solids are make-table rows.
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
        "cuts": list[str],
        "measured": Measurement,
        "verify": bool,
    },
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
        **numbers(
            "headstock_tilt_deg swing_over_bed_in between_centres_in "
            "cross_slide_travel_in compound_travel_in weight_lb worm_ratio centre_height_in "
            "swing_in plates pieces angle_deg head_in max_offset_in "
            "dial_in min_bore_in tip_in "
            "diameter_in thickness_in runout_max_in "
            "max_shank_in sfm chip_load_mm_per_tooth feed_mm_rev "
            "shank_mm capacity_mm"
        ),
        "point_angle": MeasuredAngle,
        "blade_speed_sfm": Annotated[list[Number], Field(min_length=2, max_length=2)],
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
                "resolution_mm",
                "resolution_in",
                "kerf_mm",
                "kerf_in",
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
        # How a mill moves off a single axis: ``mdi`` types each arc or diagonal row as one
        # coordinated move; ``jog`` steps it one handwheel axis at a time.
        "contouring": Literal["mdi", "jog"] | Contouring | Unknown,
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


class CuttingData(InputModel):
    revision: int | Unknown = UNKNOWN
    aliases: dict[str, str] | Unknown = UNKNOWN
    cut: list[Cut] | Unknown = UNKNOWN
    material: list[CutMaterial] | Unknown = UNKNOWN
