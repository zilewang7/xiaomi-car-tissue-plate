"""v3.3 review round 2 (findings R1-6, R2-9): one convention for the hand forces of install / removal, and the
numbers the assembly notes quote.

Hand force to lift the plate straight up off its seat at constant speed, 20 C, both tabs, INCLUDING the plate weight
and the box-face friction (mu_pu 0.35 on the magnetic pull) = study_install.vertical_flags lift_hand_force_max_N,
for v3.2 design (base magnets only), v3.2 as built on the real box (lid magnet present) and v3.3; weakest / typical /
strongest corner. Also from study_install.json (v3.3): outward push on the stacks while sliding down the face,
forward pull, one-end peel (peel_estimate.json); and where the plate's centre of gravity passes the front edge of the
lid-top flat when it is held in front of its seat (horizontal push-in).
Run: .venv/bin/python -I concept/v3.3/review/install_lift.py      (writes install_lift.json)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABS4 = HERE.parent / "tabs4"
sys.path.insert(0, str(TABS4))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

import mount22 as m22  # noqa: E402
from study_install import DU, DZ, WEIGHT_N, profile, vertical_flags  # noqa: E402
from tissueplate.params import make_params  # noqa: E402

CASES = ("weakest", "typical", "strongest")


def main():
    p = make_params(dict(mount_delta=DU, upper_delta=DU))
    br = m22.br_n52(p)
    mu = p.mu_pu[0]
    layouts = {"v3.2 design": (m22.v32_layout(p), WEIGHT_N["v3.2"]),
               "v3.2 as built": (m22.v32_with_lid(p), WEIGHT_N["v3.2"]),
               "v3.3": (m22.v33_layout(p, m22.LID_Z_MEASURED + DU), WEIGHT_N["v3.3"])}
    out = dict(convention="20 C, both tabs, incl. plate weight and box-face friction mu 0.35", lift_hand_force_N={})
    for name, (layout, weight) in layouts.items():
        row = {}
        for which in CASES:
            rows = profile(p, br, layout, m22.corner_box(which), [0.0] * len(DZ), DZ)
            flags = vertical_flags(rows, weight, mu)
            row[which] = dict(max_N=round(flags["lift_hand_force_max_N"], 2), at_dz=flags["lift_hand_force_at_dz"])
        out["lift_hand_force_N"][name] = row
        print(name, row, flush=True)
    install = json.loads((TABS4 / "study_install.json").read_text())
    peel = json.loads((TABS4 / "peel_estimate.json").read_text())["rows"]
    statics = json.loads((TABS4 / "study_statics.json").read_text())
    v33 = {}
    for which in CASES:
        block = install[f"v3.3 {which}"]
        rows = block["vertical"]["dy 0.0"]["rows"]
        lower = min(rows, key=lambda r: r["lower_Fy"])
        upper = min(rows, key=lambda r: r["upper_Fy"])
        flags = block["vertical"]["dy 0.0"]["flags"]
        v33[which] = dict(
            sliding_down_outward_total_N=round(flags["max_repulsion_N"], 2), at_dz=flags["max_repulsion_at_dz"],
            sliding_down_outward_lower_stack_per_tab_N=round(-lower["lower_Fy"] / 2, 2), lower_at_dz=lower["dz"],
            sliding_down_outward_upper_stack_per_tab_N=round(-upper["upper_Fy"] / 2, 2), upper_at_dz=upper["dz"],
            pushed_up_band_dz=flags["released_plate_pushed_up_dz"], max_up_N=round(flags["max_up_force_N"], 2),
            hand_down_extra_N=round(flags["lower_hand_force_max_N"], 2),
            forward_pull_hand_force_N=round(block["horizontal"]["flags"]["pull_forward_hand_force_max_N"], 2),
            seated_attraction_N=round(block["horizontal"]["flags"]["max_attraction_N"], 2),
            peel_one_end_N=round(peel[f"v3.3 {which}"]["peak_N"], 2))
    out["v3.3_install_numbers"] = v33
    cog_y = statics["rows"]["v3.3 du 1.75"]["cog"][1]
    out["cog_vs_lid_front_edge"] = dict(cog_y_seated=round(cog_y, 3), lid_flat_front_edge_y=p.top_fillet,
                                        cog_passes_edge_at_dy=round(p.top_fillet - cog_y, 2),
                                        note="dy < this: the centre of gravity is in front of the lid-top flat; the "
                                             "tab attraction (below the edge) and the tab down force (in front of it) "
                                             "both add to the forward tipping moment")
    print(json.dumps(out["v3.3_install_numbers"], indent=1), out["cog_vs_lid_front_edge"])
    (HERE / "install_lift.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
