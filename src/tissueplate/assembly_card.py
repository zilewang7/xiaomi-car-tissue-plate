"""Chinese assembly card (v3.4 design doc sections 3.7 and 5.4, on top of the v3.3 card and spec v3.2 sections 6 and
7), written by render.render_all after the images.

    write(model, images) -> path of out/<YYYY-MMDD-HHMM>-装配卡.md  (older cards are removed first)

The text is scripts/templates/assembly_card.md ($placeholders), for a plate taped to the lid (pad_t >= 0.5; the
magnets-only handling of v3.3 left the card when pad_t = 0 was dropped, 10-20). Counts, sizes and fits come from
model.params, so the card follows config.toml; the forces come from the checks (model.results["checks"], run before
the renders) where the build computes them, the other hand forces of the install / removal gestures from design
analyses at DESIGN_POINT (DESIGN_FORCES). The card never contains the phone numbers or texts.
"""
import math
import re
from collections import Counter
from datetime import datetime
from string import Template

from .bambu import COOLING_SPEEDS, FILAMENT_PRESET, FILAMENT_SHRINK, MACHINE_PRESET, PIN_BRIM, PROCESS_PRESET
from .export3mf import PLATES_DIR, PROJECT_FILE, display_path
from .params import OUT_DIR, PROJECT_DIR, make_params
from .render_plates import PREFIX

TEMPLATE = PROJECT_DIR / "scripts" / "templates" / "assembly_card.md"
SUFFIX = "-装配卡.md"
COLOUR_NAMES = {"navy": "藏青", "white": "白", "azure": "天蓝"}
CORNERS = ("weakest", "typical", "strongest")      # box magnet candidates, as in checks/magnets.py
# fit keys the card lists when they differ from the defaults: config [fit] key and [display] white_layers -> Params
# field; the defaults are the author's plate 0 / 0b picks, far_hex_af / hex_socket_af are listed too (v3.4 design
# values) so that every key of the README table shows up once changed
PLATE_PICKS = {"near_hole": "hole_near", "far_hole": "hole_far", "far_hex_af": "far_hex_af",
               "hex_socket_af": "hex_socket_af", "hex_af": "hex_af", "tab_cap_d": "tab_cap_d",
               "knob_cap_d": "knob_cap_d", "hub_cap_d": "hub_cap_d", "white_layers": "white_layers"}
IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\((renders/[^)]+)\)\n", re.M)
BRIM_NAMES = {"brim_ears": "四角鼠耳（Painted，每角一个 R5 耳）", "auto_brim": "自动", "outer_only": "外侧 {width} mm"}
# Hand forces the build does not compute (N, both tabs, 20 C, box magnets weakest / typical / strongest), at
# DESIGN_POINT = v3.4 as built (both stacks 2.45 above the box magnet points, 105.1 g): the v3.3 analyses
# (concept/v3.3/tabs4/study_install.py, study_install_extra.py, peel_estimate.py, review/install_lift.py) re-run
# 2026-10-19 in concept/v3.4/forces/; the same scripts at the v3.3 point (1.75, 102.5 g) give the v3.3 numbers exactly.
DESIGN_POINT = {"lid_mag_below_top": 9.0, "mag_below_top": 21.07, "mag_from_end": 47.04, "mount_stack": 2,
                "mount_delta": 2.45, "upper_delta": 2.45}
DESIGN_FORCES = {
    "slide_down_push": (5.704, 8.645, 15.437),      # outward push while sliding down the box face
    "pushed_up_from": (11.5, 11.0, 12.0),           # mm above the seat: pushed up from here ...
    "pushed_up_until": (18.5, 20.0, 23.5),          # ... to here (up force above the weight)
    "pushed_up_max": (2.402, 3.664, 7.371),
    "press_through": (1.372, 2.633, 6.340),         # extra hand force down through that band
    "pulled_down_at": (3.0, 3.0, 4.0),              # mm above the seat where the pull down peaks
    "pulled_down_max": (6.532, 10.331, 21.425),
    "peel": (4.469, 6.620, 11.634),                 # removal: one end peeled open at its end block
    "lift": (9.068, 13.481, 25.831),                # straight up (not recommended), incl. weight and face friction
    "pull_forward": (12.924, 19.272, 34.294),       # whole plate forward (not recommended)
}


def number(value):
    """1.0 -> '1', 15.5 -> '15.5'."""
    return f"{value:g}"


def triple(values, digits=1):
    """(weakest, typical, strongest) -> '9.5 / 14.5 / 26.1'."""
    return " / ".join(f"{value:.{digits}f}" for value in values)


def pad_step(p):
    """Front bar step 7-5: where the two tape strips go under the lip (v3.4 5.4)."""
    rows = []
    for title, ((x0, x1), (y0, y1)) in zip(("前条", "后条"), p.pad_zones):
        rows.append(f"{title} {number(x1 - x0)}×{number(y1 - y0)} 离唇板后边 {number(p.lip_back_y - y1)} mm、"
                    f"两端各留 {number(x0 - p.lip_x[0])} mm")
    return ("贴胶带：只撕唇板那一面的底纸，贴在唇板底面两条区域里，压实；盖子那面的底纸先留着（§12-1 才撕）。"
            + "；".join(rows) + "。贴前擦净唇板底面。")


def pad_purchase(p):
    return f"3M VHB 双面胶，{number(p.pad_t)} mm 厚（作者用的是 20 mm 宽的卷），剪两条，尺寸见 §7-5"


def fit_values(p):
    """The plate 0 / 0b picks and design values this card was built with."""
    tape = f"双面胶 {number(p.pad_t)} mm 厚"
    return (f"近端孔 {p.hole_near:.2f}、远端孔 {p.hole_far:.2f}、六角 AF {p.hex_af:.2f}、EN 六角孔 AF {p.hex_socket_af:.2f}、"
            f"远端六角 AF {p.far_hex_af:.2f}；"
            f"盖片 挂片 Ø{p.tab_cap_d:.2f}、旋钮 Ø{p.knob_cap_d:.2f}、轴盖 Ø{p.hub_cap_d:.2f}；"
            f"白字 {p.white_layers} 层；{tape}；盖磁点在盖顶下 {number(p.lid_mag_below_top)} mm；"
            f"M3 头高按 {number(p.screw_head_k)} 算（旋钮沉孔 {number(p.screw_head_depth)} 深）")


def mount_note(p):
    """Card 1-1 notice when pad_t, delta_up and tab_bottom did not change together (v3.4 5.5): the tabs and the 4
    magnet holes keep their place under the lip, so F stays the author's, only when all three move by the same amount."""
    built = make_params()
    longer = round((p.pad_t - p.tab_bottom) - (built.pad_t - built.tab_bottom), 2)
    lower = round((p.pad_t - p.mount_delta) - (built.pad_t - built.mount_delta), 2)
    changes = []
    if longer:
        changes.append(f"挂片{'长' if longer > 0 else '短'} {number(abs(longer))} mm")
    if lower:
        changes.append(f"4 个磁铁孔{'低' if lower > 0 else '高'} {number(abs(lower))} mm")
    if not changes:
        return ""
    return ("注意：`[mount]` 的 `pad_t`、`delta_up`、`tab_bottom` 没有一起改，打出来的 F 和作者的不一样（相对唇板，"
            + "、".join(changes) + "）。只是换了胶带厚度的话，`delta_up` 和 `tab_bottom` 要和 `pad_t` 加减同样的量，"
            "F 才不变（`config.example.toml` 里的两组）；有意改的不用管。")


def pick_text(value):
    """5.9 -> '5.90' (sizes as written in config.toml), 4 -> '4'."""
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def changed_picks(p):
    """Fit values that differ from the defaults (the author's plate 0 / 0b picks)."""
    picks = make_params()
    return [f"`{key}` = {pick_text(getattr(p, field))}（默认 {pick_text(getattr(picks, field))}）"
            for key, field in PLATE_PICKS.items() if getattr(p, field) != getattr(picks, field)]


def fit_note(p):
    """Where the fit values come from (also in the report): the defaults are the author's plate 0 / 0b picks; keys
    changed in config.toml are listed, they may come from the README table (a part that did not fit)."""
    changed = changed_picks(p)
    if changed:
        return ("你的配置改了 " + "、".join(changed) + "。按 README 的对照表改的不用改回；不是有意改的，"
                "就在 `config.toml` 里删掉这几行，再重跑。")
    return "这组值都是默认值（作者用盘 0 / 0b 选的），`config.toml` 里没写的键都取它们。"


def glue_dot(p, gap):
    """Glue dot on the magnet behind a cap: half the free volume behind it, and the hemisphere of that volume."""
    volume = 0.5 * math.pi * (p.mag_pocket_d / 2) ** 2 * gap
    diameter = 2 * (3 * volume / (2 * math.pi)) ** (1 / 3)
    return f"{math.floor(volume)} mm³，约 Ø{round(diameter * 2) / 2:g} 的半球"


def end_mark(config, logo_mode):
    """Card 4-1: the mark that lines the three panels up (all faces read towards the knob end from outside)."""
    texts = (config.text_a is not None) + (config.text_b is not None)
    ends = {0: "号码末位", 1: "号码末位、文字的最后一个字", 2: "A、B 面文字的最后一个字"}[texts]
    if logo_mode == "text":            # no sketch, no trails: the line of face L ends there too (6.5)
        return f"{ends}和 L 面文字的末尾都在同一端（= 近端）：从车外看，三面的字都是朝旋钮端读完"
    return f"{ends}和 Logo 拖尾都在同一端（= 近端）"


def hub_note(p):
    """Plate 0b: the 0.8 hub cap pressed in flush on the plate-0 knob (v3.2 counterbore), so the M3 head is at most
    counterbore_v32 - hub_cap_t high; say so when the counterbore leaves more than hub_cap_gap under the cap."""
    head_max = p.counterbore_v32 - p.hub_cap_t
    gap = round(p.screw_head_depth - p.hub_cap_t - head_max, 2)
    if gap <= p.hub_cap_gap:
        return ""
    return (f"沉孔按 M3 头高 {number(p.screw_head_k)} 做成 {number(p.screw_head_depth)} 深；盘 0b 里 {number(p.hub_cap_t)} 轴盖在"
            f" {p.counterbore_v32:.1f} 沉孔里能压平，说明头高不超过 {number(head_max)}，轴盖下面至少有 {number(gap)} mm 空隙："
            "轴盖不靠螺钉头托着，压到和端面平齐就停，靠沉孔壁上那点胶粘住。")


def check_numbers(model):
    """Forces and angles the checks computed (model.results["checks"])."""
    checks = model.results.get("checks")
    if checks is None:
        raise RuntimeError("the assembly card needs the check results: run checks.run_all before render.render_all")
    sections = checks["sections"]
    mount = sections["7_magnets"]["numbers"]["mount"]
    seating = sections["7_magnets"]["numbers"]["seating"]
    statics = sections["8_statics"]["numbers"]
    refill = sections["5_paths"]["numbers"]["refill"]
    seat = [2 * mount[f"{which}_20C"]["pull"] for which in CORNERS]
    return dict(seat=seat, cap_push=-mount["install"]["lower"]["min_pull"], cap_push_upper=-mount["install"]["upper"]["min_pull"],
                lobe_push=-seating["lobe_min"], stator_push=-seating["stator_min"], weight=statics["weight_N"],
                press_force=statics["press_force_20C_N"], cog_y=checks["mass"]["cog"][1],
                lid_lift=[refill["lid_lift_N"][which]["force_N"] for which in CORNERS],
                tabs_below_parting=refill["tabs_below_parting"])


def seating_text(forces):
    """Why the caps are glued all round (review M3, v3.3 2.4): the magnet forces that push on them."""
    return (f"整圈粘牢是因为磁铁会顶盖片：换档时旋钮磁铁最多往外顶约 {forces['lobe_push']:.1f} N；车内竖直装牌时下孔磁铁"
            f"最多把挂片盖片往外顶约 {forces['cap_push']:.1f} N（上孔约 {forces['cap_push_upper']:.1f} N）。背后那一小点胶只是让"
            "磁铁停在孔底。")


def force_intro(p):
    """Reading of the a / b / c force triples, and whether the configuration is the analysed design point."""
    text = "下面的三个数分别是盒里的磁铁按最弱 / 典型 / 最强估算时的力（20 ℃，两片挂片合计）。"
    changed = [name for name, value in DESIGN_POINT.items() if getattr(p, name) != value]
    if changed:
        text += (f"装、取的手力（贴合吸力除外）是按设计点算的（盖磁点 {number(DESIGN_POINT['lid_mag_below_top'])}、"
                 f"每摞 {DESIGN_POINT['mount_stack']} 颗、两摞偏置 {number(DESIGN_POINT['mount_delta'])}），"
                 f"你的配置改了 {'、'.join(changed)}，实际会有出入。")
    return text


def plate_table(model):
    lines = ["| 盘 | 零件 | 颜色 |", "|---|---|---|"]
    for plate in sorted({part.plate for part in model.parts.values()}):
        parts = model.plate(plate)
        totals = Counter(part.label for part in parts)
        spares = Counter(part.label for part in parts if not part.installed)
        aids = {part.label for part in parts if part.process == "cooling"}      # cooling tube Q: printed, thrown away
        labels = []
        for label, count in totals.items():
            text = label if count == 1 else f"{label} ×{count}"
            if label in aids:
                text += "（陪打柱，打完扔掉）"
            elif spares[label]:
                text += f"（含备用 {spares[label]}）"
            labels.append(text)
        colours = list(dict.fromkeys(colour for part in parts for colour in part.colours))
        lines.append(f"| {plate} | {'、'.join(labels)} | {' + '.join(COLOUR_NAMES[c] for c in colours)} |")
    return "\n".join(lines)


def plate_images(images, plates):
    rows = [f"![{name}]({path.relative_to(OUT_DIR).as_posix()})" for name, path in images.items()
            if name.startswith(PREFIX)]
    if rows:
        return "\n".join(rows)
    return "（没有 3MF，所以没有俯视图。）" if plates is not None and not plates["sliced"] else "（这次没出俯视图。）"


def no_slicer_reason(plates):
    reason = plates["reason"]
    return "构建时用了 `--no-slicer`" if reason == "--no-slicer" else f"没找到或起不来 Bambu Studio：{reason}"


def project_step(plates):
    """Card 1-3: open the project, or (no-slicer mode) set the plates up by hand."""
    if plates is None or plates["sliced"]:
        return (f"打开 `{display_path(PLATES_DIR / PROJECT_FILE)}`：一个文件两盘（盘 1 彩色、盘 2 藏青），已带好耗材分配、"
                "收缩 99.4 %、冲洗量和擦料塔位置，逐盘切片、打印。")
    return (f"这次没有出 3MF（{no_slicer_reason(plates)}），要在切片软件里照本节末尾的「手动设置」自己建两盘；"
            "装好 Bambu Studio 后重新构建，就会出带好全部设置的 3MF。")


def slice_numbers(plates):
    if plates is None or plates["sliced"]:
        return f"切片时间、克重、换色次数见 `{display_path(OUT_DIR / 'report.md')}`。"
    return ""


def setting_text(settings):
    """Per-object settings of the 3MF in words (wall loops, infill, brim, the cooling tube's speeds)."""
    words = [f"墙 {settings['wall_loops']}"] if "wall_loops" in settings else []
    words.append(f"填充 {settings['sparse_infill_density']} {settings['sparse_infill_pattern']}")
    brim = BRIM_NAMES.get(settings.get("brim_type"), settings.get("brim_type", "—"))
    words.append("brim " + brim.format(width=settings.get("brim_width", "")))
    if settings.get("outer_wall_speed") == COOLING_SPEEDS["outer_wall_speed"]:
        words.append(f"墙、填充、间隙填充的速度都设 {COOLING_SPEEDS['outer_wall_speed']} mm/s")
    return "，".join(words)


def manual_settings(plates):
    """No-slicer mode: what the 3MF would have carried, to set by hand (webui design 6.4)."""
    if plates is None or plates["sliced"]:
        return ""
    print_dir = display_path(OUT_DIR / "parts" / "print")
    lines = ["", "", "### 手动设置（这次没有 3MF）", "",
             f"1. 新建工程：打印机 `{MACHINE_PRESET}`、工艺 `{PROCESS_PRESET}`，三个耗材槽都选 `{FILAMENT_PRESET}`"
             "（颜色按上面的槽），热床纹理 PEI；三个耗材的收缩率（XY）都设 "
             f"{FILAMENT_SHRINK.replace('%', ' %')}。冲洗量用 Bambu Studio 按颜色给的默认值。",
             f"2. 建两盘，按下表从 `{print_dir}/` 导入 STL：同一件的几个颜色 STL 一起选中导入，问是否当成一个多零件对象时选"
             "「是」，再给每个零件选表里的槽。层高都是 0.2，每件的墙、填充、brim 在对象设置里按表改。",
             "3. 盘 1 有几种颜色：开擦料塔，放在右后角、别压到零件；首层打印顺序把 3 号槽（藏青）排第一，brim 才是藏青的。"
             "盘 2 只有藏青，不用擦料塔。",
             "4. 旋钮 K 一定要和陪打柱 Q 同盘（§1-5）；小件（K、EN、EF、P、D、S）切片后看一下，它们所在的每一层都要 ≥ 10 s。",
             "", "| 盘 | 件 | STL → 槽 | 设置 |", "|---|---|---|---|"]
    for number, plate in plates["plates"].items():
        for entry in plate["objects"]:
            parts = "、".join(f"`{name}.stl` → {slot}" for name, slot in entry["parts"].items())
            lines.append(f"| {number} | {entry['label']} `{entry['piece']}` | {parts} | {setting_text(entry['settings'])} |")
    return "\n".join(lines)


def count_hardware(model, prefix):
    return sum(1 for name in model.hardware if name.startswith(prefix))


def count_parts(model, prefix):
    return sum(1 for name in model.parts if name.startswith(prefix))


def template_values(model, images):
    p = model.params
    forces = check_numbers(model)
    tab_gap = round(p.tab_t - p.mount_floor - p.mount_stack * p.magnet_t - p.cap_t, 2)
    design = {name: triple(values) for name, values in DESIGN_FORCES.items()}
    design["pushed_up_until"] = " / ".join(number(value) for value in DESIGN_FORCES["pushed_up_until"])
    for name in ("pushed_up_from", "pulled_down_at"):
        low, high = min(DESIGN_FORCES[name]), max(DESIGN_FORCES[name])
        design[name] = number(low) if low == high else f"{low:.0f}–{high:.0f}"
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fit_values": fit_values(p),
        "fit_note": fit_note(p),
        "end_mark": end_mark(model.config, model.reports["logo"].get("mode")),
        "mount_note": mount_note(p),
        "magnets_total": count_hardware(model, "mag_"),
        "tab_magnets": count_hardware(model, "mag_tab"),
        "knob_magnets": count_hardware(model, "mag_knob"),
        "stator_magnets": count_hardware(model, "mag_stator"),
        "tab_stack": p.mount_stack,
        "knob_stack": p.knob_stack,
        "near_plug_length": number(p.plug_len_near),
        "far_plug_length": number(p.plug_len_far),
        "near_hole": f"{p.hole_near:.2f}",
        "far_hole": f"{p.hole_far:.2f}",
        "pad_purchase": pad_purchase(p),
        "tab_cap": f"Ø{p.tab_cap_d:.2f}×{number(p.cap_t)}",
        "knob_cap": f"Ø{p.knob_cap_d:.2f}×{number(p.knob_cap_t)}",
        "hub_cap": f"Ø{p.hub_cap_d:.2f}×{number(p.hub_cap_t)}",
        "tab_caps": count_parts(model, "cap_tab"),
        "knob_caps": count_parts(model, "cap_knob"),
        "notch_d": f"{p.cap_notch_d:.1f}",
        "spacer": f"Ø{number(p.spacer_d)}×{number(round(p.stator_spacer_t, 2))}",
        "tab_gap": number(tab_gap),
        "knob_gap": number(p.knob_pocket_allowance),
        "dot_tab": glue_dot(p, tab_gap),
        "dot_knob": glue_dot(p, p.knob_pocket_allowance),
        "hub_note": hub_note(p),
        "pin_brim": PIN_BRIM["brim_width"],
        "far_slot": f"{2 * (math.sqrt(2) - p.tear_top) * p.hole_far / 2:.2f}",
        "line_below_seam": number(round(p.z0 - (p.beam_line_z + p.beam_line_w / 2), 2)),
        "rotor_above_lip": f"{p.axis_z - p.r_in - (p.z0 + p.lip_t):.0f}",
        "pad_step": pad_step(p),
        "far_gap": number(round(p.rotor_x[0] - p.far_block_x[1], 2)),
        "near_face_gap": number(round(p.near_block_x[0] - p.rotor_x[1], 2)),
        "seating_text": seating_text(forces),
        "stator_push": f"{forces['stator_push']:.1f}",
        "cap_push_lower": f"{forces['cap_push']:.1f}",
        "seat_forces": triple(forces["seat"]),
        "seat_max": f"{max(forces['seat']):.0f}",
        "tip_dy": f"{forces['cog_y'] - p.top_fillet:.1f}",
        "weight": f"{forces['weight']:.1f}",
        "press_force": f"{forces['press_force']:.1f}",
        "lid_lift_extra": triple(forces["lid_lift"]),
        "tab_below_seam": f"{forces['tabs_below_parting']:.1f}",
        "tilt_dig": f"{forces['tabs_below_parting'] * math.sin(math.radians(1.0)):.2f}",
        "force_intro": force_intro(p),
        **design,
        "plate_table": plate_table(model),
        "plate_images": plate_images(images, model.results.get("plates")),
        "manual_settings": manual_settings(model.results.get("plates")),
        "project_step": project_step(model.results.get("plates")),
        "slice_numbers": slice_numbers(model.results.get("plates")),
        "coupon_legend": ("；plate0_coupons、plate0b_coupons 是作者打过的盘 0、盘 0b 试件"
                          if any(name.startswith(f"{PREFIX}plate0") for name in images) else ""),
        "cradle_plate": model.parts["cradle"].plate,
        "spacer_plate": model.parts["spacer"].plate,
        "tube_plate": model.parts["cooling_tube"].plate,
        "tube": f"外径 {number(p.cooling_tube_d)}、壁厚 {number(p.cooling_tube_wall)}",
        "tube_speed": COOLING_SPEEDS["outer_wall_speed"],
        "hex_wall": number(round((p.hex_af - p.screw_bore) / 2, 3)),
    }


def drop_missing_images(text, model):
    """Image lines of images this build did not make are left out; a note says why when the render process failed."""
    text = IMAGE_LINE.sub(lambda match: match.group(0) if (OUT_DIR / match.group(1)).exists() else "", text)
    problem = model.results.get("render_problem")
    if problem:
        title, rest = text.split("\n", 1)
        text = f"{title}\n\n**这台电脑没出渲染图**（{problem}），卡里的图都省掉了，其余照常。\n{rest}"
    return text


def write(model, images):
    text = TEMPLATE.read_text(encoding="utf-8")
    text = drop_missing_images(Template(text).substitute(template_values(model, images)), model)
    for old in OUT_DIR.glob(f"*{SUFFIX}"):
        old.unlink()
    path = OUT_DIR / f"{datetime.now().strftime('%Y-%m%d-%H%M')}{SUFFIX}"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
