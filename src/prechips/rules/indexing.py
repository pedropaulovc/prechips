"""Exact-first declared plate arithmetic and cumulative angular acceptance (PLAN §4.3)."""

from fractions import Fraction

from prechips.findings import Finding
from prechips.rules.resolution import UNKNOWN, number, record, resolve, uncertain

_CITE = "PLAN.md §4.3 indexing (360° per revolution; cumulative landings and cycle closure)"


def _citations(value, field):
    if isinstance(value, dict):
        value = value.get(field, UNKNOWN)
    if isinstance(value, str):
        return [value] if value != UNKNOWN else []
    return [item for item in value if item != UNKNOWN] if isinstance(value, list) else []


def _rational(value):
    return Fraction(str(value)) if number(value) else None


def _nearest(value):
    """An exact half-step chooses the lower signed count, independent of float rounding."""
    low = value.numerator // value.denominator
    return low if value - low <= low + 1 - value else low + 1


def _fixture(bundle, reference):
    root = reference.partition("/")[0] if isinstance(reference, str) else None
    for category in ("fixtures", "machines"):
        if root in record(bundle.inventory.get(category)):
            return resolve(bundle, category, reference), category
    if any(bundle.inventory.get(category) == UNKNOWN for category in ("fixtures", "machines")):
        return {"kind": UNKNOWN, "verify": True}, UNKNOWN
    return None, UNKNOWN


def _candidates(item, requested, source):
    candidates = []
    unresolved = []
    invalid = []

    def add(method, plate, circle, step):
        units = _nearest(requested / step)
        actual = units * step
        turns, spaces = divmod(abs(units), circle)
        candidates.append(
            {
                "method": method,
                "plate": plate,
                "circle": circle,
                "turns": turns,
                "spaces": spaces,
                "direction": "reverse" if units < 0 else "forward",
                "actual": actual,
                "error": actual - requested,
                "exact": actual == requested,
            }
        )

    # An omitted direct_index declares no direct option; an explicitly unknown
    # declaration cannot be skipped while certifying the exact-first selection.
    direct = item.get("direct_index", {})
    if direct == UNKNOWN:
        unresolved.append(f"{source}.direct_index")
    elif isinstance(direct, dict) and direct:
        unresolved.extend(
            f"{source}.direct_index.{field}"
            for field in ("positions", "step_deg")
            if direct.get(field) == UNKNOWN
        )
        positions = _rational(direct.get("positions"))
        step = _rational(direct.get("step_deg"))
        if positions is None and step is None:
            unresolved.append(f"{source}.direct_index")
        elif positions is not None and (positions <= 0 or positions.denominator != 1):
            invalid.append(f"{source}.direct_index.positions must be a positive integer")
        elif step is not None and step <= 0:
            invalid.append(f"{source}.direct_index.step_deg must be positive")
        else:
            # Either authored field determines the other by one full revolution.
            positions = positions if positions is not None else 360 / step
            step = step if step is not None else 360 / positions
            if positions.denominator != 1 or positions * step != 360:
                invalid.append(f"{source}.direct_index does not describe a 360° plate")
            else:
                add("direct", "direct", int(positions), step)

    plates = item.get("plate_holes", UNKNOWN)
    ratio = _rational(item.get("worm_ratio"))
    if not isinstance(plates, dict):
        unresolved.append(f"{source}.plate_holes")
    elif plates:
        if ratio is None:
            unresolved.append(f"{source}.worm_ratio")
        elif ratio <= 0:
            invalid.append(f"{source}.worm_ratio must be positive")
        for plate, holes in sorted(plates.items()):
            if not isinstance(holes, list):
                unresolved.append(f"{source}.plate_holes.{plate}")
                continue
            for hole in holes:
                circle = _rational(hole)
                if circle is None:
                    unresolved.append(f"{source}.plate_holes.{plate}")
                elif circle <= 0 or circle.denominator != 1:
                    invalid.append(f"{source}.plate_holes.{plate} must contain positive integers")
                elif ratio is not None and ratio > 0:
                    add("worm", plate, int(circle), 360 / (ratio * circle))
    return candidates, sorted(set(unresolved)), sorted(set(invalid))


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold", {})
        index = record(hold).get("index", UNKNOWN if hold == UNKNOWN else None)
        if index is None:
            findings.append(
                Finding(
                    "indexing",
                    setup["id"],
                    "not_applicable",
                    {},
                    [_CITE],
                    f"{setup['id']}: no angular indexing is declared.",
                )
            )
            continue
        declaration = record(index)
        reference = declaration.get("fixture", UNKNOWN)
        feature_name = declaration.get("feature", UNKNOWN)
        positions = declaration.get("positions", UNKNOWN)
        count_known = (
            isinstance(positions, int) and not isinstance(positions, bool) and positions >= 1
        )
        derived = "angle_deg" not in declaration and count_known and positions >= 2
        requested = Fraction(360, positions) if derived else _rational(declaration.get("angle_deg"))
        numbers = {
            "fixture": reference,
            "feature": feature_name,
            "positions": positions,
            "requested_angle_deg": float(requested) if requested is not None else UNKNOWN,
            "requested_angle_fraction": str(requested) if requested is not None else UNKNOWN,
            "requested_angle_source": "360/positions" if derived else "declared",
            "actual_angle_deg": UNKNOWN,
            "method": UNKNOWN,
            "plate": UNKNOWN,
            "circle": UNKNOWN,
            "turns": UNKNOWN,
            "spaces": UNKNOWN,
            "direction": UNKNOWN,
            "exact": UNKNOWN,
            "selection_complete": False,
            "verified": False,
            "tolerance_deg": UNKNOWN,
            "tolerance_source": UNKNOWN,
            "position_errors_deg": [],
            "max_position_error_deg": UNKNOWN,
            "closure": "not_applicable" if positions == 1 else UNKNOWN,
        }
        source = f"plan.setups.{setup['id']}.hold.index"
        cite = [_CITE, source]
        unresolved = []
        invalid = []
        landing_errors = []
        if requested is None:
            unresolved.append(f"{source}.angle_deg")
        if positions == UNKNOWN:
            unresolved.append(f"{source}.positions")
        elif not isinstance(positions, int) or isinstance(positions, bool) or positions < 1:
            invalid.append(f"{source}.positions must be a positive integer")

        feature = None
        selector_unknown = declaration.get("feature") == UNKNOWN
        if feature_name != UNKNOWN:
            feature = bundle.features["features"].get(feature_name)
            if feature is None:
                invalid.append(f"{source}.feature {feature_name!r} is not in the manifest")
        if selector_unknown:
            tolerance = None
            tolerance_source = UNKNOWN
            unresolved.append(f"{source}.feature")
            cite.append(f"{source}.feature")
        elif isinstance(feature, dict) and "angle_tol_deg" in feature:
            tolerance = _rational(feature["angle_tol_deg"])
            tolerance_source = f"features.features.{feature_name}.angle_tol_deg"
            cite.extend(_citations(feature.get("cite"), "angle_tol_deg"))
        else:
            general = record(bundle.features.get("general_tolerances"))
            tolerance = _rational(general.get("angular_deg"))
            tolerance_source = "features.general_tolerances.angular_deg"
            cite.extend(_citations(general.get("cite"), "angular_deg"))
        if tolerance_source != UNKNOWN:
            cite.append(tolerance_source)
        numbers["tolerance_source"] = tolerance_source
        if tolerance is None:
            if not selector_unknown:
                unresolved.append(tolerance_source)
        elif tolerance < 0:
            invalid.append(f"{tolerance_source} must be nonnegative")
        else:
            numbers["tolerance_deg"] = float(tolerance)

        fixture, category = _fixture(bundle, reference)
        if fixture is None:
            if reference == UNKNOWN:
                unresolved.append(f"{source}.fixture")
            else:
                invalid.append(f"{reference}: indexing fixture is not listed or present")
        else:
            fixture_source = f"inventory.{category}.{reference}"
            cite.append(fixture_source)
            cite.extend(_citations(fixture.get("cite"), "indexing"))
            inventory_source = fixture.get("source")
            if isinstance(inventory_source, dict):
                cite.extend(_citations(inventory_source.get("cite"), "indexing"))
                cite.extend(_citations(inventory_source.get("url"), "indexing"))
            else:
                cite.extend(_citations(inventory_source, "indexing"))
            kind = fixture.get("kind", UNKNOWN)
            if kind == UNKNOWN:
                unresolved.append(f"{fixture_source}.kind")
            elif kind != "dividing_head":
                invalid.append(f"{reference}: fixture is not a dividing head")
            numbers["verified"] = not uncertain(fixture)
            if not numbers["verified"]:
                unresolved.append(f"{fixture_source}.verify")
            if requested is not None:
                candidates, missing, errors = _candidates(fixture, requested, fixture_source)
                unresolved.extend(missing)
                invalid.extend(errors)
                numbers["selection_complete"] = not missing and not errors
                if candidates:
                    # Zero error is exact-first. Remaining ties prefer direct, then
                    # lexical plate identity and ascending circle, never input order.
                    selected = min(
                        candidates,
                        key=lambda c: (
                            abs(c["error"]),
                            c["method"] != "direct",
                            c["plate"],
                            c["circle"],
                        ),
                    )
                    numbers.update(
                        {
                            key: value
                            for key, value in selected.items()
                            if key not in {"actual", "error"}
                        }
                    )
                    actual = selected["actual"]
                    numbers["actual_angle_deg"] = float(actual)
                    if count_known:
                        landing_errors = [
                            selected["error"] * position for position in range(1, positions + 1)
                        ]
                        numbers["position_errors_deg"] = [float(error) for error in landing_errors]
                        numbers["max_position_error_deg"] = float(max(map(abs, landing_errors)))
                        if positions >= 2:
                            total = positions * actual
                            revolutions = _nearest(total / 360)
                            closure_error = total - 360 * revolutions
                            numbers["closure"] = {
                                "revolutions": revolutions,
                                "target_angle_deg": 360 * revolutions,
                                "actual_angle_deg": float(total),
                                "error_deg": float(closure_error),
                                "within_tolerance": abs(closure_error) <= tolerance
                                if tolerance is not None and tolerance >= 0
                                else UNKNOWN,
                            }
                else:
                    unresolved.append(f"{fixture_source}: no usable indexing circles")

        failed = []
        if count_known and tolerance is not None and tolerance >= 0:
            for position, error in enumerate(landing_errors, start=1):
                if abs(error) > tolerance:
                    failed.append(f"landing {position}")
            closure = numbers["closure"]
            if isinstance(closure, dict) and closure["within_tolerance"] is False:
                failed.append("cycle closure")
        numbers["unresolved"] = sorted(set(unresolved))
        numbers["invalid"] = sorted(set(invalid))
        numbers["failed"] = failed
        status = "error" if invalid else "unknown" if unresolved else "error" if failed else "pass"
        if invalid:
            message = "; ".join(numbers["invalid"]) + "."
        elif unresolved:
            message = "Indexing remains tentative: " + ", ".join(numbers["unresolved"]) + "."
        elif failed:
            message = "Indexing exceeds the angular tolerance at " + ", ".join(failed) + "."
        else:
            message = "Indexing landings fit the angular tolerance; " + (
                "one angular setting has no cycle closure."
                if positions == 1
                else "the repeated pattern closes within tolerance."
            )
        findings.append(
            Finding(
                "indexing",
                setup["id"],
                status,
                numbers,
                list(dict.fromkeys(cite)),
                f"{setup['id']}: {message}",
            )
        )
    return findings
