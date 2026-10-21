"""Follow-up to study_install.py (v3.3, du 1.75, 20 C, plate totals = 2 tabs):
  1. vertical lowering extended to dz 30 on the face (dy 0): where the up-force falls below the weight;
  2. the same lowering held 6 / 10 mm in front of the face (the L-shaped gesture: lower in front, then slide back);
  3. the upper stack's own share along the on-face lowering (does it ever repel?);
  4. the L-path end: horizontal approach from dy -10 at seat height (= study_install horizontal rows).
Run: .venv/bin/python -I concept/v3.3/tabs4/study_install_extra.py   (writes study_install_extra.json)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import mount22 as m22  # noqa: E402
from study_install import DU, WEIGHT_N, profile  # noqa: E402
from tissueplate.params import make_params  # noqa: E402

DZ = np.round(np.arange(0.0, 30.0001, 0.5), 3)


def main():
    p = make_params(dict(mount_delta=DU, upper_delta=DU))
    br = m22.br_n52(p)
    layout = m22.v33_layout(p, m22.LID_Z_MEASURED + DU)
    weight = WEIGHT_N["v3.3"]
    out = {}
    for which in ("weakest", "typical", "strongest"):
        box = m22.corner_box(which)
        block = {}
        for dy0 in (0.0, -6.0, -10.0):
            rows = profile(p, br, layout, box, [dy0] * len(DZ), DZ)
            fz = np.array([r["Fz"] for r in rows])
            fy = np.array([r["Fy"] for r in rows])
            above = DZ[fz > weight]
            block[f"dy {dy0}"] = dict(
                max_push_away_N=float(max(0.0, -fy.min())), at_dz=float(DZ[int(np.argmin(fy))]),
                max_up_N=float(fz.max()), up_at_dz=float(DZ[int(np.argmax(fz))]),
                up_exceeds_weight_dz=(float(above.min()), float(above.max())) if len(above) else None,
                max_down_N=float(-fz.min()), down_at_dz=float(DZ[int(np.argmin(fz))]),
                upper_stack_Fz_max_up=float(max(r["upper_Fz"] for r in rows)),
                upper_stack_Fy_min=float(min(r["upper_Fy"] for r in rows)),
                rows=rows)
        out[which] = block
        print(which, {k: {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "rows"}
                      for k, v in block.items()})
    (HERE / "study_install_extra.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
