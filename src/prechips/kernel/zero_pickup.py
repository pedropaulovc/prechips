"""Native finder and explicit arriving-top contact/full-stack path proofs.

FreeCAD/Part and existing native sweep primitives are injected by the job. This
module neither imports the job nor owns material routing or mounted-saw zero.
Coordinates are already in the current setup; Z is the lowest tool tip point.
"""

import math
from copy import deepcopy

_MODEL = "transverse_finder_v1"
_UNKNOWN = "unknown"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _messages(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _finish(proof):
    proof["reasons"] = list(dict.fromkeys(proof["reasons"]))
    proof["errors"] = list(dict.fromkeys(proof["errors"]))
    proof["status"] = "error" if proof["errors"] else "unknown" if proof["reasons"] else "pass"
    return proof


class _Pickup:
    def __init__(self, App, Part, setup, stock, fixtures, helpers, axis, request):
        self.Part, self.V = Part, App.Vector
        self.setup, self.stock, self.fixtures = setup, stock, fixtures
        self.helpers, self.axis, self.request = helpers, axis, request
        self.bbox, self.sweep = helpers["bbox"], helpers["sweep"]
        self.tol, self.hit, self.area = (
            helpers["plane_tol"],
            helpers["hit_mm3"],
            helpers["area_tol"],
        )
        self.result = {
            "model": _MODEL,
            "setup_id": setup.get("id", _UNKNOWN),
            "axis": axis,
            "recipe_id": request.get("recipe_id", _UNKNOWN),
            "request": deepcopy(request),
            "status": _UNKNOWN,
            "reasons": _messages(setup.get("zero_pickup_reasons"))
            + _messages(request.get("reasons")),
            "errors": _messages(setup.get("zero_pickup_errors")) + _messages(request.get("errors")),
            "collisions": [],
        }
        self.reasons, self.errors = self.result["reasons"], self.result["errors"]

    def _positive(self, source, key):
        value = source.get(key)
        if not _number(value):
            self.reasons.append(f"pickup {key} is unknown")
            return None
        if value <= 0:
            self.errors.append(f"pickup {key} must be positive")
            return None
        return value

    def _components(self, field="finder", label="finder"):
        finder = self.request.get(field)
        if not isinstance(finder, dict):
            finder = {}
        self.reasons.extend(_messages(finder.get("reasons")))
        self.errors.extend(_messages(finder.get("errors")))
        dimensions = {
            key: self._positive(finder, key)
            for key in (
                "tip_dia_mm",
                "tip_length_mm",
                "shank_dia_mm",
                "projection_mm",
                "holder_dia_mm",
                "holder_gauge_len_mm",
            )
        }
        tip, length, shank, projection, holder, gauge = dimensions.values()
        components = []
        if tip is not None and length is not None:
            components.append(("tip", 0, tip / 2, 0, length))
        if length is not None and projection is not None:
            if projection < length:
                self.errors.append(f"{label} projection is shorter than its measured tip length")
            elif projection == length:
                self.errors.append(f"{label} has no exposed shank above its measured tip")
            elif shank is not None:
                components.append(("shank", 0, shank / 2, length, projection))
        if holder is not None and projection is not None and gauge is not None:
            components.append(("holder", 0, holder / 2, projection, projection + gauge))
        return tip, length, components

    def _scene(self):
        obstacles = []
        if self.stock is None:
            self.reasons.append("actual arriving pickup stock is unresolved")
        else:
            obstacles.append({"name": "stock", "solid": self.stock})
        for fixture in self.fixtures:
            if not isinstance(fixture, dict) or fixture.get("solid") is None:
                self.reasons.append("a pickup fixture solid is unresolved")
            elif not isinstance(fixture.get("name"), str) or not fixture["name"].strip():
                self.reasons.append("a pickup fixture component identity is unresolved")
                obstacles.append({"name": _UNKNOWN, "solid": fixture["solid"]})
            else:
                obstacles.append(fixture)
        self.obstacle_boxes = [self.bbox(obstacle["solid"]) for obstacle in obstacles]
        self.result["obstacles"] = [
            {"name": obstacle["name"], "bbox_mm": list(box)}
            for obstacle, box in zip(obstacles, self.obstacle_boxes, strict=True)
        ]
        return obstacles

    def _faces(self):
        surface = self.request.get("surface")
        if not isinstance(surface, dict):
            self.reasons.append("selected pickup contact surface is unknown")
            return []
        if surface.get("kind") == "fixture":
            name = surface.get("name")
            matches = [
                item
                for item in self.fixtures
                if isinstance(item, dict) and item.get("name") == name
            ]
            if not isinstance(name, str) or not name.strip() or not matches:
                self.reasons.append("selected pickup fixture target is unresolved")
                return []
            if len(matches) != 1 or matches[0].get("solid") is None:
                self.reasons.append("selected pickup fixture target is ambiguous or incomplete")
                return []
            side = surface.get("side")
            if side not in ("+x", "-x", "+y", "-y"):
                self.reasons.append("selected pickup fixture side is unknown")
                return []
            if side != self.request.get("from"):
                self.errors.append("selected pickup fixture side disagrees with approach direction")
                return []
            return list(matches[0]["solid"].Faces)
        if surface.get("kind") != "stock" or self.stock is None:
            self.reasons.append("selected pickup stock target is unresolved")
            return []
        ref, member = surface.get("face"), surface.get("workpiece_id")
        if not isinstance(ref, str) or not ref.strip() or ref == _UNKNOWN:
            self.reasons.append("selected pickup stock face is unknown")
            return []
        if ref in ("stock:+x", "stock:-x", "stock:+y", "stock:-y"):
            side = ref.removeprefix("stock:")
            if surface.get("side") not in ("+x", "-x", "+y", "-y"):
                self.reasons.append("explicit arriving-stock pickup side is unknown")
                return []
            if surface["side"] != side or self.request.get("from") != side:
                self.errors.append("explicit arriving-stock side disagrees with pickup direction")
                return []
            if member is not None:
                self.reasons.append("raw-stock boundary selection cannot imply a carried member")
                return []
            return list(self.stock.Faces)
        key = (member, ref) if member is not None else ref
        declared = self.helpers.get("model_faces", {}).get(key)
        if declared is None:
            self.reasons.append(
                "selected pickup stock face has no current member-qualified geometry"
            )
            return []
        declared = declared if isinstance(declared, (list, tuple)) else [declared]
        faces = [
            face
            for face in self.stock.Faces
            if type(face.Surface).__name__ == "Plane"
            and any(face.common(target).Area > self.area for target in declared)
        ]
        if not faces:
            self.reasons.append("selected named pickup face is not proved on actual arriving stock")
        return faces

    def _contact(self, tip, length):
        faces = self._faces()
        if not faces:
            return None
        axis = 0 if self.axis == "x" else 1
        transverse = 1 - axis
        sign = 1 if self.request["from"][0] == "+" else -1
        normal = [0, 0, 0]
        normal[axis] = sign
        directed = [
            face
            for face in faces
            if type(face.Surface).__name__ == "Plane"
            and (face.normalAt(*face.ParameterRange[::2]) - self.V(*normal)).Length <= self.tol
        ]
        if not directed:
            self.errors.append(
                "selected actual pickup face normal disagrees with approach direction"
            )
            return None
        at = self.request["at_mm"]
        touching = []
        for face in directed:
            plane = list(face.CenterOfMass)[axis]
            low = [0.0, 0.0, at[1]]
            low[axis], low[transverse] = plane, at[0]
            high = [*low[:2], low[2] + length]
            generator = self.Part.makeLine(self.V(*low), self.V(*high))
            common = generator.common(face)
            if common.Vertexes:
                touching.append((face, [vertex.Point.z for vertex in common.Vertexes]))
        if not touching:
            self.errors.append(
                "requested pickup does not contact the selected actual face within the tip span"
            )
            return None
        coordinates = [list(face.CenterOfMass)[axis] for face, _ in touching]
        if max(coordinates) - min(coordinates) > self.tol:
            self.reasons.append("selected pickup target does not identify one actual contact plane")
            return None
        plane = coordinates[0]
        low = [0.0, 0.0, at[1]]
        low[axis], low[transverse] = plane, at[0]
        contact_low = min(z for _, heights in touching for z in heights)
        contact_high = max(z for _, heights in touching for z in heights)
        point = [*low[:2], (contact_low + contact_high) / 2]
        centre = [*low]
        centre[axis] += sign * tip / 2
        edge = self.request.get("edge_mm")
        if not _number(edge):
            self.reasons.append("declared pickup edge coordinate is unknown")
        elif abs(edge - plane) > self.tol:
            self.errors.append(
                "declared pickup edge disagrees with the actual selected contact plane"
            )
        intervals = []
        for face, _ in touching:
            box = self.bbox(face)
            start, end = [*point], [*point]
            start[transverse], end[transverse] = box[transverse], box[transverse + 3]
            if end[transverse] - start[transverse] <= self.tol:
                continue
            section = self.Part.makeLine(self.V(*start), self.V(*end)).common(face)
            for edge_shape in section.Edges:
                bounds = self.bbox(edge_shape)
                intervals.append([bounds[transverse], bounds[transverse + 3]])
        self.result["resolved_contact"] = {
            "surface": deepcopy(self.request["surface"]),
            "plane_mm": plane,
            "normal": normal,
            "axis_mm": centre,
            "point_mm": point,
            "tip_span_mm": [at[1], at[1] + length],
            "contact_z_mm": [contact_low, contact_high],
        }
        if intervals:
            self.result["window"] = {
                "scope": "contact_only",
                "transverse_axis": "y" if axis == 0 else "x",
                "centre_min_mm": min(pair[0] for pair in intervals),
                "centre_max_mm": max(pair[1] for pair in intervals),
                "intervals_mm": sorted(intervals),
                "at_mm": at[0],
                "contact_z_mm": [contact_low, contact_high],
                "section_z_mm": point[2],
            }
        else:
            self.reasons.append("actual transverse pickup contact window is unresolved")
        return centre

    def _path(self, centre, approach, clearance, jog, components, obstacles):
        axis = 0 if self.axis == "x" else 1
        sign = 1 if self.request["from"][0] == "+" else -1
        outside = [*centre]
        outside[axis] += sign * approach
        top = self.obstacle_boxes[0][5] if self.stock is not None else _UNKNOWN
        height = top + clearance if _number(top) and clearance is not None else _UNKNOWN
        start = _UNKNOWN
        legs = [(1, "approach", outside, centre)]
        if _number(height):
            if height < centre[2]:
                self.errors.append(
                    "pickup clearance height is below the requested lowest tip point"
                )
            start = [*outside[:2], height]
            retracted = [*centre[:2], height]
            legs.insert(0, (0, "descend", start, outside))
            legs.append((2, "retract", centre, retracted))
            if _number(jog):
                checked = [*retracted]
                checked[axis] += jog
                legs.append((3, "check_jog", retracted, checked))
        path = {
            "complete": len(legs) == 4,
            "start_mm": start,
            "contact_mm": centre,
            "stock_top_mm": top,
            "retract_height_mm": height,
            "jog_mm": jog,
            "legs": [],
        }
        self.result["path"] = path
        self._sweep_legs(legs, path, components, obstacles)

    def _sweep_legs(self, legs, path, components, obstacles):
        for index, kind, first, last in legs:
            leg = {"index": index, "kind": kind, "from_mm": first, "to_mm": last, "components": []}
            path["legs"].append(leg)
            for component in components:
                try:
                    swept = self.sweep(component, first, last)
                    box = self.bbox(swept)
                    leg["components"].append(
                        {"id": component[0], "bbox_mm": list(box), "swept_volume_mm3": swept.Volume}
                    )
                except Exception as exc:
                    self.reasons.append(f"exact {component[0]} pickup {kind} sweep failed: {exc}")
                    continue
                for obstacle, obstacle_box in zip(obstacles, self.obstacle_boxes, strict=True):
                    if any(
                        box[k] >= obstacle_box[k + 3] or obstacle_box[k] >= box[k + 3]
                        for k in range(3)
                    ):
                        continue
                    try:
                        common = swept.common(obstacle["solid"])
                        if common.Volume > self.hit:
                            self.result["collisions"].append(
                                {
                                    "component": component[0],
                                    "obstacle": obstacle["name"],
                                    "move_index": index,
                                    "kind": kind,
                                    "volume_mm3": common.Volume,
                                    "bbox_mm": list(self.bbox(common)),
                                }
                            )
                    except Exception as exc:
                        self.reasons.append(
                            f"pickup collision against {obstacle['name']} is unresolved: {exc}"
                        )
        if self.result["collisions"]:
            self.errors.append(
                "pickup tip, shank or selected holder collides along the exact pickup path"
            )

    def run(self):
        if self.request.get("model") != _MODEL:
            self.reasons.append("requested pickup model is unsupported or unknown")
        if not isinstance(self.request.get("recipe_id"), str) or self.request["recipe_id"] in (
            "",
            _UNKNOWN,
        ):
            self.reasons.append("current pickup recipe identity is unknown")
        if self.request.get("axis") not in ("x", "y"):
            self.reasons.append("pickup request axis identity is unknown")
        elif self.request["axis"] != self.axis:
            self.errors.append("pickup request axis disagrees with its setup axis identity")
        for key in ("tool", "holder"):
            value = self.request.get(key)
            if not isinstance(value, str) or not value.strip() or value == _UNKNOWN:
                self.reasons.append(f"selected pickup {key} identity is unknown")
        tip, length, components = self._components()
        obstacles = self._scene()
        approach = self._positive(self.request, "approach_mm")
        clearance = self._positive(self.request, "retract_clearance_mm")
        jog = self.request.get("check_jog_mm")
        if not _number(jog):
            self.reasons.append("signed pickup check jog is unknown")
        direction = self.request.get("from")
        if direction not in ("+" + self.axis, "-" + self.axis):
            if direction in ("+x", "-x", "+y", "-y", "+z", "-z"):
                self.errors.append("pickup approach direction does not match the requested axis")
            else:
                self.reasons.append("pickup approach direction is unknown")
            return _finish(self.result)
        at = self.request.get("at_mm")
        if not isinstance(at, list) or len(at) != 2 or not all(_number(value) for value in at):
            self.reasons.append("requested transverse pickup coordinates are unknown")
            return _finish(self.result)
        if tip is None or length is None:
            return _finish(self.result)
        centre = self._contact(tip, length)
        if centre is not None and approach is not None:
            self._path(centre, approach, clearance, jog, components, obstacles)
        return _finish(self.result)


def _contact_land_patch(contact, land, *, area_tol, length_tol):
    """Find one actual connected contact patch supporting the finite touch land.

    Other top islands within the occupied tool projection are not the datum.
    Join coplanar fragments only by positive-area overlap or a shared boundary
    segment; point contact and mere proximity do not connect a usable patch.
    """
    faces = contact.Faces
    if not faces or contact.Area <= area_tol or land.Area <= area_tol:
        return None
    remaining = set(range(len(faces)))
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component = [seed]
        frontier = [seed]
        while frontier and remaining:
            current = frontier.pop()
            joined = []
            for index in remaining:
                common = faces[current].common(faces[index])
                # Face common keeps overlap area, but OCC drops a shared edge
                # or point from it. Section preserves that lower-dimensional
                # topology; only a segment, not an isolated vertex, joins faces.
                if (
                    common.Area > area_tol
                    or faces[current].section(faces[index]).Length > length_tol
                ):
                    joined.append(index)
            remaining.difference_update(joined)
            frontier.extend(joined)
            component.extend(joined)
        patch = faces[seed]
        for index in sorted(component[1:]):
            patch = patch.fuse(faces[index])
        patch = patch.removeSplitter()
        if land.cut(patch).Area <= area_tol:
            return patch
    return None


class _ArrivingTop(_Pickup):
    """A qualified flat-end projection touching actual stock, not a target-face alias.

    The full occupied disk is conservative for collisions, not a claim that its
    interior is filled with cutting edges. Contact uses the existing qualified
    flat-end model and a finite planar land. Tool overhang is allowed.
    """

    def __init__(self, App, Part, setup, stock, fixtures, helpers, request):
        super().__init__(App, Part, setup, stock, fixtures, helpers, "z", request)
        self.result["model"] = "arriving_top_v1"
        self.result["arrival"] = deepcopy(helpers.get("arrival", {}))

    def _contact(self, tip):
        surface = self.request.get("surface")
        if surface != {"kind": "stock", "face": "stock:+z", "side": "+z"}:
            self.reasons.append("arriving top needs the explicit actual-stock +Z surface")
            return None
        if self.stock is None:
            return None
        edge, at, land = (
            self.request.get("edge_mm"),
            self.request.get("at_mm"),
            self.request.get("contact_land_mm"),
        )
        if not _number(edge):
            self.reasons.append("declared arriving top plane is unknown")
            return None
        if not isinstance(at, list) or len(at) != 2 or not all(map(_number, at)):
            self.reasons.append("selected arriving-top touch coordinates are unknown")
            return None
        if not _number(land):
            self.reasons.append("finite arriving-top contact land is unknown")
            return None
        if land <= 0:
            self.errors.append("arriving-top contact land must be positive")
            return None
        radius = tip / 2
        if land / math.sqrt(2) > radius:
            self.errors.append("selected tool cannot cover the finite contact land")
            return None
        directed = [
            (index, face)
            for index, face in enumerate(self.stock.Faces)
            if type(face.Surface).__name__ == "Plane"
            and (face.normalAt(*face.ParameterRange[::2]) - self.V(0, 0, 1)).Length <= self.tol
            and abs(face.CenterOfMass.z - edge) <= self.tol
        ]
        if not directed:
            self.errors.append("declared arriving top has no actual +Z planar stock patch")
            return None
        patch = directed[0][1]
        for _, face in directed[1:]:
            patch = patch.fuse(face)
        patch = patch.removeSplitter()
        point = [*at, edge]
        footprint = self.Part.Face(self.Part.Wire(self.Part.makeCircle(radius, self.V(*point))))
        contact = footprint.common(patch).removeSplitter()
        if contact.Area <= self.area:
            self.errors.append("selected top touch has no positive-area planar contact")
            return None
        half = land / 2
        corners = [
            self.V(at[0] + x, at[1] + y, edge)
            for x, y in ((-half, -half), (half, -half), (half, half), (-half, half))
        ]
        square = self.Part.Face(self.Part.makePolygon([*corners, corners[0]]))
        selected_patch = _contact_land_patch(
            contact, square, area_tol=self.area, length_tol=self.tol
        )
        if selected_patch is None:
            self.reasons.append(
                "selected top touch does not retain the finite planar contact land "
                "in one connected patch"
            )
            return None
        missing_land = square.cut(selected_patch).Area
        paper = self.request["paper_mm"]
        axis = [*at, edge + paper]
        self.result["resolved_contact"] = {
            "surface": deepcopy(surface),
            "contact_model": "flat_end_projection_v1",
            "plane_mm": edge,
            "point_mm": point,
            "axis_mm": axis,
            "normal": [0, 0, 1],
            "land_mm": land,
            "land_bbox_mm": list(self.bbox(square)),
            "land_area_mm2": square.Area,
            "missing_land_area_mm2": missing_land,
            "footprint_radius_mm": radius,
            "footprint_area_mm2": footprint.Area,
            "contact_area_mm2": contact.Area,
            "uncovered_area_mm2": footprint.cut(patch).Area,
            "patch_bbox_mm": list(self.bbox(selected_patch)),
            "patch_area_mm2": selected_patch.Area,
            "patch_face_indices": [
                index for index, face in directed if face.common(selected_patch).Area > self.area
            ],
        }
        return axis

    def _path(self, centre, clearance, jog, components, obstacles):
        height = max(box[5] for box in self.obstacle_boxes) + clearance
        if height <= centre[2]:
            self.errors.append("top pickup retract height is not above the paper-contact pose")
        start = [*centre[:2], height]
        checked = [*centre[:2], centre[2] + jog]
        path = {
            "complete": True,
            "start_mm": start,
            "contact_mm": centre,
            "stock_top_mm": self.result["physical_upper_bound_mm"],
            "retract_height_mm": height,
            "jog_mm": jog,
            "legs": [],
        }
        self.result["path"] = path
        self._sweep_legs(
            [
                (0, "descend", start, centre),
                (1, "check_jog", centre, checked),
                (2, "retract", checked, start),
            ],
            path,
            components,
            obstacles,
        )

    def run(self):
        request = self.request
        if request.get("model") != "arriving_top_v1":
            self.reasons.append("requested arriving-top model is unsupported or unknown")
        for key in ("recipe_id", "scene_id", "tool", "holder"):
            value = request.get(key)
            if not isinstance(value, str) or not value.strip() or value == _UNKNOWN:
                self.reasons.append(f"arriving-top {key} identity is unknown")
        if request.get("axis") != "z" or request.get("from") != "+z":
            self.errors.append("arriving-top touch requires setup Z from +Z")
        if request.get("method") != "paper":
            self.reasons.append("arriving-top proof requires an explicit paper touch")
        position = request.get("position", 0)
        arrival = self.result["arrival"]
        if (
            not isinstance(position, int)
            or isinstance(position, bool)
            or position < 0
            or position != arrival.get("position", 0)
        ):
            self.reasons.append("top touch does not match the actual native stock boundary")
        elif position == 0:
            if "after_op" in request or request.get("before_ops", []) != []:
                self.reasons.append("initial top touch cannot alias a later operation boundary")
        else:
            after, before = request.get("after_op"), request.get("before_ops")
            if after is None or str(after) != str(arrival.get("after_op")):
                self.reasons.append("top touch after-operation boundary is unresolved")
            if (
                not isinstance(before, list)
                or not before
                or str(arrival.get("before_op")) not in {str(item) for item in before}
            ):
                self.reasons.append("top touch before-operation boundary is unresolved")
        if request.get("tool_kind") != "endmill":
            self.reasons.append("arriving-top touch needs a qualified flat-end mill")
        envelope = request.get("tool_envelope")
        envelope = envelope if isinstance(envelope, dict) else {}
        if envelope.get("contact_kind") != "flat_end":
            self.reasons.append("selected tool flat-end contact qualification is unknown")
        nose = envelope.get("nose_radius_mm")
        if not _number(nose):
            self.reasons.append("selected tool flat-end nose radius is unknown")
        elif nose != 0:
            self.errors.append("arriving-top flat-end proof requires zero nose radius")
        paper = request.get("paper_mm")
        if not _number(paper):
            self.reasons.append("arriving-top paper thickness is unknown")
        elif paper < 0:
            self.errors.append("arriving-top paper thickness cannot be negative")
        tip, _, components = self._components("tool_envelope", "touch tool")
        obstacles = self._scene()
        if self.stock is not None:
            self.result["stock_bbox_mm"] = list(self.bbox(self.stock))
            self.result["physical_upper_bound_mm"] = self.result["stock_bbox_mm"][5]
        clearance = self._positive(request, "retract_clearance_mm")
        jog = request.get("check_jog_mm")
        if not _number(jog):
            self.reasons.append("signed arriving-top check jog is unknown")
        if tip is None or not _number(paper) or paper < 0:
            return _finish(self.result)
        centre = self._contact(tip)
        if centre is not None and clearance is not None and _number(jog):
            self._path(centre, clearance, jog, components, obstacles)
        return _finish(self.result)


def prove_pickups(App, Part, setup, stock, fixtures, *, helpers):
    """Prove explicitly requested pickups against the actual arriving native scene.

    ``helpers`` supplies the existing native ``sweep`` and ``bbox`` functions,
    exact ``model_faces`` map, and ``plane_tol``, ``hit_mm3``, ``area_tol``. The
    sweep accepts ``(id, inner_radius, outer_radius, z_min, z_max), start, end``.
    Missing geometry is debt, not an empty obstacle or a numeric-edge contact.
    """
    requests = setup.get("zero_pickups")
    if not isinstance(requests, dict):
        return {}
    results = {}
    for key, request in requests.items():
        if not isinstance(request, dict):
            continue
        if key in ("x", "y"):
            axis = key
        elif (
            isinstance(key, str)
            and (key == "z" or key.startswith("tool_touch:"))
            and request.get("model") == "arriving_top_v1"
        ):
            axis = "z"
        else:
            continue
        pickup = (
            _ArrivingTop(App, Part, setup, stock, fixtures, helpers, request)
            if axis == "z"
            else _Pickup(App, Part, setup, stock, fixtures, helpers, axis, request)
        )
        try:
            results[key] = pickup.run()
        except Exception as exc:
            pickup.reasons.append(f"native pickup geometry is unresolved: {exc}")
            if pickup.result["collisions"]:
                pickup.errors.append("known collision remains despite unresolved pickup geometry")
            results[key] = _finish(pickup.result)
    return results
