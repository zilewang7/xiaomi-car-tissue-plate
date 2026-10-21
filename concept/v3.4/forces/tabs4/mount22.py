"""v3.3 change 1 (four-magnet tabs): tab mount force model, TWO box magnets x TWO stacks per tab.

Extends checks/magnets.py mount_force (one base magnet, one stack, local frame) to the plate-0 findings:
per box point a base magnet (Z -21.07, attracts the DOTTED face) and a lid magnet (measured Z -9.0, attracts the
UNDOTTED face, opposite pole); per tab our lower stack (dotted face to the box) and the new upper stack
(undotted face to the box). Same Gilbert disc model (checks/magnet_model.py), same candidate set BASES x WALLS;
the lid magnet equals the base magnet unless a separate lid candidate is given (sensitivity).

World coordinates (spec 4.1): box front face Y = 0, box at Y > 0, Z up, one tab at X = +base_mag_x (both tabs
are identical, plate-0). Box magnets: axis along Y behind a wall, centre (x, wall + t / 2, z). Our magnets sit
on the 0.8 floor, first face at Y = -floor. Moment directions u (S -> N): base -Y and lower stack -Y (coaxial
parallel = attract); lid +Y and upper stack +Y. Cross pairs (lower <-> lid, upper <-> base) are antiparallel.
Forces are on OUR stacks (= on the plate): pull = +Fy (toward the box), down = -Fz (> 0 pulls the plate down
onto the lid). Plate displacement (dx, dy, dz) moves every stack (dy < 0 = away from the box, dz > 0 = up).
"""
import math
import sys
from pathlib import Path
from dataclasses import dataclass, replace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from tissueplate.checks.magnet_model import Disc, calibrate_br, disc_nodes, interact  # noqa: E402
from tissueplate.checks.magnets import BASES, STRONGEST, TYPICAL, WALLS, WEAKEST  # noqa: E402

LID_Z_MEASURED = -9.0          # user, caliper + single magnet, +-0.5
LID_Z_SENSITIVITY = (-8.5, -9.0, -9.5)
CANDIDATES = {"typical": TYPICAL, "weakest": WEAKEST, "strongest": STRONGEST}


@dataclass(frozen=True)
class Layout:
    """Magnet positions of one tab. lid_z None = no lid magnet; upper_z None = no upper stack (v3.2 model)."""
    x: float
    base_z: float
    lid_z: float | None
    lower_z: float
    upper_z: float | None
    floor: float = 0.8
    lower_stack: int = 2
    upper_stack: int = 2


@dataclass(frozen=True)
class BoxMagnets:
    """Box-side magnet candidates of one point: base (name, d, t, br) behind 'wall'; lid defaults to the base."""
    base: tuple
    wall: float
    lid: tuple | None = None
    lid_wall: float | None = None

    @property
    def lid_magnet(self):
        return self.base if self.lid is None else self.lid

    @property
    def lid_wall_mm(self):
        return self.wall if self.lid_wall is None else self.lid_wall


def box_discs(box, layout):
    """[(name, Disc)]: base magnet (moment -Y) and, if present, the lid magnet (moment +Y)."""
    _, d, t, br = box.base
    discs = [("base", Disc((layout.x, box.wall + t / 2, layout.base_z), (0, -1, 0), d, t, br))]
    if layout.lid_z is not None:
        _, d2, t2, br2 = box.lid_magnet
        discs.append(("lid", Disc((layout.x, box.lid_wall_mm + t2 / 2, layout.lid_z), (0, 1, 0), d2, t2, br2)))
    return discs


def our_stacks(p, br52, layout, dx=0.0, dy=0.0, dz=0.0):
    """{stack name: [Disc]} with the plate displaced by (dx, dy, dz) from its seat."""
    rows = [("lower", layout.lower_z, layout.lower_stack, -1)]
    if layout.upper_z is not None:
        rows.append(("upper", layout.upper_z, layout.upper_stack, 1))
    stacks = {}
    for name, z, count, sense in rows:
        discs = []
        for k in range(count):
            y = -(layout.floor + p.magnet_t / 2 + p.magnet_t * k) + dy
            discs.append(Disc((layout.x + dx, y, z + dz), (0, sense, 0), p.magnet_d, p.magnet_t, br52))
        stacks[name] = discs
    return stacks


def stack_centre(discs):
    return np.mean([d.c for d in discs], axis=0)


def pair_wrench(src, dsts, ref):
    """Force on the dst discs from src and its moment about ref (N, N mm)."""
    force, moment = np.zeros(3), np.zeros(3)
    for dst in dsts:
        f, per_node = interact(src, dst)
        force += f
        moment += np.cross(dst.pts - ref, per_node).sum(axis=0)
    return force, moment


def tab_wrench(p, br52, layout, box, dx=0.0, dy=0.0, dz=0.0):
    """Per stack: centre, force (N), moment about its own centre (N mm), per-source forces; tab totals."""
    sources = box_discs(box, layout)
    out, total = {}, np.zeros(3)
    for name, discs in our_stacks(p, br52, layout, dx, dy, dz).items():
        ref = stack_centre(discs)
        force, moment, split = np.zeros(3), np.zeros(3), {}
        for source_name, src in sources:
            f, m = pair_wrench(src, discs, ref)
            split[source_name] = f
            force += f
            moment += m
        out[name] = dict(centre=ref, force=force, moment=moment, split=split)
        total += force
    out["total"] = dict(force=total, pull=float(total[1]), down=float(-total[2]))
    return out


def summary(w):
    """Flat numbers of one tab_wrench result (per tab)."""
    row = dict(pull=w["total"]["pull"], down=w["total"]["down"])
    for name in ("lower", "upper"):
        if name not in w:
            continue
        f = w[name]["force"]
        row[f"{name}_pull"], row[f"{name}_down"] = float(f[1]), float(-f[2])
        row[f"{name}_moment_x"] = float(w[name]["moment"][0])
        for source, fs in w[name]["split"].items():
            row[f"{name}<-{source}_pull"], row[f"{name}<-{source}_down"] = float(fs[1]), float(-fs[2])
    return row


def factors(p, stack=2):
    """Force factors: reversible loss of both magnets x irreversible loss of our N52 stack (checks/magnets.py)."""
    at_80, at_90 = p.tab_irreversible(stack)
    return {"20C": 1.0, "80C": p.hot80 * at_80, "90C": p.hot90 * at_90}


def scaled(row, factor):
    return {k: v * factor for k, v in row.items()}


def candidate_rows(p, br52, layout, lid=None, lid_wall=None):
    """All BASES x WALLS (lid = base unless given); 20 C seat values per tab."""
    rows = []
    for base in BASES:
        for wall in WALLS:
            box = BoxMagnets(base, wall, lid, lid_wall)
            rows.append(dict(base=base[0], wall=wall, **summary(tab_wrench(p, br52, layout, box))))
    return rows


def corner_box(which, lid_which=None):
    base, wall = CANDIDATES[which]
    if lid_which is None:
        return BoxMagnets(base, wall)
    lid, lid_wall = CANDIDATES[lid_which]
    return BoxMagnets(base, wall, lid, lid_wall)


def br_n52(p):
    return calibrate_br(p.magnet_d, p.magnet_t)


def v32_layout(p):
    return Layout(x=p.base_mag_x, base_z=p.base_mag_z, lid_z=None, lower_z=p.mount_z, upper_z=None)


def v32_with_lid(p, lid_z=LID_Z_MEASURED):
    """v3.2 as built (one stack per tab) on the real box: the lid magnet repels the lower stack."""
    return Layout(x=p.base_mag_x, base_z=p.base_mag_z, lid_z=lid_z, lower_z=p.mount_z, upper_z=None)


def v33_layout(p, upper_z, lid_z=LID_Z_MEASURED):
    return Layout(x=p.base_mag_x, base_z=p.base_mag_z, lid_z=lid_z, lower_z=p.mount_z, upper_z=upper_z)


def internal_stack_force(p, br52, layout):
    """Force of our lower stack on our upper stack in the same tab (internal to the plate; seats them in the pockets)."""
    stacks = our_stacks(p, br52, layout)
    force = np.zeros(3)
    for src in stacks["lower"]:
        for dst in stacks["upper"]:
            force += interact(src, dst)[0]
    return force


# ---------------- field screen (irreversible demagnetisation, after the v3.1 review's demag screen) ----------
FIELD_K = 1.0 / (4 * math.pi)        # mu0 H (T) = sum q (P - r) / (4 pi |P - r|^3), q in T mm^2


def field_at(points, discs):
    """mu0 H (T) at points (n x 3, mm) from the surface charges of discs."""
    points = np.asarray(points, float)
    total = np.zeros_like(points)
    for disc in discs:
        d = points[:, None, :] - disc.pts[None, :, :]
        r3 = np.linalg.norm(d, axis=2) ** 3
        total += FIELD_K * ((disc.q[None, :] / r3)[:, :, None] * d).sum(axis=1)
    return total


def stack_volume_points(p, discs, n_r=4, n_t=12, n_z=7, face_margin=0.3):
    """Sample points inside a stack (one cylinder through all its discs), face_margin away from the end faces;
    weights proportional to the annulus area of each radius ring."""
    axis = discs[0].u
    centre = stack_centre(discs)
    half = 0.5 * len(discs) * p.magnet_t
    radius = p.magnet_d / 2
    helper = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(axis, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    points, weights = [], []
    for r in (np.arange(n_r) + 0.5) / n_r * radius * 0.95:
        for k in range(n_t):
            t = 2 * math.pi * (k + 0.5) / n_t
            for s in np.linspace(-half + face_margin, half - face_margin, n_z):
                points.append(centre + r * (math.cos(t) * e1 + math.sin(t) * e2) + s * axis)
                weights.append(r)
    return np.array(points), np.array(weights) / np.sum(weights), axis


class FineDisc(Disc):
    """Same disc with more charge nodes (fields evaluated inside / close to magnets)."""

    def __init__(self, disc, d, t, br, n_r=24, n_t=96):
        self.c, self.u = disc.c, disc.u
        nodes, weights = disc_nodes(d / 2, n_r, n_t)
        helper = np.array([1.0, 0, 0]) if abs(self.u[0]) < 0.9 else np.array([0, 1.0, 0])
        e1 = np.cross(self.u, helper)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(self.u, e1)
        local = nodes[:, :1] * e1 + nodes[:, 1:2] * e2
        self.pts = np.vstack([self.c + 0.5 * t * self.u + local, self.c - 0.5 * t * self.u + local])
        self.q = np.concatenate([weights, -weights]) * br


def fine_box_discs(box, layout):
    specs = [box.base[1:]] + ([box.lid_magnet[1:]] if layout.lid_z is not None else [])
    return [FineDisc(disc, *spec) for (_, disc), spec in zip(box_discs(box, layout), specs)]


def demag_screen(p, br52, layout, box, dx=0.0, dy=0.0, dz=0.0):
    """Per stack: demagnetising field along -M inside it (mu0 H, T): self (its own discs), external from the box
    magnets and from our other stack; volume mean / max at the given plate displacement."""
    stacks = our_stacks(p, br52, layout, dx, dy, dz)
    sources = fine_box_discs(box, layout)
    out = {}
    for name, discs in stacks.items():
        own = [FineDisc(disc, p.magnet_d, p.magnet_t, br52) for disc in discs]
        others = [FineDisc(disc, p.magnet_d, p.magnet_t, br52) for other, ds in stacks.items() if other != name
                  for disc in ds]
        pts, w, axis = stack_volume_points(p, discs)
        self_h = -(field_at(pts, own) @ axis)
        ext_box = -(field_at(pts, sources) @ axis)
        ext_stack = -(field_at(pts, others) @ axis) if others else np.zeros(len(pts))
        total = self_h + ext_box + ext_stack
        out[name] = dict(self_mean=float(w @ self_h), self_max=float(self_h.max()), box_mean=float(w @ ext_box),
                         box_max=float(ext_box.max()), stack_mean=float(w @ ext_stack), total_mean=float(w @ total),
                         total_max=float(total.max()), total=total, weights=w)
    return out


# N52 minimum spec (v3.1 review demag screen): Hcj 876 kA/m at 20 C, beta -0.60 %/K, knee at 0.92 Hcj
HCJ_20C_T = 876e3 * 4e-7 * math.pi
BETA_HCJ = -0.0060
KNEE = 0.92


def knee_field(temp_c):
    return KNEE * HCJ_20C_T * (1 + BETA_HCJ * (temp_c - 20.0))


def beyond_knee(screen_row, temp_c):
    """Volume share (weighted) whose demagnetising field exceeds the knee at temp_c."""
    knee = knee_field(temp_c)
    return float(screen_row["weights"] @ (screen_row["total"] > knee))


def with_lid_z(layout, lid_z):
    return replace(layout, lid_z=lid_z)
