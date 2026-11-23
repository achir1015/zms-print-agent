// 七項列印前檢查（線上版）：依 bambu-studio-ai（MIT）的規則與評分重寫成 JavaScript，訊息與電腦版（pa/checks.py）相同。
import { DATA } from "./data.js";

const PLATE_TOL = 0.1, FLAT_DEG = 5, OH_WARN = 5, OH_FAIL = 20, MIN_CONTACT = 1, SMALL_CONTACT = 5;
const THIN_WARN = 1, THIN_FAIL = 5, MAX_MEAS = 10;
export const STATUS_ZH = { pass: ["通過", "green"], warn: ["注意", "amber"], fail: ["不合格", "rose"], skipped: ["略過", "slate"] };

/** 把多個零件合併並焊接相同位置的頂點（讀進來的 STL 每個三角形各自有頂點）。 */
export function combine(parts) {
  const map = new Map(), pos = [], idx = [];
  for (const p of parts) {
    const P = p.pos, I = p.idx;
    const local = new Int32Array(P.length / 3);
    for (let i = 0; i < local.length; i++) {
      const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2];
      const key = Math.round(x * 1e4) + "," + Math.round(y * 1e4) + "," + Math.round(z * 1e4) + "#" + parts.indexOf(p);
      let k = map.get(key);
      if (k === undefined) { k = pos.length / 3; pos.push(x, y, z); map.set(key, k); }
      local[i] = k;
    }
    for (let i = 0; i < I.length; i++) idx.push(local[I[i]]);
  }
  return { pos: new Float64Array(pos), idx: new Uint32Array(idx) };
}

function faceData(m) {
  const { pos: P, idx: I } = m, n = I.length / 3;
  const area = new Float64Array(n), nz = new Float64Array(n), nrm = new Float64Array(n * 3), top = new Float64Array(n), low = new Float64Array(n);
  let vol = 0;
  for (let f = 0; f < n; f++) {
    const a = I[f * 3] * 3, b = I[f * 3 + 1] * 3, c = I[f * 3 + 2] * 3;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2];
    const vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx;
    const len = Math.hypot(cx, cy, cz);
    area[f] = len / 2;
    if (len > 0) { nrm[f * 3] = cx / len; nrm[f * 3 + 1] = cy / len; nrm[f * 3 + 2] = cz / len; }
    nz[f] = nrm[f * 3 + 2];
    top[f] = Math.max(P[a + 2], P[b + 2], P[c + 2]);
    low[f] = Math.min(P[a + 2], P[b + 2], P[c + 2]);
    vol += (P[a] * (P[b + 1] * P[c + 2] - P[b + 2] * P[c + 1]) - P[a + 1] * (P[b] * P[c + 2] - P[b + 2] * P[c])
      + P[a + 2] * (P[b] * P[c + 1] - P[b + 1] * P[c])) / 6;
  }
  return { n, area, nz, nrm, top, low, vol };
}

function bounds(P) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < P.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[i + k]); hi[k] = Math.max(hi[k], P[i + k]); }
  return [lo, hi];
}

function diagnose(m, fd) {
  const I = m.idx, edges = new Map();
  let degenerate = 0;
  for (let f = 0; f < fd.n; f++) {
    if (fd.area[f] < 1e-12) degenerate++;
    for (let k = 0; k < 3; k++) {
      const a = I[f * 3 + k], b = I[f * 3 + (k + 1) % 3];
      const key = a < b ? a + "_" + b : b + "_" + a;
      const e = edges.get(key) || [0, 0];
      e[0]++; e[1] += a < b ? 1 : -1;            // 方向：一致的話兩個面走相反方向 → 加總 0
      edges.set(key, e);
    }
  }
  let boundary = 0, nonmanifold = 0, flipped = 0;
  for (const [c, dir] of edges.values()) {
    if (c === 1) boundary++; else if (c > 2) nonmanifold++; else if (dir !== 0) flipped++;
  }
  // 連通的實體數（共用頂點）
  const parent = new Int32Array(m.pos.length / 3).map((_, i) => i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for (let f = 0; f < fd.n; f++) {
    const a = find(I[f * 3]), b = find(I[f * 3 + 1]), c = find(I[f * 3 + 2]);
    parent[b] = a; parent[find(c)] = a;
  }
  const label = new Int32Array(fd.n), roots = new Map();
  for (let f = 0; f < fd.n; f++) {
    const r = find(I[f * 3]);
    if (!roots.has(r)) roots.set(r, roots.size);
    label[f] = roots.get(r);
  }
  const watertight = boundary === 0 && nonmanifold === 0;
  return { watertight, consistent: flipped === 0, insideOut: watertight && fd.vol < 0, boundary, nonmanifold, degenerate,
    bodies: roots.size, label };
}

// 簡單的可重現亂數（取樣用）
function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

function thickness(m, fd, minWall, samples) {
  const P = m.pos, I = m.idx, n = fd.n;
  const cum = new Float64Array(n); let tot = 0;
  for (let f = 0; f < n; f++) { tot += fd.area[f]; cum[f] = tot; }
  const r = rng(7), res = [];
  for (let s = 0; s < samples; s++) {
    const t = r() * tot; let lo = 0, hi = n - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < t) lo = mid + 1; else hi = mid; }
    const f = lo; let u = r(), v = r(); if (u + v > 1) { u = 1 - u; v = 1 - v; }
    const a = I[f * 3] * 3, b = I[f * 3 + 1] * 3, c = I[f * 3 + 2] * 3;
    const o = [0, 1, 2].map((k) => P[a + k] + u * (P[b + k] - P[a + k]) + v * (P[c + k] - P[a + k]));
    const d = [-fd.nrm[f * 3], -fd.nrm[f * 3 + 1], -fd.nrm[f * 3 + 2]];
    let best = Infinity;
    for (let g = 0; g < n; g++) {
      if (g === f) continue;
      // 只算「離開實體」的面：外法線和射線同方向
      if (fd.nrm[g * 3] * d[0] + fd.nrm[g * 3 + 1] * d[1] + fd.nrm[g * 3 + 2] * d[2] <= 0) continue;
      const A = I[g * 3] * 3, Bv = I[g * 3 + 1] * 3, C = I[g * 3 + 2] * 3;
      const e1x = P[Bv] - P[A], e1y = P[Bv + 1] - P[A + 1], e1z = P[Bv + 2] - P[A + 2];
      const e2x = P[C] - P[A], e2y = P[C + 1] - P[A + 1], e2z = P[C + 2] - P[A + 2];
      const px = d[1] * e2z - d[2] * e2y, py = d[2] * e2x - d[0] * e2z, pz = d[0] * e2y - d[1] * e2x;
      const det = e1x * px + e1y * py + e1z * pz;
      if (Math.abs(det) < 1e-12) continue;
      const inv = 1 / det, tx = o[0] - P[A], ty = o[1] - P[A + 1], tz = o[2] - P[A + 2];
      const uu = (tx * px + ty * py + tz * pz) * inv; if (uu < 0 || uu > 1) continue;
      const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
      const vv = (d[0] * qx + d[1] * qy + d[2] * qz) * inv; if (vv < 0 || uu + vv > 1) continue;
      const dist = (e2x * qx + e2y * qy + e2z * qz) * inv;
      if (dist > 1e-6 && dist < best) best = dist;
    }
    res.push(Math.min(best, MAX_MEAS));
  }
  res.sort((x, y) => x - y);
  const thin = Math.round(res.filter((x) => x < minWall).length / res.length * 1000) / 10;
  return { thin, min: Math.round(res[0] * 100) / 100, p5: Math.round(res[Math.floor(res.length * 0.05)] * 100) / 100 };
}

const f1 = (x) => Math.round(x * 10) / 10;
const g = (x) => String(Math.round(x * 100) / 100);

/** 檢查 → 和電腦版同格式的報告 {score, size, items:[{id,name,status,status_zh,tone,text}], settings, suggestions} */
export function check(parts, printer = "A1", material = "PLA", purpose = "general") {
  const m = combine(parts), fd = faceData(m), dg = diagnose(m, fd);
  const [lo, hi] = bounds(m.pos), size = [0, 1, 2].map((k) => hi[k] - lo[k]);
  const pr = DATA.printers[printer], mat = DATA.materials[material] || DATA.materials.PLA;
  const items = [];
  const add = (id, name, status, text) => items.push({ id, name, status, status_zh: STATUS_ZH[status][0], tone: STATUS_ZH[status][1], text });
  // 1 網格
  if (dg.watertight && dg.consistent && !dg.insideOut && !dg.degenerate) add("mesh", "網格完整性", "pass", "封閉實體、法線方向一致，可以直接切片。");
  else {
    const bits = [];
    if (dg.boundary) bits.push(dg.boundary + " 條破洞邊");
    if (dg.nonmanifold) bits.push(dg.nonmanifold + " 條非流形邊");
    if (dg.degenerate) bits.push(dg.degenerate + " 個退化面");
    if (!dg.consistent) bits.push("面的方向不一致");
    if (dg.insideOut) bits.push("內外顛倒");
    add("mesh", "網格完整性", dg.watertight ? "warn" : "fail",
      dg.watertight ? `大致封閉，但有 ${bits.join("、")}。` : `網格沒有封閉（${bits.join("、")}），切片軟體可能補錯或漏掉部分。`);
  }
  // 2 範圍
  let fits = null;
  if (!pr) add("build_volume", "列印範圍", "skipped", "未指定印表機，沒有檢查列印範圍。");
  else {
    const u = pr.usable, pct = (s, uu) => Math.min(...s.map((x, k) => x > 0 ? uu[k] / x * 100 : Infinity));
    const straight = pct(size, u), turned = pct(size, [u[1], u[0], u[2]]);
    const us = u.map((x) => g(x)).join(" × ");
    if (straight >= 100 || turned >= 100) {
      fits = true;
      add("build_volume", "列印範圍", straight >= 100 ? "pass" : "warn", `放得進 ${printer}（可用範圍 ${us} mm）${straight >= 100 ? "" : "，需要在板上轉 90°"}。`);
    } else {
      fits = false;
      add("build_volume", "列印範圍", "fail", `超出 ${printer} 的可用範圍（${us} mm）；最多縮放到 ${Math.floor(Math.max(straight, turned) * 10) / 10}% 或分割模型。`);
    }
  }
  // 3 懸空（每個實體的最低點是否在板上，或正下方有其他實體）
  const bodyLow = new Array(dg.bodies).fill(Infinity), bodyBox = Array.from({ length: dg.bodies }, () => [[Infinity, Infinity, Infinity], [-Infinity, -Infinity, -Infinity]]);
  for (let f = 0; f < fd.n; f++) {
    const b = dg.label[f]; bodyLow[b] = Math.min(bodyLow[b], fd.low[f]);
    for (const vi of [m.idx[f * 3], m.idx[f * 3 + 1], m.idx[f * 3 + 2]]) for (let k = 0; k < 3; k++) {
      bodyBox[b][0][k] = Math.min(bodyBox[b][0][k], m.pos[vi * 3 + k]); bodyBox[b][1][k] = Math.max(bodyBox[b][1][k], m.pos[vi * 3 + k]);
    }
  }
  const gaps = [];
  for (let b = 0; b < dg.bodies; b++) {
    if (bodyLow[b] - lo[2] <= PLATE_TOL) continue;
    const [blo, bhi] = bodyBox[b], cx = (blo[0] + bhi[0]) / 2, cy = (blo[1] + bhi[1]) / 2;
    const supported = bodyBox.some(([olo, ohi], o) => o !== b && cx >= olo[0] && cx <= ohi[0] && cy >= olo[1] && cy <= ohi[1] && olo[2] < bodyLow[b]);
    if (!supported) gaps.push(bodyLow[b] - lo[2]);
  }
  if (!gaps.length) add("floating_parts", "懸空零件", "pass", dg.bodies <= 1 ? "一個實體、平放在列印板上。" : `全部 ${dg.bodies} 個實體都放在板上或其他零件上。`);
  else add("floating_parts", "懸空零件", "fail", `${dg.bodies} 個實體中有 ${gaps.length} 個懸在半空（最低離板 ${Math.min(...gaps).toFixed(1)} mm），要加支撐或移除。`);
  // 4 懸垂
  let areaTot = 0, ohArea = 0, contact = 0;
  const lim = -Math.sin(45 * Math.PI / 180), flat = -Math.cos(FLAT_DEG * Math.PI / 180);
  for (let f = 0; f < fd.n; f++) {
    areaTot += fd.area[f];
    if (fd.nz[f] < lim && fd.top[f] - lo[2] >= PLATE_TOL) ohArea += fd.area[f];
    if (fd.nz[f] < flat && fd.top[f] - lo[2] < PLATE_TOL) contact += fd.area[f];
  }
  const ohPct = areaTot > 0 ? f1(100 * ohArea / areaTot) : 0;
  const ohSt = ohPct > OH_FAIL ? "fail" : ohPct > OH_WARN ? "warn" : "pass";
  add("overhangs", "懸垂角度", ohSt, ohArea <= 0 ? "沒有超過 45° 的懸垂面，不需要支撐。" :
    `${ohPct}% 的表面（${(ohArea / 100).toFixed(1)} cm²）懸垂超過 45°${ohSt !== "pass" ? "，建議開啟支撐" : "，影響不大"}。`);
  // 5 壁厚
  let thin = 0;
  if (!dg.watertight || !dg.consistent || dg.insideOut) add("wall_thickness", "壁厚", "skipped", "網格沒有封閉，無法量測壁厚。");
  else {
    const t = thickness(m, fd, mat.min_wall, fd.n > 60000 ? 150 : fd.n > 15000 ? 300 : 600);
    thin = t.thin;
    const st = thin > THIN_FAIL ? "fail" : thin > THIN_WARN ? "warn" : "pass";
    add("wall_thickness", "壁厚", st, st === "pass" ? `沒有薄於 ${mat.min_wall} mm 的牆（95% 的表面至少 ${t.p5} mm）。` :
      `${thin}% 的表面薄於 ${mat.min_wall} mm（最薄 ${t.min} mm），可能印不出來或很脆。`);
  }
  // 6 底面
  const foot = size[0] * size[1], cPct = foot > 0 ? f1(100 * contact / foot) : 0;
  if (contact < MIN_CONTACT) add("bed_contact", "底面接觸", "warn", "只有點或線接觸列印板，請加寬邊（brim）、支撐或換個方向擺放。");
  else add("bed_contact", "底面接觸", cPct < SMALL_CONTACT ? "warn" : "pass",
    `${contact.toFixed(0)} mm² 平貼在列印板上（佔底面範圍 ${cPct}%）${cPct < SMALL_CONTACT ? "，接觸面偏小，建議加寬邊" : ""}。`);
  // 7 材料
  let matFail = false;
  if (!pr) add("material", "材料適用", "skipped", "未指定印表機，沒有檢查材料。");
  else {
    const probs = [];
    if (mat.enclosure && !pr.enclosed) probs.push("需要封閉式印表機（開放式機種容易翹曲、有氣味）");
    if (mat.high_temp && !pr.high_temp) probs.push("需要的噴嘴溫度超過這台印表機");
    matFail = probs.length > 0;
    add("material", "材料適用", matFail ? "fail" : "pass", matFail ? `${material} 不適合 ${printer}：${probs.join("；")}` : `${material} 適合 ${printer}。`);
  }
  // 評分（同 bambu-studio-ai 的規則）
  let score = 10 - f1(Math.min(4, ohPct / 5)) - f1(Math.min(4, thin / 5)) -
    (contact < MIN_CONTACT ? 2 : cPct < SMALL_CONTACT ? 1 : 0) - (matFail ? 3 : 0);
  if (!dg.watertight || gaps.length || fits === false) score = Math.min(score, 4);
  score = Math.max(0, f1(score));
  // 建議設定
  const largest = Math.max(...size);
  const layer = largest < 30 ? "0.12 mm（小模型，細節較好）" : largest > 200 ? "0.28 mm（大模型，較快）" : "0.20 mm";
  const infill = purpose === "decorative" ? "15 %" : purpose === "functional" ? "30 %" : "15-30 %（依用途）";
  const settings = [["層高", layer], ["填充", infill], ["牆數", purpose === "functional" ? "至少 4 圈" : "至少 3 圈"],
    ["頂底層", "至少 5 層"], ["噴嘴溫度", `${mat.nozzle[0]}～${mat.nozzle[1]} °C`], ["熱床溫度", `${mat.bed} °C`],
    ["支撐", ohSt === "pass" ? "大概不需要" : "懸垂處需要支撐"]];
  const sugg = [];
  const narrow = Math.min(size[0], size[1]);
  if (size[2] >= Math.max(size[0], size[1]) && narrow > 0 && size[2] / narrow > 5) sugg.push("模型細高，列印時容易晃動：加寬邊或和其他零件一起印。");
  if (fd.n > 500000) sugg.push("三角面很多，Bambu Studio 若變慢可用「簡化模型」。");
  if (purpose === "functional") sugg.push("功能零件：建議 4 圈牆；零件互相配合處留約 0.2 mm 間隙。");
  const volume = dg.watertight ? Math.abs(fd.vol) / 1000 : null;
  let weight = null;
  if (volume) { const shell = Math.min(Math.abs(fd.vol), areaTot * 0.8); weight = f1((shell + (Math.abs(fd.vol) - shell) * 0.15) / 1000 * 1.24); }
  return { score, printer, material, purpose, size: size.map((x) => Math.round(x * 100) / 100), volume_cm3: volume && Math.round(volume * 100) / 100,
    triangles: fd.n, bodies: dg.bodies, items, settings, suggestions: sugg, weight_g: weight };
}
