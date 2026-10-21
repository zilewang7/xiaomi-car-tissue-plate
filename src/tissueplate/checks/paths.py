"""Check 5: configuration paths (spec 6 / 7-5; port of concept/v3.1 section 3e onto the v3.2 assembly and
refill sequence). Every motion is a pure translation; the summed common volume of the moving and the fixed
shapes must be 0 at every offset.

Assembly (spec 6-6, 6-8): rotor dropped vertically between the end blocks (stator + spacer already in
the near block, front bar glued on), far pin pushed in from -X, knob (with its magnets and caps) pushed
in from +X, plate lowered vertically onto the closed box.
Coupon-calibrated fits (v3.3 A.1): the near and the far journal are larger than their holes in CAD, so every path
runs on verify_geometry.trimmed_model: those two shafts trimmed to the inscribed circle of their hole polygon over
the length that slides through it; a hex or a shaft that cannot pass a hole is still caught.
Refill (v3.4: the plate is taped to the lid): the lid is lifted off the base with the plate on it ("带牌提盖",
spec 6); the whole box may be carried out first (no relative motion; the carrying tilt is in the refill statics).
The plate lowered onto / lifted off the closed box (first stick, removal) and the lid alone are checked as well.
"""
from ..verify_geometry import trimmed_model
from .common import ZERO_VOLUME, item, path_intersection, section

DROP_HEIGHTS = (0.3, 1, 3, 6, 10, 20, 40, 60)
ROTOR_HEIGHTS = (0.5, 2, 5, 10, 20, 40)
PIN_OFFSETS = (1, 3, 6, 9, 14, 15)
KNOB_OFFSETS = (1, 3, 6, 10, 16, 23)
LID_HEIGHTS = (0.5, 2, 5, 10, 20, 40)
UP, MINUS_X, PLUS_X = (0, 0, 1), (-1, 0, 0), (1, 0, 0)


def part_bodies(model, names):
    return [body for name in names for body in model.parts[name].bodies.values()]


def hardware(model, prefixes):
    return [shape for name, shape in model.hardware.items() if name.startswith(prefixes)]


def plate_shapes(model):
    """Everything that moves with the mounted plate: installed printed bodies, magnets, pads."""
    shapes = [body for part in model.installed_parts() for body in part.bodies.values()]
    return shapes + list(model.hardware.values())


def paths(model):
    ref = model.reference
    rotor = part_bodies(model, ("panel_A", "panel_B", "panel_L", "plug_near", "plug_far"))
    cradle_set = (part_bodies(model, ("cradle", "front_bar", "spacer", "cap_tab-", "cap_tab+", "cap_tabU-", "cap_tabU+"))
                  + hardware(model, ("mag_stator", "mag_tab", "pad_")))
    knob = (part_bodies(model, ("knob", "cap_knob30", "cap_knob150", "cap_knob270")) + hardware(model, ("mag_knob",)))
    far_pin = part_bodies(model, ("far_pin",))
    plate = plate_shapes(model)
    return {
        "rotor dropped into the cradle": path_intersection(rotor, cradle_set, ROTOR_HEIGHTS, UP),
        "far pin pushed in from -X": path_intersection(far_pin, cradle_set + rotor, PIN_OFFSETS, MINUS_X),
        "knob pushed in from +X": path_intersection(knob, cradle_set + rotor + far_pin, KNOB_OFFSETS, PLUS_X),
        "plate lowered onto / lifted off the closed box": path_intersection(plate, [ref["box"]], DROP_HEIGHTS, UP),
        "lid lifted off the base without the plate": path_intersection([ref["lid"]], [ref["base"]], LID_HEIGHTS, UP),
        "lid lifted with the plate taped on (refill)": path_intersection(plate + [ref["lid"]], [ref["base"]],
                                                                          LID_HEIGHTS, UP),
    }


def run(model, refill_items, refill_numbers):
    results = paths(trimmed_model(model))
    items = []
    for name, by_offset in results.items():
        worst = max(by_offset.values())
        items.append(item(f"path: {name}, max common volume (mm^3)", worst, worst <= ZERO_VOLUME, f"<= {ZERO_VOLUME}",
                          note=f"offsets {list(by_offset)}; calibrated shafts trimmed (v3.3 A.1)"))
    items.append(item("whole box carried with the plate on it", "no relative motion", level="info",
                      note="geometry unchanged; tilt limits in the refill statics below"))
    items += refill_items
    numbers = dict(paths={name: {str(k): v for k, v in rows.items()} for name, rows in results.items()},
                   refill=refill_numbers)
    return section("5 configuration paths (assembly; refill: lid lifted with the plate taped on)", items, numbers)
