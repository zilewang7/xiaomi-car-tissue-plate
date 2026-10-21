"""Masses, centre of gravity and the rotating assembly (port of concept/v3.1 check_masses).

Printed parts: CAD volume x ABS density x fill factor (slicer estimate, same factors as v3.1); bought
items: magnets 1.13 g each at their CAD centres, the tape strips (silicone density: an upper bound), the M3 x 25
screw on the axis. The rotating set is model.rotating (panels, plugs, knob, knob caps, knob magnets) + the screw;
its inertia about the rotor axis comes from the B-rep inertia tensors.
"""
import build123d as bd
import numpy as np

STRUCT_FILL = {"cradle": 0.85, "front_bar": 0.90, "knob": 0.95}   # v3.1 estimates (4 walls + gyroid)


def fill_factor(part_name):
    if part_name.startswith(("panel_", "plug_", "cap_")) or part_name in ("far_pin", "spacer"):
        return 1.0
    return STRUCT_FILL[part_name]


def body_items(model):
    """[(owner, shape, density g/mm^3)] of everything installed: printed bodies, magnets, pads."""
    p = model.params
    rows = []
    for part in model.installed_parts():
        density = p.rho_abs * fill_factor(part.name)
        for body in part.bodies.values():
            rows.append((part.name, body, density))
    for name, shape in model.hardware.items():
        density = p.magnet_g / shape.volume if name.startswith("mag_") else p.rho_silicone
        rows.append((name, shape, density))
    return rows


def axis_inertia(shape, density, axis_y, axis_z):
    """Moment of inertia (g mm^2) about the line parallel to X through (axis_y, axis_z)."""
    tensor = shape.matrix_of_inertia                     # unit density, about the centre of mass
    com = shape.center(bd.CenterOf.MASS)
    offset_sq = (com.Y - axis_y) ** 2 + (com.Z - axis_z) ** 2
    return density * (tensor[0][0] + shape.volume * offset_sq)


def mass_properties(model):
    p = model.params
    screw_point = np.array([p.screw_x, *p.axis])
    grams_by_owner = {}
    total, moment = p.screw_g, p.screw_g * screw_point
    rotor_g, rotor_moment, inertia = p.screw_g, p.screw_g * screw_point, 0.0     # screw: on the axis
    for owner, shape, density in body_items(model):
        grams = shape.volume * density
        com = shape.center(bd.CenterOf.MASS)
        point = np.array([com.X, com.Y, com.Z])
        grams_by_owner[owner] = grams_by_owner.get(owner, 0.0) + grams
        total += grams
        moment += grams * point
        if owner in model.rotating:
            rotor_g += grams
            rotor_moment += grams * point
            inertia += axis_inertia(shape, density, *p.axis)
    printed = {name: g for name, g in grams_by_owner.items() if name in model.parts}
    magnet_names = [name for name in model.hardware if name.startswith("mag_")]
    pads_g = sum(g for name, g in grams_by_owner.items() if name.startswith("pad_"))
    solid_g = (sum(part.volume for part in model.installed_parts()) * p.rho_abs
               + len(magnet_names) * p.magnet_g + pads_g + p.screw_g)
    return dict(parts_g=printed, panels_g=sum(g for name, g in printed.items() if name.startswith("panel_")),
                magnets_n=len(magnet_names), magnets_g=len(magnet_names) * p.magnet_g, pads_g=pads_g,
                screw_g=p.screw_g, total_g=total, solid_upper_g=solid_g, cog=tuple(moment / total),
                rotor_assembly_g=rotor_g, rotor_cog=tuple(rotor_moment / rotor_g), inertia_kgm2=inertia * 1e-9)
