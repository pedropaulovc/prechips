"""Narrow two-bound transport for explicitly represented hand-tapped holes.

The existing route's solid is an upper bound, never an exact thread.  The lower
bound removes the complete qualified envelope; provenance survives later cuts.
"""

import math

import FreeCAD
import Part

_UNKNOWN = "unknown"
_TOL = 1e-6
_VOLUME = 1e-6
_AREA = 1e-6


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _box(shape):
    box = shape.BoundBox
    return [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]


def _same_box(first, second):
    return all(abs(a - b) <= _TOL for a, b in zip(_box(first), _box(second), strict=True))


def _cut_plan(shape, plan):
    own, groups = plan
    result = shape.cut(own) if own is not None else shape
    for group in groups:
        for cutter in group:
            result = result.cut(cutter)
    if not result.isValid() or not result.Solids:
        raise ValueError("bounded lower material is empty or invalid after this cut")
    return result


class ThreadMaterialMixin:
    """Methods use the existing _Setup route, transform and operation machinery."""

    def _init_thread_material(self):
        bounds = self.state.get("material_bounds")
        self.lower_part = self._placed(bounds["lower"]) if bounds else self.part
        self.lower_out = self.lower_part
        self.lower_cuts = {}
        self.thread_regions = (
            [
                {"shape": self._placed(row["shape"]), "public": dict(row["public"])}
                for row in bounds.get("regions", [])
            ]
            if bounds
            else []
        )
        self.arriving_thread_regions = list(self.thread_regions)
        self.manual_threads = {}
        self.thread_overlap = {}
        # Cosmetic bore walls do not protect a fictitious exact helical surface.
        # This exclusion is only the explicitly qualified bounded region, never
        # the remainder of a threaded feature or another member's exterior.
        for row in self.thread_regions:
            self.protected = self.protected.cut(row["shape"])
            self.certain = self.certain.cut(row["shape"])

    def _thread_envelope(self, op):
        spec = op.get("manual_thread", {})
        if (
            op.get("do") != "hand_tap"
            or spec.get("model") != "bounded_thread_envelope_v1"
            or spec.get("status") != "ready"
            or spec.get("kind") != "threaded_hole"
            or spec.get("representation") != "thread_envelope"
        ):
            return None, (
                spec.get("reason")
                or "; ".join(spec.get("reasons", []))
                or "manual thread envelope is unresolved"
            )
        region = spec.get("region", {})
        at, axis, depth = region.get("at_mm"), region.get("axis"), region.get("depth_mm")
        diameter, major, tap = (
            spec.get(key) for key in ("diameter_mm", "major_diameter_mm", "tap_diameter_mm")
        )
        if (
            not all(_numeric(value) and value > 0 for value in (depth, diameter, major, tap))
            or diameter + _TOL < max(major, tap)
            or not isinstance(at, list)
            or len(at) != 3
            or not all(map(_numeric, at))
            or not isinstance(axis, list)
            or len(axis) != 3
            or not all(map(_numeric, axis))
        ):
            return (
                None,
                "manual thread needs a finite resolved span and conservative qualified diameter",
            )
        tip, lead, formed, flutes = (
            spec.get(key) for key in ("tip_depth_mm", "lead_mm", "formed_depth_mm", "flute_len_mm")
        )
        if (
            not all(_numeric(value) and value > 0 for value in (tip, formed, flutes))
            or not _numeric(lead)
            or lead < 0
        ):
            return None, "manual thread requires qualified lead, tip travel and cutting reach"
        if (
            tip + _TOL < depth + lead
            or flutes + _TOL < tip
            or abs(formed - (tip - lead)) > _TOL
            or formed + _TOL < depth
        ):
            return None, "tap lead and tip travel do not prove the complete threaded span"
        direction = FreeCAD.Vector(*axis)
        if abs(direction.Length - 1.0) > _TOL:
            return None, "manual thread axis is not a resolved unit direction"
        member = spec.get("workpiece_id")
        if getattr(self.owner, "workpieces", {}) and (
            member not in self.state.get("finished_names", ())
            or member not in self.owner.workpieces
        ):
            return None, "manual thread does not name a current registered workpiece"
        envelope = Part.makeCylinder(diameter / 2.0, depth, FreeCAD.Vector(*at), direction)
        feature = spec.get("feature")
        indices = (
            self.owner.workpiece_features.get(member, {}).get(feature)
            if member is not None
            else self.owner.features.get(feature)
        )
        if not isinstance(indices, list) or not indices:
            return None, "represented thread feature has no resolved native faces"
        origin = FreeCAD.Vector(*at)
        for index in indices:
            face = self.faces[index]
            surface = face.Surface
            if not isinstance(surface, Part.Cylinder):
                return None, "represented thread feature includes a noncylindrical face"
            if (
                abs(abs(surface.Axis.dot(direction)) - 1.0) > _TOL
                or (surface.Center - origin).cross(direction).Length > _TOL
                or abs(surface.Radius * 2.0 - major) > _TOL
            ):
                return None, "thread envelope does not match the registered basic-major cylinder"
            if face.cut(envelope).Area > max(_AREA, face.Area * 1e-6):
                return (
                    None,
                    "thread envelope does not contain the complete represented threaded span",
                )
        return envelope, None

    def _thread_identity(self, op):
        spec = op.get("manual_thread", {})
        member = spec.get("workpiece_id")
        return {
            "feature": spec.get("feature"),
            "workpiece_id": member,
            "registration": self.owner.workpieces.get(member) if member is not None else None,
            "partition_path": self._partition_path() or [],
            "producer": self._subject(op),
        }

    def _bounded_thread(self, op, stock, lower):
        envelope, reason = self._thread_envelope(op)
        spec = op.get("manual_thread", {})
        facts = {
            "model": "bounded_thread_envelope_v1",
            **self._thread_identity(op),
            "status": (
                "error"
                if reason and spec.get("status") == "error"
                else _UNKNOWN
                if reason
                else "pass"
            ),
            "reasons": [reason] if reason else [],
            "region": spec.get("region", _UNKNOWN),
            "diameter_mm": spec.get("diameter_mm", _UNKNOWN),
            **{
                key: spec.get(key, _UNKNOWN)
                for key in ("tip_depth_mm", "lead_mm", "formed_depth_mm", "flute_len_mm")
            },
            "material": "bounded",
            "evaluation": "represented_geometry",
            "helical_geometry": "unmodeled",
        }
        self.manual_threads[id(op)] = facts
        if reason is not None:
            return None, reason
        axis = FreeCAD.Vector(*spec["region"]["axis"])
        rotation = FreeCAD.Rotation(axis, FreeCAD.Vector(0, 0, 1)).toMatrix()
        aligned = stock.copy()
        aligned.transformShape(rotation)
        mouth = rotation.multVec(FreeCAD.Vector(*spec["region"]["at_mm"])).z
        if abs(aligned.BoundBox.ZMin - mouth) > _TOL:
            reason = (
                "feature mouth is not the actual stock entry plane along the tap axis; "
                "tip travel cannot be assigned to the threaded span"
            )
            facts.update(status=_UNKNOWN, reasons=[reason])
            return None, reason
        # No exact nominal-major cut is made: actual residual helical material
        # lies somewhere between incoming stock and this fully cleared region.
        after = lower.cut(envelope)
        if not after.isValid() or not after.Solids:
            facts.update(
                status=_UNKNOWN,
                reasons=["thread envelope leaves invalid or empty lower material"],
            )
            return None, facts["reasons"][0]
        self.thread_regions.append({"shape": envelope, "public": dict(facts)})
        self.protected = self.protected.cut(envelope)
        self.certain = self.certain.cut(envelope)
        self.guards.clear()
        self.certain_boxes = None
        return after, None

    def _advance_lower(self, op, before, after, plan):
        lower = self.lower_out
        if not self.thread_regions:
            self.lower_out = after
            self.lower_cuts[id(op)] = (before, after, None)
            return
        # Reuse the same accepted removal plan for both bounds.  Applying a cut
        # never clears the uncertainty ledger, including when it overlaps it.
        next_lower = _cut_plan(lower, plan)
        removed = before.cut(after)
        if any(removed.common(row["shape"]).Volume > _VOLUME for row in self.thread_regions):
            self.thread_overlap[id(op)] = (
                "later cut overlaps unmodeled helical material; exact cutting facts remain unknown"
            )
        self.lower_cuts[id(op)] = (lower, next_lower, None)
        self.lower_out = next_lower

    def _bound_saw_facts(self, facts):
        if not self.thread_regions:
            return
        upper = {}

        def uncertain(values, path=()):
            for key, value in list(values.items()):
                if key.endswith("_mm3") or key.startswith("stock_bbox"):
                    upper[".".join((*path, key))] = value
                    values[key] = _UNKNOWN
                    if "reasons" in values and isinstance(values["reasons"], dict):
                        values["reasons"][key] = (
                            "this value is measured only on the material upper bound"
                        )
                elif isinstance(value, dict):
                    uncertain(value, (*path, key))

        uncertain(facts)
        facts["upper_bound_facts"] = upper
        facts["material_reason"] = (
            "saw intersects a bounded-material route; exact material removal is unmodeled"
        )
        facts["saw_reason"] = facts["material_reason"]
        if isinstance(facts.get("saw"), dict):
            facts["saw"]["status"] = _UNKNOWN

    def _material_facts(self, upper, lower, regions):
        return {
            "model": "bounded_material_v1",
            "state": "bounded",
            "volume_mm3": {"lower": round(lower.Volume, 6), "upper": round(upper.Volume, 6)},
            "bbox_status": "common" if _same_box(upper, lower) else "different",
            "unmodeled_regions": [row["public"] for row in regions],
        }

    def _material_state(self):
        if not self.thread_regions or self.stock_out_reason is not None:
            return None
        lower = self.lower_out.copy()
        lower.transformShape(self.matrix.inverse())
        regions = []
        for row in self.thread_regions:
            shape = row["shape"].copy()
            shape.transformShape(self.matrix.inverse())
            regions.append({"shape": shape, "public": dict(row["public"])})
        return {"lower": lower, "regions": regions}

    def _bounded_named_output(self, ref, name, forward):
        if not self.thread_regions:
            return
        upper = self.named_outputs[ref][0]
        lower = self.lower_out.copy()
        lower.transformShape(self.matrix.inverse())
        lower.transformShape(forward)
        lower = lower.common(upper)
        members = self.output_states[ref].get("finished_names")
        regions = []
        for row in self.thread_regions:
            member = row["public"].get("workpiece_id")
            if member is not None and members is not None and member not in members:
                continue
            shape = row["shape"].copy()
            shape.transformShape(self.matrix.inverse())
            shape.transformShape(forward)
            regions.append({"shape": shape, "public": dict(row["public"])})
        self.output_states[ref]["material_bounds"] = (
            {"lower": lower, "regions": regions} if regions else None
        )
        record = self.output_records[name]
        # Conservation on one bound does not certify exact physical volumes.
        upper_facts = {key: record.pop(key) for key in list(record) if key.endswith("_mm3")}
        record["upper_bound_conservation"] = upper_facts
        record["material"] = self._material_facts(upper, lower, regions)
        if record["material"]["bbox_status"] != "common":
            record.pop("bbox_mm", None)

    def _bounded_fixture(self, facts):
        if not self.arriving_thread_regions:
            return
        reason = None
        if not self.fixture_ready or not self.fixture:
            reason = self.fixture_reason or "actual fixture-contact geometry is unresolved"
        if not _same_box(self.part, self.lower_part):
            reason = "fixture stock extents differ between material bounds"
        if any(
            row["shape"].distToShape(component["solid"])[0] <= _TOL
            for row in self.arriving_thread_regions
            for component in self.fixture
            if component.get("solid") is not None
        ):
            reason = "fixture contact or interference intersects unmodeled thread material"
        facts["stock_material"] = self._material_facts(
            self.part, self.lower_part, self.arriving_thread_regions
        )
        facts.pop("stock_volume_mm3", None)
        facts.pop("tooling_holes", None)
        if facts["stock_material"]["bbox_status"] != "common":
            facts.pop("stock_bbox_mm", None)
        if reason is not None:
            self.fixture_reason = reason
            facts["material_contact"] = {
                "model": "common_exterior_v1",
                "status": _UNKNOWN,
                "reasons": [reason],
            }
            for key in self._VISE_KEYS_FOR_BOUNDS:
                facts[key] = _UNKNOWN
                facts["reasons"][key] = reason
            facts.pop("fixture_clashes", None)
            self.fixture_ready = False
        else:
            facts["material_contact"] = {
                "model": "common_exterior_v1",
                "status": "pass",
                "outside_unmodeled_regions": "proved",
            }

    def _represented_envelope(self, op):
        manual = self.manual_threads.get(id(op))
        identity = self._thread_identity(op)
        facts = {
            "model": "represented_thread_envelope_v1",
            **identity,
            "status": _UNKNOWN,
            "reasons": [],
            "indices": [],
            "faces": [],
        }
        if manual is None or manual["status"] != "pass":
            facts["reasons"] = ["bounded thread material transition is unproven"]
            return facts
        spec = op["manual_thread"]
        envelope, reason = self._thread_envelope(op)
        indices = self._indices(op)
        if reason is not None or not isinstance(indices, list) or not indices:
            facts["reasons"] = [reason or "represented thread face identity is unresolved"]
            return facts
        member = spec.get("workpiece_id")
        feature_indices = (
            self.owner.workpiece_features.get(member, {}).get(spec["feature"])
            if member is not None
            else self.owner.features.get(spec["feature"])
        )
        if not isinstance(feature_indices, list) or not set(indices) <= set(feature_indices):
            facts["reasons"] = ["claimed faces are not owned by the represented threaded feature"]
            return facts
        axis = FreeCAD.Vector(*spec["region"]["axis"])
        at = FreeCAD.Vector(*spec["region"]["at_mm"])
        depth = spec["region"]["depth_mm"]
        for index in indices:
            face = self.faces[index]
            surface = face.Surface
            if not isinstance(surface, Part.Cylinder):
                facts["reasons"] = ["represented thread face is not cylindrical"]
                return facts
            direction = surface.Axis
            offset = surface.Center - at
            if abs(abs(direction.dot(axis)) - 1.0) > _TOL or offset.cross(axis).Length > _TOL:
                facts["reasons"] = [
                    "represented thread cylinder is not coaxial with resolved threaded span"
                ]
                return facts
            # A geometry-matched representation must use the parsed basic major,
            # not merely fit somewhere inside an arbitrarily oversized envelope.
            if abs(surface.Radius * 2.0 - spec["major_diameter_mm"]) > _TOL:
                facts["reasons"] = [
                    "represented thread cylinder does not match basic major diameter"
                ]
                return facts
            tolerance = max(_AREA, face.Area * 1e-6)
            if face.cut(envelope).Area > tolerance:
                facts["reasons"] = [
                    "represented thread face extends outside resolved threaded span"
                ]
                return facts
            span = [(vertex.Point - at).dot(axis) for vertex in face.Vertexes]
            if not span or min(span) < -_TOL or max(span) > depth + _TOL:
                facts["reasons"] = [
                    "represented thread face span is unresolved or outside threaded region"
                ]
                return facts
            reverse = self.owner.workpiece_mapping.get(member, self.owner.mapping)
            canonical = next((ref for ref, native in reverse.items() if native == index), None)
            facts["faces"].append(
                {
                    "index": index,
                    "canonical_ref": canonical,
                    "surface": "cylinder",
                    "coaxial": "proved",
                    "within_region": "proved",
                    "radius_mm": round(surface.Radius, 6),
                    "axis": list(spec["region"]["axis"]),
                    "span_mm": [round(min(span), 6), round(max(span), 6)],
                }
            )
        facts.update(status="pass", indices=sorted(indices))
        return facts
