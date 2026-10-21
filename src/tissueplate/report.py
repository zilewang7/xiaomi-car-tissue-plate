"""Build report out/report.md (spec 7 deliverable): checks, calibrated fits, slicing per plate (v3.2 for comparison),
the v3.3 changes, deliverables.

    write(model) -> path of out/report.md (build_all hook "report", runs after checks / plates / renders)

Reads model.results ("geometry", "checks", "plates", "renders", "render_problem", "assembly_card") and, when plates
0 / 0b were built, the project's out/plate0/slice_summary.json and out/plate0b/slice_summary.json (read only, also for
a build into another folder). Check 11 (slicing) is judged here from the slicing results ("not sliced" in no-slicer
mode). The report never contains the phone numbers or texts: it only quotes check items, which hold
layout statistics and character positions, not digits or characters.
"""
import json
from datetime import datetime
from pathlib import Path

from .assembly_card import fit_note
from .bambu import COOLING_SPEEDS, PIN_BRIM
from .export3mf import MIN_SMALL_LAYER_S, PLATES_DIR, PROJECT_FILE
from .params import OUT_DIR, PROJECT_DIR, font_is_authors

REPORT_PATH = OUT_DIR / "report.md"
PLATE0_DIR = PROJECT_DIR / "out" / "plate0"          # the author's coupon plates: never rebuilt by build_all
PLATE0B_DIR = PROJECT_DIR / "out" / "plate0b"
COLOUR_NAMES = {"white": "白", "azure": "天蓝", "navy": "藏青"}
# for comparison: v3.2 as built (2026-10-14 01:43) and v3.3 option E as three projects (2026-10-16 04:23)
V32_TOTALS = {"minutes": 245.3, "grams": 83.37, "filament_changes": 18}
THREE_PLATE_TOTALS = {"minutes": 246.0, "grams": 83.67, "filament_changes": 18}
V32_MASS_G = 98.6           # CAD x fill (v3.2 report)
TEST_PLATES = (("0", PLATE0_DIR, "盘0试验卡"), ("0b", PLATE0B_DIR, "盘0b试验卡"))


# ---------------- helpers ----------------
def relative(path):
    path = Path(path)
    return (path.relative_to(PROJECT_DIR) if path.is_relative_to(PROJECT_DIR) else path).as_posix()


def number(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def minutes_text(minutes):
    return f"{int(minutes // 60)} h {minutes % 60:.0f} min（{minutes:.0f} min）"


def grams_text(grams, total):
    parts = [f"{COLOUR_NAMES.get(colour, colour)} {value:.2f}" for colour, value in grams.items()]
    return f"{total:.2f} g（{'、'.join(parts)}）"


def status_text(ok):
    if ok is None:
        return "未判定"
    return "通过" if ok else "**未通过**"


def cell(value):
    """Markdown table cell: lists / dicts as JSON, pipes escaped."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("|", "\\|")


def span_text(values):
    return " / ".join(f"{value:.3f}" for value in values)


def load_test_plates():
    """{plate: slice_summary} of the coupon plates 0 / 0b found under out/ (they are never rebuilt here)."""
    found = {}
    for name, directory, _ in TEST_PLATES:
        summary = directory / "slice_summary.json"
        if summary.exists():
            found[name] = json.loads(summary.read_text(encoding="utf-8"))
    return found


def test_plate_ok(summary):
    checks = summary["checks"]
    return all(value for value in checks.values() if isinstance(value, bool))


# ---------------- sections ----------------
def faces_text(model):
    """What the three faces carry (v3.4 6.11: L default / custom wordmark / text only), sizes only."""
    parts = []
    for name in ("A", "B"):
        layout = model.reports["faces"][name]["layout"]
        parts.append(f"{name} 文字（字号 {layout['em']:.2f} mm、压缩 {layout['condense']:.2f}）" if layout["mode"] == "text"
                     else f"{name} 号码")
    logo = model.reports["logo"]
    mode = logo.get("mode")
    if mode == "wordmark":
        parts.append(f"L 自定义字（侧影旁边，字号 {logo['em']:.2f} mm，离图案 {logo['clearance']:.2f} mm）")
    elif mode == "text":
        parts.append(f"L 只放文字（字号 {logo['em']:.2f} mm、压缩 {logo['condense']:.2f}）")
    else:
        parts.append("L 默认（YU7 侧影和「YU7 PRO」）")
    return "、".join(parts)


def summary_lines(model, test_plates):
    geometry, checks, plates = (model.results.get(key) for key in ("geometry", "checks", "plates"))
    lines = ["## 结论", ""]
    if geometry is not None:
        lines.append(f"- 几何验证：{status_text(geometry['ok'])}（实体有效、打印姿态、静止干涉和两对标定配合、v3.1 比对）。")
    if checks is not None:
        glued = checks["sections"]["10_couple_loop"]["numbers"]["levels_90C_E100"]["glue intact, min shear (hard)"]
        lines.append(f"- 自动检查 ①–⑩：硬性项 {status_text(checks['ok'])}（{len(checks['hard_failures'])} 项失败），"
                     f"警告 {len(checks['warnings'])} 条；⑩ 已改为硬性：90 ℃ 胶完好时近端唇板抬起 {span_text(glued)} mm"
                     "（≤ 0.20，按两位小数）。")
    if plates is not None and not plates["sliced"]:
        lines.append(f"- 切片 ⑪：**未切片**（{plates['reason']}）：没有 3MF，装配卡 §1 列出了要在切片软件里手动设的项。")
    elif plates is not None:
        tests = "；".join(f"盘 {name}：{status_text(test_plate_ok(summary))}" for name, summary in test_plates.items())
        lines.append(f"- 切片 ⑪（`{plates['file']}`，一个文件 {len(plates['plates'])} 盘）：{status_text(plates['ok'])}"
                     + (f"；{tests}（已打过，本次只读取）" if tests else "") + "。")
    if model.results.get("render_problem"):
        lines.append(f"- 渲染图：这台电脑没出（{model.results['render_problem']}），其余照常。")
    lines.append(f"- 本次配置：`{Path(model.config.source).name}`。")
    lines.append(f"- 三面：{faces_text(model)}。")
    if not font_is_authors():
        lines.append("- 字体和作者的不同（作者用的是 MiSans 4.009），排版可能略有差别。")
    lines.append(f"- 孔径、六角、盖片、白字层数：{fit_note(model.params)}")
    return lines + [""]


def calibrated_fit_lines(clash):
    fits = clash.get("calibrated_fits", {})
    if not fits:
        return []
    lines = ["- 标定配合（盘 0 试条选值比 CAD 里的轴小，重叠是有意的；判法：重叠只在轴的圆柱 × 孔段内、体积等于解析值 ±5 %、"
             "孔径在试条范围内）："]
    for name, fit in fits.items():
        lines.append(f"  - {name}（{fit['pair']}）：孔 Ø{fit['hole_d']:.2f} / 轴 Ø{fit['shaft_d']:.2f}，径向重叠 "
                     f"{fit['radial_overlap']:g}，交体积 {fit['common_volume']:g} mm³（解析 {fit['expected_volume']:g}，"
                     f"区域外 {fit['outside_zone_volume']:g}），{status_text(fit['ok'])}——{fit['reason']}。")
    if clash.get("calibrated_fits_not_found"):
        lines.append(f"  - 没找到的标定配合：{clash['calibrated_fits_not_found']}")
    return lines


def geometry_lines(geometry):
    validity, poses, clash = geometry["validity"], geometry["print_poses"], geometry["interference"]
    valid = sum(1 for row in validity["bodies"].values() if row["valid"])
    lines = ["## 1 几何验证", "",
             f"- 实体有效：{valid}/{len(validity['bodies'])}；打印姿态（贴床、嵌色只在前几层）：{status_text(poses['ok'])}。",
             f"- 静止干涉：测了 {clash['pairs_tested']} 对，最大交体积 {clash['max_common_volume']:.3g} mm³，"
             f"超限 {clash['offenders'] or '无'}。"]
    for pair, fit in clash.get("press_fits", {}).items():
        lines.append(f"- 预期压配 {pair}：交体积 {fit['volume']} mm³（上限 {fit['limit']}），{status_text(fit['ok'])}"
                     f"——{fit['reason']}。")
    lines += calibrated_fit_lines(clash)
    parity = geometry.get("v31_parity")
    if parity is None:
        lines.append("- v3.1 比对：未运行。")
    elif parity.get("skipped"):
        lines.append(f"- v3.1 比对：跳过（{parity['skipped']}）。")
    else:
        aligned = "、".join(f"{name} {value:g}" for name, value in parity.get("aligned_fit_constants", {}).items())
        lines.append(f"- v3.1 比对：{status_text(parity['ok'])}；意外差异 {parity['unexpected_differences'] or '无'}"
                     + (f"（v3.1 参考件先对齐配合常数：{aligned}）" if aligned else "") + "。")
        reset = "、".join(f"{name} {ours:g} → {theirs:g}" for name, (ours, theirs) in parity["reset_to_v31"].items())
        if reset:
            lines.append(f"  - 比对用的是另建的模型（不导出），这几项改回 v3.1 的值：{reset}。")
        for name, row in parity["parts"].items():
            if row["intended"]:
                lines.append(f"  - {name}：体积 {row['volume_diff_pct']:+.2f} %（允许 ±{number(row['bound_pct'])} %）"
                             f"——{row['intended']}")
    return lines + [""]


def couple_loop_lines(checks):
    """Check 10 levels (v3.3 2.5): only the glue-intact row is judged."""
    levels = checks["sections"]["10_couple_loop"]["numbers"]["levels_90C_E100"]
    lines = ["⑩ 90 ℃、ABS E 100 MPa 时近端唇板抬起（旋钮凸台受力点在下沿 / 中心，mm）：只判\"胶完好、候选全集最小剪力\"这一行"
             "（≤ 0.20，按两位小数），其余是信息：", ""]
    lines += [f"- {name}：{span_text(values)}" for name, values in levels.items()]
    return lines + [""]


def checks_lines(checks):
    lines = ["## 2 自动检查 ①–⑩", "",
             "| 节 | 结果 | 判定项 | 警告 |", "|---|---|---|---|"]
    for key, sec in checks["sections"].items():
        judged = [entry for entry in sec["items"] if entry["level"] != "info"]
        warned = sum(1 for entry in sec["items"] if entry["level"] == "warn" and not entry["ok"])
        result = "见 §3" if key.startswith("11_") else status_text(sec["ok"])
        lines.append(f"| {sec['title']} | {result} | {len(judged)} | {warned} |")
    lines.append("")
    if checks["hard_failures"]:
        lines += ["硬性项失败（原文）：", ""] + [f"- `{entry}`" for entry in checks["hard_failures"]] + [""]
    if checks["warnings"]:
        lines += ["警告（原文，不影响构建）：", ""] + [f"- `{entry}`" for entry in checks["warnings"]] + [""]
    lines += couple_loop_lines(checks)
    mass = checks["mass"]
    lines += [f"质量（CAD × 填充率）{mass['total_g']:.1f} g（v3.2 {V32_MASS_G:g} g），其中转子组件 "
              f"{mass['rotor_assembly_g']:.1f} g；磁铁 {mass['magnets_n']} 颗。全部判定项见附录。", ""]
    return lines


def plate_row(number_text, contents, ok, objects, slice_numbers):
    warning = slice_numbers["warning"] or "无"
    return (f"| {number_text} | {contents} | {status_text(ok)} | {objects} | {minutes_text(slice_numbers['minutes'])} | "
            f"{grams_text(slice_numbers['grams'], slice_numbers['grams_total'])} | {slice_numbers['filament_changes']} | "
            f"{warning} |")


def slicing_lines(plates, test_plates):
    lines = ["## 3 切片 ⑪（Bambu Studio CLI，项目内置设置）", "",
             "| 盘 | 内容 | 检查 | 对象数 | 时间 | 克重（含冲洗） | 换色 | 警告 |",
             "|---|---|---|---|---|---|---|---|"]
    for name, summary in test_plates.items():
        sliced = summary["plates"][0]
        lines.append(plate_row(name, f"试件 {len(summary['positions'])} 个（已打）", test_plate_ok(summary),
                               len(sliced["objects"]), sliced))
    if plates is not None and not plates["sliced"]:
        lines += ["", f"盘 1–{len(plates['plates'])} **未切片**（{plates['reason']}）：没有 3MF，也没有切片检查；"
                      "装配卡 §1 末尾列出了每件要在切片软件里手动设的项。"]
    elif plates is not None:
        for number_text, entry in plates["plates"].items():
            lines.append(plate_row(number_text, entry["contents"], entry["ok"], len(entry["objects"]), entry["slice"]))
        totals = plates["totals"]
        lines += ["", f"盘 1–{len(plates['plates'])} 都在 `{plates['file']}` 里，合计：{minutes_text(totals['minutes'])}，"
                      f"{grams_text(totals['grams'], totals['grams_total'])}，换色 {totals['filament_changes']} 次"
                      f"（三个文件三盘时 {THREE_PLATE_TOTALS['minutes']:.0f} min、{THREE_PLATE_TOTALS['grams']:.2f} g、换色 "
                      f"{THREE_PLATE_TOTALS['filament_changes']} 次；v3.2：{V32_TOTALS['minutes']:.0f} min、"
                      f"{V32_TOTALS['grams']:.2f} g、换色 {V32_TOTALS['filament_changes']} 次）。"]
        cooling = []
        for number_text, entry in plates["plates"].items():
            if entry["small_part_layer_time"]:
                name, worst = min(entry["small_part_layer_time"].items(), key=lambda item: item[1]["min_layer_s"])
                cooling.append(f"盘 {number_text} {name} {worst['min_layer_s']:g} s（Z {worst['at_z']:g}）")
        if cooling:
            lines.append(f"- 小件冷却（小件所在各层里最短的整层时间，下限 {MIN_SMALL_LAYER_S:g} s）：{'；'.join(cooling)}。")
        for number_text, entry in plates["plates"].items():
            failed = [name for name, ok in entry["checks"].items() if not ok]
            if failed:
                lines.append(f"- 盘 {number_text} 未通过的检查：{failed}")
        overall = [name for name, ok in plates["checks"].items() if not ok]
        if overall:
            lines.append(f"- 未通过的整体检查：{overall}")
    for name, summary in test_plates.items():
        failed = [key for key, value in summary["checks"].items() if isinstance(value, bool) and not value]
        if failed:
            lines.append(f"- 盘 {name} 未通过的检查：{failed}")
    lines += ["", "每盘检查：每件一个切片对象（多色件 = 一个对象 + 多个零件）、位置和排版一致、无警告、G-code 换色次数与 "
                  "result.json 一致、换色只在嵌色层、只有多色盘有擦料塔且在床内不碰零件、brim 用藏青且只在零件周围、"
                  f"小件和销（旋钮、端塞、远端销、盖片、垫片）所在的每一层整层用时 ≥ {MIN_SMALL_LAYER_S:g} s（按 G-code 里的速度"
                  "估算；它们都和陪打柱 Q 或托架 C 同盘）；整个文件："
                  "CLI 回读后耗材分配不变、每件只在一盘。", ""]
    return lines


def change_lines(model):
    """v3.3 changes against v3.2 as built (design doc section 0), with the values of this build."""
    p = model.params
    reports = model.reports
    stacks = 2 * p.mount_stack
    tab_magnets = sum(1 for name in model.hardware if name.startswith("mag_tab"))
    magnets = sum(1 for name in model.hardware if name.startswith("mag_"))
    seams = reports["line_seams"]
    screw = reports["screw"]
    caps = {prefix: sum(1 for name in model.parts if name.startswith(prefix)) for prefix in ("cap_tab", "cap_knob")}
    return ["## 4 v3.3 相对 v3.2 的变化（设计稿 §0，按本次构建的值）", "",
            f"- 挂片磁铁：每片 {stacks} 颗。下摞不变（Z {p.mount_z:g}，画点面朝盒子），加上摞 {p.mount_stack} 颗在 Z {p.upper_z:g}"
            f"（盖磁点 {p.lid_mag_z:.1f} 上方 {p.upper_delta:g}，无点面朝盒子）；两片相同；全件 {magnets} 颗（挂片 {tab_magnets}）。",
            f"- 挂片背面导向倒角：取消顶边那段，两侧和 R10 底边保留 {p.tab_leadin:g}×45°；平背面到 Z {p.flat_back_top:g}，托住"
            "整个上孔底（⑨ 射线复核）。",
            f"- 横梁装饰（方案 E）：8 片盖片全用藏青，正面没有圆点；天蓝细线一整条，移到 Z {p.beam_line_z:g}（上孔上方），"
            f"到横梁顶倒角 / 上孔口的藏青缝 {seams['to_top']:.2f} / {seams['to_upper_pocket']:.2f}。",
            f"- 轴承孔和六角按盘 0 试条选值：近端 {p.hole_near:.2f}、远端 {p.hole_far:.2f}、AF "
            f"{p.hex_af:.2f}（v3.2 名义 6.30 / 6.00 / 5.00）；前两个比 CAD 轴小，按标定配合判（§1）。"
            f"v3.4：远端销 P 的六角 AF {p.far_hex_af:.2f} 插 EF 六角孔（AF {p.far_socket_af:.2f}），取代 Ø6.10 远端塞圆孔。"
            f"EN 六角孔 AF {p.hex_socket_af:.2f}（10-16 正式件旋钮卡死后从 5.15 放大，旋钮陪打柱设计稿）。",
            f"- 盖片（藏青）：挂片 Ø{p.tab_cap_d:.2f}×{p.cap_t:g} ×{caps['cap_tab']}、旋钮 Ø{p.knob_cap_d:.2f}×{p.knob_cap_t:g} "
            f"×{caps['cap_knob']}、轴盖 Ø{p.hub_cap_d:.2f}×"
            f"{p.hub_cap_t:g}（v3.2 Ø8.1 / Ø8.1 / Ø6.2×0.4），每片边上 1 个 Ø{p.cap_notch_d:.1f} 撬口；垫片 S Ø{p.spacer_d:g} 压配不变。"
            "粘法：挂片、旋钮盖片整圈涂胶 + 背后一小点，轴盖点一点胶，验收后再粘。",
            f"- 旋钮沉孔 / 近端塞底孔：{screw['counterbore']:g} / {screw['pilot_depth']:g}（v3.2 3.0 / 6.5；M3 头高按 "
            f"{p.screw_head_k:g}，没量）；近端塞底 {screw['en_pilot_floor']:g}，螺钉尖到底孔底 {screw['tip_to_pilot_bottom']:g}。",
            "- 销孔：取消（10-18：横梁直接粘在唇板下，没用定位销）；横梁、托架都没有销孔。",
            "- 检查 ⑩：按胶完好判，硬性 ≤ 0.20（两位小数），剪力取候选全集最小（v3.2：胶软 + 销间隙，警告级）；胶软、"
            "不连接改为信息（10-18 起没有销，脱粘 = 不连接）。v3.2 报告里\"需要你决定\"那一节已关闭。",
            "- 检查 ⑦ / ⑧：挂片按两个盒磁铁 × 两摞（含交叉项）计算，候选全集 285 组（含 Ø5–8 盖磁铁），LP 按每摞单独的点和力；"
            "各项约为 v3.2 的 2 倍（附录）。",
            "- Logo 笔尖 0.6 → 0.7 圆头；嵌色硬下限 线 / 缝 / 孔 0.7 / 0.5 / 0.8（盘 0 阶梯 L）；号码字怀膨胀检查 0.6 → 0.8；"
            f"白字 {p.white_layers} 层。",
            "- 装 / 取：整盒拿出后水平推到贴合 / 从一端掰下；车内只能竖直装（装配卡 §12）。",
            "- 出盘：一个 3MF 两盘（两盘设计稿）。盘 1 彩色放全部嵌色件，换色只在头 4 层做一轮；盘 2 藏青放其余件，"
            "不换色、没有擦料塔（v3.2 / v3.3 之前是三个文件三盘）。",
            f"- 陪打柱 Q：旋钮旁边一根和它一样高的空心管（外径 {p.cooling_tube_d:g}、壁厚 {p.cooling_tube_wall:g}，自身按 "
            f"{COOLING_SPEEDS['outer_wall_speed']} mm/s 打），打完扔掉。旋钮单独打时每层只有 2–3 s，六角很可能过热打胖，卡死在 EN 里"
            "（10-16）；有 Q 后旋钮照常速度打，每层约 12 s。",
            "- v3.2 构建时的修正全部沿用：S Ø8.4 压配、换档反向力由 S 和整圈粘牢的盖片承担、远端销 P "
            f"{PIN_BRIM['brim_width']} mm brim。", ""]


def deliverable_lines(model):
    renders = model.results.get("renders") or {}
    card = model.results.get("assembly_card")
    lines = ["## 5 交付文件", ""]
    plate_files = [path for _, directory, _ in TEST_PLATES for path in sorted(directory.glob("*.3mf"))]
    plate_files += [path for path in (PLATES_DIR / PROJECT_FILE,) if path.exists()]
    lines.append("- 3MF（已带耗材分配，打开直接切片）：" + ("、".join(f"`{relative(path)}`" for path in plate_files)
                                                     or "没有（未切片）"))
    print_dir, assembled_dir = OUT_DIR / "parts" / "print", OUT_DIR / "parts" / "assembled"
    lines.append(f"- STL / STEP：`{relative(print_dir)}/`（打印姿态，{len(list(print_dir.glob('*.stl')))} 个 STL、"
                 f"{len(list(print_dir.glob('*.step')))} 个 STEP）、`{relative(assembled_dir)}/`（装配姿态，"
                 f"{len(list(assembled_dir.glob('*.stl')))} 个 STL）、`{relative(OUT_DIR / 'parts' / 'assembly.step')}`")
    if renders:
        lines.append("- 渲染图：" + "、".join(f"`{relative(path)}`" for path in renders.values()))
    elif model.results.get("render_problem"):
        lines.append("- 渲染图：没有（这台电脑没出）")
    if card is not None:
        lines.append(f"- 装配卡：`{relative(card)}`")
    for name, directory, card_name in TEST_PLATES:
        for test_card in sorted(directory.glob(f"*-{card_name}.md")):
            lines.append(f"- 盘 {name} 试验卡（含你的结果）：`{relative(test_card)}`")
    details = [OUT_DIR / "parts" / "geometry_report.json", OUT_DIR / "checks" / "checks_report.json",
               OUT_DIR / "plates" / "slice_report.json"]
    details += [directory / "slice_summary.json" for _, directory, _ in TEST_PLATES]
    lines.append("- 明细：" + "、".join(f"`{relative(path)}`" for path in details if path.exists()))
    return lines + [""]


def privacy_lines():
    return ["## 6 隐私", "",
            "- 号码和文字只在本机 `config.toml`（已在 .gitignore）；本报告不含号码和文字。",
            "- `out/` 里的 3MF、STL、STEP 和渲染图都含号码或文字：只在本机切片，用局域网或 SD 卡打印；不要上传 MakerWorld，"
            "也不要用拓竹云打印（会上传 3MF）。", ""]


def appendix_lines(checks):
    lines = ["## 附录：全部判定项（hard = 硬性，warn = 警告级）", ""]
    for sec in checks["sections"].values():
        judged = [entry for entry in sec["items"] if entry["level"] != "info"]
        if not judged:
            continue
        lines += [f"**{sec['title']}**", "", "| 项 | 值 | 限值 | 级别 | 结果 |", "|---|---|---|---|---|"]
        for entry in judged:
            result = "通过" if entry["ok"] else ("**未通过**" if entry["level"] == "hard" else "警告")
            lines.append(f"| {cell(entry['name'])} | {cell(entry['value'])} | {cell(entry['limit'])} | {entry['level']} | "
                         f"{result} |")
        lines.append("")
    return lines


def write(model):
    checks, plates, geometry = (model.results.get(key) for key in ("checks", "plates", "geometry"))
    test_plates = load_test_plates()
    lines = ["# 挪车号码牌 v3.4 构建报告", "",
             f"生成：{datetime.now().strftime('%Y-%m-%d %H:%M')}（`scripts/build_all.py`）。本报告不含号码和文字。", ""]
    lines += summary_lines(model, test_plates)
    if geometry is not None:
        lines += geometry_lines(geometry)
    if checks is not None:
        lines += checks_lines(checks)
    lines += slicing_lines(plates, test_plates)
    lines += change_lines(model)
    lines += deliverable_lines(model)
    lines += privacy_lines()
    if checks is not None:
        lines += appendix_lines(checks)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return REPORT_PATH
