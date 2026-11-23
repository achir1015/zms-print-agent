"""參數化零件庫（全部自己寫，使用 manifold3d 做實體布林運算）。

構想參考 Form Studio（MIT）的「建構模組」：輸入幾個量得到的尺寸 → 產生一個保證封閉（watertight）的實體。
座標：Z 朝上、單位 mm、零件底面在 z=0、XY 置中；多個零件（例如盒身＋盒蓋）並排放在列印板上。
每個零件都照列印方向設計（大平面朝下、懸空不超過 45°），列印時通常不需要支撐。
"""
import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

SEG = 96          # 圓的分段數（越多越圓，檔案越大）


@dataclass
class Param:
    key: str
    label: str
    default: float
    lo: float
    hi: float
    step: float = 1
    unit: str = "mm"
    doc: str = ""
    kind: str = "num"          # num、int、bool、choice
    choices: tuple = ()


@dataclass
class Recipe:
    id: str
    name: str
    category: str
    icon: str
    desc: str
    params: list
    build: object
    keywords: tuple = ()
    tips: list = field(default_factory=list)

    def defaults(self):
        return {p.key: p.default for p in self.params}

    def clean(self, values):
        """把輸入值整理成合法範圍（字串轉數字、超出範圍就夾到邊界）。"""
        out = self.defaults()
        for p in self.params:
            if p.key not in (values or {}):
                continue
            v = values[p.key]
            if p.kind == "bool":
                out[p.key] = v in (True, 1, "1", "true", "True", "是", "on")
                continue
            if p.kind == "choice":
                out[p.key] = v if v in p.choices else p.default
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            v = min(max(v, p.lo), p.hi)
            out[p.key] = int(round(v)) if p.kind == "int" else round(v, 3)
        return out


# ====================================================================== 基本形狀工具
def rrect(w, d, r):
    """圓角矩形截面（置中）。"""
    r = max(0.0, min(r, w / 2 - 0.01, d / 2 - 0.01))
    if r <= 0.01:
        return CrossSection.square((w, d), center=True)
    return CrossSection.square((w - 2 * r, d - 2 * r), center=True).offset(r, JoinType.Round, circular_segments=SEG)


def rbox(w, d, h, r=0.0, z=0.0):
    return rrect(w, d, r).extrude(h).translate((0, 0, z))


def cyl(d, h, z=0.0, d2=None, seg=SEG):
    return Manifold.cylinder(h, d / 2, (d2 if d2 is not None else d) / 2, circular_segments=seg).translate((0, 0, z))


def hole_z(d, h, x=0.0, y=0.0, z=-1.0):
    """垂直穿孔（多出一點避免共面）。"""
    return cyl(d, h + 2, z).translate((x, y, 0))


def hole_y(d, length, x=0.0, y=0.0, z=0.0):
    """沿 Y 軸的水平孔：做成淚滴形（上方 45° 尖頂），印在垂直牆上不需要支撐。"""
    r = d / 2
    circle = CrossSection.circle(r, SEG)
    tip = CrossSection([[(-r * math.sqrt(0.5), r * math.sqrt(0.5)), (0, r * math.sqrt(2)),
                         (r * math.sqrt(0.5), r * math.sqrt(0.5)), (0, 0)]])
    tear = circle + tip
    return tear.extrude(length).translate((0, 0, -length / 2)).rotate((90, 0, 0)).translate((x, y, z))


def hole_x(d, length, x=0.0, y=0.0, z=0.0):
    return hole_y(d, length).rotate((0, 0, 90)).translate((x, y, z))


def chamfer_base(m, c=0.4):
    """底部小倒角（遮住第一層擠壓外擴）：用縮小的底層取代。簡化版：直接回傳。"""
    return m


def place_side_by_side(parts, gap=8.0):
    """把多個零件沿 X 排在列印板上（各自底面 z=0），整體置中。"""
    out, x = [], 0.0
    boxes = []
    for name, m in parts:
        lo, hi = bbox(m)
        boxes.append((name, m, lo, hi))
    total = sum(hi[0] - lo[0] for _, _, lo, hi in boxes) + gap * (len(boxes) - 1)
    x = -total / 2
    for name, m, lo, hi in boxes:
        w = hi[0] - lo[0]
        m = m.translate((x - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]))
        out.append((name, m))
        x += w + gap
    return out


def bbox(m):
    b = m.bounding_box()
    return np.array(b[:3]), np.array(b[3:])


# ====================================================================== 零件
def build_block(v):
    m = rbox(v["width"], v["depth"], v["height"], v["corner"])
    return [("方塊", m)]


def build_tube(v):
    m = cyl(v["outer_d"], v["height"])
    if v["inner_d"] > 0:
        m = m - hole_z(min(v["inner_d"], v["outer_d"] - 1.2), v["height"])
    return [("圓柱", m)]


def build_washer(v):
    m = cyl(v["outer_d"], v["thick"]) - hole_z(min(v["inner_d"], v["outer_d"] - 1), v["thick"])
    n = int(v["count"])
    return place_side_by_side([("墊圈%d" % (i + 1), m) for i in range(n)], gap=4)


def build_storage_box(v):
    w, d, h, t, r = v["width"], v["depth"], v["height"], v["wall"], v["corner"]
    c = v["clearance"]
    body = rbox(w, d, h, r) - rbox(w - 2 * t, d - 2 * t, h, max(r - t, 0.5), z=t)
    lid_top = v["lid_thick"]
    lip_h = 4.0
    lip_w, lip_d = w - 2 * t - 2 * c, d - 2 * t - 2 * c
    lid = rbox(w, d, lid_top, r)
    lip = rbox(lip_w, lip_d, lip_h, max(r - t - c, 0.5), z=lid_top) - rbox(
        lip_w - 2 * 1.6, lip_d - 2 * 1.6, lip_h + 1, max(r - t - c - 1.6, 0.4), z=lid_top)
    lid = lid + lip
    if v["finger"]:
        lid = lid - Manifold.sphere(9, SEG).scale((1.6, 1, 1)).translate((0, 0, -9 + 1.2))
    return place_side_by_side([("盒身", body), ("盒蓋", lid)])


def build_enclosure(v):
    """電子元件盒：內部尺寸＋四角 M3 螺絲柱、上蓋螺絲孔、側邊線孔。"""
    iw, id_, ih, t = v["inner_w"], v["inner_d"], v["inner_h"], v["wall"]
    w, d, h = iw + 2 * t, id_ + 2 * t, ih + t
    r = 3.0
    body = rbox(w, d, h, r) - rbox(iw, id_, h, max(r - t, 0.5), z=t)
    post_d, hole_d = 7.0, v["screw_d"] * 0.85         # 自攻螺絲：孔略小於螺絲
    px, py = iw / 2 - post_d / 2 + 0.5, id_ / 2 - post_d / 2 + 0.5
    lid_t = 2.4
    for sx in (-1, 1):
        for sy in (-1, 1):
            post = cyl(post_d, h - lid_t * 0 - t, t).translate((sx * px, sy * py, 0))
            body = body + post
            body = body - cyl(hole_d, h, t + 2).translate((sx * px, sy * py, 0))
    if v["cable_d"] > 0:
        body = body - hole_x(v["cable_d"], t * 4, x=w / 2 - t / 2, z=t + v["cable_d"] / 2 + 3)
    if v["vents"]:
        n = max(2, int(iw // 8))
        for i in range(n):
            x = -iw / 2 + 8 + i * (iw - 16) / max(n - 1, 1)
            body = body - rbox(2.2, t * 4, ih * 0.45, 1.0, z=t + ih * 0.3).translate((x, d / 2 - t / 2, 0))
    lid = rbox(w, d, lid_t, r)
    head_d = v["screw_d"] * 2 + 0.6
    for sx in (-1, 1):
        for sy in (-1, 1):
            lid = lid - hole_z(v["screw_d"] + 0.4, lid_t).translate((sx * px, sy * py, 0))
            lid = lid - cyl(v["screw_d"] + 0.4, 1.2, lid_t - 1.2, d2=head_d).translate((sx * px, sy * py, 0))
    return place_side_by_side([("盒身", body), ("上蓋", lid)])


def build_plate(v):
    w, d, t = v["width"], v["depth"], v["thick"]
    m = rbox(w, d, t, v["corner"])
    rows, cols, mg = int(v["rows"]), int(v["cols"]), v["margin"]
    if v["hole_d"] > 0 and rows > 0 and cols > 0:
        xs = [0.0] if cols == 1 else np.linspace(-w / 2 + mg, w / 2 - mg, cols)
        ys = [0.0] if rows == 1 else np.linspace(-d / 2 + mg, d / 2 - mg, rows)
        for x in xs:
            for y in ys:
                m = m - hole_z(v["hole_d"], t).translate((float(x), float(y), 0))
    return [("開孔平板", m)]


def build_l_bracket(v):
    w, a, b, t = v["width"], v["leg_a"], v["leg_b"], v["thick"]
    base = rbox(a, w, t, 1.0).translate((a / 2, 0, 0))
    up = rbox(t, w, b, 1.0).translate((t / 2, 0, 0))
    m = base + up
    if v["gusset"]:
        g = min(a, b) * 0.55
        tri = CrossSection([[(t, t), (t + g, t), (t, t + g)]]).extrude(min(4.0, w / 4)).translate((0, 0, -min(4.0, w / 4) / 2))
        m = m + tri.rotate((90, 0, 0))
    n, hd = int(v["holes"]), v["hole_d"]
    if hd > 0 and n > 0:
        ys = [0.0] if n == 1 else np.linspace(-w / 2 + w / (2 * n), w / 2 - w / (2 * n), n)
        for y in ys:
            m = m - hole_z(hd, t).translate((t + (a - t) * 0.6, float(y), 0))
            m = m - hole_x(hd, t * 4, x=t / 2, y=float(y), z=t + (b - t) * 0.6)
    return [("L 型支架", m)]


def build_hook(v):
    """牆面掛鉤：背板（兩個螺絲孔）＋向上彎的鉤子，整個平躺列印（側面朝下）最堅固。"""
    w, hgt, reach, t = v["width"], v["height"], v["reach"], v["thick"]
    lip = v["lip"]
    # 在 XZ 平面畫側面輪廓，再沿 Y 擠出寬度
    pts = [(0, 0), (t, 0), (t, hgt - reach * 0.2), (0, hgt)]
    back = CrossSection([[(0, 0), (t, 0), (t, hgt), (0, hgt)]])
    arm = CrossSection([[(0, 0), (reach + t, 0), (reach + t, t), (0, t)]])
    tip = CrossSection([[(reach, 0), (reach + t, 0), (reach + t, lip), (reach, lip)]])
    prof = back + arm + tip
    _ = pts
    m = prof.extrude(w).translate((0, 0, -w / 2))          # 輪廓在 XY、厚度沿 Z → 平躺
    m = m.rotate((0, 0, 0))
    sd = v["screw_d"]
    if sd > 0:
        for frac in (0.55, 0.85):
            m = m - hole_x(sd, t * 4, x=t / 2, y=hgt * frac, z=0).rotate((0, 0, 0))
    # 平躺：底面 z 從 -w/2 開始
    return [("掛鉤", m)]


def build_cable_clip(v):
    """理線夾：底座（螺絲孔或背膠）上一排 C 形夾。"""
    cd, n, t, w = v["cable_d"], int(v["count"]), v["thick"], v["width"]
    ring_od = cd + 2 * t
    pitch = ring_od + 2
    length = pitch * n + 10
    base = rbox(length, w, t, 2.0)
    m = base
    for i in range(n):
        x = -length / 2 + 5 + pitch * (i + 0.5)
        ring = Manifold.cylinder(w, ring_od / 2, circular_segments=SEG) - Manifold.cylinder(
            w + 2, cd / 2, circular_segments=SEG).translate((0, 0, -1))
        ring = ring.translate((0, 0, -w / 2)).rotate((90, 0, 0)).translate((x, 0, t + cd / 2))
        gap = cd * v["opening"]
        cut = rbox(gap, w + 2, ring_od, 0).translate((x, 0, t + cd / 2 + cd * 0.15))
        m = m + (ring - cut)
    if v["screw_d"] > 0:
        for sx in (-1, 1):
            m = m - hole_z(v["screw_d"], t).translate((sx * (length / 2 - 2.6), 0, 0))
    return [("理線夾", m)]


def build_phone_stand(v):
    """手機／平板支架：側面輪廓擠出寬度；斜靠背＋前擋＋放置槽。"""
    w, ang, dev_t, depth, lip = v["width"], math.radians(v["angle"]), v["device_t"], v["base_depth"], v["lip"]
    t = 4.0
    back_len = v["back_h"]
    # 側面（X 前後、Y 高度）
    base = CrossSection([[(0, 0), (depth, 0), (depth, t), (0, t)]])
    x0 = depth * 0.35
    slot_front = x0
    slot_back = x0 + dev_t + 0.8
    front_lip = CrossSection([[(slot_front - t, t - 0.01), (slot_front, t - 0.01), (slot_front, t + lip), (slot_front - t, t + lip)]])
    bx = slot_back
    dx, dy = math.cos(ang) * back_len, math.sin(ang) * back_len
    nx, ny = math.sin(ang) * t, -math.cos(ang) * t
    back = CrossSection([[(bx, t - 0.01), (bx + nx * 0 + t / math.sin(ang), t - 0.01), (bx + dx + nx * -1 + t, t + dy),
                          (bx + dx, t + dy)]])
    # 後方撐腳
    strut = CrossSection([[(bx + dx * 0.55, t + dy * 0.55), (bx + dx * 0.55 + t, t + dy * 0.55 - 1),
                           (depth, t - 0.01), (depth - t * 1.2, t - 0.01)]])
    prof = base + front_lip + back + strut
    m = prof.extrude(w).rotate((90, 0, 0)).translate((-depth / 2, w / 2, 0))
    if v["cable_hole"]:
        m = m - rbox(14, 14, 40, 3).translate((x0 - depth / 2 + dev_t / 2 + 0.4, 0, -5))
    return [("手機支架", m)]


def build_gridfinity(v):
    """Gridfinity 收納盒（42 mm 格、7 mm 高度單位，底部為簡化的階梯底座，可放在標準底板上）。"""
    nx, ny, hu = int(v["units_x"]), int(v["units_y"]), int(v["height_u"])
    pitch, clr = 42.0, 0.5
    w, d = nx * pitch - clr, ny * pitch - clr
    h = hu * 7.0
    wall = v["wall"]
    # 底座：每一格一個 41.5 底座，三段階梯（0.8 斜、1.8 直、2.15 斜）
    foot = None
    for ix in range(nx):
        for iy in range(ny):
            cx, cy = (ix - (nx - 1) / 2) * pitch, (iy - (ny - 1) / 2) * pitch
            f = rbox(35.6, 35.6, 0.8, 0.8).translate((cx, cy, 0))
            f += rbox(37.2, 37.2, 1.8, 1.6, z=0.8).translate((cx, cy, 0))
            f += rbox(41.5, 41.5, 2.15, 3.75, z=2.6).translate((cx, cy, 0))
            foot = f if foot is None else foot + f
    body = rbox(w, d, h - 4.75, 3.75, z=4.75)
    m = foot + body
    m = m - rbox(w - 2 * wall, d - 2 * wall, h, max(3.75 - wall, 0.5), z=4.75 + v["floor"])
    if v["lip"]:
        m = m + (rbox(w, d, 4.4, 3.75, z=h) - rbox(w - 2 * 2.6, d - 2 * 2.6, 6, 1.2, z=h - 1))
    if int(v["dividers"]) > 0:
        n = int(v["dividers"])
        for i in range(1, n + 1):
            x = -w / 2 + i * w / (n + 1)
            m = m + rbox(1.2, d - 2 * wall + 0.2, h - 4.75 - v["floor"] - 1, 0, z=4.75 + v["floor"]).translate((x, 0, 0))
    return [("Gridfinity 收納盒", m)]


def build_vase(v):
    """花瓶／燈罩：多邊形截面向上扭轉、漸縮；可選擇實心（用花瓶模式列印）或有壁厚。"""
    d, h, n, tw = v["bottom_d"], v["height"], int(v["sides"]), v["twist"]
    scale = v["top_d"] / d
    poly = [(d / 2 * math.cos(2 * math.pi * i / n), d / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    sec = CrossSection([poly]).offset(-1.0, JoinType.Round).offset(1.0, JoinType.Round, circular_segments=24)
    outer = sec.extrude(h, n_divisions=max(8, int(h / 2)), twist_degrees=tw, scale_top=(scale, scale))
    if v["solid"]:
        return [("花瓶（請用花瓶模式列印）", outer)]
    t = v["wall"]
    inner_sec = sec.offset(-t, JoinType.Round, circular_segments=24)
    inner = inner_sec.extrude(h, n_divisions=max(8, int(h / 2)), twist_degrees=tw, scale_top=(scale, scale))
    inner = inner.translate((0, 0, t * 1.5))
    return [("花瓶", outer - inner)]


def build_plant_pot(v):
    td, bd, h, t = v["top_d"], v["bottom_d"], v["height"], v["wall"]
    pot = cyl(bd, h, d2=td) - cyl(bd - 2 * t, h, z=t, d2=td - 2 * t)
    if v["drain_d"] > 0:
        pot = pot - hole_z(v["drain_d"], t)
        for a in range(0, 360, 90):
            r = bd / 4
            pot = pot - hole_z(v["drain_d"] * 0.6, t).translate((r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), 0))
    parts = [("花盆", pot)]
    if v["saucer"]:
        sd = bd + 16
        saucer = cyl(sd, 12, d2=sd + 6) - cyl(sd - 4, 12, z=2, d2=sd + 2)
        parts.append(("接水盤", saucer))
    return place_side_by_side(parts)


def build_knob(v):
    d, h, sd = v["diameter"], v["height"], v["shaft_d"]
    n = int(v["grips"])
    m = cyl(d, h, d2=d * 0.92)
    for i in range(n):
        a = 2 * math.pi * i / n
        m = m - cyl(d * 0.16, h + 2, z=-1).translate((d / 2 * math.cos(a), d / 2 * math.sin(a), 0))
    m = m - cyl(1.6, 1.0, z=h - 0.8).translate((0, d * 0.32, 0))        # 指示點
    shaft = cyl(sd + 0.2, h - 2)
    if v["d_flat"]:
        shaft = shaft - rbox(sd + 2, sd, h, 0).translate((0, sd * 0.5 + (sd / 2 - sd * 0.1), 0))
    m = m - shaft
    return [("旋鈕", m)]


def build_hose_adapter(v):
    d1, d2, t, l1, l2 = v["outer_d1"], v["outer_d2"], v["wall"], v["length1"], v["length2"]
    trans = max(abs(d1 - d2), 6.0)
    outer = cyl(d1, l1) + cyl(d1, trans, z=l1, d2=d2) + cyl(d2, l2, z=l1 + trans)
    if v["barbs"]:
        for k in range(3):
            z = l1 + trans + l2 * (0.2 + 0.25 * k)
            outer = outer + cyl(d2 + 1.6, l2 * 0.16, z=z, d2=d2)
    inner = cyl(d1 - 2 * t, l1 + 0.01, z=-1) + cyl(d1 - 2 * t, trans, z=l1, d2=d2 - 2 * t) + \
        cyl(d2 - 2 * t, l2 + 2, z=l1 + trans)
    return [("管接頭", outer - inner)]


def build_shelf_bracket(v):
    depth, hgt, w, t = v["shelf_depth"], v["height"], v["width"], v["thick"]
    prof = CrossSection([[(0, 0), (t, 0), (t, hgt), (0, hgt)]]) + \
        CrossSection([[(0, hgt - t), (depth, hgt - t), (depth, hgt), (0, hgt)]]) + \
        CrossSection([[(t, hgt * 0.25), (t + t * 1.2, hgt * 0.25), (depth, hgt - t), (depth - t * 1.5, hgt - t)]])
    m = prof.extrude(w).translate((0, 0, 0))          # 側面平躺列印
    sd = v["screw_d"]
    for y in (hgt * 0.3, hgt * 0.75):
        m = m - Manifold.cylinder(t * 4, sd / 2, circular_segments=SEG).rotate((0, 90, 0)).translate((-t, y, w / 2))
    m = m - Manifold.cylinder(t * 4, sd / 2, circular_segments=SEG).rotate((90, 0, 0)).translate((depth * 0.7, hgt + t, w / 2))
    return [("層板支架", m)]


def _involute_gear(module, teeth, pa_deg=20.0, steps=10):
    """標準漸開線正齒輪截面：每齒左右齒面在半徑 r 的角度＝齒中心 ± (π/2z + inv(α分度) − inv(α_r))。"""
    pa = math.radians(pa_deg)
    rp = module * teeth / 2
    rb = rp * math.cos(pa)
    ra = rp + module
    rf = max(rp - 1.25 * module, 0.5)

    def inv(a):
        return math.tan(a) - a

    def theta(r):
        r = max(r, rb)
        return math.pi / (2 * teeth) + inv(pa) - inv(math.acos(min(rb / r, 1.0)))
    r0 = max(rb, rf)
    radii = [r0 + (ra - r0) * k / steps for k in range(steps + 1)]
    pts = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth
        if rf < rb:
            pts.append((rf * math.cos(a0 - theta(rb)), rf * math.sin(a0 - theta(rb))))
        for r in radii:
            t = max(theta(r), 0.0)
            pts.append((r * math.cos(a0 - t), r * math.sin(a0 - t)))
        for r in reversed(radii):
            t = max(theta(r), 0.0)
            pts.append((r * math.cos(a0 + t), r * math.sin(a0 + t)))
        if rf < rb:
            pts.append((rf * math.cos(a0 + theta(rb)), rf * math.sin(a0 + theta(rb))))
    return CrossSection([pts])


def build_gear(v):
    m_, z, t = v["module"], int(v["teeth"]), v["thick"]
    g = _involute_gear(m_, z).extrude(t)
    if v["bore"] > 0:
        g = g - hole_z(v["bore"], t)
    return [("正齒輪 m%g z%d" % (m_, z), g)]


def build_desk_hook(v):
    """桌下耳機掛架：上方平板用螺絲鎖在桌子下面，下方 J 形鉤。側面輪廓平躺列印。"""
    w, drop, reach, t = v["width"], v["drop"], v["reach"], v["thick"]
    top_len = reach + t + 30
    prof = CrossSection([[(0, drop), (top_len, drop), (top_len, drop + t), (0, drop + t)]]) + \
        CrossSection([[(0, 0), (t, 0), (t, drop + t), (0, drop + t)]]) + \
        CrossSection([[(0, 0), (reach + t, 0), (reach + t, t), (0, t)]]) + \
        CrossSection([[(reach, 0), (reach + t, 0), (reach + t, v["lip"]), (reach, v["lip"])]])
    m = prof.extrude(w)
    sd = v["screw_d"]
    for x in (reach + t + 8, top_len - 8):
        m = m - Manifold.cylinder(t * 4, sd / 2, circular_segments=SEG).rotate((90, 0, 0)).translate((x, drop + t * 3, w / 2))
    return [("桌下掛鉤", m)]


P = Param
RECIPES = [
    Recipe("storage_box", "帶蓋收納盒", "收納", "INVENTORY_2", "盒身＋壓入式盒蓋，指定外部尺寸與壁厚。", [
        P("width", "外寬", 60, 20, 250, 1, doc="盒子外部寬度（X）"),
        P("depth", "外深", 40, 20, 250, 1, doc="盒子外部深度（Y）"),
        P("height", "盒身高度", 30, 8, 200, 1),
        P("wall", "壁厚", 2.0, 1.2, 5, 0.2),
        P("corner", "圓角半徑", 4, 0, 20, 0.5),
        P("clearance", "盒蓋間隙（單邊）", 0.25, 0.1, 0.6, 0.05, doc="太緊加大、太鬆減少"),
        P("lid_thick", "盒蓋厚度", 2.0, 1.2, 5, 0.2),
        P("finger", "盒蓋指扣凹槽", True, 0, 1, 1, "", kind="bool")],
        build_storage_box, ("盒", "收納", "蓋", "box", "lid", "container", "storage")),
    Recipe("enclosure", "電子元件盒", "外殼", "DEVELOPER_BOARD", "依電路板的內部尺寸產生盒身與上蓋，四角 M3 螺絲柱、可加線孔與散熱孔。", [
        P("inner_w", "內寬", 60, 20, 250, 1), P("inner_d", "內深", 40, 20, 250, 1),
        P("inner_h", "內高", 25, 8, 150, 1), P("wall", "壁厚", 2.0, 1.2, 4, 0.2),
        P("screw_d", "螺絲直徑", 3.0, 2, 5, 0.5, doc="M3 就填 3"),
        P("cable_d", "側邊線孔直徑（0＝不開）", 6, 0, 20, 0.5),
        P("vents", "散熱孔", True, 0, 1, 1, "", kind="bool")],
        build_enclosure, ("電子", "元件", "外殼", "電路", "enclosure", "pcb", "arduino", "樹莓派")),
    Recipe("plate", "開孔平板", "基本", "GRID_ON", "平板加上排列整齊的孔，可做墊板、面板、安裝板。", [
        P("width", "寬", 80, 10, 250, 1), P("depth", "深", 50, 10, 250, 1), P("thick", "厚度", 3, 1, 20, 0.2),
        P("corner", "圓角", 3, 0, 20, 0.5), P("hole_d", "孔徑", 3.4, 0, 30, 0.1, doc="M3 螺絲通孔用 3.4"),
        P("rows", "孔排數", 2, 0, 20, 1, "排", kind="int"), P("cols", "每排孔數", 2, 0, 20, 1, "個", kind="int"),
        P("margin", "孔距邊緣", 6, 2, 50, 0.5)],
        build_plate, ("平板", "板", "孔", "面板", "plate", "panel", "holes")),
    Recipe("l_bracket", "L 型支架", "五金", "STRAIGHTEN", "兩片互相垂直的板加補強三角，各邊有螺絲孔（水平孔做成淚滴形免支撐）。", [
        P("width", "寬度", 30, 10, 150, 1), P("leg_a", "底邊長", 40, 15, 200, 1), P("leg_b", "立邊高", 40, 15, 200, 1),
        P("thick", "厚度", 4, 2, 12, 0.5), P("hole_d", "螺絲孔徑", 4.4, 0, 10, 0.1),
        P("holes", "每邊孔數", 2, 0, 5, 1, "個", kind="int"), P("gusset", "補強三角", True, 0, 1, 1, "", kind="bool")],
        build_l_bracket, ("l型", "角鐵", "支架", "bracket", "角碼", "固定")),
    Recipe("hook", "牆面掛鉤", "壁掛", "CHECKROOM", "背板鎖在牆上，向外伸出再上彎的掛鉤；側躺列印最堅固。", [
        P("width", "掛鉤寬度", 20, 8, 80, 1), P("height", "背板高度", 50, 20, 150, 1),
        P("reach", "伸出長度", 30, 10, 100, 1), P("lip", "前端上彎高度", 12, 4, 50, 1),
        P("thick", "厚度", 5, 2.5, 12, 0.5), P("screw_d", "螺絲孔徑（0＝不開）", 4.2, 0, 8, 0.1)],
        build_hook, ("掛鉤", "鉤", "吊", "hook", "掛")),
    Recipe("desk_hook", "桌下掛鉤（耳機架）", "壁掛", "HEADPHONES", "鎖在桌面底下的 J 形掛鉤，可掛耳機、包包。", [
        P("width", "寬度", 25, 10, 80, 1), P("drop", "下垂高度", 35, 15, 120, 1), P("reach", "鉤子深度", 35, 15, 100, 1),
        P("lip", "前端上彎高度", 12, 4, 40, 1), P("thick", "厚度", 5, 3, 12, 0.5), P("screw_d", "螺絲孔徑", 4.2, 2, 8, 0.1)],
        build_desk_hook, ("耳機", "桌下", "headphone", "desk")),
    Recipe("cable_clip", "理線夾", "壁掛", "CABLE", "一排 C 形夾固定電線，底座可鎖螺絲或貼雙面膠。", [
        P("cable_d", "電線直徑", 6, 2, 20, 0.5), P("count", "夾數", 4, 1, 12, 1, "個", kind="int"),
        P("thick", "厚度", 2.0, 1.2, 4, 0.2), P("width", "夾子寬度", 10, 5, 30, 1),
        P("opening", "開口比例", 0.75, 0.5, 0.95, 0.05, "", doc="開口寬＝線徑×比例，越小越緊"),
        P("screw_d", "螺絲孔徑（0＝貼膠）", 3.4, 0, 6, 0.1)],
        build_cable_clip, ("理線", "電線", "線", "cable", "wire", "整理")),
    Recipe("phone_stand", "手機／平板支架", "桌面", "STAY_CURRENT_PORTRAIT", "斜靠背支架，前方擋邊、可留充電線孔。", [
        P("width", "寬度", 70, 30, 200, 1), P("angle", "傾斜角度", 65, 45, 80, 1, "°"),
        P("device_t", "裝置厚度（含手機殼）", 12, 6, 30, 0.5), P("base_depth", "底座深度", 80, 50, 160, 1),
        P("back_h", "靠背長度", 70, 40, 160, 1), P("lip", "前擋高度", 10, 4, 30, 1),
        P("cable_hole", "充電線孔", True, 0, 1, 1, "", kind="bool")],
        build_phone_stand, ("手機", "平板", "支架", "phone", "tablet", "stand", "ipad")),
    Recipe("gridfinity", "Gridfinity 收納盒", "收納", "VIEW_MODULE", "42 mm 模組化收納格，可放在 Gridfinity 底板上，可加隔板。", [
        P("units_x", "寬（格）", 2, 1, 6, 1, "格", kind="int"), P("units_y", "深（格）", 1, 1, 6, 1, "格", kind="int"),
        P("height_u", "高度（單位，7 mm）", 6, 2, 15, 1, "u", kind="int"), P("wall", "壁厚", 1.2, 0.8, 3, 0.1),
        P("floor", "底厚", 1.0, 0.6, 3, 0.1), P("dividers", "隔板數", 0, 0, 5, 1, "片", kind="int"),
        P("lip", "堆疊唇邊", True, 0, 1, 1, "", kind="bool")],
        build_gridfinity, ("gridfinity", "格", "模組", "抽屜")),
    Recipe("vase", "花瓶與燈罩", "居家", "LOCAL_FLORIST", "多邊形截面向上扭轉、漸縮，可選實心用花瓶模式列印。", [
        P("bottom_d", "底部直徑", 70, 30, 200, 1), P("top_d", "頂部直徑", 90, 20, 250, 1),
        P("height", "高度", 120, 30, 250, 1), P("sides", "邊數", 8, 3, 24, 1, "邊", kind="int"),
        P("twist", "扭轉角度", 60, 0, 360, 5, "°"), P("wall", "壁厚", 1.6, 0.8, 4, 0.2),
        P("solid", "實心（花瓶模式）", False, 0, 1, 1, "", kind="bool")],
        build_vase, ("花瓶", "瓶", "燈罩", "vase", "lamp")),
    Recipe("plant_pot", "花盆（含接水盤）", "居家", "YARD", "上寬下窄的花盆，底部排水孔，可附接水盤。", [
        P("top_d", "上口直徑", 100, 40, 220, 1), P("bottom_d", "底部直徑", 75, 30, 200, 1),
        P("height", "高度", 90, 30, 220, 1), P("wall", "壁厚", 2.0, 1.2, 5, 0.2),
        P("drain_d", "排水孔徑（0＝不開）", 10, 0, 25, 1), P("saucer", "附接水盤", True, 0, 1, 1, "", kind="bool")],
        build_plant_pot, ("花盆", "盆栽", "植物", "pot", "planter")),
    Recipe("knob", "旋鈕", "五金", "TUNE", "電位器或調整桿用的旋鈕，周圍防滑凹槽、D 形軸孔。", [
        P("diameter", "直徑", 25, 10, 80, 1), P("height", "高度", 15, 6, 50, 1), P("shaft_d", "軸徑", 6, 2, 15, 0.1),
        P("grips", "防滑凹槽數", 12, 0, 30, 1, "個", kind="int"), P("d_flat", "D 形軸", True, 0, 1, 1, "", kind="bool")],
        build_knob, ("旋鈕", "knob", "電位器", "按鈕")),
    Recipe("hose_adapter", "管接頭（變徑）", "工坊", "PLUMBING", "兩種外徑的軟管或吸塵器管互接，倒鉤增加咬合。", [
        P("outer_d1", "管口 1 外徑", 32, 6, 120, 0.5), P("outer_d2", "管口 2 外徑", 25, 6, 120, 0.5),
        P("wall", "壁厚", 2.0, 1.2, 5, 0.2), P("length1", "管口 1 長度", 25, 8, 80, 1),
        P("length2", "管口 2 長度", 25, 8, 80, 1), P("barbs", "倒鉤", True, 0, 1, 1, "", kind="bool")],
        build_hose_adapter, ("管", "接頭", "軟管", "吸塵器", "hose", "adapter", "pipe")),
    Recipe("shelf_bracket", "層板支架", "壁掛", "SHELVES", "三角形層板托架，牆面兩孔、層板一孔；側躺列印。", [
        P("shelf_depth", "層板深度", 120, 50, 250, 1), P("height", "支架高度", 100, 40, 250, 1),
        P("width", "支架寬度", 20, 10, 60, 1), P("thick", "厚度", 6, 3, 15, 0.5), P("screw_d", "螺絲孔徑", 4.5, 2, 8, 0.1)],
        build_shelf_bracket, ("層板", "層架", "shelf", "托架")),
    Recipe("gear", "正齒輪", "機構", "SETTINGS", "標準漸開線正齒輪（壓力角 20°），模數相同的齒輪可互相嚙合。", [
        P("module", "模數", 1.5, 0.5, 5, 0.25, "", doc="齒的大小；嚙合的齒輪模數要一樣"),
        P("teeth", "齒數", 20, 8, 120, 1, "齒", kind="int"), P("thick", "厚度", 6, 2, 40, 0.5),
        P("bore", "軸孔直徑", 5, 0, 50, 0.1)],
        build_gear, ("齒輪", "gear")),
    Recipe("block", "方塊", "基本", "CROP_SQUARE", "最基本的圓角方塊，可做墊塊、測試件。", [
        P("width", "寬", 20, 1, 250, 0.5), P("depth", "深", 20, 1, 250, 0.5), P("height", "高", 20, 0.4, 250, 0.5),
        P("corner", "圓角", 0, 0, 50, 0.5)],
        build_block, ("方塊", "立方", "墊塊", "cube", "block")),
    Recipe("tube", "圓柱／圓管", "基本", "CIRCLE", "實心圓柱或空心圓管（間隔柱、套管）。", [
        P("outer_d", "外徑", 20, 2, 250, 0.5), P("inner_d", "內徑（0＝實心）", 0, 0, 240, 0.5),
        P("height", "高度", 20, 0.4, 250, 0.5)],
        build_tube, ("圓柱", "圓管", "間隔柱", "套管", "cylinder", "tube", "spacer")),
    Recipe("washer", "墊圈", "五金", "RADIO_BUTTON_CHECKED", "平墊圈，一次可產生多個。", [
        P("outer_d", "外徑", 12, 4, 100, 0.5), P("inner_d", "內徑", 6.4, 1, 90, 0.1), P("thick", "厚度", 1.6, 0.4, 10, 0.2),
        P("count", "數量", 4, 1, 20, 1, "個", kind="int")],
        build_washer, ("墊圈", "華司", "washer")),
]
BY_ID = {r.id: r for r in RECIPES}
CATEGORIES = []
for _r in RECIPES:
    if _r.category not in CATEGORIES:
        CATEGORIES.append(_r.category)


def build(recipe_id, values=None):
    """產生零件 → (整理後參數, [(零件名, Manifold)])。"""
    r = BY_ID.get(recipe_id)
    if not r:
        raise KeyError("沒有這個零件類型：%s" % recipe_id)
    v = r.clean(values or {})
    parts = r.build(v)
    out = []
    for name, m in parts:
        if m.is_empty():
            continue
        lo, _ = bbox(m)
        if abs(lo[2]) > 1e-6:
            m = m.translate((0, 0, -lo[2]))
        out.append((name, m))
    if not out:
        raise ValueError("參數組合產生了空的零件，請調整尺寸")
    return v, out


def describe(recipe_id):
    r = BY_ID[recipe_id]
    return {"id": r.id, "name": r.name, "category": r.category, "desc": r.desc,
            "params": [{"key": p.key, "label": p.label, "default": p.default, "min": p.lo, "max": p.hi,
                        "step": p.step, "unit": p.unit, "type": p.kind, "doc": p.doc} for p in r.params]}
