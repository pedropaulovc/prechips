"""Conservative nominal thread designation comparisons, not fit or strength checks.

Only explicit size/pitch identities are read. Tool names, prose standards, unspecified
coarse pitches and member spelling never supply missing thread facts.
"""

import math
import re
from fractions import Fraction

_INCH = re.compile(r"(#\d+|\d+(?:/\d+)?|\d*\.\d+)-(\d+)(UNC|UNF|UNEF|UNS)?")
_METRIC = re.compile(r"M(\d+(?:\.\d+)?)[X×](\d+(?:\.\d+)?)")
# ANSI/ASME B1.1 basic numbered diameters: D = 0.060 + 0.013*N inches.
# Supported sizes are the standard UNC/UNF table entries, not every possible gauge.
# https://www.engineeringtoolbox.com/unified-screw-threads-unc-unf-d_1809.html
_NUMBERED_SIZES = frozenset({0, 1, 2, 3, 4, 5, 6, 8, 10, 12})


def _identity(value):
    if not isinstance(value, str) or not value.strip() or value == "unknown":
        return None
    text = re.sub(r"\s+", "", value).upper().replace("−", "-")
    metric = _METRIC.fullmatch(text)
    if metric:
        try:
            diameter, pitch = map(Fraction, metric.groups())
        except (ValueError, ZeroDivisionError):
            return None
        return ("metric", diameter, pitch, None) if diameter > 0 and pitch > 0 else None
    inch = _INCH.fullmatch(text)
    if inch is None:
        return None
    size, tpi, series = inch.groups()
    try:
        if size.startswith("#"):
            digits = size[1:]
            gauge = int(digits)
            if digits != str(gauge) or gauge not in _NUMBERED_SIZES:
                return None
            diameter = Fraction(60 + 13 * gauge, 1000)
        else:
            diameter = Fraction(size)
        pitch = int(tpi)
    except (ValueError, ZeroDivisionError):
        return None
    if diameter <= 0 or pitch <= 0:
        return None
    return "inch", diameter, pitch, series


def basic_major_mm(value):
    """Basic major diameter in millimetres, or None for an unsupported designation.

    This is nominal thread identity, not a measured cutting diameter or thread-fit
    limit. Keep the parser's inch-valued private tuple inside this module.
    """
    identity = _identity(value)
    if identity is None:
        return None
    units, diameter, _, _ = identity
    try:
        diameter_mm = float(diameter * Fraction(127, 5) if units == "inch" else diameter)
    except OverflowError:
        return None
    return diameter_mm if math.isfinite(diameter_mm) and diameter_mm > 0 else None


def match(required, actual):
    """True/False for known nominal compatibility, None for unsupported or unknown facts.

    An omitted Unified series does not invent a series: size and TPI still compare, while
    two explicitly different series contradict. Classes and hand are separate facts.
    """
    left, right = _identity(required), _identity(actual)
    if left is None or right is None:
        return None
    if left[:3] != right[:3]:
        return False
    return not (left[3] is not None and right[3] is not None and left[3] != right[3])


def selected_class_status(feature, tool, *, acceptance="formal"):
    """Same-role selected tool class, including a narrowly explicit non-adoption.

    ``not_adopted`` is not a formal-class match. Both fields must be absent, the
    feature's complete requirement list must not require a class, and the caller
    must establish a known explicit ``manual_functional`` acceptance separately.
    """
    requirements = feature.get("requirements")
    if (
        "thread_class" not in feature
        and "thread_class" not in tool
        and isinstance(requirements, list)
        and all(isinstance(requirement, str) for requirement in requirements)
        and not {"thread_class", "unknown"}.intersection(requirements)
        and acceptance == "manual_functional"
    ):
        return "not_adopted"
    required, selected = feature.get("thread_class"), tool.get("thread_class")
    if (
        not isinstance(required, str)
        or not isinstance(selected, str)
        or required.strip().casefold() in {"", "unknown"}
        or selected.strip().casefold() in {"", "unknown"}
    ):
        return "unknown"
    return "match" if required.strip().casefold() == selected.strip().casefold() else "mismatch"


def mating_classes(socket, spigot):
    """Compare Unified internal B/external A classes without pretending class is fit proof.

    Metric tolerance positions and nonstandard designations need a dedicated standards
    model; they remain unknown rather than becoming an exact-string apparent pass.
    """
    if not isinstance(socket, str) or not isinstance(spigot, str):
        return None
    inner = re.fullmatch(r"([123])([AB])", socket.strip().upper())
    outer = re.fullmatch(r"([123])([AB])", spigot.strip().upper())
    if inner is None or outer is None:
        return None
    # A/B names the internal/external role. Different tolerance grades alone do not
    # establish incompatibility; do not invent a grade-equality fit requirement.
    return inner[2] == "B" and outer[2] == "A"
