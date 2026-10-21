"""Hand force to peel the plate off one end (rigid rotation about a vertical axis at the far tab's outer back edge),
per box case (20 C): near-tab magnet resistance (study_install.json peel rows, one tab pulled straight off) plus the
pad friction moment (mu_pad on the pads, load = weight + magnet down-force of both tabs, uniform over the two pad
strips); force applied forward at the near end block centre. Read the peak over the first 3 mm of near-tab travel.
Run: .venv/bin/python -I concept/v3.3/tabs4/peel_estimate.py
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from study_install import DU, WEIGHT_N  # noqa: E402
from tissueplate.params import make_params  # noqa: E402

p = make_params(dict(mount_delta=DU, upper_delta=DU))
pivot_x = -(p.base_mag_x + p.tab_w / 2)
lever_tab = p.base_mag_x - pivot_x
lever_hand = 0.5 * sum(p.near_block_x) - pivot_x
# mean distance of the pad strips from the pivot (area weighted)
points = []
for (x0, x1), (y0, y1) in p.pad_zones:
    xs, ys = np.meshgrid(np.linspace(x0, x1, 200), np.linspace(y0, y1, 20))
    points.append(np.c_[xs.ravel(), ys.ravel(), np.full(xs.size, (x1 - x0) * (y1 - y0) / xs.size)])
pts = np.vstack(points)
r_mean = float(np.average(np.hypot(pts[:, 0] - pivot_x, pts[:, 1]), weights=pts[:, 2]))
r = json.load(open(HERE / "study_install.json"))
out = {}
for version in ("v3.2", "v3.3"):
    for which in ("weakest", "typical", "strongest"):
        rows = r[f"{version} {which}"]["peel"]["rows"]
        seat_down = -r[f"{version} {which}"]["vertical"]["dy 0.0"]["rows"][0]["Fz"]      # both tabs, at the seat
        need = []
        for row in rows:
            if row["dy"] < -3.0:
                continue
            friction = p.mu_pad * (WEIGHT_N[version] + seat_down) * r_mean
            need.append((row["Fy_tab"] * lever_tab + friction) / lever_hand)
        out[f"{version} {which}"] = dict(peak_N=max(need), magnets_only_N=rows[0]["Fy_tab"] * lever_tab / lever_hand)
print(f"pivot X {pivot_x:.2f}, lever tab {lever_tab:.2f}, hand {lever_hand:.2f}, pad mean radius {r_mean:.1f}")
for k, v in out.items():
    print(k, {kk: round(vv, 2) for kk, vv in v.items()})
(HERE / "peel_estimate.json").write_text(json.dumps(dict(pivot_x=pivot_x, lever_tab=lever_tab, lever_hand=lever_hand,
                                                         pad_mean_radius=r_mean, rows=out), indent=1))
