"""Numerical analysis for math-service: roots, turning points, integrals,
derivatives, tidy graph data and statistics.

Every function here works on NumPy arrays, so a whole graph is computed in a
few vector operations instead of a Python loop per point.
"""
import math

import numpy as np

GOLDEN = (math.sqrt(5) - 1) / 2


# ---------------------------------------------------------------------------
# JSON-friendly numbers
# ---------------------------------------------------------------------------

def to_list(values, digits=6):
    """NumPy array -> list of rounded floats, with None where there's no real value."""
    flat = np.asarray(values, dtype=float).ravel().tolist()
    return [float(f"{v:.{digits}g}") if math.isfinite(v) else None for v in flat]


def to_grid(values, digits=6):
    """2D NumPy array -> list of rows."""
    return [to_list(row, digits) for row in np.asarray(values, dtype=float)]


def clean(value, digits=12):
    """Drop floating-point noise: 0.1 + 0.2 -> 0.3."""
    if value is None or not math.isfinite(value):
        return None
    return float(f"{value:.{digits}g}") + 0.0   # + 0.0 turns -0.0 into 0.0


# ---------------------------------------------------------------------------
# Roots and turning points
# ---------------------------------------------------------------------------

def _golden_section(f, lo, hi, maximize, iterations=80):
    """Vectorised golden-section search on many brackets at once."""
    sign = -1.0 if maximize else 1.0
    lo = np.asarray(lo, dtype=float).copy()
    hi = np.asarray(hi, dtype=float).copy()
    for _ in range(iterations):
        c = hi - GOLDEN * (hi - lo)
        d = lo + GOLDEN * (hi - lo)
        fc = sign * f(c)
        fd = sign * f(d)
        left = fc < fd
        hi = np.where(left, d, hi)
        lo = np.where(left, lo, c)
    x = (lo + hi) / 2
    return x, f(x)


def _snap_zero(value, scale):
    """-1e-15 -> 0: values that are zero apart from rounding noise."""
    return 0.0 if abs(value) < 1e-12 * max(1.0, scale) else value


def _round_to_scale(value, scale, relative=1e-7):
    """Keep only the digits we can trust: at a turning point the curve is flat, so x is
    accurate to about 1e-7 of the plotted range. 2.98e-08 on a range of 8 becomes 0."""
    step = 10.0 ** math.floor(math.log10(max(scale, 1e-300) * relative))
    return round(value / step) * step


def _dedupe(points, limit):
    points = sorted(p for p in points if math.isfinite(p))
    unique = []
    for p in points:
        if not unique or abs(p - unique[-1]) > 1e-7 * max(1.0, abs(p)):
            unique.append(p)
    return unique[:limit], len(unique) > limit


def find_roots(f, a, b, samples=4000, limit=25):
    """Zeros of f in [a, b]. Sign changes at poles (like tan at 90°) are ignored."""
    xs = np.linspace(a, b, samples)
    ys = f(xs)
    finite = np.isfinite(ys)
    roots = list(xs[finite & (ys == 0)])
    signs = np.sign(ys)

    # 1. sign changes, narrowed down by bisection (all brackets at once)
    change = np.where(finite[:-1] & finite[1:] & (signs[:-1] * signs[1:] < 0))[0]
    if change.size:
        lo, hi = xs[change].copy(), xs[change + 1].copy()
        f_lo = ys[change].copy()
        for _ in range(64):
            mid = (lo + hi) / 2
            f_mid = f(mid)
            same = np.sign(f_mid) == np.sign(f_lo)
            lo = np.where(same, mid, lo)
            f_lo = np.where(same, f_mid, f_lo)
            hi = np.where(same, hi, mid)
        mid = (lo + hi) / 2
        f_mid = f(mid)
        genuine = np.isfinite(f_mid) & (np.abs(f_mid) < 1e-6)
        roots.extend(mid[genuine])

    # 2. roots that touch zero without crossing it, like x^2 at 0
    magnitude = np.abs(ys)
    i = np.arange(1, samples - 1)
    touching = i[finite[i] & finite[i - 1] & finite[i + 1]
                 & (magnitude[i] <= magnitude[i - 1]) & (magnitude[i] < magnitude[i + 1])
                 & (signs[i - 1] == signs[i + 1]) & (ys[i] != 0)]
    if touching.size:
        touching = touching[np.argsort(magnitude[touching])[:200]]
        x_min, f_at = _golden_section(lambda v: np.abs(f(v)), xs[touching - 1], xs[touching + 1], maximize=False)
        roots.extend(x_min[np.isfinite(f_at) & (f_at < 1e-9)])

    scale = max(abs(a), abs(b), b - a)
    return _dedupe([_snap_zero(float(r), scale) for r in roots], limit)


def find_extrema(f, xs, ys, limit=12):
    """Local maxima and minima of f on the sampled range, refined to high accuracy."""
    finite = np.isfinite(ys)
    i = np.arange(1, len(xs) - 1)
    ok = finite[i] & finite[i - 1] & finite[i + 1]
    peaks = i[ok & (ys[i] > ys[i - 1]) & (ys[i] >= ys[i + 1])]
    dips = i[ok & (ys[i] < ys[i - 1]) & (ys[i] <= ys[i + 1])]
    found = []
    x_scale = float(abs(xs[-1] - xs[0]))
    y_scale = float(np.max(np.abs(ys[finite]))) if finite.any() else 1.0
    for indices, kind in ((peaks, "max"), (dips, "min")):
        if indices.size:
            x_best, y_best = _golden_section(f, xs[indices - 1], xs[indices + 1], maximize=(kind == "max"))
            for x, y in zip(x_best.tolist(), y_best.tolist()):
                if math.isfinite(y):
                    found.append({"x": clean(_round_to_scale(x, x_scale), 10),
                                  "y": clean(_snap_zero(y, y_scale), 10), "kind": kind})
    found.sort(key=lambda point: point["x"])
    return found[:limit], len(found) > limit


# ---------------------------------------------------------------------------
# Calculus
# ---------------------------------------------------------------------------

def numeric_derivative(f, x):
    """Central difference with Richardson extrapolation. Works on arrays too."""
    x = np.asarray(x, dtype=float)
    h = 1e-3 * np.maximum(1.0, np.abs(x))
    coarse = (f(x + h) - f(x - h)) / (2 * h)
    fine = (f(x + h / 2) - f(x - h / 2)) / h
    return (4 * fine - coarse) / 3


def _simpson(values, h):
    return float(values[0] + values[-1] + 4 * values[1:-1:2].sum() + 2 * values[2:-1:2].sum()) * h / 3


def integrate(f, a, b, breaks=(), intervals=2000):
    """Definite integral by Simpson's rule. Returns (integral, area) or None if f isn't defined on [a, b].

    breaks: the roots of f between a and b. The area (the integral of |f|) is added up piece by piece
    between them: |f| has a sharp corner at each root, which Simpson's rule handles badly.
    """
    if a == b:
        return 0.0, 0.0
    sign = 1.0
    if a > b:
        a, b, sign = b, a, -1.0
    ys = f(np.linspace(a, b, intervals + 1))
    if not np.all(np.isfinite(ys)):
        return None
    integral = _simpson(ys, (b - a) / intervals)

    edges = [a] + sorted(r for r in breaks if a < r < b) + [b]
    area = 0.0
    for low, high in zip(edges, edges[1:]):
        n = max(20, round(intervals * (high - low) / (b - a)))
        n += n % 2                       # Simpson's rule needs an even number of steps
        piece = f(np.linspace(low, high, n + 1))
        if not np.all(np.isfinite(piece)):
            return None
        area += abs(_simpson(piece, (high - low) / n))
    return _snap_zero(sign * integral, area), area


# ---------------------------------------------------------------------------
# Graph data
# ---------------------------------------------------------------------------

def tidy_series(f, xs, ys):
    """Break the line at poles (so tan(x) has no vertical lines) and suggest a y-range."""
    y = np.where(np.isfinite(ys), ys, np.nan)
    finite = np.isfinite(y)
    if finite.sum() < 3:
        return y, None
    low, high = np.percentile(y[finite], [2, 98])
    span = high - low if high > low else max(1.0, abs(high))

    jumps = np.where(np.abs(np.diff(y)) > 3 * span)[0]
    if jumps.size:
        middle = f((xs[jumps] + xs[jumps + 1]) / 2)
        lower = np.minimum(y[jumps], y[jumps + 1])
        upper = np.maximum(y[jumps], y[jumps + 1])
        tolerance = 1e-9 * np.maximum(1.0, np.abs(upper))
        pole = ~np.isfinite(middle) | (middle < lower - tolerance) | (middle > upper + tolerance)
        for index in jumps[pole]:
            target = index if abs(y[index]) > abs(y[index + 1]) else index + 1
            y[target] = np.nan

    finite = np.isfinite(y)
    full_low, full_high = float(np.min(y[finite])), float(np.max(y[finite]))
    if full_high - full_low > 6 * span:   # a few huge values would squash the rest of the graph
        return y, [float(low - 0.5 * span), float(high + 0.5 * span)]
    return y, None


def clip_surface(z):
    """Hide extreme values (poles) so the rest of a 3D surface stays readable."""
    finite = np.isfinite(z)
    if finite.sum() < 4:
        return z, False
    low, high = np.percentile(z[finite], [1, 99])
    span = high - low
    full = float(np.max(z[finite]) - np.min(z[finite]))
    if span > 0 and full > 10 * span:
        keep = (z >= low - span) & (z <= high + span)
        return np.where(keep, z, np.nan), True
    return z, False


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def describe(values, sample=True):
    v = np.asarray(values, dtype=float)
    n = v.size
    mean = float(v.mean())
    unique, counts = np.unique(v, return_counts=True)
    top = counts.max()
    modes = unique[counts == top].tolist() if top > 1 else []
    q1, median, q3 = (float(q) for q in np.percentile(v, [25, 50, 75]))
    iqr = q3 - q1
    lower_fence, upper_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = v[(v < lower_fence) | (v > upper_fence)]
    ddof = 1 if sample and n > 1 else 0
    variance = float(v.var(ddof=ddof))
    std = math.sqrt(variance)
    m2 = float(np.mean((v - mean) ** 2))
    m3 = float(np.mean((v - mean) ** 3))

    bins = min(30, max(1, round(math.sqrt(n))))   # square-root rule, at most 30 bars
    counts_h, edges = np.histogram(v, bins=bins)
    return {
        "count": n,
        "sum": clean(float(v.sum())),
        "mean": clean(mean),
        "median": clean(median),
        "modes": [clean(m) for m in modes[:6]],
        "more_modes": len(modes) > 6,
        "mode_count": int(top),
        "min": clean(float(v.min())),
        "max": clean(float(v.max())),
        "range": clean(float(v.max() - v.min())),
        "q1": clean(q1),
        "q3": clean(q3),
        "iqr": clean(iqr),
        "lower_fence": clean(lower_fence),
        "upper_fence": clean(upper_fence),
        "outliers": [clean(o) for o in outliers[:20].tolist()],
        "outlier_count": int(outliers.size),
        "variance": clean(variance),
        "std": clean(std),
        "cv": clean(std / abs(mean) * 100) if mean != 0 else None,
        "standard_error": clean(std / math.sqrt(n)),
        "skewness": clean(m3 / m2 ** 1.5) if m2 > 0 else None,
        "used_sample_formula": ddof == 1,
        "histogram": {"edges": to_list(edges, 8), "counts": counts_h.tolist()},
    }


def regression(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x_mean, y_mean = x.mean(), y.mean()
    sxx = float(np.sum((x - x_mean) ** 2))
    sxy = float(np.sum((x - x_mean) * (y - y_mean)))
    syy = float(np.sum((y - y_mean) ** 2))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    r = sxy / math.sqrt(sxx * syy) if syy > 0 else None
    if r is None:
        strength = "No correlation (every y value is the same)"
    elif abs(r) < 0.3:
        strength = "Very weak or no correlation"
    else:
        size = abs(r)
        word = "Very strong" if size >= 0.9 else "Strong" if size >= 0.7 else "Moderate" if size >= 0.5 else "Weak"
        strength = f"{word} {'positive' if r > 0 else 'negative'} correlation"
    x_line = np.array([x.min(), x.max()])
    return {
        "slope": clean(slope),
        "intercept": clean(intercept),
        "r": clean(r) if r is not None else None,
        "r2": clean(r * r) if r is not None else None,
        "strength": strength,
        "line": {"x": to_list(x_line, 10), "y": to_list(slope * x_line + intercept, 10)},
    }
