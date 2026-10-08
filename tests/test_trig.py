"""prechips.trig: one double on every platform, within fdlibm's error of the true value.

The reference is the decimal module at 400 significant digits (the pi recipe of its
documentation and Taylor series), enough to reduce any double argument exactly.
"""

import functools
import math
import random
from decimal import Decimal, localcontext

import pytest

from prechips import trig

DIGITS = 400


@functools.cache
def _pi():
    with localcontext() as ctx:
        ctx.prec = DIGITS + 2
        lasts, t, s, n, na, d, da = 0, Decimal(3), 3, 1, 0, 0, 24
        while s != lasts:
            lasts = s
            n, na = n + na, na + 8
            d, da = d + da, da + 32
            t = (t * n) / d
            s += t
    return s


def _sin_cos(x):
    """The true sine and cosine of the double ``x``."""
    with localcontext() as ctx:
        ctx.prec = DIGITS
        turn = 2 * _pi()
        x = Decimal(x)
        x -= turn * (x / turn).to_integral_value()
        sums = []
        for term, k in ((x, 1), (Decimal(1), 0)):
            total = term
            while abs(term) > abs(total) * Decimal("1e-80"):
                term = -term * x * x / ((k + 1) * (k + 2))
                total += term
                k += 2
            sums.append(total)
        return sums


def _ulps(value, true):
    return float(abs(Decimal(value) - true) / Decimal(math.ulp(float(true))))


_RANDOM = random.Random(20260101)
ANGLES = [
    *(_RANDOM.uniform(-10.0, 10.0) for _ in range(200)),
    *(math.radians(k / 11) for k in range(-4000, 4000, 37)),
    # Just either side of a multiple of pi/2, where the reduction cancels most bits.
    *(math.nextafter(n * math.pi / 2, toward) for n in range(-40, 41) for toward in (-1, 1)),
    # Either side of the integer reduction from 2**20 * pi/2, and far past it.
    1.6e6,
    1.7e6,
    3.0 * 2**20,
    1e22,
    -(2.0**1023) * 1.9,
    *(_RANDOM.uniform(-1.0, 1.0) * 10.0 ** _RANDOM.uniform(6.0, 300.0) for _ in range(40)),
    1e-9,
    -1e-30,
]


@pytest.mark.parametrize("name", ["sin", "cos"])
def test_sine_and_cosine_are_within_one_ulp_of_the_true_value(name):
    worst = max((_ulps(getattr(trig, name)(x), _sin_cos(x)[name == "cos"]), x) for x in ANGLES)
    assert worst[0] < 1.0, worst


def test_atan2_is_within_two_ulps_of_the_true_angle():
    rng = random.Random(20260101)
    points = [(rng.uniform(-50, 50), rng.uniform(-50, 50)) for _ in range(300)]
    points += [(rng.choice((-1, 1)) * 10.0 ** rng.uniform(-200, 200), rng.uniform(-1, 1))]
    points += [(y, 1.0) for y in (0.3, -0.3, 0.5, 1e30, -1e30, 2.0**70)]
    points += [(1.0, 1.0), (-1.0, -1.0), (1e-300, -1.0), (-1e-300, -1.0), (1.0, 1e-300)]
    worst = (0.0, None)
    for y, x in points:
        angle = trig.atan2(y, x)
        # tan(true - angle), which is (true - angle) to far below an ulp here.
        s, c = _sin_cos(angle)
        with localcontext() as ctx:
            ctx.prec = DIGITS
            assert -math.pi <= angle <= math.pi, (y, x, angle)
            assert math.copysign(1.0, angle) == math.copysign(1.0, y), (y, x, angle)
            assert Decimal(x) * c + Decimal(y) * s > 0, (y, x, angle)
            off = (Decimal(y) * c - Decimal(x) * s) / (Decimal(x) * c + Decimal(y) * s)
        worst = max(worst, (float(abs(off) / Decimal(math.ulp(angle))), (y, x)))
    assert worst[0] < 2.0, worst


SPECIAL = [0.0, -0.0, 1.0, -1.0, 5e-324, -5e-324, math.inf, -math.inf, math.nan]


@pytest.mark.parametrize("y", SPECIAL)
def test_atan2_settles_zeros_infinities_and_nans_as_python_does(y):
    for x in SPECIAL:
        ours, python = trig.atan2(y, x), math.atan2(y, x)
        if math.isnan(python):
            assert math.isnan(ours), (y, x)
        else:
            assert (ours, math.copysign(1.0, ours)) == (python, math.copysign(1.0, python)), (y, x)


def test_non_finite_and_signed_zero_arguments_read_as_math_reads_them():
    assert math.copysign(1.0, trig.sin(-0.0)) == -1.0 and trig.cos(-0.0) == 1.0
    assert math.isnan(trig.sin(math.nan)) and math.isnan(trig.cos(math.nan))
    for function in (trig.sin, trig.cos):
        with pytest.raises(ValueError):
            function(math.inf)


def test_no_result_comes_from_the_platform_libm(monkeypatch):
    expected = [(trig.sin(x), trig.cos(x), trig.atan2(x, 0.75)) for x in ANGLES]

    def refuse(*args):
        raise AssertionError("the platform libm was called")

    for name in ("sin", "cos", "tan", "atan", "atan2", "asin", "acos", "exp", "log"):
        monkeypatch.setattr(math, name, refuse)
    assert [(trig.sin(x), trig.cos(x), trig.atan2(x, 0.75)) for x in ANGLES] == expected
