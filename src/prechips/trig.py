"""Sine, cosine and arc tangent that return the same double on every platform.

``math.sin``, ``math.cos`` and ``math.atan2`` call the platform's C library, and the C
libraries of Windows and Linux round some results to neighbouring doubles: a table built
from them, and the report that prints it, then differs in its last bits between platforms.
These functions are fdlibm's algorithms (FreeBSD msun ``k_sin.c``, ``k_cos.c``,
``e_rem_pio2.c``, ``s_atan.c`` and ``e_atan2.c``, whose coefficients and hexadecimal words
they quote) in Python. They use only IEEE 754 double arithmetic, which rounds the same way
on every platform Python runs on, and exact integer arithmetic, so each result is one
double everywhere. Their error is fdlibm's: under one unit in the last place for sin and
cos, under two for atan2. Arguments beyond 2**20 * pi/2 are reduced exactly on integers
instead of by fdlibm's Payne-Hanek tables."""

from __future__ import annotations

import functools
import math

# k_sin.c
_S1 = -1.66666666666666324348e-01  # 0xBFC55555, 0x55555549
_S2 = 8.33333333332248946124e-03  # 0x3F811111, 0x1110F8A6
_S3 = -1.98412698298579493134e-04  # 0xBF2A01A0, 0x19C161D5
_S4 = 2.75573137070700676789e-06  # 0x3EC71DE3, 0x57B1FE7D
_S5 = -2.50507602534068634195e-08  # 0xBE5AE5E6, 0x8A2B9CEB
_S6 = 1.58969099521155010221e-10  # 0x3DE5D93A, 0x5ACFD57C
# k_cos.c
_C1 = 4.16666666666666019037e-02  # 0x3FA55555, 0x5555554C
_C2 = -1.38888888888741095749e-03  # 0xBF56C16C, 0x16C15177
_C3 = 2.48015872894767294178e-05  # 0x3EFA01A0, 0x19CB1590
_C4 = -2.75573143513906633035e-07  # 0xBE927E4F, 0x809C52AD
_C5 = 2.08757232129817482790e-09  # 0x3E21EE9E, 0xBDB4B1C4
_C6 = -1.13596475577881948265e-11  # 0xBDA8FAE9, 0xBE8838D4
# e_rem_pio2.c: pi/2 as 33-bit pieces (_PIO2_n) and their tails (_PIO2_nT)
_INVPIO2 = 6.36619772367581382433e-01  # 0x3FE45F30, 0x6DC9C883
_PIO2_1 = 1.57079632673412561417e00  # 0x3FF921FB, 0x54400000
_PIO2_1T = 6.07710050650619224932e-11  # 0x3DD0B461, 0x1A626331
_PIO2_2 = 6.07710050630396597660e-11  # 0x3DD0B461, 0x1A600000
_PIO2_2T = 2.02226624879595063154e-21  # 0x3BA3198A, 0x2E037073
_PIO2_3 = 2.02226624871116645580e-21  # 0x3BA3198A, 0x2E000000
_PIO2_3T = 8.47842766036889956997e-32  # 0x397B839A, 0x252049C1
# s_atan.c: atan(0.5), atan(1), atan(1.5) and atan(inf), each as a double and its tail
_ATANHI = (
    4.63647609000806093515e-01,  # 0x3FDDAC67, 0x0561BB4F
    7.85398163397448278999e-01,  # 0x3FE921FB, 0x54442D18
    9.82793723247329054082e-01,  # 0x3FEF730B, 0xD281F69B
    1.57079632679489655800e00,  # 0x3FF921FB, 0x54442D18
)
_ATANLO = (
    2.26987774529616870924e-17,  # 0x3C7A2B7F, 0x222F65E2
    3.06161699786838301793e-17,  # 0x3C81A626, 0x33145C07
    1.39033110312309984516e-17,  # 0x3C700788, 0x7AF0CBBD
    6.12323399573676603587e-17,  # 0x3C91A626, 0x33145C07
)
_AT0 = 3.33333333333329318027e-01  # 0x3FD55555, 0x5555550D
_AT1 = -1.99999999998764832476e-01  # 0xBFC99999, 0x9998EBC4
_AT2 = 1.42857142725034663711e-01  # 0x3FC24924, 0x920083FF
_AT3 = -1.11111104054623557880e-01  # 0xBFBC71C6, 0xFE231671
_AT4 = 9.09088713343650656196e-02  # 0x3FB745CD, 0xC54C206E
_AT5 = -7.69187620504482999495e-02  # 0xBFB3B0F2, 0xAF749A6D
_AT6 = 6.66107313738753120669e-02  # 0x3FB10D66, 0xA0D03D51
_AT7 = -5.83357013379057348645e-02  # 0xBFADDE2D, 0x52DEFD9A
_AT8 = 4.97687799461593236017e-02  # 0x3FA97B4B, 0x24760DEB
_AT9 = -3.65315727442169155270e-02  # 0xBFA2B444, 0x2C6A6C2F
_AT10 = 1.62858201153657823623e-02  # 0x3F90AD3A, 0xE322DA11
# e_atan2.c
_PI = 3.1415926535897931160e00  # 0x400921FB, 0x54442D18
_PI_LO = 1.2246467991473531772e-16  # 0x3CA1A626, 0x33145C07
_PI_O_2 = 1.5707963267948965580e00  # 0x3FF921FB, 0x54442D18

_PIO4_BOUND = float.fromhex("0x1.921fcp-1")  # fdlibm's |x| ~<= pi/4: high word <= 0x3fe921fb
_MEDIUM_BOUND = float.fromhex("0x1.921fcp+20")  # its medium reduction: high word <= 0x413921fb
_LARGE_BITS = 1280  # binary places of pi/2 for an argument up to 2**1024


def sin(x: float) -> float:
    if abs(x) < _PIO4_BOUND:
        return x if abs(x) < 2.0**-26 else _sin_kernel(x, 0.0, False)
    n, y0, y1 = _rem_pio2(x)
    if n == 0:
        return _sin_kernel(y0, y1, True)
    if n == 1:
        return _cos_kernel(y0, y1)
    if n == 2:
        return -_sin_kernel(y0, y1, True)
    return -_cos_kernel(y0, y1)


def cos(x: float) -> float:
    if abs(x) < _PIO4_BOUND:
        return _cos_kernel(x, 0.0)
    n, y0, y1 = _rem_pio2(x)
    if n == 0:
        return _cos_kernel(y0, y1)
    if n == 1:
        return -_sin_kernel(y0, y1, True)
    if n == 2:
        return -_cos_kernel(y0, y1)
    return _sin_kernel(y0, y1, True)


def atan2(y: float, x: float) -> float:
    # Non-finite and zero cases as CPython's math.atan2 settles them before it calls libm.
    if math.isnan(x) or math.isnan(y):
        return math.nan
    if math.isinf(y):
        if math.isinf(x):
            return math.copysign(0.25 * _PI if math.copysign(1.0, x) > 0 else 0.75 * _PI, y)
        return math.copysign(0.5 * _PI, y)
    if math.isinf(x) or y == 0:
        return math.copysign(0.0 if math.copysign(1.0, x) > 0 else _PI, y)
    if x == 0:
        return math.copysign(_PI_O_2, y)
    if x == 1.0:
        return _atan(y)
    k = math.frexp(y)[1] - math.frexp(x)[1]
    if k > 60:  # |y/x| > 2**60
        return math.copysign(_PI_O_2 + 0.5 * _PI_LO, y)
    z = 0.0 if x < 0 and k < -60 else _atan(abs(y / x))
    if x > 0:
        return z if y > 0 else -z
    return _PI - (z - _PI_LO) if y > 0 else (z - _PI_LO) - _PI


def _sin_kernel(x, y, tail):
    """sin(x + y) for |x + y| ~<= pi/4, ``y`` the tail of ``x`` when ``tail``."""
    z = x * x
    w = z * z
    r = _S2 + z * (_S3 + z * _S4) + z * w * (_S5 + z * _S6)
    v = z * x
    if not tail:
        return x + v * (_S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * _S1)


def _cos_kernel(x, y):
    """cos(x + y) for |x + y| ~<= pi/4, ``y`` the tail of ``x``."""
    z = x * x
    w = z * z
    r = z * (_C1 + z * (_C2 + z * _C3)) + w * w * (_C4 + z * (_C5 + z * _C6))
    hz = 0.5 * z
    w = 1.0 - hz
    return w + (((1.0 - w) - hz) + (z * r - x * y))


def _rem_pio2(x):
    """(n mod 4, y0, y1) with x - n*pi/2 = y0 + y1 and |y0 + y1| ~<= pi/4."""
    if math.isnan(x):
        return 0, x, 0.0
    if math.isinf(x):
        raise ValueError("math domain error")
    if abs(x) >= _MEDIUM_BOUND:
        return _rem_pio2_large(x)
    fn = float(round(x * _INVPIO2))
    r = x - fn * _PIO2_1
    w = fn * _PIO2_1T  # first round, good to 85 bits
    y0 = r - w
    exponent = math.frexp(x)[1]
    if exponent - math.frexp(y0)[1] > 16:  # second round, good to 118 bits
        t = r
        w = fn * _PIO2_2
        r = t - w
        w = fn * _PIO2_2T - ((t - r) - w)
        y0 = r - w
        if exponent - math.frexp(y0)[1] > 49:  # third round, good to 151 bits
            t = r
            w = fn * _PIO2_3
            r = t - w
            w = fn * _PIO2_3T - ((t - r) - w)
            y0 = r - w
    return int(fn) & 3, y0, (r - y0) - w


def _rem_pio2_large(x):
    """:func:`_rem_pio2` on integers: from 2**20, ``x`` is a whole number of 2**-32."""
    numerator, denominator = x.as_integer_ratio()
    scaled = (numerator << _LARGE_BITS) // denominator
    half_pi = _half_pi()
    n = (2 * scaled + half_pi) // (2 * half_pi)
    rest = scaled - n * half_pi
    y0 = rest / (1 << _LARGE_BITS)  # Python rounds an integer quotient correctly
    head, power = y0.as_integer_ratio()
    return n & 3, y0, (rest - (head << _LARGE_BITS) // power) / (1 << _LARGE_BITS)


@functools.cache
def _half_pi():
    """pi/2 * 2**_LARGE_BITS to within one, by Machin's formula on integers, 32 bits spare."""
    unit = 1 << (_LARGE_BITS + 32)

    def arccot(n):
        term = total = unit // n
        k, sign = 1, 1
        while term:
            term //= n * n
            k += 2
            sign = -sign
            total += sign * (term // k)
        return total

    return (16 * arccot(5) - 4 * arccot(239)) >> 33


def _atan(x):
    """s_atan.c: atan(x) from atan of 0, 0.5, 1, 1.5 or infinity and a polynomial."""
    ax = abs(x)
    if ax >= 2.0**66:
        return math.copysign(_ATANHI[3] + _ATANLO[3], x)
    if ax < 0.4375:
        if ax < 2.0**-27:
            return x
        i, t = -1, x
    elif ax < 0.6875:
        i, t = 0, (2.0 * ax - 1.0) / (2.0 + ax)
    elif ax < 1.1875:
        i, t = 1, (ax - 1.0) / (ax + 1.0)
    elif ax < 2.4375:
        i, t = 2, (ax - 1.5) / (1.0 + 1.5 * ax)
    else:
        i, t = 3, -1.0 / ax
    z = t * t
    w = z * z
    s1 = z * (_AT0 + w * (_AT2 + w * (_AT4 + w * (_AT6 + w * (_AT8 + w * _AT10)))))
    s2 = w * (_AT1 + w * (_AT3 + w * (_AT5 + w * (_AT7 + w * _AT9))))
    if i < 0:
        return t - t * (s1 + s2)
    z = _ATANHI[i] - ((t * (s1 + s2) - _ATANLO[i]) - t)
    return -z if x < 0 else z
