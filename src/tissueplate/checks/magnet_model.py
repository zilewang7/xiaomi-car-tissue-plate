"""Gilbert surface-charge model of axially magnetised discs (port of concept/v3.1 section 5).

Each disc face carries a surface charge +-Br sampled on Gauss-Legendre (radius) x uniform (angle) nodes;
forces follow Coulomb's law for magnetic charges. Br_eff is calibrated to the brief: two N52 8 x 3 discs
at a 1.2 mm face gap pull 8.6 N. Units: mm, N, T.
"""
import math

import numpy as np

MU0 = 4e-7 * np.pi
RADIAL_NODES, ANGULAR_NODES = 10, 40
CALIBRATION_FORCE, CALIBRATION_GAP = 8.6, 1.2


def disc_nodes(radius, n_r=RADIAL_NODES, n_t=ANGULAR_NODES):
    x, wx = np.polynomial.legendre.leggauss(n_r)
    r = 0.5 * radius * (x + 1.0)
    wr = 0.5 * radius * wx * r
    t = (np.arange(n_t) + 0.5) * 2 * np.pi / n_t
    rr, tt = np.meshgrid(r, t, indexing="ij")
    ww = np.outer(wr, np.full(n_t, 2 * np.pi / n_t))
    return np.stack([(rr * np.cos(tt)).ravel(), (rr * np.sin(tt)).ravel()], axis=1), ww.ravel()


class Disc:
    """Axially magnetised disc: centre c, unit axis u (S -> N), diameter d, thickness t, remanence br (T)."""

    def __init__(self, c, u, d=8.0, t=3.0, br=1.37):
        self.c = np.asarray(c, float)
        u = np.asarray(u, float)
        self.u = u / np.linalg.norm(u)
        nodes, weights = disc_nodes(d / 2)
        helper = np.array([1.0, 0, 0]) if abs(self.u[0]) < 0.9 else np.array([0, 1.0, 0])
        e1 = np.cross(self.u, helper)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(self.u, e1)
        local = nodes[:, :1] * e1 + nodes[:, 1:2] * e2
        self.pts = np.vstack([self.c + 0.5 * t * self.u + local, self.c - 0.5 * t * self.u + local])
        self.q = np.concatenate([weights, -weights]) * br


def interact(src, dst):
    """Total force on dst from src (N) and the per-node forces."""
    k = 1.0 / (4 * np.pi * MU0) * 1e-6
    d = dst.pts[:, None, :] - src.pts[None, :, :]
    r3 = np.linalg.norm(d, axis=2) ** 3
    per_node = k * dst.q[:, None] * ((src.q[None, :] / r3)[:, :, None] * d).sum(axis=1)
    return per_node.sum(axis=0), per_node


def force_torque(srcs, dsts, axis_point=(0, 0, 0), axis_dir=(1, 0, 0)):
    """Force on the dst discs and their torque about the axis (axis_point, axis_dir)."""
    force, torque = np.zeros(3), 0.0
    axis_point, axis_dir = np.asarray(axis_point, float), np.asarray(axis_dir, float)
    for s in srcs:
        for d in dsts:
            f, per_node = interact(s, d)
            force += f
            torque += float(np.dot(np.cross(d.pts - axis_point, per_node).sum(axis=0), axis_dir))
    return force, torque


def calibrate_br(magnet_d, magnet_t):
    """Br_eff that makes two coaxial discs at the calibration gap pull the calibration force."""
    def pull(br):
        lower = Disc((0, 0, -magnet_t / 2), (0, 0, 1), magnet_d, magnet_t, br)
        upper = Disc((0, 0, CALIBRATION_GAP + magnet_t / 2), (0, 0, 1), magnet_d, magnet_t, br)
        return -interact(lower, upper)[0][2]
    return 1.45 * math.sqrt(CALIBRATION_FORCE / pull(1.45))
