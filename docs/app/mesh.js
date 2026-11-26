// 模型讀寫（線上版）：3MF（含 Bambu 上色筆刷解碼）、STL、OBJ、GLB、PLY；匯出 3MF／STL／GLB／OBJ；縮放、擺放。
// Bambu 上色筆刷解碼移植自 bambu-3mf-to-glb（AGPL-3.0，kylertran），原為 PrusaSlicer／Bambu Studio 的 TriangleSelector。
import { unzipSync, zipSync, strToU8, strFromU8 } from "./lib/jsm/libs/fflate.module.js";

export const DEFAULT_PALETTE = ["#00AE42", "#FFFFFF", "#F5222D", "#1890FF", "#FAAD14", "#722ED1", "#13C2C2", "#EB2F96",
  "#A0D911", "#FA541C", "#2F54EB", "#8C8C8C", "#000000", "#FADB14", "#52C41A", "#FF85C0"];
export const PART_COLORS = [[91, 155, 213], [244, 177, 66], [112, 190, 124], [229, 115, 115], [171, 134, 214], [96, 196, 196]];
const hexRgb = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16) || 0); };

// ====================================================================== 3MF 讀取
const attrRe = /([\w:]+)\s*=\s*"([^"]*)"/g;
function attrs(s) { const o = {}; let m; attrRe.lastIndex = 0; while ((m = attrRe.exec(s))) o[m[1].replace(/^.*:/, "")] = m[2]; return o; }
function mat3mf(t) {           // 3MF 的 4×3 列向量矩陣 → 4×4 欄向量（陣列 [r0..r3] 每列 4 個）
  if (!t) return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
  const v = t.trim().split(/\s+/).map(Number);
  return [[v[0], v[3], v[6], v[9]], [v[1], v[4], v[7], v[10]], [v[2], v[5], v[8], v[11]], [0, 0, 0, 1]];
}
const mmul = (a, b) => a.map((r) => [0, 1, 2, 3].map((j) => r[0] * b[0][j] + r[1] * b[1][j] + r[2] * b[2][j] + r[3] * b[3][j]));
const apply = (m, x, y, z) => [m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3], m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
  m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]];
const normPath = (p, base = "") => {
  p = p.replace(/\\/g, "/");
  if (p.startsWith("/")) return p.slice(1);
  const parts = (base ? base + "/" + p : p).split("/"), out = [];
  for (const s of parts) { if (s === "..") out.pop(); else if (s && s !== ".") out.push(s); }
  return out.join("/");
};

function parseModel(xml, path) {
  const objects = {}, build = [], base = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const objRe = /<(?:\w+:)?object\b([^>]*)>([\s\S]*?)<\/(?:\w+:)?object>/g;
  let m;
  while ((m = objRe.exec(xml))) {
    const a = attrs(m[1]), body = m[2], o = { id: a.id, name: a.name || "", verts: [], tris: [], paint: [], comps: [] };
    const vre = /<(?:\w+:)?vertex\b([^>]*)\/>/g; let v;
    while ((v = vre.exec(body))) { const t = attrs(v[1]); o.verts.push(+t.x, +t.y, +t.z); }
    const tre = /<(?:\w+:)?triangle\b([^>]*)\/>/g; let t;
    while ((t = tre.exec(body))) { const q = attrs(t[1]); o.tris.push(+q.v1, +q.v2, +q.v3); o.paint.push(q.paint_color || q.mmu_segmentation || null); }
    const cre = /<(?:\w+:)?component\b([^>]*)\/>/g; let c;
    while ((c = cre.exec(body))) { const q = attrs(c[1]); o.comps.push({ path: q.path ? normPath(q.path, base) : path, id: q.objectid, tf: mat3mf(q.transform) }); }
    objects[o.id] = o;
  }
  const ire = /<(?:\w+:)?item\b([^>]*)\/?>/g;
  while ((m = ire.exec(xml))) { const q = attrs(m[1]); build.push({ id: q.objectid, tf: mat3mf(q.transform) }); }
  return { objects, build };
}

const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
function splitChildren(tri, sides, special) {
  const a = tri[special % 3], b = tri[(special + 1) % 3], c = tri[(special + 2) % 3];
  if (sides === 1) { const m = mid(c, b); return [[a, b, m], [m, c, a]]; }
  if (sides === 2) { const mab = mid(b, a), mca = mid(a, c); return [[a, mab, mca], [mab, b, mca], [b, c, mca]]; }
  const mab = mid(b, a), mbc = mid(c, b), mca = mid(a, c);
  return [[a, mab, mca], [mab, b, mbc], [mbc, c, mca], [mab, mbc, mca]];
}
export function decodePaint(code, tri) {
  const nib = [...code].reverse().map((ch) => parseInt(ch, 16));
  let pos = 0;
  const next = () => { if (pos >= nib.length) throw new Error("paint code truncated"); return nib[pos++]; };
  const leaves = [], stack = [];
  for (;;) {
    const c = next(), sides = c & 3, special = c >> 2;
    let state = 0;
    if (sides === 0) {
      if ((c & 12) === 12) { let n = next(), num = 0; while (n === 15) { num++; n = next(); } state = n + 15 * num + 3; }
      else state = c >> 2;
    }
    if (!stack.length) {
      if (sides) { stack.push([splitChildren(tri, sides, special), 0]); continue; }
      leaves.push([tri, state]); break;
    }
    const last = stack[stack.length - 1], child = last[0][last[0].length - last[1] - 1];
    if (sides) stack.push([splitChildren(child, sides, special), 0]);
    else { leaves.push([child, state]); last[1]++; }
    while (stack.length && stack[stack.length - 1][1] === stack[stack.length - 1][0].length) {
      stack.pop(); if (stack.length) stack[stack.length - 1][1]++;
    }
    if (!stack.length) break;
  }
  return leaves;
}

/** 3MF → {parts:[{name,pos,idx,rgb}], palette, bambu, stats} 座標為 3MF 的世界座標（Z 朝上 mm）。 */
export function parse3MF(buf) {
  const zip = unzipSync(new Uint8Array(buf)), txt = (n) => zip[n] ? strFromU8(zip[n]) : null;
  let root = "3D/3dmodel.model";
  const rels = txt("_rels/.rels");
  if (rels) { const m = /Target="([^"]+)"[^>]*Type="[^"]*\/3dmodel"|Type="[^"]*\/3dmodel"[^>]*Target="([^"]+)"/.exec(rels); if (m) root = normPath(m[1] || m[2]); }
  let palette = [], bambu = false;
  const ps = txt("Metadata/project_settings.config");
  if (ps) { bambu = true; try { const j = JSON.parse(ps); if (Array.isArray(j.filament_colour)) palette = j.filament_colour; } catch (e) { /* ini */ } }
  const extr = {}, names = {}, ms = txt("Metadata/model_settings.config");
  if (ms) {
    bambu = true;
    const ore = /<(object|part)\b([^>]*)>([\s\S]*?)<\/\1>/g; let m;
    while ((m = ore.exec(ms))) {
      const id = attrs(m[2]).id; if (!id) continue;
      const mre = /<metadata\b([^>]*)\/>/g; let q;
      while ((q = mre.exec(m[3]))) { const a = attrs(q[1]); if (a.key === "extruder") extr[id] = parseInt(a.value) || 1; if (a.key === "name") names[id] = a.value; }
    }
  }
  if (!palette.length) palette = DEFAULT_PALETTE;
  const files = {};
  const load = (p) => {
    if (!files[p]) {
      const x = txt(p); if (!x) throw new Error("3MF 裡找不到 " + p);
      files[p] = parseModel(x, p);
      for (const o of Object.values(files[p].objects)) for (const c of o.comps) if (c.path !== p) load(c.path);
    }
    return files[p];
  };
  const top = load(root);
  let build = top.build;
  if (!build.length) build = Object.values(top.objects).map((o) => ({ id: o.id, tf: mat3mf(null) }));
  const parts = [], stats = {};
  const emit = (path, o, world, fil) => {
    const dfil = extr[o.id] || fil, name = names[o.id] || o.name || "物件" + o.id;
    if (o.tris.length) {
      const pos = [], idx = [], rgb = [], V = o.verts;
      const vtx = (p) => { const w = apply(world, p[0], p[1], p[2]); pos.push(...w); return pos.length / 3 - 1; };
      const colorOf = (f) => hexRgb(palette[f - 1] || "#808080");
      const base = new Int32Array(V.length / 3).fill(-1);
      const bv = (i) => base[i] >= 0 ? base[i] : (base[i] = vtx([V[i * 3], V[i * 3 + 1], V[i * 3 + 2]]));
      for (let t = 0; t < o.tris.length / 3; t++) {
        const code = o.paint[t];
        const i0 = o.tris[t * 3], i1 = o.tris[t * 3 + 1], i2 = o.tris[t * 3 + 2];
        if (!code) { idx.push(bv(i0), bv(i1), bv(i2)); rgb.push(...colorOf(dfil)); stats[dfil] = (stats[dfil] || 0) + 1; continue; }
        const tri = [i0, i1, i2].map((i) => [V[i * 3], V[i * 3 + 1], V[i * 3 + 2]]);
        for (const [[a, b, c], st] of decodePaint(code, tri)) {
          const f = st > 0 ? st : dfil;
          idx.push(vtx(a), vtx(b), vtx(c)); rgb.push(...colorOf(f)); stats[f] = (stats[f] || 0) + 1;
        }
      }
      parts.push({ name, pos: new Float32Array(pos), idx: new Uint32Array(idx), rgb: bambu ? new Uint8Array(rgb) : null });
    }
    for (const c of o.comps) {
      const t = files[c.path]?.objects[c.id];
      if (t) emit(c.path, t, mmul(world, c.tf), dfil);
    }
  };
  for (const it of build) { const o = top.objects[it.id]; if (o) emit(root, o, it.tf, 1); }
  if (!parts.length) throw new Error("檔案裡沒有任何三角面");
  if (!bambu) parts.forEach((p) => { p.rgb = null; });
  return { parts, palette: bambu ? palette : [], bambu, stats };
}

// ====================================================================== 其他格式（用 three.js 的讀取器）
export async function loadFile(name, buf) {
  const ext = name.toLowerCase().split(".").pop(), notes = [];
  if (ext === "3mf") { const r = parse3MF(buf); r.notes = notes; return r; }
  let cmObj = false;
  if (["fbx", "ma", "mb", "mtl", "obj"].includes(ext)) {          // FBX、Maya、有材質群組的 OBJ：材質變成「區塊」（regions.js）
    const R = await import("./regions.js"), g = R.loadGrouped(name, buf);
    if (g && g.parts) return g;
    cmObj = !!(g && g.cmObj);
  }
  const THREE = await import("./lib/three.module.min.js");
  let obj;
  if (ext === "stl") { const { STLLoader } = await import("./lib/jsm/loaders/STLLoader.js"); obj = new THREE.Mesh(new STLLoader().parse(buf)); }
  else if (ext === "ply") { const { PLYLoader } = await import("./lib/jsm/loaders/PLYLoader.js"); obj = new THREE.Mesh(new PLYLoader().parse(buf)); }
  else if (ext === "obj") { const { OBJLoader } = await import("./lib/jsm/loaders/OBJLoader.js"); obj = new OBJLoader().parse(new TextDecoder().decode(buf)); }
  else if (ext === "glb" || ext === "gltf") {
    const { GLTFLoader } = await import("./lib/jsm/loaders/GLTFLoader.js");
    const g = await new GLTFLoader().parseAsync(buf, "");
    obj = g.scene;
    const upright = []; obj.traverse((o) => { if ((o.name || "").includes("Y-up to Z-up")) upright.push(o); });
    if (!upright.length) obj.rotation.x = Math.PI / 2;          // glTF 是 Y 朝上 → 轉成 Z 朝上
  } else throw new Error("不支援的格式：" + ext);
  obj.updateMatrixWorld(true);
  const parts = [];
  obj.traverse((o) => {
    if (!o.isMesh) return;
    let g = o.geometry.clone().applyMatrix4(o.matrixWorld);
    const P = g.attributes.position, n = g.index ? g.index.count / 3 : P.count / 3;
    const pos = new Float32Array(P.count * 3); for (let i = 0; i < P.count; i++) { pos[i * 3] = P.getX(i); pos[i * 3 + 1] = P.getY(i); pos[i * 3 + 2] = P.getZ(i); }
    const idx = g.index ? new Uint32Array(g.index.array) : Uint32Array.from({ length: P.count }, (_, i) => i);
    let rgb = null;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    const col = g.attributes.color;
    if (col) {
      rgb = new Uint8Array(n * 3);
      for (let f = 0; f < n; f++) for (let k = 0; k < 3; k++) {
        let s = 0; for (let j = 0; j < 3; j++) s += [col.getX, col.getY, col.getZ][k].call(col, idx[f * 3 + j]);
        rgb[f * 3 + k] = Math.round(Math.pow(s / 3, 1 / 2.2) * 255);
      }
    } else if (mats[0] && mats[0].color && !(mats[0].map)) {
      rgb = new Uint8Array(n * 3);
      const groups = g.groups.length ? g.groups : [{ start: 0, count: n * 3, materialIndex: 0 }];
      for (const gr of groups) {
        const c = (mats[gr.materialIndex] || mats[0]).color.clone().convertLinearToSRGB();
        for (let f = gr.start / 3; f < (gr.start + gr.count) / 3; f++) { rgb[f * 3] = c.r * 255; rgb[f * 3 + 1] = c.g * 255; rgb[f * 3 + 2] = c.b * 255; }
      }
    }
    parts.push({ name: o.name || "模型", pos, idx, rgb });
  });
  if (!parts.length) throw new Error("檔案裡沒有任何三角面");
  if (cmObj) { scaleParts(parts, 10); notes.push("OBJ 註明單位是公分，已換算成 mm（×10）"); }
  if (ext === "obj" && parts.length > 1) {
    const R = await import("./regions.js");
    const one = R.toSingle(parts);
    notes.push(`OBJ 有 ${parts.length} 個群組，已變成 ${one[0].labelNames.length} 個區塊（可以在「匯入與分區編輯」逐區修改）`);
    return { parts: one, palette: [], notes };
  }
  if (ext === "glb" || ext === "gltf") {
    const s = extent(parts);
    if (s > 0 && s < 0.5) { scaleParts(parts, 1000); notes.push("GLB 單位是公尺，已換算成 mm"); }
  }
  return { parts, palette: [], notes };
}

// ====================================================================== 幾何工具
export function bounds(parts) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const p of parts) for (let i = 0; i < p.pos.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p.pos[i + k]); hi[k] = Math.max(hi[k], p.pos[i + k]); }
  return [lo, hi];
}
export const extent = (parts) => { const [lo, hi] = bounds(parts); return Math.max(...hi.map((h, k) => h - lo[k])); };
export function scaleParts(parts, f) { for (const p of parts) for (let i = 0; i < p.pos.length; i++) p.pos[i] *= f; return parts; }
export function placeOnPlate(parts) {
  const [lo, hi] = bounds(parts), cx = (lo[0] + hi[0]) / 2, cy = (lo[1] + hi[1]) / 2;
  for (const p of parts) for (let i = 0; i < p.pos.length; i += 3) { p.pos[i] -= cx; p.pos[i + 1] -= cy; p.pos[i + 2] -= lo[2]; }
  return parts;
}
export function clone(parts) { return parts.map((p) => ({ ...p, pos: new Float32Array(p.pos), idx: new Uint32Array(p.idx), rgb: p.rgb ? new Uint8Array(p.rgb) : null })); }
function rotate(parts, R) {
  for (const p of parts) for (let i = 0; i < p.pos.length; i += 3) {
    const x = p.pos[i], y = p.pos[i + 1], z = p.pos[i + 2];
    p.pos[i] = R[0] * x + R[1] * y + R[2] * z; p.pos[i + 1] = R[3] * x + R[4] * y + R[5] * z; p.pos[i + 2] = R[6] * x + R[7] * y + R[8] * z;
  }
}
function contactArea(parts) {
  const [lo] = bounds(parts); let a = 0;
  for (const p of parts) for (let f = 0; f < p.idx.length / 3; f++) {
    const [i, j, k] = [p.idx[f * 3] * 3, p.idx[f * 3 + 1] * 3, p.idx[f * 3 + 2] * 3], P = p.pos;
    if (Math.max(P[i + 2], P[j + 2], P[k + 2]) - lo[2] > 0.1) continue;
    a += Math.abs((P[j] - P[i]) * (P[k + 1] - P[i + 1]) - (P[k] - P[i]) * (P[j + 1] - P[i + 1])) / 2;
  }
  return a;
}
/** 自動擺放：在 6 個軸向擺法中挑底面接觸最大的（原本就平穩的不轉）。回傳說明文字。 */
export function orient(parts) {
  const before = contactArea(parts);
  const rots = [[1, 0, 0, 0, 1, 0, 0, 0, 1], [1, 0, 0, 0, -1, 0, 0, 0, -1], [1, 0, 0, 0, 0, -1, 0, 1, 0], [1, 0, 0, 0, 0, 1, 0, -1, 0],
    [0, 0, 1, 0, 1, 0, -1, 0, 0], [0, 0, -1, 0, 1, 0, 1, 0, 0]];
  let best = null, bestA = before * 1.15;
  for (const R of rots.slice(1)) {
    const c = clone(parts); rotate(c, R); placeOnPlate(c);
    const a = contactArea(c); if (a > bestA) { best = R; bestA = a; }
  }
  if (!best) { placeOnPlate(parts); return `原本已平穩放在板上（接觸面 ${before.toFixed(0)} mm²），不需要轉`; }
  rotate(parts, best); placeOnPlate(parts);
  return `轉到平底朝下（接觸面 ${before.toFixed(0)} → ${bestA.toFixed(0)} mm²）`;
}

// ====================================================================== 匯出
export function write3MF(parts, title = "model") {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const objs = parts.map((p, n) => {
    let vx = "", tx = "";
    for (let i = 0; i < p.pos.length; i += 3) vx += `<vertex x="${p.pos[i].toFixed(5)}" y="${p.pos[i + 1].toFixed(5)}" z="${p.pos[i + 2].toFixed(5)}"/>`;
    for (let i = 0; i < p.idx.length; i += 3) tx += `<triangle v1="${p.idx[i]}" v2="${p.idx[i + 1]}" v3="${p.idx[i + 2]}"/>`;
    return `<object id="${n + 1}" name="${esc(p.name)}" type="model"><mesh><vertices>${vx}</vertices><triangles>${tx}</triangles></mesh></object>`;
  }).join("");
  const items = parts.map((_, n) => `<item objectid="${n + 1}" transform="1 0 0 0 1 0 0 0 1 128 128 0"/>`).join("");
  const model = `<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="zh-TW" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="Title">${esc(title)}</metadata><metadata name="Application">資料助秘3D列印AI代理人工具</metadata><resources>${objs}</resources><build>${items}</build></model>`;
  return zipSync({
    "[Content_Types].xml": strToU8('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'),
    "_rels/.rels": strToU8('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'),
    "3D/3dmodel.model": strToU8(model)}, { level: 6 });
}
export function writeSTL(parts) {
  const n = parts.reduce((s, p) => s + p.idx.length / 3, 0), buf = new ArrayBuffer(84 + 50 * n), dv = new DataView(buf);
  dv.setUint32(80, n, true); let o = 84;
  for (const p of parts) for (let f = 0; f < p.idx.length / 3; f++) {
    const v = [0, 1, 2].map((k) => p.idx[f * 3 + k] * 3), P = p.pos;
    const ux = P[v[1]] - P[v[0]], uy = P[v[1] + 1] - P[v[0] + 1], uz = P[v[1] + 2] - P[v[0] + 2];
    const wx = P[v[2]] - P[v[0]], wy = P[v[2] + 1] - P[v[0] + 1], wz = P[v[2] + 2] - P[v[0] + 2];
    let nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx; const l = Math.hypot(nx, ny, nz) || 1;
    for (const x of [nx / l, ny / l, nz / l]) { dv.setFloat32(o, x, true); o += 4; }
    for (const vi of v) for (let k = 0; k < 3; k++) { dv.setFloat32(o, P[vi + k], true); o += 4; }
    o += 2;
  }
  return buf;
}
export function writeOBJ(parts) {
  let s = "# 資料助秘3D列印AI代理人工具\n", base = 1;
  for (const p of parts) {
    s += `o ${p.name}\n`;
    for (let i = 0; i < p.pos.length; i += 3) s += `v ${p.pos[i]} ${p.pos[i + 1]} ${p.pos[i + 2]}\n`;
    for (let i = 0; i < p.idx.length; i += 3) s += `f ${p.idx[i] + base} ${p.idx[i + 1] + base} ${p.idx[i + 2] + base}\n`;
    base += p.pos.length / 3;
  }
  return strToU8(s);
}
/** GLB：每個零件一個節點、每種顏色一個材質；Z 朝上 mm → glTF 的 Y 朝上（公尺或毫米）。 */
export async function writeGLB(parts, units = "m") {
  const THREE = await import("./lib/three.module.min.js");
  const { GLTFExporter } = await import("./lib/jsm/exporters/GLTFExporter.js");
  const root = new THREE.Group(); root.name = "資料助秘3D列印";
  const s = units === "m" ? 0.001 : 1;
  parts.forEach((p, n) => {
    const nf = p.idx.length / 3, groups = new Map();
    for (let f = 0; f < nf; f++) {
      const c = p.rgb ? `${p.rgb[f * 3]},${p.rgb[f * 3 + 1]},${p.rgb[f * 3 + 2]}` : PART_COLORS[n % PART_COLORS.length].join(",");
      if (!groups.has(c)) groups.set(c, []);
      groups.get(c).push(p.idx[f * 3], p.idx[f * 3 + 1], p.idx[f * 3 + 2]);
    }
    const g = new THREE.BufferGeometry(), mats = [], all = [];
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(p.pos), 3));
    for (const [c, ix] of groups) {
      g.addGroup(all.length, ix.length, mats.length); all.push(...ix);
      const [r, gg, b] = c.split(",").map(Number);
      mats.push(new THREE.MeshStandardMaterial({ color: new THREE.Color().setRGB(r / 255, gg / 255, b / 255, THREE.SRGBColorSpace), roughness: 0.7, metalness: 0, name: "#" + [r, gg, b].map((x) => x.toString(16).padStart(2, "0")).join("").toUpperCase() }));
    }
    g.setIndex(all); g.computeVertexNormals();
    const mesh = new THREE.Mesh(g, mats); mesh.name = p.name; root.add(mesh);
  });
  root.rotation.x = -Math.PI / 2; root.scale.setScalar(s);
  const scene = new THREE.Scene(); scene.add(root);
  return await new GLTFExporter().parseAsync(scene, { binary: true });
}

export async function sha256(bytes) {
  const h = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
