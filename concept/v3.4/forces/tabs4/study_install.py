"""v3.3 change 1, task 5: install / remove force profiles from all four box magnets (two per point, two points).

Plate forces from the magnets only (both tabs, = 2 x one tab), 20 C, per box candidate (lid = base):
  (i)   lowering vertically: plate dz = +20 .. 0 above its seat, tab back face on the box face plane (dy = 0),
        also dy = -1 / -3 (held slightly off the face);
  (ii)  horizontal approach at seat height: dy = -15 .. 0 (dz = 0);
  (iii) removal: lifting = (i) read upward; pulling forward = (ii) read outward; peeling one side = one tab
        pulled straight off (dy on that tab only), the other tab and the lip acting as the hinge.
Fy > 0 = toward the box (attraction), Fz > 0 = up. W = plate weight (CAD x fill, v3.3 model 102.5 g -> 1.005 N).
Flags: net vertical force on a released plate N = Fz_total - W (> 0 = it floats / the hand must push down);
stable floating points (N falls through 0 with rising dz); sticky ranges where friction (mu_pu 0.35 on the
attraction) holds the plate although |N| > 0; repulsion (Fy < 0) and where it peaks. Lift / pull / peel forces
the hand needs (incl. weight and friction where they act). Also the package's refill item (extra lift force) and
the demagnetising-field screen during the lower stack's pass in front of the lid magnet.

Run: .venv/bin/python -I concept/v3.3/tabs4/study_install.py   (writes study_install.json)
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

import numpy as np  # noqa: E402

import mount22 as m22  # noqa: E402
from tissueplate.params import make_params  # noqa: E402

import os
DU = float(os.environ["FORCES_DU"])
WEIGHT_N = {"v3.2": 98.584 * 9.81e-3, "v3.3": float(os.environ["FORCES_WEIGHT_G"]) * 9.81e-3}     # CAD x fill (study_statics.json)
DZ = np.round(np.arange(0.0, 20.0001, 0.25), 3)
DY = np.round(np.arange(0.0, -15.0001, -0.25), 3)
DY_OFF_FACE = (0.0, -1.0, -3.0)
CASES = ("weakest", "typical", "strongest")
LID_N52_8x3 = ("8x3 N52 (lid, plausible strong)", 8.0, 3.0, 1.43)   # fits in the lid skirt (d <= 9.2), outside BASES


def profile(p, br, layout, box, dys, dzs):
    rows = []
    for dy, dz in zip(dys, dzs):
        w = m22.tab_wrench(p, br, layout, box, dy=dy, dz=dz)
        row = dict(dy=float(dy), dz=float(dz), Fy=2 * float(w["total"]["force"][1]), Fz=2 * float(w["total"]["force"][2]))
        for name in ("lower", "upper"):
            if name in w:
                row[f"{name}_Fy"] = 2 * float(w[name]["force"][1])
                row[f"{name}_Fz"] = 2 * float(w[name]["force"][2])
        rows.append(row)
    return rows


def vertical_flags(rows, weight, mu):
    """Released-plate analysis along the vertical path (rows sorted by dz ascending)."""
    dz = np.array([r["dz"] for r in rows])
    fz = np.array([r["Fz"] for r in rows])
    fy = np.array([r["Fy"] for r in rows])
    net = fz - weight
    friction = mu * np.maximum(fy, 0.0)
    floating = [float(0.5 * (dz[i] + dz[i + 1])) for i in range(len(dz) - 1) if net[i] > 0 >= net[i + 1]]
    pushed_up = dz[net > 0]
    sticky = dz[(np.abs(net) <= friction) & (dz > 0)]
    lift_need = np.where(fy > 0, weight - fz + mu * fy, weight - fz)      # hand force up to lift at constant speed
    lower_need = np.where(fy > 0, fz - weight + mu * fy, fz - weight)     # hand force down to keep lowering
    i_rep = int(np.argmin(fy))
    i_up = int(np.argmax(fz))
    i_lift = int(np.argmax(lift_need))
    i_lower = int(np.argmax(lower_need))
    return dict(
        max_repulsion_N=float(-fy.min()) if fy.min() < 0 else 0.0, max_repulsion_at_dz=float(dz[i_rep]),
        repulsion_range_dz=(float(dz[fy < 0].min()), float(dz[fy < 0].max())) if (fy < 0).any() else None,
        max_up_force_N=float(fz.max()), max_up_at_dz=float(dz[i_up]),
        released_plate_pushed_up_dz=(float(pushed_up.min()), float(pushed_up.max())) if len(pushed_up) else None,
        stable_floating_dz=floating, sticky_dz=(float(sticky.min()), float(sticky.max())) if len(sticky) else None,
        lift_hand_force_max_N=float(lift_need[i_lift]), lift_hand_force_at_dz=float(dz[i_lift]),
        lower_hand_force_max_N=float(max(lower_need[i_lower], 0.0)), lower_hand_force_at_dz=float(dz[i_lower]),
        seat=dict(Fy=float(fy[0]), Fz=float(fz[0])))


def horizontal_flags(rows, weight, mu_pad):
    dy = np.array([r["dy"] for r in rows])
    fy = np.array([r["Fy"] for r in rows])
    fz = np.array([r["Fz"] for r in rows])
    normal_on_lid = np.maximum(weight - fz, 0.0)                 # pads on the lid top carry weight + magnet down
    pad_friction = mu_pad * normal_on_lid
    pulled_in = dy[fy > pad_friction]
    i_rep = int(np.argmin(fy))
    return dict(max_attraction_N=float(fy.max()), at_dy=float(dy[int(np.argmax(fy))]),
                max_repulsion_N=float(-fy.min()) if fy.min() < 0 else 0.0, repulsion_at_dy=float(dy[i_rep]),
                snaps_in_from_dy=float(pulled_in.min()) if len(pulled_in) else None,
                pull_forward_hand_force_max_N=float(np.max(fy + pad_friction)),
                Fz_range=(float(fz.min()), float(fz.max())))


def peel_one_side(p, br, layout, box, dys):
    """One tab pulled straight off the face (the other seated): that tab's normal force vs dy (per tab)."""
    out = []
    for dy in dys:
        w = m22.tab_wrench(p, br, layout, box, dy=dy)
        out.append(dict(dy=float(dy), Fy_tab=float(w["total"]["force"][1]), Fz_tab=float(w["total"]["force"][2])))
    fy = np.array([r["Fy_tab"] for r in out])
    return dict(rows=out, max_pull_N=float(fy.max()), max_at_dy=float(out[int(np.argmax(fy))]["dy"]),
                pull_at_1mm=float(np.interp(-1.0, [r["dy"] for r in out][::-1], fy[::-1])),
                pull_at_3mm=float(np.interp(-3.0, [r["dy"] for r in out][::-1], fy[::-1])))


def refill_extra_lift(p, br, layout, weight):
    """Package refill item: max over the lift of 2 (down + mu pull) (weak 80 C .. strong 20 C), plus weight."""
    f = m22.factors(p)
    mu = p.mu_pu[0]
    out = {}
    for which, factor in (("weakest", f["80C"]), ("typical", 1.0), ("strongest", 1.0)):
        box = m22.corner_box(which)
        need = []
        for h in (0, 1, 2, 3, 4, 5, 6, 8, 10, 14):
            w = m22.tab_wrench(p, br, layout, box, dz=h)
            need.append(2 * (-w["total"]["force"][2] + mu * w["total"]["force"][1]) * factor)
        out[which] = dict(extra_max_N=float(max(need)), plus_weight_N=weight)
    return out


def demag_pass(p, br, layout, box, dz_list):
    rows = []
    for dz in dz_list:
        screen = m22.demag_screen(p, br, layout, box, dz=dz)
        row = dict(dz=dz)
        for name, s in screen.items():
            row[name] = dict(mean=s["total_mean"], max=s["total_max"], self_mean=s["self_mean"], box_mean=s["box_mean"],
                             stack_mean=s["stack_mean"], beyond_knee_80C=m22.beyond_knee(s, 80.0),
                             beyond_knee_90C=m22.beyond_knee(s, 90.0), beyond_knee_60C=m22.beyond_knee(s, 60.0))
        rows.append(row)
    return rows


def main():
    t0 = time.time()
    p = make_params(dict(mount_delta=DU, upper_delta=DU))
    br = m22.br_n52(p)
    mu, mu_pad = p.mu_pu[0], p.mu_pad
    layouts = {"v3.2": m22.v32_with_lid(p), "v3.3": m22.v33_layout(p, m22.LID_Z_MEASURED + DU)}
    result = dict(inputs=dict(du=DU, weight_N=WEIGHT_N, mu_pu=mu, mu_pad=mu_pad, lid_z=m22.LID_Z_MEASURED,
                              note="v3.2 = as built on the real box (lid magnet present); 20 C; plate totals"))
    for version, layout in layouts.items():
        weight = WEIGHT_N[version]
        for which in CASES:
            box = m22.corner_box(which)
            key = f"{version} {which}"
            vertical = {}
            for dy0 in DY_OFF_FACE:
                rows = profile(p, br, layout, box, [dy0] * len(DZ), DZ)
                vertical[f"dy {dy0}"] = dict(rows=rows, flags=vertical_flags(rows, weight, mu if dy0 == 0 else 0.0))
            rows_h = profile(p, br, layout, box, DY, [0.0] * len(DY))
            result[key] = dict(vertical=vertical,
                               horizontal=dict(rows=rows_h, flags=horizontal_flags(rows_h, weight, mu_pad)),
                               peel=peel_one_side(p, br, layout, box, DY[::4]))
            print(key, "done", round(time.time() - t0, 1), "s")
        result[f"{version} refill extra lift"] = refill_extra_lift(p, br, layout, weight)
    # demag screen: seat vs the lower stack's pass in front of the lid magnet (dz 10.32 = coaxial)
    coaxial = round(m22.LID_Z_MEASURED - p.mount_z, 2)
    dz_list = [0.0, coaxial - 2.0, coaxial, coaxial + 2.0]
    demag = {}
    for version, layout in layouts.items():
        for label, box in (("typical", m22.corner_box("typical")), ("weakest", m22.corner_box("weakest")),
                           ("strongest (lid = base, not feasible)", m22.corner_box("strongest")),
                           ("base strongest + lid 8x3 N52 @2.0", m22.BoxMagnets(m22.CANDIDATES["strongest"][0], 2.0,
                                                                                 LID_N52_8x3, 2.0))):
            demag[f"{version} {label}"] = demag_pass(p, br, layout, box, dz_list)
    v32_design = m22.v32_layout(p)
    demag["v3.2 design (no lid) typical"] = demag_pass(p, br, v32_design, m22.corner_box("typical"), [0.0])
    demag["v3.2 design (no lid) strongest"] = demag_pass(p, br, v32_design, m22.corner_box("strongest"), [0.0])
    result["demag_screen"] = dict(knee_T={t: m22.knee_field(t) for t in (20.0, 60.0, 80.0, 90.0)}, rows=demag,
                                  coaxial_dz=coaxial)
    result["seconds"] = time.time() - t0
    (HERE / "study_install.json").write_text(json.dumps(result, indent=1, default=float))
    report(result)


def report(r):
    for key, v in r.items():
        if not isinstance(v, dict) or "vertical" not in v:
            continue
        print(f"== {key}")
        for dy0, block in v["vertical"].items():
            print(f"  vertical {dy0}: {json.dumps(block['flags'], default=lambda x: round(float(x), 3))}")
        print(f"  horizontal: {json.dumps(v['horizontal']['flags'], default=lambda x: round(float(x), 3))}")
        peel = v["peel"]
        print(f"  peel one tab: max {peel['max_pull_N']:.3f} N at dy {peel['max_at_dy']}, at 1 mm {peel['pull_at_1mm']:.3f}, "
              f"at 3 mm {peel['pull_at_3mm']:.3f}")
        rows = v["vertical"]["dy 0.0"]["rows"]
        sample = [rr for rr in rows if rr["dz"] in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10.25, 10.5, 11, 12, 13, 14, 15, 16, 18, 20)]
        print("  dz:  " + " ".join(f"{rr['dz']:6.2f}" for rr in sample))
        print("  Fy:  " + " ".join(f"{rr['Fy']:6.2f}" for rr in sample))
        print("  Fz:  " + " ".join(f"{rr['Fz']:6.2f}" for rr in sample))
        rows = v["horizontal"]["rows"]
        sample = [rr for rr in rows if rr["dy"] in (0, -0.5, -1, -2, -3, -4, -5, -6, -8, -10, -12, -15)]
        print("  dy:  " + " ".join(f"{rr['dy']:6.2f}" for rr in sample))
        print("  Fy:  " + " ".join(f"{rr['Fy']:6.2f}" for rr in sample))
        print("  Fz:  " + " ".join(f"{rr['Fz']:6.2f}" for rr in sample))
    for version in ("v3.2", "v3.3"):
        print(version, "refill extra lift", {k: round(x["extra_max_N"], 3) for k, x in r[f"{version} refill extra lift"].items()})
    print("knee", {k: round(v, 3) for k, v in r["demag_screen"]["knee_T"].items()}, "coaxial dz", r["demag_screen"]["coaxial_dz"])
    for name, rows in r["demag_screen"]["rows"].items():
        for row in rows:
            parts = []
            for stack in ("lower", "upper"):
                if stack in row:
                    s = row[stack]
                    parts.append(f"{stack}: mean {s['mean']:.3f} max {s['max']:.3f} (self {s['self_mean']:.3f} box {s['box_mean']:+.3f} "
                                 f"stack {s['stack_mean']:+.3f}) >knee 60/80/90C {s['beyond_knee_60C']:.2f}/{s['beyond_knee_80C']:.2f}/"
                                 f"{s['beyond_knee_90C']:.2f}")
            print(f"  {name} dz {row['dz']}: " + " | ".join(parts))
    print(f"seconds {r['seconds']:.0f}")


if __name__ == "__main__":
    main()
