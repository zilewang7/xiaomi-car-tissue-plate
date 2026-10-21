"""Shared helpers for the checks: result items, shape pre-filters, translated-path intersections.

Every check returns section(title, items, numbers): items are the judged quantities, numbers the
detailed results. Item levels:
    hard  spec threshold; a failing hard item fails the build (build_all exits non-zero)
    warn  reference value or rule interpretation; reported, never fails the build
    info  reported number without a limit
"""
import math

import build123d as bd
import numpy as np

ZERO_VOLUME = 1e-3          # mm^3: touching shapes give ~0
LEVELS = ("hard", "warn", "info")


def rounded(value, digits=5):
    """Floats to 'digits' significant digits (also inside lists / tuples / dicts) for readable reports."""
    if isinstance(value, dict):
        return {key: rounded(v, digits) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if not math.isfinite(number) else float(f"{number:.{digits}g}")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def item(name, value, ok=None, limit="", level="hard", note=""):
    """One judged quantity; 'ok' is computed by the caller from the raw value."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}")
    if level != "info" and ok is None:
        raise ValueError(f"item {name!r}: a {level} item needs ok")
    return dict(name=name, value=rounded(value), limit=limit, level=level,
                ok=None if level == "info" else bool(ok), note=note)


def section(title, items, numbers):
    hard_ok = all(entry["ok"] for entry in items if entry["level"] == "hard")
    return dict(title=title, ok=bool(hard_ok), items=items, numbers=rounded(numbers))


def bbox_list(shape):
    box = shape.bounding_box(optimal=True)
    return [box.min.X, box.min.Y, box.min.Z, box.max.X, box.max.Y, box.max.Z]


def boxes_touch(a, b, tol=0.01):
    return all(a[i] <= b[i + 3] + tol and b[i] <= a[i + 3] + tol for i in range(3))


def common_volume(a, b):
    common = a & b
    return 0.0 if common is None else abs(common.volume)


def path_intersection(moving, fixed, offsets, direction):
    """Sum of common volumes between every moving and every fixed shape, for each offset along direction."""
    fixed_boxes = [bbox_list(shape) for shape in fixed]
    result = {}
    for offset in offsets:
        move = bd.Pos(*(offset * np.asarray(direction, float)))
        total = 0.0
        for shape in moving:
            moved = move * shape
            moved_box = bbox_list(moved)
            for other, other_box in zip(fixed, fixed_boxes):
                if boxes_touch(moved_box, other_box):
                    total += common_volume(moved, other)
        result[offset] = total
    return result


def solid_of(part):
    """All colour bodies of a printed part as one shape (inlays are printed material too)."""
    bodies = list(part.bodies.values())
    if len(bodies) == 1:
        return bodies[0]
    fused = bodies[0]
    for body in bodies[1:]:
        fused = fused + body
    return fused


def centre(shape):
    box = shape.bounding_box(optimal=True)
    return np.array([box.center().X, box.center().Y, box.center().Z])
