# YU7 挪车号码牌 v3.2 构建报告

生成：2026-10-14 01:43（`scripts/build_all.py`）。本报告不含号码。

## 结论

- 几何验证：通过（实体有效、打印姿态、静止干涉、v3.1 比对）。
- 自动检查 ①–⑩：硬性项 通过（0 项失败），警告 2 条。
- 切片 ⑪（盘 1–3）：通过；盘 0：通过。
- **先打盘 0 并回传**：盘 1–3 现在是按名义孔径、名义白字层数生成的预览。盘 0 的结果填进 `config.toml`（`[fit]` 的孔径和六角、`[display] white_layers`）后重跑 `scripts/build_all.py`，再打盘 1–3。
- **需要你决定**：AB 胶高温变软时托架刚度不达标（检查 ⑩ 的 2 条警告），见 §5。

## 1 几何验证

- 实体有效：46/46；打印姿态（贴床、嵌色只在前几层）：通过。
- 静止干涉：测了 83 对，最大交体积 0 mm³，超限 无。
- 预期压配 cradle.navy & spacer.navy：交体积 1.2739 mm³（上限 5.0），通过——spacer S Ø8.4 pressed into the Ø8.3 stator pocket (review M3)。
- v3.1 比对：通过；意外差异 无。
  - cradle：体积 -0.06 %（允许 ±1 %）——v3.2: dowel holes 3 -> 6 (Ø1.9, X = -93.5 .. 93.5 evenly)
  - front_bar：体积 -0.12 %（允许 ±1 %）——v3.2: dowel holes 3 -> 6, teardrops (review INT-4); tab bottom true R10 arc instead of a 96-gon; azure line inlay split out of the navy body (sum unchanged)
  - knob：体积 +0.00 %（允许 ±1 %）——white A / B / ◆ letter inlays split out of the navy body (sum unchanged)
  - spacer：体积 +4.94 %（允许 ±6 %）——review M3: stator spacer Ø8.2 -> 8.4, press fit
  - caps：体积 -21.32 %（允许 ±40 %）——review m4: tab / knob caps Ø8.2 -> 8.1, knob caps 0.6 -> 0.4 thick, hub cap Ø6.38 x 0.6 -> Ø6.2 x 0.4

## 2 自动检查 ①–⑩

| 节 | 结果 | 判定项 | 警告 |
|---|---|---|---|
| 1 typography and layout | 通过 | 16 | 0 |
| 2 sweep radius at the chamfer corners, clearance to the lip | 通过 | 3 | 0 |
| 3 static interference 0, running clearances over 0-120 deg | 通过 | 7 | 0 |
| 4 envelope Y >= -32, length <= 200 | 通过 | 2 | 0 |
| 5 configuration paths (assembly, refill: whole box out, plate off before the lid) | 通过 | 7 | 0 |
| 6 visibility from outside (ray casting) | 通过 | 1 | 0 |
| 7 magnet model (mount pull both stacks, detent, dead zone, snap, floors) | 通过 | 9 | 0 |
| 8 3D rigid-body LP at 80 C weakest (gestures, pinch, braking, lift-off) | 通过 | 5 | 0 |
| 9 hole walls >= 1.2 (pressed 0.8 floors excepted), horizontal holes are teardrops | 通过 | 16 | 0 |
| 10 detent couple loop: journals, far-force flip, lip lift (v3.2 dowel joint, soft epoxy) | 通过 | 2 | 2 |
| 11 per-plate CLI slicing (judged by the slicing step) | 见 §3 | 0 | 0 |

警告（原文，不影响构建）：

- `10_couple_loop: lip lift 90 C, E 100, epoxy soft, 6 dowels bearing without play (mm) = [0.11857, 0.34582] (limit <= 0.2 (spec 4.3: stiffness kept when the epoxy softens))`
- `10_couple_loop: lip lift 90 C, E 100, epoxy soft, 6 dowels with the Ø1.9 hole / Ø1.75 filament play (mm) = [0.20479, 0.61675] (limit <= 0.2 (spec 4.3: stiffness kept when the epoxy softens))`

质量（CAD × 填充率）98.6 g，其中转子组件 51.3 g。全部判定项见附录。

## 3 切片 ⑪（Bambu Studio CLI，项目内置设置）

| 盘 | 内容 | 检查 | 对象数 | 时间 | 克重（含冲洗） | 换色 | 警告 | §5 估计 |
|---|---|---|---|---|---|---|---|---|
| 0 | 试件 25 个 | 通过 | 25 | 3 h 11 min（191 min） | 66.05 g（白 3.10、藏青 62.94） | 5 | 无 | 90 min |
| 1 | panels PA PB PL | 通过 | 3 | 1 h 33 min（93 min） | 38.03 g（白 5.57、天蓝 1.30、藏青 31.17） | 9 | 无 | 91 min / 37 g / 换色 8 次 |
| 2 | cradle C | 通过 | 1 | 1 h 5 min（65 min） | 18.29 g（藏青 18.29） | 0 | 无 | 58.5 min / 18.3 g / 换色 0 次 |
| 3 | front bar F, knob K, plugs EN EF, far pins P, caps D, spacer S | 通过 | 13 | 1 h 28 min（88 min） | 27.03 g（白 2.59、天蓝 1.40、藏青 23.05） | 9 | 无 | 76 min / 22.5 g / 换色 6 次 |

盘 1–3 合计：4 h 5 min（245 min），83.37 g（白 8.16、天蓝 2.70、藏青 72.51），换色 18 次。

每盘检查：每件一个切片对象（多色件 = 一个对象 + 多个零件）、无警告、CLI 回读后耗材分配不变、G-code 换色次数与 result.json 一致、换色只在嵌色层、擦料塔不碰零件、brim 用藏青且只在零件周围。

## 4 与 SPEC v3.2 的差异（评审确认的缺陷修复，SPEC 文档未改）

- 前横梁 F 的 6 个 Ø1.9 销孔改成泪滴（打印时是水平孔，§2.3"水平孔一律泪滴"）。
- 盖片：挂片 Ø8.1×0.8、旋钮 Ø8.1×0.4（盖片后留 0.2 余量，旋钮厚度不变）、轴盖 Ø6.2×0.4（SPEC：Ø8.2×0.8、Ø8.2×0.6、Ø6.4×0.6）：竖孔打出来偏小，原来几乎零间隙。
- 定子垫片 S 改 Ø8.4，压配进 Ø8.3 定子孔（SPEC Ø8.2）。
- 换档时磁力会反向（SPEC §4.5 "7 颗都被吸力压在打印的底或壁上"只在静止时成立）：转到 35–85° 时定子被推向垫片，最大 1.03 N，由压配垫片承担；旋钮磁铁最大 0.62 N 推向盖片（静止时另两个角各 0.08 N），由整圈 AB 胶粘住的盖片承担。
- 远端销 P 加 3 mm brim（盘 3 和盘 0），盘 0 的近端块切片 N 加 5 mm brim（同托架）。
- 盘 0 增加两条销孔试条 JB / JL（Ø1.70…1.90），为下面 ⑩ 的决定提供压配数据。

## 5 需要你决定：AB 胶高温变软时的托架刚度（检查 ⑩）

90 ℃、ABS E 100 MPa 时近端唇板抬起量（旋钮凸台受力点在下沿 / 中心，mm；SPEC 参考值 ≤ 0.20）：

- 胶完好（刚性粘接）：0.068 / 0.204
- 胶变软，销压配无间隙：0.119 / 0.346
- 胶变软，现在的 Ø1.9 孔 + Ø1.75 销（有间隙）：0.205 / 0.617
- 胶变软，加多压配销：12 根 0.103 / 0.302；24 根 0.089 / 0.262

现在的 Ø1.9 孔有间隙，胶一软销就不传力，和不连接一样，所以 SPEC §1 / §4.3 "销传剪力、胶软不影响刚度"没有达成。加销作用有限：抬起量的下限是胶完好时的值，它本身就在 0.20 附近。可选：
- (a) 销改压配（按盘 0 的 JB / JL 试条选孔径）：胶软时最大抬起量从 0.62 降到 0.35 mm；要做到 ≤ 0.20 还得加刚截面（横梁加深或唇板加厚，属于设计改动）。
- (b) 销只负责定位，高温刚度靠耐温 ≥ 90 ℃ 的 AB 胶：在 SPEC §1 / §4.3 / §8 写明，装配卡和盘 0 ⑤ 记录胶的耐温标签，⑩ 以胶完好时的值判定（即 SPEC 的 0.07–0.20，按两位小数）。
- 无论选哪个，定下后把 ⑩ 改成硬性项。抬起只影响高温下的刚度（近端可能轻微翘起、过坎"嗒"），不影响强度；现在 ⑩ 仍是警告级，不阻断构建。

## 6 交付文件

- 3MF（已带耗材分配，打开直接切片）：`out/plate0/plate0_coupons.3mf`、`out/plates/plate1.3mf`、`out/plates/plate2.3mf`、`out/plates/plate3.3mf`
- STL / STEP：`out/parts/print/`（打印姿态，23 个 STL、17 个 STEP）、`out/parts/assembled/`（装配姿态，37 个 STL）、`out/parts/assembly.step`
- 渲染图：`out/renders/outside_35deg.png`、`out/renders/outside_25deg.png`、`out/renders/outside_35deg_B.png`、`out/renders/outside_35deg_logo.png`、`out/renders/knob_end.png`、`out/renders/cabin_side.png`、`out/renders/exploded.png`、`out/renders/plate_plate0_coupons.png`、`out/renders/plate_plate1.png`、`out/renders/plate_plate2.png`、`out/renders/plate_plate3.png`
- 装配卡：`out/2026-1014-0143-装配卡.md`
- 盘 0 试验卡：`out/plate0/2026-1014-0140-盘0试验卡.md`
- 明细：`out/parts/geometry_report.json`、`out/checks/checks_report.json`、`out/plates/slice_report.json`、`out/plate0/slice_summary.json`

## 7 隐私

- 号码只在本机 `config.toml`（已在 .gitignore）；本报告不含号码。
- `out/` 里的 3MF、STL、STEP 和渲染图都含号码：只在本机切片，用局域网或 SD 卡打印；不要上传 MakerWorld，也不要用拓竹云打印（会上传 3MF）。

## 附录：全部判定项（hard = 硬性，warn = 警告级）

**1 typography and layout**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| numbers A / B: 11 digits starting with 1 | true | format (never shrunk) | hard | 通过 |
| digit height, flat '1' (mm) | 20.849 | >= 20.0 | hard | 通过 |
| em set by the face fits the length limit (mm) | [26.73, 26.775] | em <= length limit | hard | 通过 |
| face margin top / bottom (mm) | 3.0011 | >= 3.0 | hard | 通过 |
| ink margin far end (first digit '1', mm) | 3.1977 | >= 2.0 | hard | 通过 |
| cell-box margin knob end (worst case, mm) | 2.1288 | >= 2.0 | hard | 通过 |
| strokes survive 1.0 mm erosion, counters survive 0.6 mm dilation | true | every digit | hard | 通过 |
| thinnest stroke every digit survives (mm) | 2.8 | >= 2.8 | hard | 通过 |
| face A: group gap / ink gap | 3.2143 | >= 2.0 (or fixed cells) | hard | 通过 |
| face A: glyph checks (valid, counters, area, margins, ink gap >= 1.8) | true | build-time glyph_checks | hard | 通过 |
| face B: group gap / ink gap | 3.2143 | >= 2.0 (or fixed cells) | hard | 通过 |
| face B: glyph checks (valid, counters, area, margins, ink gap >= 1.8) | true | build-time glyph_checks | hard | 通过 |
| example 1 (spec example): group gap / ink gap | 3.2143 | >= 2.0 (or fixed cells) | hard | 通过 |
| example 2 (spec example): group gap / ink gap | 3.2143 | >= 2.0 (or fixed cells) | hard | 通过 |
| example 3 (many narrow ones): group gap / ink gap | 3.2143 | >= 2.0 (or fixed cells) | hard | 通过 |
| example 4 (worst case, widest digits): group gap / ink gap | 2.0 | >= 2.0 (or fixed cells) | hard | 通过 |

**2 sweep radius at the chamfer corners, clearance to the lip**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| true sweep radius measured on the tube corners (mm) | 16.292 | = chamfer-corner radius 16.292 | hard | 通过 |
| sweep circle -> lip top, analytic (mm) | 1.2077 | >= 1.0 | hard | 通过 |
| rotor -> lip over 0-120 deg, CAD incl. corner-down angles (mm) | 1.2077 | >= 1.0 | hard | 通过 |

**3 static interference 0, running clearances over 0-120 deg**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| static interference, max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| sweep rotor-cradle (running gap, incl. thrust ring), min over 0-120 deg (mm) | 0.2 | >= 0.2 running gap | hard | 通过 |
| sweep rotor-front bar, min over 0-120 deg (mm) | 6.8173 | >= 0.2 running gap | hard | 通过 |
| sweep rotor-far block, min over 0-120 deg (mm) | 0.5 | >= 0.2 running gap | hard | 通过 |
| sweep knob-box, min over 0-120 deg (mm) | 11.9 | >= 0.2 running gap | hard | 通过 |
| sweep knob-front bar, min over 0-120 deg (mm) | 6.5567 | >= 0.2 running gap | hard | 通过 |
| sweep knob body-near block, min over 0-120 deg (mm) | 0.6 | >= 0.2 running gap | hard | 通过 |

**4 envelope Y >= -32, length <= 200**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| overall length X (mm) | 200.0 | <= 200.0 | hard | 通过 |
| frontmost point Y incl. swept circles (mm) | -8.0 | >= -32.0 | hard | 通过 |

**5 configuration paths (assembly, refill: whole box out, plate off before the lid)**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| path: rotor dropped into the cradle, max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| path: far pin pushed in from -X, max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| path: knob pushed in from +X, max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| path: plate lowered onto / lifted off the closed box, max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| path: lid lifted off the base (plate already removed), max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| path: lid lifted with the plate on (not recommended), max common volume (mm^3) | 0.0 | <= 0.001 | hard | 通过 |
| box tilt the plate survives while the whole box is carried (80 C weakest, deg) | 90.0 | >= friction-only slide angle atan(0.8) = 38.7 (spec 6: 39 with pads) | warn | 通过 |

**6 visibility from outside (ray casting)**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| visible share, elevation 15-45 x yaw +-45 deg (%) | 100.0 | = 100 | hard | 通过 |

**7 magnet model (mount pull both stacks, detent, dead zone, snap, floors)**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| detent peak / friction (dry mu 0.35) | 3.5345 | >= 2.5 | hard | 通过 |
| detent peak / friction (layer-line faces mu 0.45) | 2.749 | >= 2.5 | warn | 通过 |
| pocket floor bulge at E 100 MPa (mm) | 0.12888 | < boss gap / 2 = 0.3 | hard | 通过 |
| detent magnet face gap (mm) | 2.2 | = 2.20 (0.8 floor + boss + 0.8 wall) | hard | 通过 |
| stator seating force over 0-120 deg, min (N, + = onto its 0.8 wall) | -1.0319 | >= 0, else carried by a press-fit spacer (S Ø8.4 in the Ø8.3 pocket) | hard | 通过 |
| snap settles in the next detent (dry, released) | 0.57115 | settles < 1.5 s, \|error\| <= stop band 3.3 deg | hard | 通过 |
| snap settles in the next detent (dry, finger 2 rad/s) | 0.56364 | settles < 1.5 s, \|error\| <= stop band 3.3 deg | hard | 通过 |
| snap settles in the next detent (PTFE, released) | -0.037437 | settles < 1.5 s, \|error\| <= stop band 1.6 deg | hard | 通过 |
| snap settles in the next detent (PTFE + damping grease c=1.0) | 0.53378 | settles < 1.5 s, \|error\| <= stop band 1.6 deg | hard | 通过 |

**8 3D rigid-body LP at 80 C weakest (gestures, pinch, braking, lift-off)**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| documented gestures, worst margin (80 C weakest) | 2.4412 | >= 1.5x | hard | 通过 |
| vertical press on a corner, worst margin (80 C weakest) | 4.1666 | >= 2.0x | hard | 通过 |
| pinch capacity / switching torque (80 C weakest) | 4.3243 | >= 1.5x | hard | 通过 |
| braking (80 C weakest, g) | 3.4931 | >= 1.5 g | hard | 通过 |
| lift-off needs downward acceleration (80 C weakest, g) | 3.2993 | >= 3.0 g | hard | 通过 |

**9 hole walls >= 1.2 (pressed 0.8 floors excepted), horizontal holes are teardrops**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| tab pocket -: wall (mm) | 5.4 | >= 1.2 | hard | 通过 |
| tab pocket -: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| tab pocket +: wall (mm) | 5.4 | >= 1.2 | hard | 通过 |
| tab pocket +: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| knob pocket 30: wall (mm) | 1.447 | >= 1.2 | hard | 通过 |
| knob pocket 30: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| knob pocket 150: wall (mm) | 1.447 | >= 1.2 | hard | 通过 |
| knob pocket 150: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| knob pocket 270: wall (mm) | 1.447 | >= 1.2 | hard | 通过 |
| knob pocket 270: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| stator pocket: wall (mm) | 3.5775 | >= 1.2 | hard | 通过 |
| stator pocket: pressed floor (mm) | 0.8 | >= 0.8 (exception to the wall rule) | hard | 通过 |
| far bearing teardrop: teardrop roof in the print pose (deg from vertical) | 45.0 | <= 45 roof + one flat bridge (flat 1.59 mm) | hard | 通过 |
| near bearing teardrop: teardrop roof in the print pose (deg from vertical) | 45.0 | <= 45 roof + one flat bridge (flat 1.66 mm) | hard | 通过 |
| stator pocket: teardrop roof in the print pose (deg from vertical) | 45.0 | <= 45 roof + one flat bridge (flat 2.19 mm) | hard | 通过 |
| beam dowel hole: teardrop roof in the print pose (deg from vertical) | 45.0 | <= 45 roof + one flat bridge (flat 0.50 mm) | hard | 通过 |

**10 detent couple loop: journals, far-force flip, lip lift (v3.2 dowel joint, soft epoxy)**

| 项 | 值 | 限值 | 级别 | 结果 |
|---|---|---|---|---|
| lip lift 90 C, E 100, epoxy soft, 6 dowels bearing without play (mm) | [0.11857, 0.34582] | <= 0.2 (spec 4.3: stiffness kept when the epoxy softens) | warn | 警告 |
| lip lift 90 C, E 100, epoxy soft, 6 dowels with the Ø1.9 hole / Ø1.75 filament play (mm) | [0.20479, 0.61675] | <= 0.2 (spec 4.3: stiffness kept when the epoxy softens) | warn | 警告 |

