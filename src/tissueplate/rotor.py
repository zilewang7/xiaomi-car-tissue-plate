"""Rotor end plugs EN / EF (spec 4.2, 4.4), glued flush into the tube ends.

Near plug (16 mm, +X end): keyed-hex blind socket (AF 5.20, 5.15 until 10-16; bottom at knob_hex_end = the knob
hex tip, which sets the 0.2 near gap) + Ø2.5 pilot for the M3x25 axis screw, depth params.pilot_depth: deepened with the
knob counterbore (v3.3 2.4: 6.9 for k 2.4), EN floor under it >= pilot_floor_min, screw tip clear of its bottom.
Its key (the flattened hex corner) points at +Z at rest, i.e. at the edge above face A ("key to A's top edge", 6-5).
Far plug (10 mm, -X end, v3.4): regular hex blind socket (AF far_socket_af, as EN, no key), floor at far_pin_end_x;
the far pin P is pushed into it at any of 6 angles and turns with the rotor.
"""
from .shapes import keyed_hex, tri_pts, x_cyl, x_hex, yz_prism


def plug_section(p):
    return tri_pts(p.r_in - p.panel_t - p.plug_clr, p.plug_chamfer, p.axis)


def build_plug_near(p):
    if p.en_pilot_floor < p.pilot_floor_min - 1e-9 or p.screw_tip_clearance <= 0:
        raise ValueError(f"M3 x {p.screw_len:g} with counterbore {p.screw_head_depth} / pilot {p.pilot_depth}: EN floor "
                         f"{p.en_pilot_floor:.2f} (>= {p.pilot_floor_min}), screw tip -> pilot bottom "
                         f"{p.screw_tip_clearance:.2f} (> 0)")
    y, z = p.axis
    plug = yz_prism(plug_section(p), p.rotor_x[1] - p.plug_len_near, p.rotor_x[1])
    plug = plug - keyed_hex(p.hex_socket_af, p.knob_hex_end, p.rotor_x[1] + 1, y, z, p.hex_key)
    plug = plug - x_cyl(p.screw_pilot / 2, p.knob_hex_end - p.pilot_depth, p.knob_hex_end + 0.01, y, z)
    return plug


def build_plug_far(p):
    y, z = p.axis
    plug = yz_prism(plug_section(p), p.rotor_x[0], p.rotor_x[0] + p.plug_len_far)
    plug = plug - x_hex(p.far_socket_af, p.rotor_x[0] - 1, p.far_pin_end_x, y, z)
    return plug
