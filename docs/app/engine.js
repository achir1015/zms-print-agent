// 參數化零件（線上版）：逐行移植 pa/recipes.py，使用 manifold-3d（wasm）。改零件時兩邊要一起改。
// 座標：Z 朝上、mm、零件底面 z=0、XY 置中；多個零件並排。
import Module from "./lib/manifold.js";
import { DATA } from "./data.js";

const SEG = 96;
let M = null, Manifold, CrossSection;
const reg = [];                 // 這次建模產生的 wasm 物件（建完一起 delete，避免記憶體越用越多）

export async function initEngine(opts = {}) {
  if (M) return;
  M = await Module({ locateFile: opts.locateFile || ((p) => new URL("./lib/" + p, import.meta.url).href) });
  M.setup();
  Manifold = M.Manifold; CrossSection = M.CrossSection;
  for (const cls of [Manifold, CrossSection]) {
    for (const obj of [cls, cls.prototype]) {
      for (const name of Object.getOwnPropertyNames(obj)) {
        if (name === "constructor" || name === "delete" || name === "prototype" || name === "length" || name === "name") continue;
        const d = Object.getOwnPropertyDescriptor(obj, name);
        if (!d || typeof d.value !== "function") continue;
        const f = d.value;
        obj[name] = function (...a) {
          const r = f.apply(this, a);
          if (r instanceof Manifold || r instanceof CrossSection) reg.push(r);
          return r;
        };
      }
    }
  }
}

function poly(pts) { const c = new CrossSection([pts]); reg.push(c); return c; }
function cleanup() { while (reg.length) { try { reg.pop().delete(); } catch (e) { /* 已刪除 */ } } }

// ------------------------------------------------------------------ 基本形狀
function rrect(w, d, r) {
  r = Math.max(0, Math.min(r, w / 2 - 0.01, d / 2 - 0.01));
  if (r <= 0.01) return CrossSection.square([w, d], true);
  return CrossSection.square([w - 2 * r, d - 2 * r], true).offset(r, "Round", 2, SEG);
}
const rbox = (w, d, h, r = 0, z = 0) => rrect(w, d, r).extrude(h).translate([0, 0, z]);
const cyl = (d, h, z = 0, d2 = null, seg = SEG) => Manifold.cylinder(h, d / 2, (d2 ?? d) / 2, seg).translate([0, 0, z]);
const holeZ = (d, h) => cyl(d, h + 2, -1);
function holeY(d, length, x = 0, y = 0, z = 0) {
  const r = d / 2, s = Math.SQRT1_2;
  const tear = CrossSection.circle(r, SEG).add(poly([[-r * s, r * s], [0, r * Math.SQRT2], [r * s, r * s], [0, 0]]));
  return tear.extrude(length).translate([0, 0, -length / 2]).rotate([90, 0, 0]).translate([x, y, z]);
}
const holeX = (d, length, x = 0, y = 0, z = 0) => holeY(d, length).rotate([0, 0, 90]).translate([x, y, z]);
function bbox(m) { const b = m.boundingBox(); return [b.min, b.max]; }

function sideBySide(parts, gap = 8) {
  const boxes = parts.map(([n, m]) => [n, m, ...bbox(m)]);
  const total = boxes.reduce((s, [, , lo, hi]) => s + hi[0] - lo[0], 0) + gap * (boxes.length - 1);
  let x = -total / 2;
  return boxes.map(([n, m, lo, hi]) => {
    const w = hi[0] - lo[0];
    const out = [n, m.translate([x - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])];
    x += w + gap;
    return out;
  });
}
const linspace = (a, b, n) => n === 1 ? [(a + b) / 2] : Array.from({ length: n }, (_, i) => a + (b - a) * i / (n - 1));

// ------------------------------------------------------------------ 零件
const B = {};
B.block = (v) => [["方塊", rbox(v.width, v.depth, v.height, v.corner)]];
B.tube = (v) => {
  let m = cyl(v.outer_d, v.height);
  if (v.inner_d > 0) m = m.subtract(holeZ(Math.min(v.inner_d, v.outer_d - 1.2), v.height));
  return [["圓柱", m]];
};
B.washer = (v) => {
  const m = cyl(v.outer_d, v.thick).subtract(holeZ(Math.min(v.inner_d, v.outer_d - 1), v.thick));
  return sideBySide(Array.from({ length: v.count }, (_, i) => ["墊圈" + (i + 1), m]), 4);
};
B.storage_box = (v) => {
  const { width: w, depth: d, height: h, wall: t, corner: r, clearance: c } = v;
  const body = rbox(w, d, h, r).subtract(rbox(w - 2 * t, d - 2 * t, h, Math.max(r - t, 0.5), t));
  const lt = v.lid_thick, lipH = 4, lw = w - 2 * t - 2 * c, ld = d - 2 * t - 2 * c;
  let lid = rbox(w, d, lt, r);
  const lip = rbox(lw, ld, lipH, Math.max(r - t - c, 0.5), lt).subtract(
    rbox(lw - 3.2, ld - 3.2, lipH + 1, Math.max(r - t - c - 1.6, 0.4), lt));
  lid = lid.add(lip);
  if (v.finger) lid = lid.subtract(Manifold.sphere(9, SEG).scale([1.6, 1, 1]).translate([0, 0, -9 + 1.2]));
  return sideBySide([["盒身", body], ["盒蓋", lid]]);
};
B.enclosure = (v) => {
  const { inner_w: iw, inner_d: id, inner_h: ih, wall: t } = v;
  const w = iw + 2 * t, d = id + 2 * t, h = ih + t, r = 3;
  let body = rbox(w, d, h, r).subtract(rbox(iw, id, h, Math.max(r - t, 0.5), t));
  const postD = 7, holeD = v.screw_d * 0.85, px = iw / 2 - postD / 2 + 0.5, py = id / 2 - postD / 2 + 0.5, lidT = 2.4;
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    body = body.add(cyl(postD, h - t, t).translate([sx * px, sy * py, 0]));
    body = body.subtract(cyl(holeD, h, t + 2).translate([sx * px, sy * py, 0]));
  }
  if (v.cable_d > 0) body = body.subtract(holeX(v.cable_d, t * 4, w / 2 - t / 2, 0, t + v.cable_d / 2 + 3));
  if (v.vents) {
    const n = Math.max(2, Math.floor(iw / 8));
    for (let i = 0; i < n; i++) {
      const x = -iw / 2 + 8 + i * (iw - 16) / Math.max(n - 1, 1);
      body = body.subtract(rbox(2.2, t * 4, ih * 0.45, 1.0, t + ih * 0.3).translate([x, d / 2 - t / 2, 0]));
    }
  }
  let lid = rbox(w, d, lidT, r);
  const head = v.screw_d * 2 + 0.6;
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    lid = lid.subtract(holeZ(v.screw_d + 0.4, lidT).translate([sx * px, sy * py, 0]));
    lid = lid.subtract(cyl(v.screw_d + 0.4, 1.2, lidT - 1.2, head).translate([sx * px, sy * py, 0]));
  }
  return sideBySide([["盒身", body], ["上蓋", lid]]);
};
B.plate = (v) => {
  const { width: w, depth: d, thick: t } = v;
  let m = rbox(w, d, t, v.corner);
  const rows = v.rows, cols = v.cols, mg = v.margin;
  if (v.hole_d > 0 && rows > 0 && cols > 0) {
    for (const x of cols === 1 ? [0] : linspace(-w / 2 + mg, w / 2 - mg, cols))
      for (const y of rows === 1 ? [0] : linspace(-d / 2 + mg, d / 2 - mg, rows))
        m = m.subtract(holeZ(v.hole_d, t).translate([x, y, 0]));
  }
  return [["開孔平板", m]];
};
B.l_bracket = (v) => {
  const { width: w, leg_a: a, leg_b: b, thick: t } = v;
  let m = rbox(a, w, t, 1.0).translate([a / 2, 0, 0]).add(rbox(t, w, b, 1.0).translate([t / 2, 0, 0]));
  if (v.gusset) {
    const g = Math.min(a, b) * 0.55, gw = Math.min(4.0, w / 4);
    m = m.add(poly([[t, t], [t + g, t], [t, t + g]]).extrude(gw).translate([0, 0, -gw / 2]).rotate([90, 0, 0]));
  }
  const n = v.holes, hd = v.hole_d;
  if (hd > 0 && n > 0) {
    for (const y of n === 1 ? [0] : linspace(-w / 2 + w / (2 * n), w / 2 - w / (2 * n), n)) {
      m = m.subtract(holeZ(hd, t).translate([t + (a - t) * 0.6, y, 0]));
      m = m.subtract(holeX(hd, t * 4, t / 2, y, t + (b - t) * 0.6));
    }
  }
  return [["L 型支架", m]];
};
B.hook = (v) => {
  const { width: w, height: hgt, reach, thick: t, lip } = v;
  const prof = poly([[0, 0], [t, 0], [t, hgt], [0, hgt]]).add(poly([[0, 0], [reach + t, 0], [reach + t, t], [0, t]]))
    .add(poly([[reach, 0], [reach + t, 0], [reach + t, lip], [reach, lip]]));
  let m = prof.extrude(w).translate([0, 0, -w / 2]);
  if (v.screw_d > 0) for (const f of [0.55, 0.85]) m = m.subtract(holeX(v.screw_d, t * 4, t / 2, hgt * f, 0));
  return [["掛鉤", m]];
};
B.cable_clip = (v) => {
  const cd = v.cable_d, n = v.count, t = v.thick, w = v.width;
  const od = cd + 2 * t, pitch = od + 2, length = pitch * n + 10;
  let m = rbox(length, w, t, 2.0);
  for (let i = 0; i < n; i++) {
    const x = -length / 2 + 5 + pitch * (i + 0.5);
    let ring = Manifold.cylinder(w, od / 2, od / 2, SEG).subtract(Manifold.cylinder(w + 2, cd / 2, cd / 2, SEG).translate([0, 0, -1]));
    ring = ring.translate([0, 0, -w / 2]).rotate([90, 0, 0]).translate([x, 0, t + cd / 2]);
    const cut = rbox(cd * v.opening, w + 2, od, 0).translate([x, 0, t + cd / 2 + cd * 0.15]);
    m = m.add(ring.subtract(cut));
  }
  if (v.screw_d > 0) for (const sx of [-1, 1]) m = m.subtract(holeZ(v.screw_d, t).translate([sx * (length / 2 - 2.6), 0, 0]));
  return [["理線夾", m]];
};
B.phone_stand = (v) => {
  const w = v.width, ang = v.angle * Math.PI / 180, devT = v.device_t, depth = v.base_depth, lip = v.lip, t = 4, back = v.back_h;
  const base = poly([[0, 0], [depth, 0], [depth, t], [0, t]]);
  const x0 = depth * 0.35, sf = x0, sb = x0 + devT + 0.8;
  const front = poly([[sf - t, t - 0.01], [sf, t - 0.01], [sf, t + lip], [sf - t, t + lip]]);
  const dx = Math.cos(ang) * back, dy = Math.sin(ang) * back, bx = sb;
  const backP = poly([[bx, t - 0.01], [bx + t / Math.sin(ang), t - 0.01], [bx + dx - Math.sin(ang) * t + t, t + dy], [bx + dx, t + dy]]);
  const strut = poly([[bx + dx * 0.55, t + dy * 0.55], [bx + dx * 0.55 + t, t + dy * 0.55 - 1], [depth, t - 0.01], [depth - t * 1.2, t - 0.01]]);
  let m = base.add(front).add(backP).add(strut).extrude(w).rotate([90, 0, 0]).translate([-depth / 2, w / 2, 0]);
  if (v.cable_hole) m = m.subtract(rbox(14, 14, 40, 3).translate([x0 - depth / 2 + devT / 2 + 0.4, 0, -5]));
  return [["手機支架", m]];
};
B.gridfinity = (v) => {
  const nx = v.units_x, ny = v.units_y, hu = v.height_u, pitch = 42, clr = 0.5;
  const w = nx * pitch - clr, d = ny * pitch - clr, h = hu * 7, wall = v.wall;
  let foot = null;
  for (let ix = 0; ix < nx; ix++) for (let iy = 0; iy < ny; iy++) {
    const cx = (ix - (nx - 1) / 2) * pitch, cy = (iy - (ny - 1) / 2) * pitch;
    let f = rbox(35.6, 35.6, 0.8, 0.8).translate([cx, cy, 0]);
    f = f.add(rbox(37.2, 37.2, 1.8, 1.6, 0.8).translate([cx, cy, 0]));
    f = f.add(rbox(41.5, 41.5, 2.15, 3.75, 2.6).translate([cx, cy, 0]));
    foot = foot ? foot.add(f) : f;
  }
  let m = foot.add(rbox(w, d, h - 4.75, 3.75, 4.75));
  m = m.subtract(rbox(w - 2 * wall, d - 2 * wall, h, Math.max(3.75 - wall, 0.5), 4.75 + v.floor));
  if (v.lip) m = m.add(rbox(w, d, 4.4, 3.75, h).subtract(rbox(w - 5.2, d - 5.2, 6, 1.2, h - 1)));
  for (let i = 1; i <= v.dividers; i++) {
    const x = -w / 2 + i * w / (v.dividers + 1);
    m = m.add(rbox(1.2, d - 2 * wall + 0.2, h - 4.75 - v.floor - 1, 0, 4.75 + v.floor).translate([x, 0, 0]));
  }
  return [["Gridfinity 收納盒", m]];
};
B.vase = (v) => {
  const d = v.bottom_d, h = v.height, n = v.sides, tw = v.twist, sc = v.top_d / d;
  const pts = Array.from({ length: n }, (_, i) => [d / 2 * Math.cos(2 * Math.PI * i / n), d / 2 * Math.sin(2 * Math.PI * i / n)]);
  const sec = poly(pts).offset(-1, "Round", 2, 0).offset(1, "Round", 2, 24);
  const div = Math.max(8, Math.floor(h / 2));
  const outer = sec.extrude(h, div, tw, [sc, sc]);
  if (v.solid) return [["花瓶（請用花瓶模式列印）", outer]];
  const inner = sec.offset(-v.wall, "Round", 2, 24).extrude(h, div, tw, [sc, sc]).translate([0, 0, v.wall * 1.5]);
  return [["花瓶", outer.subtract(inner)]];
};
B.plant_pot = (v) => {
  const { top_d: td, bottom_d: bd, height: h, wall: t } = v;
  let pot = cyl(bd, h, 0, td).subtract(cyl(bd - 2 * t, h, t, td - 2 * t));
  if (v.drain_d > 0) {
    pot = pot.subtract(holeZ(v.drain_d, t));
    for (const a of [0, 90, 180, 270]) {
      const r = bd / 4, rad = a * Math.PI / 180;
      pot = pot.subtract(holeZ(v.drain_d * 0.6, t).translate([r * Math.cos(rad), r * Math.sin(rad), 0]));
    }
  }
  const parts = [["花盆", pot]];
  if (v.saucer) { const sd = bd + 16; parts.push(["接水盤", cyl(sd, 12, 0, sd + 6).subtract(cyl(sd - 4, 12, 2, sd + 2))]); }
  return sideBySide(parts);
};
B.knob = (v) => {
  const d = v.diameter, h = v.height, sd = v.shaft_d, n = v.grips;
  let m = cyl(d, h, 0, d * 0.92);
  for (let i = 0; i < n; i++) {
    const a = 2 * Math.PI * i / n;
    m = m.subtract(cyl(d * 0.16, h + 2, -1).translate([d / 2 * Math.cos(a), d / 2 * Math.sin(a), 0]));
  }
  m = m.subtract(cyl(1.6, 1.0, h - 0.8).translate([0, d * 0.32, 0]));
  let shaft = cyl(sd + 0.2, h - 2);
  if (v.d_flat) shaft = shaft.subtract(rbox(sd + 2, sd, h, 0).translate([0, sd * 0.5 + (sd / 2 - sd * 0.1), 0]));
  return [["旋鈕", m.subtract(shaft)]];
};
B.hose_adapter = (v) => {
  const { outer_d1: d1, outer_d2: d2, wall: t, length1: l1, length2: l2 } = v;
  const tr = Math.max(Math.abs(d1 - d2), 6);
  let outer = cyl(d1, l1).add(cyl(d1, tr, l1, d2)).add(cyl(d2, l2, l1 + tr));
  if (v.barbs) for (let k = 0; k < 3; k++) outer = outer.add(cyl(d2 + 1.6, l2 * 0.16, l1 + tr + l2 * (0.2 + 0.25 * k), d2));
  const inner = cyl(d1 - 2 * t, l1 + 0.01, -1).add(cyl(d1 - 2 * t, tr, l1, d2 - 2 * t)).add(cyl(d2 - 2 * t, l2 + 2, l1 + tr));
  return [["管接頭", outer.subtract(inner)]];
};
B.shelf_bracket = (v) => {
  const { shelf_depth: depth, height: hgt, width: w, thick: t } = v;
  const prof = poly([[0, 0], [t, 0], [t, hgt], [0, hgt]]).add(poly([[0, hgt - t], [depth, hgt - t], [depth, hgt], [0, hgt]]))
    .add(poly([[t, hgt * 0.25], [t + t * 1.2, hgt * 0.25], [depth, hgt - t], [depth - t * 1.5, hgt - t]]));
  let m = prof.extrude(w);
  const sd = v.screw_d;
  for (const y of [hgt * 0.3, hgt * 0.75])
    m = m.subtract(Manifold.cylinder(t * 4, sd / 2, sd / 2, SEG).rotate([0, 90, 0]).translate([-t, y, w / 2]));
  m = m.subtract(Manifold.cylinder(t * 4, sd / 2, sd / 2, SEG).rotate([90, 0, 0]).translate([depth * 0.7, hgt + t, w / 2]));
  return [["層板支架", m]];
};
function gearSection(module, teeth, paDeg = 20, steps = 10) {
  const pa = paDeg * Math.PI / 180, rp = module * teeth / 2, rb = rp * Math.cos(pa), ra = rp + module;
  const rf = Math.max(rp - 1.25 * module, 0.5), inv = (a) => Math.tan(a) - a;
  const theta = (r) => Math.PI / (2 * teeth) + inv(pa) - inv(Math.acos(Math.min(rb / Math.max(r, rb), 1)));
  const r0 = Math.max(rb, rf), radii = Array.from({ length: steps + 1 }, (_, k) => r0 + (ra - r0) * k / steps);
  const pts = [];
  for (let i = 0; i < teeth; i++) {
    const a0 = 2 * Math.PI * i / teeth;
    if (rf < rb) pts.push([rf * Math.cos(a0 - theta(rb)), rf * Math.sin(a0 - theta(rb))]);
    for (const r of radii) { const t = Math.max(theta(r), 0); pts.push([r * Math.cos(a0 - t), r * Math.sin(a0 - t)]); }
    for (const r of [...radii].reverse()) { const t = Math.max(theta(r), 0); pts.push([r * Math.cos(a0 + t), r * Math.sin(a0 + t)]); }
    if (rf < rb) pts.push([rf * Math.cos(a0 + theta(rb)), rf * Math.sin(a0 + theta(rb))]);
  }
  return poly(pts);
}
B.gear = (v) => {
  let g = gearSection(v.module, v.teeth).extrude(v.thick);
  if (v.bore > 0) g = g.subtract(holeZ(v.bore, v.thick));
  return [[`正齒輪 m${v.module} z${v.teeth}`, g]];
};
B.desk_hook = (v) => {
  const { width: w, drop, reach, thick: t } = v, top = reach + t + 30;
  const prof = poly([[0, drop], [top, drop], [top, drop + t], [0, drop + t]]).add(poly([[0, 0], [t, 0], [t, drop + t], [0, drop + t]]))
    .add(poly([[0, 0], [reach + t, 0], [reach + t, t], [0, t]])).add(poly([[reach, 0], [reach + t, 0], [reach + t, v.lip], [reach, v.lip]]));
  let m = prof.extrude(w);
  for (const x of [reach + t + 8, top - 8])
    m = m.subtract(Manifold.cylinder(t * 4, v.screw_d / 2, v.screw_d / 2, SEG).rotate([90, 0, 0]).translate([x, drop + t * 3, w / 2]));
  return [["桌下掛鉤", m]];
};

// 額溫槍外殼（移植 pa/recipes.py build_thermo_gun）
const tubeY = (d, length, y0, z = 0, d2 = null, x = 0) =>
  Manifold.cylinder(length, d / 2, (d2 ?? d) / 2, SEG).rotate([90, 0, 0]).translate([x, y0, z]);
const barY = (w, h, length, r, yc, zc = 0) => rrect(w, h, r).extrude(length).rotate([90, 0, 0]).translate([0, yc + length / 2, zc]);
const bossX = (width, y, z, d = 6) => Manifold.cylinder(width, d / 2, d / 2, 48).rotate([0, 90, 0]).translate([-width / 2, y, z]);
function screwHoles(shellW, y, z, sd) {
  const pilot = Manifold.cylinder(shellW + 4, sd * 0.42, sd * 0.42, 32).rotate([0, 90, 0]).translate([-shellW / 2 - 2, y, z]);
  const clear = Manifold.cylinder(shellW / 2 + 2, sd / 2 + 0.2, sd / 2 + 0.2, 32).rotate([0, 90, 0]).translate([-shellW / 2 - 2, y, z]);
  const head = Manifold.cylinder(2.2, sd + 0.4, sd + 0.4, 32).rotate([0, 90, 0]).translate([-shellW / 2 - 0.2, y, z]);
  return pilot.add(clear).add(head);
}
B.thermo_gun = (v) => {
  const t = v.wall, r = v.corner, W = v.head_w, H = v.head_h, stick = Math.round(v.style) === 2;
  const need = t * 2 + 22 + v.battery_l + 6 + v.board_l + 8;
  const L = stick ? Math.max(v.head_l, need) : v.head_l;
  const adds = [], subs = [], screws = [];
  let outer = barY(W, H, L, r, 0);
  let inner = barY(W - 2 * t, H - 2 * t, L - 2 * t, Math.max(r - t, 0.8), 0);
  const nz = -H * 0.05;
  const nose = tubeY(v.nose_d, v.nose_l + 4, -L / 2 + 4, nz, v.nose_d * 0.86);
  outer = outer.add(nose);
  subs.push(tubeY(v.sensor_d + 0.4, v.nose_l + 4 - 1.5, -L / 2 + 4, nz));
  subs.push(tubeY(Math.max(v.sensor_d - 2, 3), 6, -L / 2 - v.nose_l + 3, nz));
  const yb = -L / 2 + t + 22 + v.battery_l / 2;
  const hl = v.handle_l, hW = v.handle_w, hD = v.handle_d, ang = v.handle_angle;
  const ya = L / 2 - hD / 2 - 10, za = -H / 2 + 4;
  const place = (m) => m.rotate([ang, 0, 0]).translate([0, ya, za]);
  if (!stick) {
    const hr = Math.min(r, hW / 2 - 1, hD / 2 - 1);
    outer = outer.add(place(rrect(hW, hD, hr).extrude(hl + 4).translate([0, 0, -hl])));
    inner = inner.add(place(rrect(hW - 2 * t, hD - 2 * t, Math.max(hr - t, 0.8)).extrude(hl + H / 2 + 4 - t).translate([0, 0, -hl + t])));
    const yb0 = -hD / 2 + t + v.board_under + v.board_t / 2, zb0 = -hl + t + 0.5;
    const xIn = hW / 2 - t, xTip = v.board_w / 2 - 1.5;
    for (const sx of [-1, 1]) for (const dy of [-1, 1]) {
      const y = yb0 + dy * (v.board_t / 2 + 0.25 + 0.6);
      adds.push(place(Manifold.cube([xIn - xTip + 0.5, 1.2, v.board_l], false).translate([sx > 0 ? xTip : -xIn - 0.5, y - 0.6, zb0])));
    }
    if (v.usb) subs.push(place(Manifold.cube([v.usb_w, v.usb_h, t * 4 + 2], true).translate([0, yb0 + v.board_t / 2 + 1.6, -hl])));
    subs.push(place(tubeY(v.button_d, t * 4, -hD / 2 + t * 2, -18)));
    adds.push(place(bossX(hW - 2 * t, hD / 2 - t - 5, -hl + 12)));
    screws.push(place(screwHoles(hW, hD / 2 - t - 5, -hl + 12, v.screw_d)));
  } else {
    inner = inner.subtract(nose);
    const yBoard = yb + v.battery_l / 2 + 6 + v.board_l / 2, zb = -H / 2 + t + v.board_under + v.board_t / 2;
    const xIn = W / 2 - t, xTip = v.board_w / 2 - 1.5;
    for (const sx of [-1, 1]) for (const dz of [-1, 1]) {
      const z = zb + dz * (v.board_t / 2 + 0.25 + 0.6);
      adds.push(Manifold.cube([xIn - xTip + 0.5, v.board_l, 1.2], false).translate([sx > 0 ? xTip : -xIn - 0.5, yBoard - v.board_l / 2, z - 0.6]));
    }
    if (v.usb) subs.push(Manifold.cube([v.usb_w, t * 4 + 2, v.usb_h], true).translate([0, L / 2, zb + v.board_t / 2 + 1.6]));
    subs.push(Manifold.cylinder(t * 4, v.button_d / 2, v.button_d / 2, SEG).translate([0, -L / 2 + 30, H / 2 - t * 2]));
  }
  for (const dy of [-1, 1])
    adds.push(Manifold.cube([W - 2 * t + 0.2, 1.6, 5], false).translate([-(W - 2 * t + 0.2) / 2, yb + dy * (v.battery_l / 2 + 0.8) - 0.8, -H / 2 + t - 0.1]));
  const ow = v.oled_w / 2 - 2.5, oh = v.oled_h / 2 - 2.5;
  if (!stick) {
    const zc = H * 0.12;
    subs.push(Manifold.cube([v.win_w, t * 4, v.win_h], true).translate([0, L / 2 - t / 2, zc]));
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      adds.push(tubeY(4.5, 3.5, L / 2 - t + 0.01, zc + sz * oh, null, sx * ow));
      subs.push(tubeY(1.8, 5, L / 2 - t + 0.01, zc + sz * oh, null, sx * ow));
    }
  } else {
    const yc = -L / 2 + 45;
    subs.push(Manifold.cube([v.win_w, v.win_h, t * 4], true).translate([0, yc, H / 2 - t / 2]));
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
      adds.push(Manifold.cylinder(3.5, 2.25, 2.25, 32).translate([sx * ow, yc + sy * oh, H / 2 - t - 3.5 + 0.01]));
      subs.push(Manifold.cylinder(5, 0.9, 0.9, 24).translate([sx * ow, yc + sy * oh, H / 2 - t - 4.5]));
    }
  }
  const zt = H / 2 - t - 5;
  for (const [y, z] of [[-L / 2 + 14, zt], [L / 2 - 12, stick ? -H / 2 + t + 5 : zt]]) {
    adds.push(bossX(W - 2 * t, y, z));
    screws.push(screwHoles(W, y, z, v.screw_d));
  }
  let shell = outer.subtract(inner);
  for (const f of adds) shell = shell.add(f.intersect(outer));
  for (const f of [...subs, ...screws]) shell = shell.subtract(f);
  shell = shell.translate([0, 0, -bbox(shell)[0][2]]);
  if (!v.split) return [["額溫槍外殼（組合）", shell]];
  const [lo, hi] = bbox(shell);
  const big = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) * 3;
  const right = shell.intersect(Manifold.cube([big, big, big], false).translate([0, -big / 2, -big / 2]));
  const left = shell.intersect(Manifold.cube([big, big, big], false).translate([-big, -big / 2, -big / 2]));
  const halves = [["左半殼", left.rotate([0, -90, 0])], ["右半殼", right.rotate([0, 90, 0])]];
  if (v.style === 1) {
    const nested = nestPair(halves[0][1], halves[1][1], 5);
    if (nested) return [[halves[0][0], nested[0]], [halves[1][0], nested[1]]];
  }
  return sideBySide(halves, 10);
};
function nestPair(a, b, gap = 5, step = 3) {
  b = b.rotate([0, 0, 180]);
  const pa = a.project().offset(gap / 2, "Round", 2, 0), pb = b.project().offset(gap / 2, "Round", 2, 0);
  const A = pa.bounds(), Bb = pb.bounds();
  const [ax0, ay0] = A.min, [ax1, ay1] = A.max, [bx0, by0] = Bb.min, [bx1, by1] = Bb.max;
  const side = Math.max(ax1 - ax0 + bx1 - bx0, Math.max(ay1 - ay0, by1 - by0));
  const cands = [];
  const nx = Math.floor((ax1 - ax0 + bx1 - bx0) / step) + 1, ny = Math.floor((ay1 - ay0 + by1 - by0) / step) + 1;
  for (let i = 0; i <= nx; i++) for (let j = 0; j <= ny; j++) {
    const dx = ax0 - bx1 + i * step, dy = ay0 - by1 + j * step;
    const w = Math.max(ax1, bx1 + dx) - Math.min(ax0, bx0 + dx), d = Math.max(ay1, by1 + dy) - Math.min(ay0, by0 + dy);
    if (Math.max(w, d) < side - 1) cands.push([Math.max(w, d), w + d, dx, dy]);
  }
  cands.sort((p, q) => p[0] - q[0] || p[1] - q[1] || p[2] - q[2] || p[3] - q[3]);
  for (const [, , dx, dy] of cands) {
    if (pa.intersect(pb.translate([dx, dy])).area() < 0.5) {
      const b2 = b.translate([dx, dy, 0]), [al, ah] = bbox(a), [bl, bh] = bbox(b2);
      const lo = al.map((x, k) => Math.min(x, bl[k])), hi = ah.map((x, k) => Math.max(x, bh[k]));
      const c = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, 0];
      return [a.translate(c).translate([0, 0, -al[2]]), b2.translate(c).translate([0, 0, -bl[2]])];
    }
  }
  return null;
}

// ------------------------------------------------------------------ 對外
export const RECIPES = DATA.recipes;
export const BY_ID = Object.fromEntries(RECIPES.map((r) => [r.id, r]));

export function clean(rid, values = {}) {
  const r = BY_ID[rid], out = {};
  for (const p of r.params) {
    let v = p.key in values ? values[p.key] : p.default;
    if (p.kind === "bool") { out[p.key] = v === true || v === 1 || v === "1" || v === "true" || v === "是"; continue; }
    v = Number(v);
    if (!Number.isFinite(v)) v = p.default;
    v = Math.min(Math.max(v, p.min), p.max);
    out[p.key] = p.kind === "int" ? Math.round(v) : Math.round(v * 1000) / 1000;
  }
  return out;
}

/** 建模 → {params, parts:[{name, pos: Float32Array, idx: Uint32Array, volume}]}（Z 朝上 mm） */
export function build(rid, values) {
  if (!M) throw new Error("建模引擎尚未載入");
  const v = clean(rid, values);
  try {
    const parts = [];
    for (let [name, m] of B[rid](v)) {
      if (m.isEmpty()) continue;
      const lo = bbox(m)[0];
      if (Math.abs(lo[2]) > 1e-6) m = m.translate([0, 0, -lo[2]]);
      const mesh = m.getMesh(), np = mesh.numProp, vp = mesh.vertProperties, n = vp.length / np;
      const pos = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) { pos[i * 3] = vp[i * np]; pos[i * 3 + 1] = vp[i * np + 1]; pos[i * 3 + 2] = vp[i * np + 2]; }
      parts.push({ name, pos, idx: new Uint32Array(mesh.triVerts), volume: m.volume() });
    }
    if (!parts.length) throw new Error("參數組合產生了空的零件，請調整尺寸");
    return { params: v, parts };
  } finally {
    cleanup();
  }
}

/** 給分區編輯（regions.js）用的 manifold 類別：鑽孔、加凸台、切開。 */
export function manifoldKit() {
  if (!M) throw new Error("建模引擎尚未載入");
  return { Manifold, Mesh: M.Mesh, release: cleanup };
}
