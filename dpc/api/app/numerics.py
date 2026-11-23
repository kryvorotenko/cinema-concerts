"""Pure C01 quadrature kernels; importable by experiments without API dependencies."""

import math

A = 120.0  # arrivals / minute^2
TAU = 30.0  # minutes
T = 90.0  # minutes from opening


def rate(t: float) -> float:
    return A * t * math.exp(-t / TAU)


def antiderivative(t: float) -> float:
    return -A * TAU * (t + TAU) * math.exp(-t / TAU)


def reference(a: float, b: float) -> float:
    return antiderivative(b) - antiderivative(a)


def split(n: int, parts: int) -> list[tuple[int, int]]:
    """Integer boundaries cover [0,n) exactly once, even when n % parts != 0."""
    return [(n * i // parts, n * (i + 1) // parts) for i in range(parts)]


def partial(a: float, width: float, start: int, end: int, method: str) -> float:
    add = math.fsum
    if method == "midpoint":
        return width * add(rate(a + (i + 0.5) * width) for i in range(start, end))
    return width / 6 * add(
        rate(a + i * width) + 4 * rate(a + (i + 0.5) * width) + rate(a + (i + 1) * width)
        for i in range(start, end)
    )
