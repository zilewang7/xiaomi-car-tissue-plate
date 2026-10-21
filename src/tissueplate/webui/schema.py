"""The config as the page edits it: Chinese name and help of every config key (KEYS, one place; a test checks that
every key of config.SCHEMA has one), validation in Chinese, redaction, config.toml import / export and the save rules
(webui design 3.3, 5.2).

State = the JSON the page sends, in the config.toml layout: {"numbers": {"a"}, "text": {"b", "l"}, "display": {...},
...}; each of faces A / B in exactly one of [numbers] / [text]. The messages never hold a number or a text: config.py
names positions and keys only, and redact() removes the submitted values and every run of 7+ digits on top of that.
"""
import dataclasses
import hashlib
import math
import os
import re
import secrets
import tomllib
from datetime import date, datetime, time
from pathlib import Path

from ..config import DIGIT_RUN, RETIRED, SCHEMA, ConfigError, check_field, parse_config
from ..free_text import EM_MAX
from ..params import FONT_URL, PROJECT_DIR, Params
from .platform import open_private

CONFIG_PATH = PROJECT_DIR / "config.toml"
EXAMPLE_PATH = PROJECT_DIR / "config.example.toml"
REDACTED = "•••"
BACKUPS_KEPT = 5
FACE_SECTIONS = ("numbers", "text")
SECTION_ORDER = ("numbers", "text") + tuple(SCHEMA)
PHONE_LIKE = re.compile(r"1[0-9]{10}")

SECTION_TITLES = {
    "display": ("显示", ""),
    "mount": ("安装", "唇板下的胶带厚度和挂片位置。三项要一起改：用垫厚预设。"),
    "detent": ("档位", "v3.4 只支持这一组值，只读。"),
    "box": ("纸巾盒实测", "在作者的盒子上量的（XIAOMI LIFE 车载磁吸纸巾盒，铭牌型号 O636）；同款盒子不用改。"),
    "fit": ("配合（不合适时改）", "默认值是作者在 P1S 上用盘 0 / 0b 选的。装配卡在粘之前逐个试配；哪一件不合适，就改它的键、只重打那一件"
                         "（小件和陪打柱 Q 同盘打）。盖片和 P 也可以直接在切片软件里缩放一点再打；C、K、EN 缩放会带歪别的配合面，要改键。"),
    "hardware": ("五金", ""),
}
# key -> (title, help, unit); choices of str / int keys: {value: title}
KEYS = {
    "display.logo": ("L 面图案", "「YU7 侧影」：侧影旁边一行字（不填就是 YU7 PRO）。「只放文字」：去掉侧影，L 面只放一行大字。"
                     "SU7 车主建议选「只放文字」。", ""),
    "display.condense": ("号码字宽", "号码的横向压缩，越小越窄。号码不会缩小字号去凑长度，放不下时报错。", ""),
    "display.white_layers": ("白字层数", "白字嵌色的深度 = 层数 × 0.2 mm。", "层"),
    "display.layout": ("号码排法", "「按字宽排」：字距相等、组距更宽；「固定格」：每个数字一格。", ""),
    "mount.stack": ("每摞磁铁", "每片挂片上下各一摞，每摞几颗 N52 8×3。", "颗"),
    "mount.delta_up": ("两摞磁铁上移", "挂片上下两摞磁铁的中心，比盒子的底座、盒盖磁点高多少。", "mm"),
    "mount.tab_bottom": ("挂片底边", "挂片下沿在盖顶以下多深（负数）。作者的 YU7 里，盖顶下 40 mm 以内前方有 8 mm 空隙。", "mm"),
    "mount.pad_t": ("胶带厚", "唇板下面的 3M VHB 双面胶厚度，两面都粘（牌子粘在盖上，补纸时连盖一起掀）。", "mm"),
    "detent.knob_stack": ("旋钮每瓣磁铁", "", "颗"),
    "detent.boss_h": ("止推凸台高", "", "mm"),
    "box.skirt": ("盒盖裙边高", "", "mm"),
    "box.mag_from_end": ("底座磁点离端面", "", "mm"),
    "box.mag_below_top": ("底座磁点在盖顶下", "", "mm"),
    "box.lid_mag_below_top": ("盒盖磁点在盖顶下", "上摞磁铁对着它。这组安装值下能建的范围约 8.8–11.55。", "mm"),
    "box.top_fillet": ("盖顶圆角", "估计值。", "mm"),
    "fit.near_hole": ("近端孔（托架 C）", "K 的圆轴在这里转。转不开：先手拧 Ø6.0 钻头铰孔（卡 §3-2），再加 0.05，只重打 C。", "mm"),
    "fit.far_hole": ("远端孔（托架 C）", "P 的圆轴在这里转，要转得开（卡 §3-5）。转不开：先铰孔，再加 0.05，只重打 C。", "mm"),
    "fit.far_hex_af": ("远端六角（P）", "P 的六角插进 EF 的六角孔（AF 5.20）。推不进（卡 §3-4）：减 0.05，只重打 P。", "mm"),
    "fit.hex_socket_af": ("EN 六角孔", "K 的六角插进 EN。推不进（卡 §3-3）：加 0.05，只重打 EN。", "mm"),
    "fit.hex_af": ("旋钮六角（K）", "K 插进 EN 后明显晃（卡 §3-3）：加 0.05，只重打 K。", "mm"),
    "fit.tab_cap_d": ("挂片盖片直径", "按不进（卡 §8）：减 0.05，只重打这一组盖片。偏松就照卡 §11 点胶，8.25 已是最大。", "mm"),
    "fit.knob_cap_d": ("旋钮盖片直径", "规则同挂片盖片，只重打这一组盖片。", "mm"),
    "fit.hub_cap_d": ("轴盖直径", "按不进（卡 §11-3）：减 0.05，只重打轴盖。6.40 已是最大，再大会碰沉孔。", "mm"),
    "hardware.screw_head_k": ("M3 头高", "M3×25 盘头螺钉的头高，旋钮沉孔按它做。头太高、轴盖压不平（卡 §11-3）：改成量到的值，只重打 K。",
                              "mm"),
}
CHOICE_TITLES = {"display.logo": {"final": "YU7 侧影", "speed_dramatic": "YU7 侧影（旧名）", "none": "只放文字"},
                 "display.layout": {"proportional": "按字宽排", "fixed": "固定格"}}
READ_ONLY = {"detent", "mount.stack"}
STEPS = {"fit": 0.05}
FACE_TITLES = {"a": "A 面", "b": "B 面", "l": "L 面文字"}
# [mount] presets (webui design 3.3): both give the same printed parts, only the card and the report differ
MOUNT_PRESETS = (
    {"id": "tape", "title": "1.2 mm 双面胶（作者实装）", "values": {"pad_t": 1.2, "delta_up": 2.45, "tab_bottom": -39.3}},
    {"id": "pads", "title": "0.5 mm 硅胶条（v3.3 设计值）", "values": {"pad_t": 0.5, "delta_up": 1.75, "tab_bottom": -40.0}},
)


# ---------------------------------------------------------------- schema for the page
def defaults():
    """{"section.key": default} from the Params fields (what a key that is not written takes)."""
    fields = {field.name: field.default for field in dataclasses.fields(Params)}
    return {f"{section}.{key}": fields[field] for section, keys in SCHEMA.items() for key, (field, _, _) in keys.items()}


def build_schema():
    """Sections and keys as the form shows them."""
    values = defaults()
    sections = []
    for section, keys in SCHEMA.items():
        title, help_text = SECTION_TITLES[section]
        rows = []
        for key, (_, kind, allowed) in keys.items():
            name = f"{section}.{key}"
            key_title, key_help, unit = KEYS[name]
            row = {"key": key, "name": name, "title": key_title, "help": key_help, "unit": unit, "kind": kind,
                   "default": values[name], "readonly": section in READ_ONLY or name in READ_ONLY}
            if kind == "float":
                row.update(min=allowed[0], max=allowed[1], step=STEPS.get(section, 0.01))
            else:
                titles = CHOICE_TITLES.get(name, {})
                row["choices"] = [{"value": value, "title": titles.get(value, str(value))} for value in allowed
                                  if not (name == "display.logo" and value == "speed_dramatic")]
            rows.append(row)
        sections.append({"name": section, "title": title, "help": help_text, "keys": rows})
    return {"sections": sections, "mount_presets": MOUNT_PRESETS,
            "retired": {section: sorted(keys) for section, keys in RETIRED.items()}, "font_url": FONT_URL,
            "text_em_max": EM_MAX}


# ---------------------------------------------------------------- redaction
def secrets_of(state):
    """The submitted numbers and texts, also without their spaces and dashes."""
    found = set()
    for section in FACE_SECTIONS:
        table = state.get(section) if isinstance(state, dict) else None
        for value in (table.values() if isinstance(table, dict) else ()):
            if isinstance(value, str) and value.strip():
                found.update({value, value.strip(), re.sub(r"[\s-]", "", value)})
    return sorted((secret for secret in found if secret), key=len, reverse=True)


def redact(text, hidden=()):
    for secret in hidden:
        text = text.replace(secret, REDACTED)
    return DIGIT_RUN.sub(REDACTED, text)


# ---------------------------------------------------------------- messages in Chinese
def _positions(text):
    return "、".join(text.replace(" ", "").strip("[]").split(","))


def _names(text):
    return "、".join(name.strip(" '\"") for name in text.split(","))


def _title(section, key):
    if section in FACE_SECTIONS:
        return FACE_TITLES.get(key, f"[{section}] {key}")
    return KEYS.get(f"{section}.{key}", (f"[{section}] {key}",))[0]


REACH = ((re.compile(r"more than this face allows \(([\d.]+) mm\): use other characters"), "超过这一面的上限 {0} mm：换别的字"),
         (re.compile(r"fewer characters give a larger size"), "少几个字，字号就能变大"))
LOGO_REASONS = ((re.compile(r"the line does not fit the usable area"), "这一行放不进可用区域"),
                (re.compile(r"the line runs into the sketch wherever it is placed"), "放在哪里都会碰到侧影"),
                (re.compile(r"the best position keeps only ([\d.]+) mm to the sketch"), "最好的位置也只离侧影 {0} mm"))
# (pattern, Chinese with {0}.. for the groups, optional group converters); the first match wins
MESSAGES = (
    (r"\[numbers\] (a|b) must be a quoted string of 11 digits starting with 1", "{face0}号码要填 11 位数字、1 开头"),
    (r"\[numbers\] (a|b) must be exactly 11 digits starting with 1 \(got (\d+) characters, (\d+) digits\)",
     "{face0}号码要正好 11 位数字、1 开头（现在是 {1} 个字符、{2} 位数字）；号码不会缩小或截断来凑"),
    (r"\[text\] (a|b|l) must be a quoted string", "「{face0}」要填文字"),
    (r"\[(\w+)\] (\w+) must be a number", "「{title}」要填数字"),
    (r"\[(\w+)\] (\w+) is outside the allowed range (-?[\d.]+) \.\. (-?[\d.]+)", "「{title}」超出允许范围 {2}–{3}"),
    (r"\[(\w+)\] (\w+) must be (-?[\d.]+|'\w+'): the only value v3.4 supports", "「{title}」只能是 {2}（v3.4 只支持这个值）"),
    (r"\[(\w+)\] (\w+) must be an integer", "「{title}」要填整数"),
    (r"\[(\w+)\] (\w+) must be a string", "「{title}」要选一项"),
    (r"\[display\] logo must be one of", "「L 面图案」只能选「YU7 侧影」或「只放文字」；L 面的文字填在「L 面文字」里"),
    (r"\[(\w+)\] (\w+) must be one of \[(.*?)\]", "「{title}」只能选 {names2}"),
    (r"unknown key\(s\) \[(.*?)\] in \[(\w+)\]", "[{1}] 里有不认识的键：{names0}"),
    (r"unknown section\(s\) \[(.*?)\]", "不认识的段：{names0}"),
    (r"\[(\w+)\] must be a table", "[{0}] 的格式不对"),
    (r"face (A|B) is set twice", "{0} 面同时填了号码和文字，只能留一个"),
    (r"face (A|B) needs", "{0} 面要填号码或文字"),
    (r"front bar layout does not fit this \[mount\]: (.*)\. pad_t, delta_up", "这组 [mount]（胶带厚、两摞磁铁上移、挂片底边）放不下"
     "（{0}）：用垫厚预设一次改三项"),
    (r"\[display\] condense is too large", "号码字宽太大，3-4-4 排不下（号码不会缩小字号）：调小，默认 0.86"),
    (r'\[display\] logo = "none" needs \[text\] l', "L 面选了「只放文字」，要填 L 面文字"),
    (r"font fonts/MiSans-Bold.ttf not found", "缺字体 fonts/MiSans-Bold.ttf：从 MiSans 官网下载，把 MiSans-Bold.ttf 放进 fonts/"),
    (r"logo geometry file for .* not found", "缺 L 面图案文件"),
    (r"character (\d+) is a control character", "第 {0} 个字是换行或制表符：每面只能一行"),
    (r"character (\d+) is an invisible format character", "第 {0} 个字是看不见的格式字符"),
    (r"character (\d+) is a combining mark", "第 {0} 个字是组合符号，单独打不出来"),
    (r"character (\d+) is not in MiSans-Bold.ttf", "第 {0} 个字 MiSans 里没有（会打成空框或别的字体）：换个字"),
    (r"character (\d+) does not print on its own", "第 {0} 个字单独打不出来"),
    (r"has no visible character", "没有看得见的字（一面不能空着）"),
    (r"too long for one line: condensed to ([\d.]+) the font size would be ([\d.]+) mm",
     "太长：压缩到 {0} 时字号只有 {1} mm，字号 × 压缩低于盘 0 打过的 8 mm；删短一些"),
    (r"at font size ([\d.]+) mm \(condense ([\d.]+)\), character\(s\) (\[[\d, ]+\]) have counters below [\d.]+ mm and would "
     r"print filled; they need about ([\d.]+) mm, (.*)", "字号 {0} mm 时，第 {pos2} 个字的字怀小于 0.8 mm，会糊成一块；要约 {3} mm 的字号，{reach4}"),
    (r"too long for the logo face: at the [\d.]+ mm minimum font size (.*) \(needs >= ([\d.]+) mm; (\d+) visible characters, "
     r"the first (\d+) visible characters fit\)", "侧影旁边放不下：最小字号 8 mm 时{logo0}（要离侧影 ≥ {1} mm；{2} 个可见字，前 {3} 个放得下）："
     "删短，或者 L 面选「只放文字」"),
    (r"character\(s\) (\[[\d, ]+\]) have counters below [\d.]+ mm at font size ([\d.]+) mm", "第 {pos0} 个字的字怀小于 0.8 mm（字号 {1} mm），会糊成一块"),
    (r"character\(s\) (\[[\d, ]+\]) have strokes below [\d.]+ mm at font size ([\d.]+) mm", "第 {pos0} 个字有一笔细于 0.7 mm（字号 {1} mm），会断"),
    (r"ink gap ([\d.]+) mm between characters", "有两个字之间只有 {0} mm，少于 0.5 mm"),
    (r"the CAD glyphs fail their checks", "CAD 字形检查没过：换别的字"),
    (r"cannot be cut into a closed solid", "切出来不是封闭实体：换别的字"),
)
COMPILED = tuple((re.compile(pattern), text) for pattern, text in MESSAGES)
SKETCH_LIMIT = re.compile(r' \(beside the sketch the font size is at most ([\d.]+) mm; \[display\] logo = "none" allows up to '
                          r'([\d.]+) mm\)')


def _replaced(regexes, text):
    for regex, chinese in regexes:
        match = regex.search(text)
        if match:
            return chinese.format(*match.groups())
    return text


def _one(part):
    for regex, text in COMPILED:
        match = regex.search(part)
        if match:
            groups = [value or "" for value in match.groups()]
            values = {"title": _title(*groups[:2]) if len(groups) >= 2 else ""}
            for index, value in enumerate(groups):
                values.update({f"face{index}": FACE_TITLES.get(value, value), f"pos{index}": _positions(value),
                               f"names{index}": _names(value),
                               f"reach{index}": _replaced(REACH, value), f"logo{index}": _replaced(LOGO_REASONS, value)})
            return text.format(*groups, **values)
    return part


def chinese(message):
    """Chinese for a ConfigError message of config.py / free_text.py / logo_text.py (the logo face joins several with
    '; '), the English text when no pattern knows it. Faces are named, positions kept, values never quoted."""
    tail = ""
    limit = SKETCH_LIMIT.search(message)
    if limit:
        message = message[:limit.start()] + message[limit.end():]
        tail = f"（侧影旁边字号最大 {limit.group(1)} mm；L 面选「只放文字」最大 {limit.group(2)} mm）"
    parts = [_one(part) for part in re.split(r"; (?=character|ink gap)", message)]
    return "；".join(dict.fromkeys(parts)) + tail


def positions_in(message):
    """Character positions (1-based) a face message names."""
    found = set()
    for match in re.finditer(r"character\(s\) \[([\d, ]+)\]|character (\d+)", message):
        found.update(int(value) for value in re.findall(r"\d+", match.group(1) or match.group(2)))
    return sorted(found)


# ---------------------------------------------------------------- validation
def _tables(state):
    if not isinstance(state, dict) or not all(isinstance(table, dict) for table in state.values()):
        raise ConfigError("[state] must be a table")
    return state


def field_messages(state):
    """[{"field", "level", "text"}] of the keys one by one (check_field), in Chinese."""
    messages = []
    for section, table in state.items():
        for key, value in table.items():
            name = f"{section}.{key}"
            if key in RETIRED.get(section, {}):
                messages.append({"field": name, "level": "warning", "text": f"[{section}] {key}：v3.4 起不用，读入时忽略，"
                                                                         "保存时去掉"})
                continue
            try:
                check_field(section, key, value)
            except ConfigError as error:
                messages.append({"field": name, "level": "error", "text": chinese(str(error))})
    return messages


def advice(state):
    """Warnings that do not stop the build (webui design 3.3)."""
    messages = []
    for key in ("a", "b"):
        text = state.get("text", {}).get(key)
        if isinstance(text, str) and PHONE_LIKE.fullmatch(text.strip()):
            messages.append({"field": f"text.{key}", "level": "warning",
                             "text": f"{key.upper()} 面填的像手机号：改用「号码」，两种排法不一样"})
    mount = {key: state.get("mount", {}).get(key, defaults()[f"mount.{key}"]) for key in ("pad_t", "delta_up", "tab_bottom")}
    if any(mount["pad_t"] != preset["values"]["pad_t"] and all(mount[key] == preset["values"][key]
                                                              for key in ("delta_up", "tab_bottom"))
           for preset in MOUNT_PRESETS):
        messages.append({"field": "mount.pad_t", "level": "warning",
                         "text": "只改了胶带厚：挂片长度和下孔会跟着变，两摞磁铁上移和挂片底边要一起改（用垫厚预设）"})
    logo = state.get("display", {}).get("logo", "final")
    line = state.get("text", {}).get("l")
    if logo != "none" and isinstance(line, str) and re.search(r"[㐀-鿿]", line):
        messages.append({"field": "text.l", "level": "warning", "text": "侧影旁边放中文多半放不下或打不清：中文建议选「只放文字」"})
    return messages


def validate(state):
    """{"ok", "messages"}: ok = parse_config accepts the whole config (the faces' layout is checked by the preview)."""
    try:
        state = _tables(state)
    except ConfigError:
        return {"ok": False, "messages": [{"field": None, "level": "error", "text": "格式不对"}]}
    hidden = secrets_of(state)
    messages = field_messages(state)
    if not any(message["level"] == "error" for message in messages):
        try:
            parse_config(state, source="web form")
        except ConfigError as error:
            messages.append({"field": None, "level": "error", "text": chinese(str(error))})
    messages += advice(state)
    for message in messages:                 # a key name may be a number someone typed there
        message["text"] = redact(message["text"], hidden)
        if message["field"] is not None:
            message["field"] = redact(message["field"], hidden)
    return {"ok": not any(message["level"] == "error" for message in messages), "messages": messages}


def unknown_names(data):
    """Sections and keys config.py does not know (retired keys excepted), masked: they block "save"."""
    names = []
    for section, table in data.items():
        if section not in SECTION_ORDER:
            names.append(f"[{section}]")
        elif isinstance(table, dict):
            known = ({"a", "b"} if section == "numbers" else {"a", "b", "l"}) if section in FACE_SECTIONS else (
                set(SCHEMA[section]) | set(RETIRED.get(section, {})))
            names += [f"[{section}] {key}" for key in table if key not in known]
    return [DIGIT_RUN.sub(REDACTED, name) for name in names]


# ---------------------------------------------------------------- config.toml text
def toml_string(text):
    escapes = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    return '"' + "".join(escapes.get(ch, f"\\u{ord(ch):04X}" if ord(ch) < 0x20 or ord(ch) == 0x7F else ch)
                         for ch in text) + '"'


def toml_value(value, kind):
    if kind not in ("float", "int"):
        return toml_string(str(value))
    try:
        number = float(value) if kind == "float" else int(value)
    except (TypeError, ValueError, OverflowError):      # null (the page sends NaN as null) or text: never quoted
        raise ConfigError("[state] values must be finite numbers") from None
    if kind == "int":
        return str(number)
    if not math.isfinite(number):
        raise ConfigError("[state] values must be finite numbers")
    return repr(number)


def to_toml(state):
    """config.toml of a state: every key written (a later change of a default does not change your parts), in the
    order of config.example.toml, Chinese comments; retired keys left out; A / B in one place each, l only when
    filled."""
    state = _tables(state)
    unknown = unknown_names(state)
    if unknown:
        raise ConfigError(f"unknown names {unknown}")
    values = defaults()
    lines = [f"# 挪车号码牌配置，网页 {datetime.now().strftime('%Y-%m-%d %H:%M')} 保存。只留在本机：里面有你的号码和文字，",
             "# 别上传它，也别上传用它做出的 3MF / STL / STEP / G-code / 渲染图。", ""]
    for section in FACE_SECTIONS:
        table = {key: value for key, value in state.get(section, {}).items() if isinstance(value, str) and value != ""}
        if table:
            lines.append(f"[{section}]")
            lines += [f"{key} = {toml_string(value)}  # {FACE_TITLES[key]}" for key, value in table.items()]
            lines.append("")
    for section, keys in SCHEMA.items():
        lines.append(f"[{section}]  # {SECTION_TITLES[section][0]}")
        for key, (_, kind, _) in keys.items():
            name = f"{section}.{key}"
            value = state.get(section, {}).get(key, values[name])
            title, _, unit = KEYS[name]
            lines.append(f"{key} = {toml_value(value, kind)}  # {title}{f'（{unit}）' if unit else ''}")
        lines.append("")
    return "\n".join(lines)


def from_toml(text):
    """(state, messages) of a config.toml text; state is None when the text is not TOML (the message names only the
    line and column, never the content)."""
    try:
        state = tomllib.loads(text)
    except (ValueError, RecursionError) as error:     # a TOMLDecodeError; or a 5000-digit integer, arrays too deep
        where = re.search(r"\(at line (\d+), column (\d+)\)", str(error))
        return None, [{"field": None, "level": "error",
                       "text": f"不是有效的 TOML（第 {where.group(1)} 行第 {where.group(2)} 列）" if where else "不是有效的 TOML"}]
    messages = [{"field": None, "level": "error", "text": f"有不认识的段或键：{'、'.join(names)}。请先在文件里改好再读入；"
                                                          "这样拼错的键不会在保存时被悄悄丢掉。", "blocks_save": True}
                for names in [unknown_names(state)] if names]
    state = {section: table for section, table in state.items() if section in SECTION_ORDER and isinstance(table, dict)}
    for section in list(state):
        known = set(SCHEMA.get(section, {})) | set(RETIRED.get(section, {})) | {"a", "b", "l"}
        state[section] = {key: value for key, value in state[section].items() if key in known}
    result = validate(state)
    return _json_values(state), messages + result["messages"]


def _json_values(value):
    """value with TOML dates, times, nan and inf as text: JSON has none of them (validate() has flagged them)."""
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_values(item) for item in value]
    if isinstance(value, (date, time)):                  # a datetime is a date too
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):          # TOML nan, inf (and 1e400)
        return str(value)
    return value


# ---------------------------------------------------------------- reading and saving config.toml
def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read_config(path=CONFIG_PATH):
    """{"state", "sha256", "messages"} of config.toml (None when there is none)."""
    if not path.exists():
        return None
    state, messages = from_toml(path.read_text(encoding="utf-8"))
    return {"state": state, "sha256": sha256_of(path), "messages": messages}


class SaveConflict(Exception):
    """config.toml changed since the page read it (409), or exists and the page never read it (428), or a face of
    the state is not a string or holds the redaction mark (422)."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


def remove_stale_temp(path=CONFIG_PATH):
    for stale in path.parent.glob(f"{path.name}.tmp-*"):
        stale.unlink(missing_ok=True)


def _private_copy(source, target):
    with open_private(target) as handle:
        handle.write(source.read_text(encoding="utf-8"))


def save_config(state, expected_sha256, overwrite=False, path=CONFIG_PATH):
    """Atomic save (webui design 3.3): only if config.toml is still what the page read (sha256), or the page never
    read it and the user confirmed overwriting; the old file goes to config.toml.orig.bak (first save only, never
    overwritten) and config.toml.<time>.bak (the newest BACKUPS_KEPT kept); every file 0600."""
    text = to_toml(state)
    for section in FACE_SECTIONS:           # a redacted or mangled face must never replace the real one
        for value in state.get(section, {}).values():
            if not isinstance(value, str) or REDACTED in value:
                raise SaveConflict(422, "号码或文字不对（不是字符串，或者是脱敏后的 •••）：没有保存，请重新读取")
    current = sha256_of(path)
    if expected_sha256 is None and current is not None and not overwrite:
        raise SaveConflict(428, "config.toml 已经存在，页面没读过它：确认后才会用页面上的内容覆盖（原文件留在备份里）")
    if expected_sha256 is not None and current != expected_sha256:
        raise SaveConflict(409, "config.toml 在外面被改过：请先重新读取")
    if current is not None:
        original = path.with_name(path.name + ".orig.bak")
        if not original.exists():
            _private_copy(path, original)
        stamp = datetime.now().strftime("%Y-%m%d-%H%M%S-%f")        # microseconds: saves in one second keep apart
        _private_copy(path, path.with_name(f"{path.name}.{stamp}.bak"))
        stamped = sorted(path.parent.glob(f"{path.name}.[0-9]*.bak"))
        for old in stamped[:-BACKUPS_KEPT]:
            old.unlink()
    temp = path.with_name(f"{path.name}.tmp-{secrets.token_hex(4)}")
    with open_private(temp, exclusive=True) as handle:
        handle.write(text)
    os.replace(temp, path)
    return sha256_of(path)
