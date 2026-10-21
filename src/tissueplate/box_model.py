"""Reference tissue box (lid + base) for checks and renders; not printed.

Plan: rounded rectangle 172.5 x 107.35, front face at Y = 0, lid top at Z = 0, lid top edge filleted,
parting line at Z = -skirt.
"""
import build123d as bd


def build_box(p):
    plan = bd.Pos(0, p.box_d / 2) * bd.RectangleRounded(p.box_l, p.box_d, p.box_corner_r)
    box = bd.Pos(0, 0, -p.box_h) * bd.extrude(plan, p.box_h)
    box = bd.fillet(box.edges().group_by(bd.Axis.Z)[-1], p.top_fillet)
    lid = box & bd.Pos(0, 0, p.parting_z / 2) * bd.Box(400, 400, -p.parting_z)
    base = box - lid
    return {"box": box, "lid": lid, "base": base}
