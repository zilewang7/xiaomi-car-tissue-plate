"""Plate 0b (v3.3 design phase, re-test after plate 0): dowel holes printed like the cradle C, cap ladder printed
like the plate-3 caps -> Bambu 3MF -> CLI slice -> layout figure -> test card.

Run from the project directory:
    .venv/bin/python -I scripts/build_plate0b.py
Outputs (out/plate0b/): plate0b_coupons.3mf, presets/, slice/ (G-code, result.json, CLI round trip),
slice_summary.json, plate0b_layout.png, <YYYY-MMDD-HHMM>-盘0b试验卡.md (older cards removed). No phone numbers.

Coupons (all navy, AMS slot 3):
  dowel holes, vertical, printed from the bed like C (lip down, plate-2 settings: 4 walls, 25 % gyroid, 5 mm outer
  brim, 0.2 layers); Ø1.80 / 1.85 / 1.90 / 1.95 / 2.00, labels 180 .. 200 on the top face:
    JE   end-block depth: blind 3.0 in a 6.0 tall block, 0.4 x 45 deg mouth chamfer at the bed side
    T    real lip 2.0, through holes, no chamfer
    TC   real lip 2.0, through holes, 0.4 mouth chamfer          (lip option (a): through holes)
    B    real lip 2.0, blind 1.4 (production lip depth), 0.2 mouth chamfer   (lip option (b): blind holes)
  caps, flat discs like plate 3 (process "small": 4 walls, 40 % gyroid, auto brim, 0.2 layers), one object each:
    tab caps 0.8 thick Ø8.15 / 8.20 / 8.25, knob caps 0.4 thick Ø8.15 / 8.20 / 8.25: 1 / 2 / 3 rim notches
    hub caps 0.8 thick Ø6.25 / 6.30 / 6.35 (slip fit, for a glue dot) / 6.40 / 6.45 (press fit, no glue): one pry
    notch each (as a press-fit production cap would have), 1 .. 5 debossed dots on the top (back) face = size
Exit code 1 when a slicing check fails.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import build123d as bd  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tissueplate import bambu, coupons, export3mf  # noqa: E402
from tissueplate.params import OUT_DIR as BUILD_OUT_DIR, make_params  # noqa: E402

OUT_DIR = BUILD_OUT_DIR / "plate0b"          # follows TISSUEPLATE_OUT_DIR
PROJECT_PATH = OUT_DIR / "plate0b_coupons.3mf"
LAYOUT_PATH = OUT_DIR / "plate0b_layout.png"
CARD_SUFFIX = "-盘0b试验卡.md"

DOWEL_DIAMETERS = (1.80, 1.85, 1.90, 1.95, 2.00)
DOWEL_PITCH, DOWEL_MARGIN, STRIP_W = 9.0, 5.0, 12.0
HOLE_Y, LABEL_Y = 4.0, 9.0
MOUTH_CHAMFER = 0.4           # 45 deg lead-in at the bed side (where the beam's dowel stubs enter C)
BLIND_LIP_CHAMFER = 0.2       # lip option (b): smaller lead-in keeps 1.0 of cylinder for a 4.2 dowel (review R1-1)
BLOCK_HEIGHT = 6.0            # end-block coupon: 3 mm of material above the 3.0 deep holes
BLOCK_DEPTH = 3.0             # end-block hole depth as printed (10-15; production C has no dowel holes since 10-18)
LIP_BLIND_DEPTH = 1.4         # lip blind hole depth as printed (10-15)
MARK_SPACE = 8.0              # strip end with the debossed strip letter
TAB_CAPS = (8.15, 8.20, 8.25)
KNOB_CAPS = (8.15, 8.20, 8.25)
HUB_CAPS = (6.25, 6.30, 6.35, 6.40, 6.45)   # 6.40 / 6.45: planned ~0 / interference, for a press fit without glue
HUB_CAP_T = 0.8               # v3.3: hub cap 0.4 -> 0.8 (user 2026-10-15)
NOTCH_R = 0.5                 # rim notch: Ø1.0 half in the disc; the fit changes by < 0.04 mm (sagitta)
NOTCH_STEP = 30.0             # deg between notches
DOT_D, DOT_DEPTH, DOT_RING = 1.0, 0.4, 1.6   # hub-cap size dots on the top face (2 layers), on a Ø3.2 ring
STRUCT_BRIM_REACH = export3mf.STRUCT_BRIM_REACH


# ------------------------------------------------------------------ geometry
def dowel_cutter(diameter, z_top, chamfer):
    """Vertical hole from the bed (z = 0) up to z_top (through when z_top > part height), optional 45 deg mouth."""
    radius = diameter / 2
    cutter = coupons.z_cylinder(radius, -0.1, z_top)
    if chamfer > 0:
        cone = bd.Cone(radius + chamfer, radius, chamfer, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        cutter = cutter + cone + coupons.z_cylinder(radius + chamfer, -0.1, 0.0)
    return cutter


def dowel_strip(name, letter, height, depth, chamfer, through):
    """Strip with five vertical dowel holes Ø1.80 .. 2.00, labels (x100) and the strip letter on the top face."""
    length = 2 * DOWEL_MARGIN + DOWEL_PITCH * (len(DOWEL_DIAMETERS) - 1) + MARK_SPACE
    body = coupons.box((0.0, length), (0.0, STRIP_W), (0.0, height))
    for index, diameter in enumerate(DOWEL_DIAMETERS):
        x = DOWEL_MARGIN + index * DOWEL_PITCH
        z_top = height + 0.1 if through else depth
        body = body - bd.Pos(x, HOLE_Y, 0) * dowel_cutter(diameter, z_top, chamfer)
        body = coupons.deboss(body, f"{diameter * 100:.0f}", 3.2, (x, LABEL_Y, height), (1, 0, 0), (0, 0, 1), depth=0.4)
    body = coupons.deboss(body, letter, 4.0, (length - MARK_SPACE / 2 - 0.5, STRIP_W / 2, height), (1, 0, 0), (0, 0, 1),
                          depth=0.4)
    return coupons.single(name, "0b", body, (0, 0, 0), bambu.production_settings("struct", 0.2))


def notched_cap(name, diameter, thickness, notches):
    """Flat disc (bed face = textured face, outward when fitted) with 1 / 2 / 3 rim notches grouped at the top."""
    radius = diameter / 2
    disc = coupons.z_cylinder(radius, 0.0, thickness)
    start = 90.0 - NOTCH_STEP * (notches - 1) / 2
    for k in range(notches):
        angle = math.radians(start + NOTCH_STEP * k)
        disc = disc - coupons.z_cylinder(NOTCH_R, -0.1, thickness + 0.1, radius * math.cos(angle), radius * math.sin(angle))
    return coupons.single(name, "0b", disc, (0, 0, 0), bambu.production_settings("small", 0.2))


def dotted_hub_cap(name, diameter, thickness, dots):
    """Hub cap: one pry notch at the rim, size = 1 .. 5 dots debossed DOT_DEPTH into the top (back) face."""
    radius = diameter / 2
    disc = coupons.z_cylinder(radius, 0.0, thickness)
    disc = disc - coupons.z_cylinder(NOTCH_R, -0.1, thickness + 0.1, 0.0, radius)
    for k in range(dots):
        angle = math.radians(-90.0 + 72.0 * k)
        disc = disc - coupons.z_cylinder(DOT_D / 2, thickness - DOT_DEPTH, thickness + 0.1,
                                         DOT_RING * math.cos(angle), DOT_RING * math.sin(angle))
    return coupons.single(name, "0b", disc, (0, 0, 0), bambu.production_settings("small", 0.2))


def build_coupons():
    p = make_params()
    strips = [
        dowel_strip("JE_block_blind3_chamfer", "E", BLOCK_HEIGHT, BLOCK_DEPTH, MOUTH_CHAMFER, through=False),
        dowel_strip("T_lip_through", "T", p.lip_t, p.lip_t, 0.0, through=True),
        dowel_strip("TC_lip_through_chamfer", "TC", p.lip_t, p.lip_t, MOUTH_CHAMFER, through=True),
        dowel_strip("B_lip_blind1.4_chamfer0.2", "B", p.lip_t, LIP_BLIND_DEPTH, BLIND_LIP_CHAMFER, through=False),
    ]
    caps = []
    for kind, sizes, thickness in (("tab", TAB_CAPS, p.cap_t), ("knob", KNOB_CAPS, p.knob_cap_t)):
        for notches, diameter in enumerate(sizes, start=1):
            caps.append(notched_cap(f"D_{kind}_{diameter * 100:.0f}_x{thickness:g}_notch{notches}", diameter, thickness,
                                    notches))
    for dots, diameter in enumerate(HUB_CAPS, start=1):
        caps.append(dotted_hub_cap(f"D_hub_{diameter * 100:.0f}_x{HUB_CAP_T:g}_dots{dots}", diameter, HUB_CAP_T, dots))
    return strips, caps, p


def process_of(coupon):
    return "struct" if coupon.settings.get("brim_type") == "outer_only" else "small"


# ------------------------------------------------------------------ plate
def plate_objects(coupon_list, project_settings):
    objects = {}
    for coupon in coupon_list:
        parts = [export3mf.Part(name, export3mf.mesh_from_shape(solid), slot) for name, solid, slot in coupon.parts]
        objects[coupon.name] = export3mf.PlateObject(coupon.name, parts, (0.0, 0.0), dict(coupon.settings))
    boxes = {c.name: export3mf.layout_box(objects[c.name], process_of(c)) for c in coupon_list}
    positions = export3mf.arrange(boxes, export3mf.keep_out_zones(project_settings, with_tower=False))
    for name, plate_object in objects.items():
        plate_object.position = positions[name]
    return objects, boxes


def bed_outline(solid):
    """Outline wires of the first layer (section at z = 0.1) as point arrays (print pose, coupon coordinates)."""
    section = solid & (bd.Plane.XY.offset(0.1) * bd.Rectangle(400, 400)).faces()[0]
    rings = []
    for face in section.faces():
        for wire in [face.outer_wire()] + list(face.inner_wires()):
            points = [wire.position_at(t) for t in np.linspace(0, 1, 160)]
            rings.append(np.array([(q.X, q.Y) for q in points]))
    return rings


def short_label(name):
    """'D_knob_820_x0.4_notch2' -> 'knob\n8.20'; strips -> their letter code."""
    if name.startswith("D_"):
        _, kind, size, _, _ = name.split("_")
        return f"{kind}\n{int(size) / 100:.2f}"
    return name.split("_")[0]


def layout_figure(coupon_list, objects, path):
    """Top view of the bed (as the slicer's prepare view): first-layer outlines, labels, bed front at the bottom."""
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    width, depth = export3mf.BED_SIZE
    ax.add_patch(plt.Rectangle((0, 0), width, depth, fc="#e3dcc8", ec="#888888"))
    ax.add_patch(plt.Rectangle((0, 0), 18, 28, fc="#c9c2ae", ec="none"))
    for coupon in coupon_list:
        x0, y0 = objects[coupon.name].position
        rings = bed_outline(coupon.parts[0][1])
        for ring in rings:
            ax.fill(ring[:, 0] + x0, ring[:, 1] + y0, fc="#0C2340" if ring is rings[0] else "#e3dcc8", ec="#0C2340", lw=0.6)
        box = coupon.parts[0][1].bounding_box()
        ax.text(x0 + box.center().X, y0 + box.min.Y - 2.0, short_label(coupon.name), ha="center", va="top", fontsize=7.5)
    ax.text(width / 2, -4, "front (printer door)", ha="center", va="top", fontsize=8)
    ax.set_xlim(-5, width + 5)
    ax.set_ylim(-12, depth + 5)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("plate 0b: first-layer outlines, bed top view (mm)", fontsize=9)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ slice checks
def slice_and_check(objects, boxes, coupon_list):
    plan = {o.name: {"parts": {part.name: part.extruder for part in o.parts}, "settings": o.settings}
            for o in objects.values()}
    roundtrip = bambu.roundtrip_3mf(PROJECT_PATH, OUT_DIR / "slice" / "cli_roundtrip" / PROJECT_PATH.name)
    problems = {"3mf": export3mf.assignment_problems(export3mf.read_model_settings(PROJECT_PATH), plan),
                "cli_roundtrip": export3mf.assignment_problems(export3mf.read_model_settings(roundtrip), plan)}
    summary = bambu.slice_project(PROJECT_PATH, OUT_DIR / "slice")       # embedded project settings, like plate 0
    plate = summary["plates"][0]
    details = bambu.sliced_plate_details(OUT_DIR / "slice")
    scan = bambu.scan_gcode(OUT_DIR / "slice" / "plate_1.gcode")
    brims = export3mf.brim_report(objects, boxes, scan.points["Brim"])
    misplaced = []
    for name, plate_object in objects.items():
        vertices = np.vstack([part.mesh.vertices for part in plate_object.parts])
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        want = (*(low[:2] + plate_object.position), *(high[:2] + plate_object.position), high[2])
        got = details["boxes"].get(name)
        if got is None or max(abs(a - b) for a, b in zip(got, want)) > export3mf.PLACE_TOLERANCE:
            misplaced.append(name)
    struct = [c.name for c in coupon_list if process_of(c) == "struct"]
    summary["checks"] = {
        "one_slicer_object_per_coupon": sorted(plate["objects"]) == sorted(objects),
        "extruders_and_settings_in_3mf": not problems["3mf"],
        "extruders_and_settings_after_cli_load": not problems["cli_roundtrip"],
        "placed_as_arranged": not misplaced,
        "no_warning": not plate["warning"],
        "navy_only": set(plate["grams"]) == {"navy"},
        "gcode_tool_changes_match": plate["tool_changes_in_gcode"] == plate["filament_changes"] == 0,
        "struct_brim_about_5mm": all(STRUCT_BRIM_REACH[0] <= brims["objects"][name]["reach_mm"] <= STRUCT_BRIM_REACH[1]
                                     for name in struct),
        "brim_only_inside_layout_boxes": brims["points_outside_layout_boxes"] == 0,
    }
    summary["brims"] = brims
    summary["assignment_problems"] = problems
    summary["misplaced"] = misplaced
    summary["model_grams"] = details["model_grams"]
    summary["layers"] = scan.layers
    return summary


# ------------------------------------------------------------------ card
CARD = """# 盘 0b 试验卡（挪车号码牌 v3.3 设计阶段）

完成：{stamp}（`scripts/build_plate0b.py`）。盘 0b 不含任何号码。④ 不用打印，可以先做。

## 0 打印

- 文件：`out/plate0b/plate0b_coupons.3mf`，Bambu Studio 打开 → 切片 → 局域网或 SD 卡打印。设置和盘 0 相同：P1S 0.4、0.20 mm、纹理 PEI（涂胶）、ABS 先烘干、关门盖顶盖、预热 10–15 min；收缩 99.4 % 已写进项目。
- **只用 3 号槽藏青**（本盘不换色）。CLI 切片：**约 {minutes:.0f} min**，藏青 **{grams:.1f} g**，换色 0 次，警告：{warning}；{count} 个对象。
- 销孔试条 E / T / TC / B 和正式托架 C 的打印方式完全一样（唇板面贴床、4 墙、25 % gyroid、5 mm brim、0.2 层高）；盖片和盘 3 的正式盖片一样（平放、4 墙、40 % gyroid、自动 brim、每片一个对象）。盖片用藏青打（正式件是天蓝），尺寸不受影响。
- 打完撕掉 brim。**盖片的纹理面（贴床那面）是正面**，试配时朝外。

## 1 盘上有什么

![盘 0b 布局（俯视，下方 = 打印机门一侧）](plate0b_layout.png)

| 对象名 | 是什么 | 决定什么 | 怎么认 |
|---|---|---|---|
| JE_block_blind3_chamfer | 6 mm 高块，竖孔从贴床面往上 3.0 深（盲孔），孔口 0.4×45° 倒角；孔径 Ø1.80 / 1.85 / 1.90 / 1.95 / 2.00 | 托架两端端块的 2 个销孔 | 最高的那条，顶面印 180…200 和 E |
| B_lip_blind1.4_chamfer0.2 | 唇板厚 2.0，盲孔 1.4 深 + 0.2 倒角，孔径同上 | 唇板 4 个销孔，**方案 (b) 盲孔** | 顶面印 B，从顶面看不到孔 |
| TC_lip_through_chamfer | 唇板 2.0，通孔 + 贴床面 0.4 倒角 | 唇板 4 个销孔，**方案 (a) 通孔** | 顶面印 TC |
| T_lip_through | 唇板 2.0，通孔、无倒角 | 只用来和 TC 比倒角好不好插 | 顶面印 T |
| D_tab_…_x0.8_notch1/2/3 | 挂片盖片 0.8 厚，Ø8.15 / 8.20 / 8.25 | 挂片盖片直径 | 直径约 8、较厚；边上 1 / 2 / 3 个小缺口 = 小 / 中 / 大 |
| D_knob_…_x0.4_notch1/2/3 | 旋钮盖片 0.4 厚，Ø8.15 / 8.20 / 8.25 | 旋钮盖片直径 | 直径约 8、薄；缺口同上 |
| D_hub_…_x0.8_dots1…5 | 轴盖 0.8 厚（加厚一倍），Ø6.25 / 6.30 / 6.35 / 6.40 / 6.45；每片 1 个撬口 | 轴盖直径，以及轴盖要不要点胶 | 直径约 6；背面（非纹理面）1–5 个小凹点 = 由小到大 |

盘 0 留下的旧盖片（Ø8.1、Ø6.2）没有缺口，可以一起比较。

## 2 要准备的东西

- 盘 0 的 T2 挂片件、K_knob 旋钮、EN 近端塞、M3×25 螺钉，和 **JB 销孔条**（横梁段，175 孔正好夹住 1.75 耗材）。
- N52 磁铁 8 颗（T2 放 2 颗、旋钮每角 2 颗），④ 另用 1 颗。
- 1.75 藏青耗材：用卡尺量着剪 **4.2、4.9、5.5 mm 各 1 段**（端面剪平，宁短勿长），再剪 2 段约 10 mm。
- 硬币或钢尺（压盖片平齐用）；缝衣针或牙签（撬盖片）；卡尺；笔杆（④ 轻敲用）。

## 3 试验与通过条件

### ① 竖孔销孔（决定托架 C 的销孔直径；横梁 F 那侧已由盘 0 JB 定为 Ø1.75，不再测）

按正式装配的样子试：销子先压在横梁孔里，再把托架的孔套上去。JB 平放、175 孔朝上，就当横梁。

1. **B（方案 b）**：4.2 mm 段压进 JB 的 175 孔到底，露出约 1.2，这就是正式唇板销的伸出长度。B 贴床面朝下，用一个孔对准销头压下去，直到 B 平贴在 JB 上，再捏住 B 轻轻晃。拔下 B，换下一个孔径再试。
2. **E（端块）**：换成 5.5 mm 段（露出约 2.5），同样试 E。
3. **TC（方案 a）**：换成 4.9 mm 段（露出约 1.9），同样试 TC。TC 平贴后从顶面看，销头应比顶面略低、不冒头。
4. **T 和 TC**：再用 10 mm 段从贴床面直接往孔里推，比较有倒角的 TC 是不是更容易对准、插进去。
5. B、E、TC 每条选**压得下去、贴平后不晃的最大一档**（和盘 0 JB 的选法一样），三条可以不同，都写下来。B 插好后有没有"插住了"的感觉，也写一句（盘 0 的 JL 你说"洞太浅、没感觉"）。

**通过**：每条至少有一档"压得进、不晃"。Ø2.00 还太紧写"200 仍紧"；Ø1.80 就已经晃写"180 已晃"。

### ② 盖片和轴盖（决定"大一点点"的新尺寸）

- **挂片盖片**：T2 孔里先放 2 颗磁铁，盖片纹理面朝外按进孔口，用硬币压到和孔口平齐（别再往里压）。正式件会整圈涂胶，所以选**手指按得进、硬币压得平、放进去不晃的最大一档**。
- **旋钮盖片**：K_knob 每个角先放 2 颗磁铁，同样按进孔口、压平齐，三个角都试一下；选法同上。
- **轴盖**：直接按进 K_knob 外端面中心的沉孔，压到和端面平齐为止（盘 0 旋钮的沉孔还是旧的 3.0 深，别压到底）。选**手指压得进、压平后不晃的最紧一档**（5 档里任选；太紧 = 要用工具才压得进，或压了会翘）。再记下哪几档倒过来轻敲不掉、哪几档能用针从撬口撬出来：6.40、6.45 是为"不粘、只靠压配"准备的两档。5 档都掉写"645 仍掉"；都太紧写"625 仍紧"。
- **顺便估螺钉头高**：把旋钮、EN、M3 装起来拧紧，再放 0.8 轴盖，看它比端面**高出 / 平齐 / 凹进**多少。

### ③ 量一下 M3×25 螺钉（卡尺）

- 头高 k（螺钉头顶到头下平面）、头部直径、螺钉长度（头下到尖）。旋钮沉孔深度按 k 定：深度 = k + 1.0（0.8 轴盖 + 0.2 余量），k ≤ 2.0 时保持现在的 3.0；没量之前按 k = 2.4 设计成 3.4。

### ④ 重新确认盖磁点（不用打印，只要 1 颗磁铁和卡尺）

单颗磁铁贴在盒面上有摩擦，按计算可以停在离真中心约 ±1–2 mm 的任何地方，比上次估的 ±0.5 大。从上、下两个方向各让它停一次，取中点就准了。

1. 盒子拿出来放在桌上。只用 1 颗磁铁，**无点面朝盒子**；另一颗拿远，别让两颗互相吸。
2. **从上往下**：把磁铁贴在盖磁点上方约 5 mm，手指推着它慢慢往下滑，同时用笔杆轻敲盒面，直到它自己停住、敲也不动。量磁铁上沿到盖顶的距离，加 4（半径）= 中心深度 a。
3. **从下往上**：贴在盖磁点下方约 5 mm（接缝附近），往上推、轻敲到停住，同样量出中心深度 b。
4. 在停住的位置量磁铁边到最近端面的距离，加 4 = 中心到端面的距离 c（底座点是 47.04）。
5. 两侧各做一次。

## 4 请回传

| 项目 | 结果 |
|---|---|
| ① B（方案 b，唇板盲孔）选几号；插住了有没有感觉 | |
| ① E（端块）选几号 | |
| ① TC（方案 a，唇板通孔）选几号；销头是否不冒头；倒角是否比 T 好插 | |
| ② 挂片盖片选几个缺口（1 / 2 / 3） | |
| ② 旋钮盖片选几个缺口（三个角都一样吗） | |
| ② 轴盖选几个点；哪几档倒过来不掉、撬得出（或"645 仍掉""625 仍紧"） | |
| ② 装上螺钉后 0.8 轴盖高出 / 平齐 / 凹进多少 | |
| ③ M3×25 头高 k、头径、长度（mm） | |
| ④ 副驾侧 a / b / c，主驾侧 a / b / c（mm） | |
| 打印：有无翘边，孔口有没有被压扁 | |
"""


def completion_stamp():
    return datetime.now().strftime("%Y-%m%d-%H%M")


def write_card(summary):
    plate = summary["plates"][0]
    stamp = completion_stamp()
    for old in OUT_DIR.glob(f"*{CARD_SUFFIX}"):
        old.unlink()
    path = OUT_DIR / f"{stamp}{CARD_SUFFIX}"
    shown = f"{stamp[:4]}-{stamp[5:7]}-{stamp[7:9]} {stamp[10:12]}:{stamp[12:14]}"
    path.write_text(CARD.format(stamp=shown, minutes=plate["minutes"], grams=plate["grams"].get("navy", 0.0),
                                warning=plate["warning"] or "无", count=len(plate["objects"])), encoding="utf-8")
    return path


def main():
    started = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    strips, caps, _ = build_coupons()
    coupon_list = strips + caps
    print(f"built {len(coupon_list)} coupons in {time.time() - started:.0f} s")
    presets = bambu.plate_presets()
    preset_files = bambu.write_presets(presets, OUT_DIR / "presets")
    project_settings = bambu.export_project_settings(preset_files, OUT_DIR / "presets")
    objects, boxes = plate_objects(coupon_list, project_settings)
    export3mf.write_bambu_3mf(PROJECT_PATH, [export3mf.Plate("plate0b_coupons", list(objects.values()))], project_settings,
                              title="Parking plate: plate 0b re-test coupons")
    print(f"wrote {PROJECT_PATH}")
    summary = slice_and_check(objects, boxes, coupon_list)
    summary["positions"] = {name: [round(v, 2) for v in o.position] for name, o in objects.items()}
    summary["coupons"] = {c.name: dict(process=process_of(c), settings=c.settings) for c in coupon_list}
    layout_figure(coupon_list, objects, LAYOUT_PATH)
    card_path = write_card(summary)
    summary["card"] = export3mf.display_path(card_path)
    (OUT_DIR / "slice_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    plate = summary["plates"][0]
    print(json.dumps({k: plate[k] for k in ("minutes", "grams", "grams_total", "filament_changes", "warning")},
                     ensure_ascii=False))
    print("checks:", summary["checks"])
    print(f"card: {card_path}")
    failed = [name for name, value in summary["checks"].items() if not value]
    if failed:
        print(f"plate 0b checks FAILED: {failed} - see {OUT_DIR / 'slice_summary.json'}")
        return 1
    print(f"done in {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
