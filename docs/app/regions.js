// 匯入現成模型與分區編輯（線上版）：逐行移植 pa/importers.py 與 pa/segment.py。改其中一邊時兩邊要一起改。
// 區塊模型＝只有一個零件，零件多帶 labels（每個面的區塊編號）、labelNames、colors（使用者指定的耗材顏色 {區塊名: #hex}）。
import { unzlibSync, zipSync, strToU8 } from "./lib/jsm/libs/fflate.module.js";
import { manifoldKit } from "./engine.js";

export const PALETTE = ["#5B9BD5", "#F4B142", "#70BE7C", "#E57373", "#AB86D6", "#60C4C4", "#F28DB2", "#A1887F",
  "#9CCC65", "#FFB74D", "#4DB6AC", "#7986CB", "#E0E0E0", "#BA68C8", "#4FC3F7", "#DCE775"];
export const COLOR_NAMES = { "紅": "#E53935", "紅色": "#E53935", "橙": "#FB8C00", "橘": "#FB8C00", "黃": "#FDD835", "綠": "#43A047",
  "藍": "#1E88E5", "淺藍": "#4FC3F7", "深藍": "#1A237E", "紫": "#8E24AA", "粉紅": "#F06292", "黑": "#212121",
  "白": "#FAFAFA", "灰": "#9E9E9E", "銀": "#BDBDBD", "金": "#D4AF37", "咖啡": "#6D4C41", "棕": "#6D4C41",
  "透明": "#E3F2FD", "red": "#E53935", "orange": "#FB8C00", "yellow": "#FDD835", "green": "#43A047",
  "blue": "#1E88E5", "purple": "#8E24AA", "pink": "#F06292", "black": "#212121", "white": "#FAFAFA",
  "gray": "#9E9E9E", "grey": "#9E9E9E" };
export const METHODS = { auto: "自動（有材質群組就用群組，否則依表面或空間分塊）", groups: "原檔材質／群組",
  bodies: "互不相連的實體", surface: "表面轉折", zones: "空間分塊（適合一體成形的曲面模型）", height: "由下往上分層" };

export class EditError extends Error {}

export function hexrgb(h) {
  h = String(h).trim();
  if (COLOR_NAMES[h]) h = COLOR_NAMES[h];
  h = h.replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) throw new EditError("顏色格式要像 #FF0000，或用中文：紅、橙、黃、綠、藍、紫、粉紅、黑、白、灰…");
  return [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16));
}

// ====================================================================== 讀檔（OBJ 群組、FBX 二進位、Maya ASCII）
const UNIT_MM = { mm: 1, millimeter: 1, cm: 10, centimeter: 10, m: 1000, meter: 1000, in: 25.4, inch: 25.4, ft: 304.8, foot: 304.8, yd: 914.4, yard: 914.4 };
export const triangulate = (poly) => { const out = []; for (let i = 1; i < poly.length - 1; i++) out.push([poly[0], poly[i], poly[i + 1]]); return out; };
function eulerXYZ(rx, ry, rz) {           // Maya／FBX 旋轉順序 XYZ（度）→ R＝Z·Y·X
  [rx, ry, rz] = [rx, ry, rz].map((a) => a * Math.PI / 180);
  const [cx, sx, cy, sy, cz, sz] = [Math.cos(rx), Math.sin(rx), Math.cos(ry), Math.sin(ry), Math.cos(rz), Math.sin(rz)];
  const X = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]], Y = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], Z = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]];
  const mul = (a, b) => a.map((r) => [0, 1, 2].map((j) => r[0] * b[0][j] + r[1] * b[1][j] + r[2] * b[2][j]));
  return mul(mul(Z, Y), X);
}
function applyTF(v, tf) {                 // v（扁平陣列）← (v·s)·Rᵀ + t
  const R = eulerXYZ(...tf.r), [sx, sy, sz] = tf.s, [tx, ty, tz] = tf.t;
  for (let i = 0; i < v.length; i += 3) {
    const x = v[i] * sx, y = v[i + 1] * sy, z = v[i + 2] * sz;
    v[i] = R[0][0] * x + R[0][1] * y + R[0][2] * z + tx; v[i + 1] = R[1][0] * x + R[1][1] * y + R[1][2] * z + ty; v[i + 2] = R[2][0] * x + R[2][1] * y + R[2][2] * z + tz;
  }
}
function yUpToZUp(v) { for (let i = 0; i < v.length; i += 3) { const y = v[i + 1], z = v[i + 2]; v[i + 1] = -z; v[i + 2] = y; } }

/** OBJ：每個面記住 usemtl 材質名；Maya 匯出（註明公分）→ ×10 並轉成 Z 朝上。 */
export function loadOBJGroups(text) {
  const verts = [], tris = [], groups = [];
  let cur = null;
  const lines = text.split(/\r?\n/), head = lines.slice(0, 5).join("\n").toLowerCase();
  for (const line of lines) {
    if (line.startsWith("v ")) { const p = line.trim().split(/\s+/); verts.push(+p[1], +p[2], +p[3]); }
    else if (line.startsWith("usemtl")) { const p = line.trim().split(/\s+/); cur = p.length > 1 ? line.trim().slice(6).trim() : null; }
    else if (line.startsWith("f ")) {
      const n = verts.length / 3, idx = line.trim().split(/\s+/).slice(1).map((tok) => { const k = parseInt(tok.split("/")[0]); return k > 0 ? k - 1 : n + k; });
      for (const t of triangulate(idx)) { tris.push(t); groups.push(cur ? cur.replace(/SG$/, "") : null); }
    }
  }
  if (!tris.length) throw new EditError("OBJ 裡沒有面");
  const v = new Float64Array(verts), maya = head.includes("centimeter");
  if (maya) { for (let i = 0; i < v.length; i++) v[i] *= 10; yUpToZUp(v); }
  return { parts: [{ name: "模型", v, tris, groups }], maya };
}
export function objHasGroups(text) {
  const seen = new Set();
  for (const m of text.matchAll(/^usemtl.*$/gm)) { seen.add(m[0].trim()); if (seen.size > 1) return true; }
  return false;
}

// ---------------------------------------------------------------- Maya ASCII
export function loadMA(text) {
  const unit = /currentUnit\s+-l\s+(\w+)/.exec(text);
  const scale = unit ? (UNIT_MM[unit[1]] ?? 10) : 10;
  const upZ = /upAxis\s+"?z/i.test(text);
  const blocks = text.split("\ncreateNode "), transforms = {}, out = [];
  for (const b of blocks.slice(1)) {
    const head = b.split("\n", 1)[0], kind = head.split(/\s+/)[0];
    const name = (/-n\s+"([^"]+)"/.exec(head) || [null, ""])[1], parent = (/-p\s+"([^"]+)"/.exec(head) || [null, ""])[1];
    if (kind === "transform") {
      const tf = { t: [0, 0, 0], r: [0, 0, 0], s: [1, 1, 1], parent };
      for (const key of ["t", "r", "s"]) {
        const m = new RegExp(String.raw`setAttr "\.${key}" -type "double3" ([-\d.e+ ]+);`).exec(b);
        if (m) tf[key] = m[1].trim().split(/\s+/).map(Number);
      }
      transforms[name] = tf;
    } else if (kind === "mesh") {
      if (/setAttr "\.io" yes/.test(b)) continue;
      out.push([name, parent, b]);
    }
  }
  if (!out.length) throw new EditError("Maya 檔裡沒有多邊形網格（mesh）");
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matOf = {};
  for (const m of text.matchAll(/connectAttr "([^".]+)\.(?:oc|out|outColor)" "([^".]+)\.ss"/g)) matOf[m[2]] = m[1];
  const parts = [];
  for (const [name, parent, b] of out) {
    const verts = maArray(b, "vt", 3), edges = maArray(b, "ed", 3), facesRaw = maFaces(b);
    if (!verts.length || !facesRaw.length) continue;
    const short = reEsc(name.split("|").pop()), sgOf = {}, ogName = {}, groupOf = {};
    for (const m of text.matchAll(new RegExp(String.raw`connectAttr "([^".]+)\.mwc" "[^"]*${short}\.iog\.og\[(\d+)\]\.gco"`, "g"))) sgOf[+m[2]] = m[1];
    for (const m of text.matchAll(new RegExp(String.raw`connectAttr "[^"]*${short}\.iog\.og\[(\d+)\]" "([^".]+)\.dsm"`, "g"))) if (!(+m[1] in sgOf)) sgOf[+m[1]] = m[2];
    for (const [k, sg] of Object.entries(sgOf)) ogName[k] = matOf[sg] || sg.replace(/SG$/, "");
    for (const m of b.matchAll(/\.iog\[0\]\.og\[(\d+)\]\.gcl" -type "componentList" \d+ ((?:"[^"]*"\s*)+);/g)) {
      for (const c of m[2].matchAll(/"f\[(\d+)(?::(\d+))?\]"/g)) {
        for (let fi = +c[1]; fi <= +(c[2] ?? c[1]); fi++) groupOf[fi] = ogName[+m[1]] ?? `區塊 ${+m[1] + 1}`;
      }
    }
    const tris = [], tgroups = [];
    facesRaw.forEach((elist, fi) => {
      const poly = elist.map((e) => e >= 0 ? edges[e * 3] : edges[(-e - 1) * 3 + 1]);
      for (const t of triangulate(poly)) { tris.push(t); tgroups.push(groupOf[fi] ?? null); }
    });
    const v = Float64Array.from(verts);
    let p = parent;
    while (p && transforms[p]) { applyTF(v, transforms[p]); p = transforms[p].parent; }
    for (let i = 0; i < v.length; i++) v[i] *= scale;
    if (!upZ) yUpToZUp(v);
    parts.push({ name: name || "Maya 網格", v, tris, groups: tgroups });
  }
  if (!parts.length) throw new EditError("Maya 網格沒有面");
  return parts;
}
function maArray(block, attr, width) {
  const vals = [];
  for (const m of block.matchAll(new RegExp(String.raw`setAttr "\.${attr}\[\d+(?::\d+)?\]"\s+([^;]*);`, "g"))) vals.push(...m[1].replace(/\n/g, " ").trim().split(/\s+/));
  const nums = vals.filter((x) => /^[-+]?\d*\.?\d+(?:e[-+]?\d+)?$/i.test(x)).map(Number);
  return nums.slice(0, Math.floor(nums.length / width) * width);
}
function maFaces(block) {
  const faces = [];
  for (const m of block.matchAll(/setAttr "\.fc\[\d+(?::\d+)?\]"(?:\s+-type "polyFaces")?\s+([^;]*);/g)) {
    const toks = m[1].trim().split(/\s+/);
    let i = 0;
    while (i < toks.length) {
      const t = toks[i];
      if (t === "f") { const n = +toks[i + 1]; faces.push(toks.slice(i + 2, i + 2 + n).map(Number)); i += 2 + n; }
      else if (t === "h") i += 2 + +toks[i + 1];
      else if (t === "mu" || t === "mc") i += 3 + +toks[i + 2];
      else if (t === "fc") i += 2 + +toks[i + 1];
      else i += 1;
    }
  }
  return faces;
}

// ---------------------------------------------------------------- FBX（二進位 7.x）
function fbxNode(dv, u8, pos, wide) {
  let end, nprops;
  if (wide) { end = Number(dv.getBigUint64(pos, true)); nprops = Number(dv.getBigUint64(pos + 8, true)); pos += 24; }
  else { end = dv.getUint32(pos, true); nprops = dv.getUint32(pos + 4, true); pos += 12; }
  const nlen = u8[pos]; pos += 1;
  if (end === 0) return [null, pos + nlen];
  const name = new TextDecoder("ascii").decode(u8.subarray(pos, pos + nlen)); pos += nlen;
  const props = [];
  for (let k = 0; k < nprops; k++) {
    const t = String.fromCharCode(u8[pos]); pos += 1;
    if (t === "Y") { props.push(dv.getInt16(pos, true)); pos += 2; }
    else if (t === "C") { props.push(!!u8[pos]); pos += 1; }
    else if (t === "I") { props.push(dv.getInt32(pos, true)); pos += 4; }
    else if (t === "F") { props.push(dv.getFloat32(pos, true)); pos += 4; }
    else if (t === "D") { props.push(dv.getFloat64(pos, true)); pos += 8; }
    else if (t === "L") { props.push(Number(dv.getBigInt64(pos, true))); pos += 8; }
    else if ("fdlib".includes(t)) {
      const n = dv.getUint32(pos, true), enc = dv.getUint32(pos + 4, true), clen = dv.getUint32(pos + 8, true); pos += 12;
      let raw = u8.slice(pos, pos + clen); pos += clen;
      if (enc === 1) raw = unzlibSync(raw);
      const b = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
      if (t === "f") props.push(new Float32Array(b, 0, n));
      else if (t === "d") props.push(new Float64Array(b, 0, n));
      else if (t === "i") props.push(new Int32Array(b, 0, n));
      else if (t === "b") props.push(new Uint8Array(b, 0, n));
      else props.push(Array.from(new BigInt64Array(b, 0, n), Number));
    } else if (t === "S" || t === "R") {
      const n = dv.getUint32(pos, true); pos += 4;
      const data = u8.subarray(pos, pos + n); pos += n;
      props.push(t === "S" ? new TextDecoder().decode(data) : data);
    } else throw new EditError("FBX 屬性型別無法辨識：" + t);
  }
  const children = [];
  while (pos < end) { const [c, p2] = fbxNode(dv, u8, pos, wide); pos = p2; if (!c) break; children.push(c); }
  return [{ name, props, children, get(n) { return this.children.find((c) => c.name === n) || null; } }, end];
}
export function loadFBX(buf) {
  const u8 = new Uint8Array(buf), dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  if (new TextDecoder("ascii").decode(u8.subarray(0, 18)) !== "Kaydara FBX Binary") throw new EditError("只支援二進位 FBX（ASCII FBX 請在 3D 軟體另存成二進位或 OBJ）");
  const version = dv.getUint32(23, true), wide = version >= 7500, top = [];
  let pos = 27;
  while (pos < u8.length - 160) { const [n, p2] = fbxNode(dv, u8, pos, wide); pos = p2; if (!n) break; top.push(n); }
  const root = { children: top, get(n) { return this.children.find((c) => c.name === n) || null; } };
  let scaleCm = 1, up = 1;
  const p70 = root.get("GlobalSettings")?.get("Properties70");
  for (const p of p70 ? p70.children : []) {
    if (p.props[0] === "UnitScaleFactor") scaleCm = Number(p.props[p.props.length - 1]);
    if (p.props[0] === "UpAxis") up = Number(p.props[p.props.length - 1]);
  }
  const mmF = scaleCm * 10, objs = root.get("Objects");
  if (!objs) throw new EditError("FBX 裡沒有物件");
  const geoms = new Map(), models = new Map(), mats = new Map();
  for (const n of objs.children) {
    const oid = n.props[0], nm = String(n.props[1] ?? "").split("\x00")[0];
    if (n.name === "Geometry" && n.props[2] === "Mesh") geoms.set(oid, [nm, n]);
    else if (n.name === "Model") {
      const tf = { t: [0, 0, 0], r: [0, 0, 0], s: [1, 1, 1], name: nm };
      for (const p of n.get("Properties70")?.children || []) {
        const k = { "Lcl Translation": "t", "Lcl Rotation": "r", "Lcl Scaling": "s" }[p.props[0]];
        if (k) tf[k] = p.props.slice(-3).map(Number);
      }
      models.set(oid, tf);
    } else if (n.name === "Material") mats.set(oid, nm);
  }
  const parent = new Map(), matOfModel = new Map();
  for (const c of root.get("Connections")?.children || []) {
    if (c.props.length >= 3 && c.props[0] === "OO") {
      const [, ch, pa] = c.props;
      if (mats.has(ch) && models.has(pa)) { if (!matOfModel.has(pa)) matOfModel.set(pa, []); matOfModel.get(pa).push(mats.get(ch)); }
      else if (!parent.has(ch)) parent.set(ch, pa);
    }
  }
  const parts = [];
  for (const [gid, [gname, g]] of geoms) {
    const vn = g.get("Vertices"), inode = g.get("PolygonVertexIndex");
    if (!vn || !inode) continue;
    const v = Float64Array.from(vn.props[0]), idx = inode.props[0];
    const polys = []; let cur = [];
    for (const i of idx) { if (i < 0) { cur.push(~i); polys.push(cur); cur = []; } else cur.push(i); }
    let pmat = null;
    const lem = g.get("LayerElementMaterial");
    if (lem && lem.get("Materials")) {
      const arr = Array.from(lem.get("Materials").props[0]), mode = lem.get("MappingInformationType")?.props[0] || "";
      pmat = mode === "ByPolygon" && arr.length === polys.length ? arr : (arr.length ? polys.map(() => arr[0]) : null);
    }
    const mid = parent.get(gid), mnames = matOfModel.get(mid) || [], tris = [], groups = [];
    polys.forEach((poly, pi) => {
      let gn = null;
      if (pmat && mnames.length) { const k = pmat[pi]; gn = k >= 0 && k < mnames.length ? mnames[k] : null; }
      for (const t of triangulate(poly)) { tris.push(t); groups.push(gn); }
    });
    let m = mid;
    while (models.has(m)) { applyTF(v, models.get(m)); m = parent.get(m); }
    for (let i = 0; i < v.length; i++) v[i] *= mmF;
    if (up === 1) yUpToZUp(v);
    parts.push({ name: models.get(mid)?.name || gname || "FBX 網格", v, tris, groups });
  }
  if (!parts.length) throw new EditError("FBX 裡沒有多邊形網格");
  return parts;
}

/** 讀檔 → {parts, palette, notes}；FBX／MA／有材質群組的 OBJ 會變成一個帶區塊的零件。其他格式回傳 null（交給 mesh.js）。 */
export function loadGrouped(name, buf) {
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "mb") throw new EditError("Maya .mb 是 Autodesk 的封閉二進位格式，沒有公開規格無法讀取。請在 Maya 用「另存新檔」存成 .ma（Maya ASCII），或「匯出」成 .fbx／.obj 再開啟");
  if (ext === "mtl") throw new EditError(".mtl 只是 OBJ 的材質（顏色）表，沒有形狀。請開啟同名的 .obj");
  let got, maya = false;
  if (ext === "fbx") got = loadFBX(buf);
  else if (ext === "ma") got = loadMA(new TextDecoder().decode(buf));
  else if (ext === "obj") {
    const text = new TextDecoder().decode(buf);
    if (!objHasGroups(text)) {
      if (/centimeter|units: cm/i.test(text.slice(0, 400))) return { cmObj: true };
      return null;
    }
    ({ parts: got, maya } = loadOBJGroups(text));
  } else return null;
  const parts = got.map(({ name: pn, v, tris, groups }) => {
    const names = [];
    for (const g of groups) if (!names.includes(g || pn)) names.push(g || pn);
    const p = { name: pn, pos: Float32Array.from(v), idx: Uint32Array.from(tris.flat()), rgb: null };
    if (names.length > 1) { p.labels = Int32Array.from(groups.map((g) => names.indexOf(g || pn))); p.labelNames = names; }
    return p;
  });
  const single = toSingle(parts), notes = [];
  if (maya) notes.push("OBJ 是 Maya 匯出（公分、Y 朝上），已換算成 mm 並轉成 Z 朝上");
  const n = single[0].labelNames.length;
  if (n > 1) notes.push(`讀到 ${n} 個材質群組，已變成區塊：${single[0].labelNames.slice(0, 8).join("、")}`);
  return { parts: single, palette: [], notes };
}

// ====================================================================== 網格工具
/** 相同位置的頂點焊在一起（才能判斷封閉、做布林運算）。 */
function weld(pos, idx) {
  const map = new Map(), out = [], remap = new Uint32Array(pos.length / 3);
  for (let i = 0; i < pos.length / 3; i++) {
    const k = Math.round(pos[i * 3] * 1e4) + "," + Math.round(pos[i * 3 + 1] * 1e4) + "," + Math.round(pos[i * 3 + 2] * 1e4);
    let j = map.get(k);
    if (j === undefined) { j = out.length / 3; map.set(k, j); out.push(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]); }
    remap[i] = j;
  }
  return { pos: Float32Array.from(out), idx: Uint32Array.from(idx, (i) => remap[i]) };
}
function faceData(pos, idx) {
  const nf = idx.length / 3, cen = new Float64Array(nf * 3), nrm = new Float64Array(nf * 3), area = new Float64Array(nf);
  for (let f = 0; f < nf; f++) {
    const a = idx[f * 3] * 3, b = idx[f * 3 + 1] * 3, c = idx[f * 3 + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const wx = pos[c] - pos[a], wy = pos[c + 1] - pos[a + 1], wz = pos[c + 2] - pos[a + 2];
    const nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx, l = Math.hypot(nx, ny, nz);
    area[f] = l / 2;
    if (l > 0) { nrm[f * 3] = nx / l; nrm[f * 3 + 1] = ny / l; nrm[f * 3 + 2] = nz / l; }
    for (let k = 0; k < 3; k++) cen[f * 3 + k] = (pos[a + k] + pos[b + k] + pos[c + k]) / 3;
  }
  return { nf, cen, nrm, area };
}
function bbox(pos) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pos.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], pos[i + k]); hi[k] = Math.max(hi[k], pos[i + k]); }
  return [lo, hi];
}
/** 相鄰面（共用一條邊的兩個面）：[[f1, f2, 邊長], …] */
function adjacency(pos, idx) {
  const edges = new Map(), adj = [];
  const nv = pos.length / 3;
  for (let f = 0; f < idx.length / 3; f++) for (let k = 0; k < 3; k++) {
    const a = idx[f * 3 + k], b = idx[f * 3 + (k + 1) % 3], key = a < b ? a * nv + b : b * nv + a;
    const e = edges.get(key);
    if (e === undefined) edges.set(key, f);
    else if (e >= 0) {
      adj.push([e, f, Math.hypot(pos[a * 3] - pos[b * 3], pos[a * 3 + 1] - pos[b * 3 + 1], pos[a * 3 + 2] - pos[b * 3 + 2])]);
      edges.set(key, -1);
    }
  }
  return adj;
}
function components(n, pairs) {
  const p = Int32Array.from({ length: n }, (_, i) => i);
  const find = (x) => { while (p[x] !== x) { p[x] = p[p[x]]; x = p[x]; } return x; };
  for (const [a, b] of pairs) { const ra = find(a), rb = find(b); if (ra !== rb) p[ra] = rb; }
  const lab = new Int32Array(n), ids = new Map();
  for (let i = 0; i < n; i++) { const r = find(i); if (!ids.has(r)) ids.set(r, ids.size); lab[i] = ids.get(r); }
  return lab;
}
/** 依面積由大到小重新編號 */
function rankByArea(lab, area) {
  const n = Math.max(...lab) + 1, a = new Float64Array(n);
  for (let f = 0; f < lab.length; f++) a[lab[f]] += area[f];
  const used = [...Array(n).keys()].filter((i) => a[i] > 0 || lab.includes(i)).sort((x, y) => a[y] - a[x]);
  const remap = new Int32Array(n).fill(-1); used.forEach((o, i) => { remap[o] = i; });
  return Int32Array.from(lab, (x) => remap[x]);
}
/** 最近點查詢（均勻格子）：給布林運算、切開後把新的面對應回原本的區塊。 */
class Nearest {
  constructor(cen, n) {
    const [lo, hi] = bbox(cen);
    this.lo = lo; this.cen = cen;
    const diag = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1;
    this.s = Math.max(diag / Math.cbrt(Math.max(n, 1)) * 1.5, 1e-6);
    this.g = new Map();
    for (let i = 0; i < n; i++) { const k = this.key(cen[i * 3], cen[i * 3 + 1], cen[i * 3 + 2]); if (!this.g.has(k)) this.g.set(k, []); this.g.get(k).push(i); }
  }
  cell(x, k) { return Math.floor((x - this.lo[k]) / this.s); }
  key(x, y, z) { return this.cell(x, 0) + "," + this.cell(y, 1) + "," + this.cell(z, 2); }
  query(x, y, z) {
    const cx = this.cell(x, 0), cy = this.cell(y, 1), cz = this.cell(z, 2);
    let best = -1, bd = Infinity;
    for (let r = 0; r < 64; r++) {
      for (let i = -r; i <= r; i++) for (let j = -r; j <= r; j++) for (let k = -r; k <= r; k++) {
        if (Math.max(Math.abs(i), Math.abs(j), Math.abs(k)) !== r) continue;
        const L = this.g.get((cx + i) + "," + (cy + j) + "," + (cz + k)); if (!L) continue;
        for (const f of L) { const d = (this.cen[f * 3] - x) ** 2 + (this.cen[f * 3 + 1] - y) ** 2 + (this.cen[f * 3 + 2] - z) ** 2; if (d < bd) { bd = d; best = f; } }
      }
      if (best >= 0 && Math.sqrt(bd) <= r * this.s) break;
    }
    return [best, Math.sqrt(bd)];
  }
}

// ====================================================================== 區塊模型
export const hasRegions = (parts) => !!(parts && parts.length === 1 && parts[0].labels);

function paint(p) {
  const cols = p.labelNames.map((n, i) => hexrgb(p.colors[n] || PALETTE[i % PALETTE.length]));
  const rgb = new Uint8Array(p.labels.length * 3);
  for (let f = 0; f < p.labels.length; f++) rgb.set(cols[p.labels[f]], f * 3);
  p.rgb = rgb;
  return p;
}
/** 重新編號（去掉沒有面的區塊、退化三角形）→ [單一零件] */
function make(pos, idx, labels, names, colors = {}) {
  const keepF = [];
  for (let f = 0; f < idx.length / 3; f++) { const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; if (a !== b && b !== c && a !== c) keepF.push(f); }
  const used = [...new Set(keepF.map((f) => labels[f]))].sort((a, b) => a - b), remap = new Map(used.map((o, n) => [o, n]));
  const idx2 = new Uint32Array(keepF.length * 3), lab = new Int32Array(keepF.length);
  keepF.forEach((f, i) => { idx2.set([idx[f * 3], idx[f * 3 + 1], idx[f * 3 + 2]], i * 3); lab[i] = remap.get(labels[f]); });
  const nm = used.map((i) => names[i]);
  const cols = Object.fromEntries(Object.entries(colors).filter(([k]) => nm.includes(k)));
  return [paint({ name: "模型", pos, idx: idx2, rgb: null, labels: lab, labelNames: nm, colors: cols })];
}
/** 所有零件合併成一個網格（焊接頂點），每個面帶區塊編號。 */
export function toSingle(parts) {
  if (hasRegions(parts)) { if (!parts[0].colors) parts[0].colors = {}; if (!parts[0].rgb || parts[0].rgb.length !== parts[0].labels.length * 3) paint(parts[0]); return parts; }
  const pos = [], idx = [], labels = [], names = [];
  let off = 0;
  for (const p of parts) {
    for (const x of p.pos) pos.push(x);
    for (const i of p.idx) idx.push(i + off);
    off += p.pos.length / 3;
    if (p.labels) { const base = names.length; names.push(...p.labelNames); for (const l of p.labels) labels.push(l + base); }
    else { for (let f = 0; f < p.idx.length / 3; f++) labels.push(names.length); names.push(p.name); }
  }
  const w = weld(Float32Array.from(pos), idx);
  return make(w.pos, w.idx, labels, names, {});
}

/** 拆開檢視（只給畫面用）：每個區塊沿「整體中心 → 區塊中心」的方向往外推。k＝0 組裝、1 完全拆開。 */
export function explodeView(parts, k = 1, rgb = null) {
  const p = parts[0], { nf, cen, area } = faceData(p.pos, p.idx), lab = p.labels;
  let A = 0; const whole = [0, 0, 0];
  for (let f = 0; f < nf; f++) { A += area[f] + 1e-12; for (let j = 0; j < 3; j++) whole[j] += cen[f * 3 + j] * (area[f] + 1e-12); }
  whole.forEach((_, j) => { whole[j] /= A; });
  const [lo, hi] = bbox(p.pos), diag = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
  const n = p.labelNames.length, rc = Array.from({ length: n }, () => [0, 0, 0, 0]);
  for (let f = 0; f < nf; f++) { const r = rc[lab[f]], a = area[f] + 1e-12; r[0] += cen[f * 3] * a; r[1] += cen[f * 3 + 1] * a; r[2] += cen[f * 3 + 2] * a; r[3] += a; }
  const shift = rc.map((r) => {
    if (!r[3]) return [0, 0, 0];
    const d = [r[0] / r[3] - whole[0], r[1] / r[3] - whole[1], r[2] / r[3] - whole[2]], len = Math.hypot(...d);
    if (len < diag * 0.02) return [0, 0, 0];
    return d.map((x) => (x * 0.8 + x / len * diag * 0.15) * k);
  });
  const pos = new Float32Array(nf * 9);
  for (let f = 0; f < nf; f++) { const s = shift[lab[f]]; for (let c = 0; c < 3; c++) { const v = p.idx[f * 3 + c] * 3; for (let j = 0; j < 3; j++) pos[f * 9 + c * 3 + j] = p.pos[v + j] + s[j]; } }
  return [{ name: p.name, pos, idx: Uint32Array.from({ length: nf * 3 }, (_, i) => i), rgb: rgb || p.rgb }];
}

/** 勾選的區塊保留顏色，其他變淡灰（只給畫面用）。 */
export function dimmed(parts, sel) {
  const p = parts[0], rgb = new Uint8Array(p.rgb), s = new Set(sel.map((i) => i - 1));
  if (!sel.length) return rgb;
  for (let f = 0; f < p.labels.length; f++) if (!s.has(p.labels[f])) for (let j = 0; j < 3; j++) rgb[f * 3 + j] = Math.round(rgb[f * 3 + j] * 0.25 + 190 * 0.75);
  return rgb;
}

// ====================================================================== 分區
export function segment(parts, method = "auto", target = 8, angle = 30, layers = 4) {
  const single = toSingle(parts)[0];
  const { pos, idx, labels: lab, labelNames: names } = single, fd = faceData(pos, idx);
  const auto = method === "auto";
  let adj = null;
  const getAdj = () => adj || (adj = adjacency(pos, idx));
  if (auto) method = names.length > 1 ? "groups" : (Math.max(...components(fd.nf, getAdj())) > 0 ? "bodies" : "surface");
  let newLab, newNames = null;
  if (method === "groups") {
    if (names.length <= 1) throw new EditError("這個檔案沒有材質或群組資料，請改用「表面轉折」或「分層」");
    newLab = lab; newNames = names;
  } else if (method === "bodies") {
    newLab = rankByArea(components(fd.nf, getAdj()), fd.area);
    newNames = Array.from({ length: Math.max(...newLab) + 1 }, (_, i) => `實體 ${i + 1}`);
  } else if (method === "surface") newLab = surfaceRegions(fd, getAdj(), target, angle);
  else if (method === "zones") newLab = zones(pos, fd, getAdj(), target);
  else if (method === "height") {
    const [lo, hi] = bbox(pos), n = Math.max(2, Math.min(Math.round(layers), 12)), step = (hi[2] - lo[2]) / n;
    newLab = Int32Array.from({ length: fd.nf }, (_, f) => Math.min(Math.floor((fd.cen[f * 3 + 2] - lo[2]) / Math.max(hi[2] - lo[2], 1e-6) * n), n - 1));
    newNames = Array.from({ length: n }, (_, i) => `第 ${i + 1} 層（${(lo[2] + i * step).toFixed(0)}～${(lo[2] + (i + 1) * step).toFixed(0)} mm）`);
  } else throw new EditError("沒有這種分區方法：" + method);
  if (auto && method === "surface") {
    const a = new Float64Array(Math.max(...newLab) + 1); let tot = 0;
    for (let f = 0; f < fd.nf; f++) { a[newLab[f]] += fd.area[f]; tot += fd.area[f]; }
    if (a.length < 3 || Math.max(...a) > 0.8 * tot) newLab = zones(pos, fd, getAdj(), target);
  }
  if (!newNames) newNames = describe(pos, fd, newLab);
  return make(pos, idx, newLab, newNames, {});
}

function surfaceRegions(fd, adj, target, angle) {
  const cosA = Math.cos(angle * Math.PI / 180), keep = [];
  for (const [a, b] of adj) {
    const d = fd.nrm[a * 3] * fd.nrm[b * 3] + fd.nrm[a * 3 + 1] * fd.nrm[b * 3 + 1] + fd.nrm[a * 3 + 2] * fd.nrm[b * 3 + 2];
    if (d > cosA) keep.push([a, b]);
  }
  const lab = components(fd.nf, keep), area = fd.area;
  let total = 0; for (const a of area) total += a; total = total || 1;
  target = Math.max(2, Math.round(target));
  for (let it = 0; it < 200; it++) {
    const n = Math.max(...lab) + 1, rarea = new Float64Array(n);
    for (let f = 0; f < fd.nf; f++) rarea[lab[f]] += area[f];
    const alive = [...Array(n).keys()].filter((i) => rarea[i] > 0);
    let small = alive[0]; for (const i of alive) if (rarea[i] < rarea[small]) small = i;
    if (alive.length <= target && rarea[small] >= total * 0.01) break;
    const shared = new Float64Array(n); let any = false;
    for (const [a, b, len] of adj) {
      const la = lab[a], lb = lab[b];
      if ((la === small) !== (lb === small)) { shared[la === small ? lb : la] += len; any = true; }
    }
    let to;
    if (!any) { to = alive[0]; for (const i of alive) if (rarea[i] > rarea[to]) to = i; }
    else { to = 0; for (let i = 0; i < n; i++) if (shared[i] > shared[to]) to = i; }
    for (let f = 0; f < fd.nf; f++) if (lab[f] === small) lab[f] = to;
  }
  return rankByArea(lab, area);
}

function zones(pos, fd, adj, target) {
  const k = Math.max(2, Math.min(Math.round(target), 16)), [lo, hi] = bbox(pos);
  const sz = Math.max(...hi.map((h, j) => Math.max(h - lo[j], 1e-6)));
  const feat = new Float64Array(fd.nf * 6);
  for (let f = 0; f < fd.nf; f++) for (let j = 0; j < 3; j++) { feat[f * 6 + j] = (fd.cen[f * 3 + j] - lo[j]) / sz; feat[f * 6 + 3 + j] = fd.nrm[f * 3 + j] * 0.15; }
  let seed = 7; const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  // 依面積抽樣
  let tot = 0; const cum = new Float64Array(fd.nf); for (let f = 0; f < fd.nf; f++) { tot += fd.area[f]; cum[f] = tot; }
  const pickOne = () => { const r = rnd() * tot; let a = 0, b = fd.nf - 1; while (a < b) { const m = (a + b) >> 1; if (cum[m] < r) a = m + 1; else b = m; } return a; };
  const sample = Array.from({ length: Math.min(fd.nf, 4000) }, pickOne);
  const dist = (f, c) => { let s = 0; for (let j = 0; j < 6; j++) s += (feat[f * 6 + j] - c[j]) ** 2; return s; };
  const cents = [Array.from(feat.subarray(sample[0] * 6, sample[0] * 6 + 6))];
  while (cents.length < k) {             // k-means++
    const d = sample.map((f) => Math.min(...cents.map((c) => dist(f, c)))), s = d.reduce((a, b) => a + b, 0);
    let r = rnd() * s, i = 0; while (i < d.length - 1 && r > d[i]) { r -= d[i]; i++; }
    cents.push(Array.from(feat.subarray(sample[i] * 6, sample[i] * 6 + 6)));
  }
  for (let it = 0; it < 12; it++) {
    const acc = cents.map(() => new Float64Array(7));
    for (const f of sample) { let b = 0, bd = Infinity; cents.forEach((c, ci) => { const d = dist(f, c); if (d < bd) { bd = d; b = ci; } }); for (let j = 0; j < 6; j++) acc[b][j] += feat[f * 6 + j]; acc[b][6]++; }
    acc.forEach((a, ci) => { if (a[6]) for (let j = 0; j < 6; j++) cents[ci][j] = a[j] / a[6]; });
  }
  const lab = new Int32Array(fd.nf);
  for (let f = 0; f < fd.nf; f++) { let b = 0, bd = Infinity; cents.forEach((c, ci) => { const d = dist(f, c); if (d < bd) { bd = d; b = ci; } }); lab[f] = b; }
  // 每塊只留最大的連通片，其他碎片併到相鄰最多的區塊
  const nb = Array.from({ length: fd.nf }, () => []);
  for (const [a, b] of adj) { nb[a].push(b); nb[b].push(a); }
  for (let round = 0; round < 3; round++) {
    const comp = components(fd.nf, adj.filter(([a, b]) => lab[a] === lab[b]));
    const carea = new Float64Array(Math.max(...comp) + 1); for (let f = 0; f < fd.nf; f++) carea[comp[f]] += fd.area[f];
    const best = new Map();
    for (let f = 0; f < fd.nf; f++) { const L = lab[f], c = comp[f]; if (!best.has(L) || carea[c] > carea[best.get(L)]) best.set(L, c); }
    const keepC = new Set(best.values()), stray = Uint8Array.from(comp, (c) => keepC.has(c) ? 0 : 1);
    if (!stray.some((x) => x)) break;
    for (let f = 0; f < fd.nf; f++) {
      if (!stray[f]) continue;
      let ns = nb[f].filter((g) => !stray[g]); if (!ns.length) ns = nb[f];
      if (ns.length) { const cnt = new Map(); let bl = lab[ns[0]], bc = 0; for (const g of ns) { const c = (cnt.get(lab[g]) || 0) + 1; cnt.set(lab[g], c); if (c > bc || (c === bc && lab[g] < bl)) { bc = c; bl = lab[g]; } } lab[f] = bl; }
    }
  }
  return rankByArea(lab, fd.area);
}

function describe(pos, fd, lab) {
  const [lo, hi] = bbox(pos), c0 = lo.map((x, j) => (x + hi[j]) / 2), size = lo.map((x, j) => Math.max(hi[j] - x, 1e-6));
  const n = Math.max(...lab) + 1, names = [];
  for (let i = 0; i < n; i++) {
    let a = 0; const c = [0, 0, 0], nr = [0, 0, 0];
    for (let f = 0; f < fd.nf; f++) if (lab[f] === i) { const w = fd.area[f]; a += w; for (let j = 0; j < 3; j++) { c[j] += fd.cen[f * 3 + j] * w; nr[j] += fd.nrm[f * 3 + j] * w; } }
    if (!a) { names.push(`區塊 ${i + 1}`); continue; }
    const rel = c.map((x, j) => (x / a - c0[j]) / size[j]), where = [];
    if (rel[2] > 0.25) where.push("上"); else if (rel[2] < -0.25) where.push("下");
    if (rel[1] < -0.25) where.push("前"); else if (rel[1] > 0.25) where.push("後");
    if (rel[0] < -0.25) where.push("左"); else if (rel[0] > 0.25) where.push("右");
    const nl = Math.hypot(...nr);
    let face = "";
    if (nl > a * 0.6) {
      const d = nr.map((x) => x / nl), k = [0, 1, 2].reduce((m, j) => Math.abs(d[j]) > Math.abs(d[m]) ? j : m, 0);
      face = { "0,1": "右側面", "0,-1": "左側面", "1,1": "背面", "1,-1": "正面", "2,1": "頂面", "2,-1": "底面" }[k + "," + (d[k] > 0 ? 1 : -1)];
    }
    names.push(`區塊 ${i + 1} ${where.join("") || "中"}${face}`);
  }
  return names;
}

const r1 = (x) => Math.round(x * 10) / 10;
/** 每個區塊的資訊（給畫面與 AI 代理人）。 */
export function regions(parts) {
  if (!hasRegions(parts)) return [];
  const p = parts[0], n = p.labelNames.length;
  const st = Array.from({ length: n }, () => ({ faces: 0, area: 0, lo: [Infinity, Infinity, Infinity], hi: [-Infinity, -Infinity, -Infinity] }));
  const { area } = faceData(p.pos, p.idx);
  for (let f = 0; f < p.labels.length; f++) {
    const s = st[p.labels[f]]; s.faces++; s.area += area[f];
    for (let c = 0; c < 3; c++) { const v = p.idx[f * 3 + c] * 3; for (let j = 0; j < 3; j++) { s.lo[j] = Math.min(s.lo[j], p.pos[v + j]); s.hi[j] = Math.max(s.hi[j], p.pos[v + j]); } }
  }
  return p.labelNames.map((name, i) => ({ id: i + 1, name, faces: st[i].faces, area_cm2: Math.round(st[i].area) / 100,
    size_mm: st[i].hi.map((h, j) => r1(h - st[i].lo[j])), center_mm: st[i].hi.map((h, j) => r1((h + st[i].lo[j]) / 2)),
    color: p.colors[name] || PALETTE[i % PALETTE.length], filament: name in p.colors }));
}

// ====================================================================== 區塊修改
function ids(parts, sel) {
  const p = parts[0];
  if (sel == null) sel = [];
  if (!Array.isArray(sel)) sel = [sel];
  const out = [];
  for (const x of sel) {
    if (typeof x === "string" && !/^\s*\d+\s*$/.test(x)) {
      const t = x.trim(), exact = p.labelNames.map((n, i) => n === t ? i : -1).filter((i) => i >= 0);
      const hit = exact.length ? exact : p.labelNames.map((n, i) => n.includes(t) ? i : -1).filter((i) => i >= 0);
      if (!hit.length) throw new EditError(`找不到區塊「${x}」`);
      out.push(...hit);
    } else {
      const k = parseInt(x) - 1;
      if (!(k >= 0 && k < p.labelNames.length)) throw new EditError(`沒有第 ${x} 區（目前有 ${p.labelNames.length} 區）`);
      out.push(k);
    }
  }
  if (!out.length) throw new EditError("請指定要修改的區塊");
  return [...new Set(out)].sort((a, b) => a - b);
}
const need = (parts) => { if (!hasRegions(parts)) throw new EditError("請先分區"); return parts[0]; };
const g = (x) => +(+x).toPrecision(6);

/** 回傳 [新零件陣列, 說明文字]。op：delete keep move scale rotate color uncolor rename merge cut hole boss */
export function edit(parts, op, sel = null, kw = {}) {
  const p = need(parts), names = [...p.labelNames], colors = { ...p.colors }, lab = p.labels;
  if (op === "cut") return cut(parts, kw);
  if (op === "hole") return hole(parts, sel, kw);
  if (op === "boss") return boss(parts, sel, kw);
  const s = ids(parts, sel), which = s.map((i) => i + 1).join("、"), inSel = new Set(s);
  if (op === "delete" || op === "keep") {
    const keepF = []; for (let f = 0; f < lab.length; f++) if (inSel.has(lab[f]) === (op === "keep")) keepF.push(f);
    if (!keepF.length) throw new EditError("不能把全部區塊都刪掉");
    const vmap = new Map(), pos = [], idx = [];
    for (const f of keepF) for (let c = 0; c < 3; c++) {
      const v = p.idx[f * 3 + c]; let j = vmap.get(v);
      if (j === undefined) { j = pos.length / 3; vmap.set(v, j); pos.push(p.pos[v * 3], p.pos[v * 3 + 1], p.pos[v * 3 + 2]); }
      idx.push(j);
    }
    return [make(Float32Array.from(pos), Uint32Array.from(idx), Int32Array.from(keepF, (f) => lab[f]), names, colors),
      (op === "delete" ? "已刪除第 %s 區" : "只保留第 %s 區").replace("%s", which)];
  }
  if (op === "move" || op === "scale" || op === "rotate") {
    const pos = new Float32Array(p.pos), vid = new Set();
    for (let f = 0; f < lab.length; f++) if (inSel.has(lab[f])) for (let c = 0; c < 3; c++) vid.add(p.idx[f * 3 + c]);
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const v of vid) for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], pos[v * 3 + j]); hi[j] = Math.max(hi[j], pos[v * 3 + j]); }
    const c = lo.map((x, j) => (x + hi[j]) / 2);
    let msg;
    if (op === "move") {
      const d = [+(kw.dx || 0), +(kw.dy || 0), +(kw.dz || 0)];
      for (const v of vid) for (let j = 0; j < 3; j++) pos[v * 3 + j] += d[j];
      msg = `第 ${which} 區移動 (${d.map(g).join(", ")}) mm`;
    } else if (op === "scale") {
      const f = kw.factor, sc = [+(kw.sx || f || 1), +(kw.sy || f || 1), +(kw.sz || f || 1)];
      if (sc.some((x) => x <= 0 || x > 20)) throw new EditError("縮放倍數要在 0～20 之間");
      for (const v of vid) for (let j = 0; j < 3; j++) pos[v * 3 + j] = (pos[v * 3 + j] - c[j]) * sc[j] + c[j];
      msg = `第 ${which} 區縮放 ×${new Set(sc).size > 1 ? sc.map(g).join("×") : g(sc[0])}`;
    } else {
      const ax = { x: 0, y: 1, z: 2 }[String(kw.axis || "z").toLowerCase()], deg = kw.degrees ?? 90, a = deg * Math.PI / 180;
      const [i, j] = [[1, 2], [2, 0], [0, 1]][ax], co = Math.cos(a), si = Math.sin(a);
      for (const v of vid) { const x = pos[v * 3 + i] - c[i], y = pos[v * 3 + j] - c[j]; pos[v * 3 + i] = co * x - si * y + c[i]; pos[v * 3 + j] = si * x + co * y + c[j]; }
      msg = `第 ${which} 區繞 ${"XYZ"[ax]} 軸旋轉 ${g(deg)}°`;
    }
    if (s.length < names.length) msg += "（和相鄰區塊共用的邊會跟著拉動）";
    return [make(pos, new Uint32Array(p.idx), lab, names, colors), msg];
  }
  if (op === "color" || op === "uncolor") {
    for (const i of s) {
      if (op === "color") { const h = String(kw.color || ""); hexrgb(h); colors[names[i]] = (COLOR_NAMES[h] || (h.startsWith("#") ? h : "#" + h)).toUpperCase(); }
      else delete colors[names[i]];
    }
    return [make(p.pos, p.idx, lab, names, colors), op === "color" ? `第 ${which} 區改成 ${kw.color}（會變成 Bambu 多色 3MF 的耗材）` : `第 ${which} 區取消指定顏色`];
  }
  if (op === "rename") {
    const nm = String(kw.name || "").trim().slice(0, 30);
    if (!nm || s.length !== 1) throw new EditError("改名一次指定一個區塊與新名稱");
    const old = names[s[0]]; names[s[0]] = nm;
    if (old in colors) { colors[nm] = colors[old]; delete colors[old]; }
    return [make(p.pos, p.idx, lab, names, colors), `第 ${which} 區改名為「${nm}」`];
  }
  if (op === "merge") {
    if (s.length < 2) throw new EditError("合併要指定兩個以上的區塊");
    return [make(p.pos, p.idx, Int32Array.from(lab, (l) => inSel.has(l) ? s[0] : l), names, colors), `已把第 ${which} 區合併成一區`];
  }
  throw new EditError("沒有這種修改：" + op);
}

function relabel(old, pos, idx) {
  const fo = faceData(old.pos, old.idx), fn = faceData(pos, idx), nn = new Nearest(fo.cen, fo.nf);
  const lab = new Int32Array(fn.nf), dist = new Float64Array(fn.nf);
  for (let f = 0; f < fn.nf; f++) { const [i, d] = nn.query(fn.cen[f * 3], fn.cen[f * 3 + 1], fn.cen[f * 3 + 2]); lab[f] = old.labels[Math.max(i, 0)]; dist[f] = d; }
  return { lab, dist };
}
function toManifold(p) {
  const { Manifold, Mesh } = manifoldKit();
  try {
    const m = new Manifold(new Mesh({ numProp: 3, vertProperties: new Float32Array(p.pos), triVerts: new Uint32Array(p.idx) }));
    if (m.status && m.status() !== "NoError" && m.status() !== 0) { m.delete(); return null; }
    if (m.isEmpty()) { m.delete(); return null; }
    return m;
  } catch (e) { return null; }
}
function fromManifold(m) {
  const mesh = m.getMesh(), np = mesh.numProp, vp = mesh.vertProperties, n = vp.length / np, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { pos[i * 3] = vp[i * np]; pos[i * 3 + 1] = vp[i * np + 1]; pos[i * 3 + 2] = vp[i * np + 2]; }
  return { pos, idx: new Uint32Array(mesh.triVerts) };
}
function translate(pos, d) { for (let i = 0; i < pos.length; i += 3) for (let j = 0; j < 3; j++) pos[i + j] += d[j]; return pos; }

/** 沒有封閉的網格：直接把三角形切開（切面不補蓋子）。 */
function clipOpen(p, ax, val, sign) {
  const pos = [], idx = [], src = [];
  const P = (v) => [p.pos[v * 3], p.pos[v * 3 + 1], p.pos[v * 3 + 2]];
  const add = (pts, f) => { const b = pos.length / 3; for (const q of pts) pos.push(...q); for (const t of triangulate(pts.map((_, i) => b + i))) { idx.push(...t); src.push(f); } };
  for (let f = 0; f < p.idx.length / 3; f++) {
    const vs = [0, 1, 2].map((c) => P(p.idx[f * 3 + c])), out = [];
    for (let i = 0; i < 3; i++) {
      const a = vs[i], b = vs[(i + 1) % 3], da = (a[ax] - val) * sign, db = (b[ax] - val) * sign;
      if (da >= 0) out.push(a);
      if ((da >= 0) !== (db >= 0)) { const t = da / (da - db); out.push(a.map((x, j) => x + (b[j] - x) * t)); }
    }
    if (out.length >= 3) add(out, f);
  }
  return { pos: Float32Array.from(pos), idx: Uint32Array.from(idx), lab: Int32Array.from(src, (f) => p.labels[f]) };
}

function cut(parts, { axis = "z", value = null, keep = "both", gap = 10 } = {}) {
  const p = toSingle(parts)[0], ax = { x: 0, y: 1, z: 2 }[String(axis).toLowerCase()];
  const [lo, hi] = bbox(p.pos), val = value != null && value !== "" ? +value : (lo[ax] + hi[ax]) / 2;
  if (!(lo[ax] < val && val < hi[ax])) throw new EditError(`切面 ${"XYZ"[ax]}=${g(val)} 不在模型範圍內（${lo[ax].toFixed(1)}～${hi[ax].toFixed(1)} mm）`);
  const man = toManifold(p), pieces = [];
  for (const [side, sign] of [["below", -1], ["above", 1]]) {
    if (keep !== "both" && keep !== side) continue;
    let piece;
    if (man) {
      const n = [0, 0, 0]; n[ax] = sign;
      const t = man.trimByPlane(n, sign * val);
      if (t.isEmpty()) { t.delete(); continue; }
      const m = fromManifold(t); t.delete();
      piece = { ...m, lab: relabel(p, m.pos, m.idx).lab };
    } else piece = clipOpen(p, ax, val, sign);
    if (piece.idx.length) pieces.push(piece);
  }
  if (man) man.delete();
  if (!pieces.length) throw new EditError("切開後沒有留下任何東西");
  let pos, idx, lab, msg;
  if (keep === "both" && pieces.length === 2) {
    const [a, b] = pieces, bp = new Float32Array(b.pos);
    if (ax === 2) for (let i = 0; i < bp.length; i += 3) { bp[i + 1] = -bp[i + 1]; bp[i + 2] = -bp[i + 2]; }   // 繞 X 轉 180°
    const ap = new Float32Array(a.pos), [alo, ahi] = bbox(ap); translate(ap, [0, 0, -alo[2]]);
    let [blo] = bbox(bp); translate(bp, [0, 0, -blo[2]]); [blo] = bbox(bp);
    translate(bp, [ahi[0] - blo[0] + gap, 0, 0]);
    pos = new Float32Array(ap.length + bp.length); pos.set(ap); pos.set(bp, ap.length);
    idx = new Uint32Array(a.idx.length + b.idx.length); idx.set(a.idx); idx.set(Uint32Array.from(b.idx, (i) => i + ap.length / 3), a.idx.length);
    lab = new Int32Array(a.lab.length + b.lab.length); lab.set(a.lab); lab.set(b.lab, a.lab.length);
    msg = `沿 ${"XYZ"[ax]}=${g(val)} mm 切成兩半（上半部翻面放在旁邊，兩塊都可以直接列印）`;
  } else {
    ({ pos, idx, lab } = pieces[0]);
    msg = `沿 ${"XYZ"[ax]}=${g(val)} mm 切開，只保留${keep === "below" ? "下" : "上"}半部`;
  }
  const [l2] = bbox(pos); translate(pos, [0, 0, -l2[2]]);
  if (!man) msg += "（模型不是封閉實體，切面沒有補蓋子）";
  return [make(pos, idx, lab, p.labelNames, p.colors), msg];
}

function prim(shape, size, depth, at, axis) {
  const { Manifold } = manifoldKit(), ax = { x: 0, y: 1, z: 2 }[String(axis || "z").toLowerCase()];
  let m;
  if (shape === "box") { const [w, d] = Array.isArray(size) ? size : [size, size]; m = Manifold.cube([+w, +d, +depth], true); }
  else m = Manifold.cylinder(+depth, size / 2, size / 2, 64, true);
  const r = ax === 0 ? m.rotate([0, 90, 0]) : ax === 1 ? m.rotate([90, 0, 0]) : m;
  const out = r.translate(at.map(Number));
  if (r !== m) r.delete();
  m.delete();
  return out;
}
function boolOp(parts, pr, subtract, msg) {
  const p = parts[0], man = toManifold(p);
  if (!man) { pr.delete(); throw new EditError("鑽孔、加凸台需要封閉的實體：請先在「檢查與修復」修復網格，或改用電腦版"); }
  const out = subtract ? man.subtract(pr) : man.add(pr);
  const m = fromManifold(out);
  out.delete(); man.delete(); pr.delete();
  if (!m.idx.length) throw new EditError("運算後沒有留下任何東西");
  const { lab, dist } = relabel(p, m.pos, m.idx), names = [...p.labelNames];
  if (!subtract && dist.some((d) => d > 0.5)) {
    names.push(`新增凸台 ${names.filter((n) => n.startsWith("新增凸台")).length + 1}`);
    for (let f = 0; f < lab.length; f++) if (dist[f] > 0.5) lab[f] = names.length - 1;
  }
  return [make(m.pos, m.idx, lab, names, p.colors), msg];
}
function at(parts, sel, a) {
  if (a != null) { if (a.length !== 3) throw new EditError("位置要給 x, y, z 三個數字（mm）"); return a.map(Number); }
  if (sel != null && (!Array.isArray(sel) || sel.length)) return regions(parts)[ids(parts, sel)[0]].center_mm;
  throw new EditError("請指定位置（x, y, z）或區塊");
}
const fmtAt = (a) => a.map((x) => x.toFixed(1)).join(", ");
function hole(parts, sel, { at: a = null, diameter = 5, depth = null, axis = "z", shape = "circle", width = null, height = null } = {}) {
  const p = need(parts), pt = at(parts, sel, a), [lo, hi] = bbox(p.pos), span = Math.hypot(...hi.map((h, j) => h - lo[j])) * 2;
  const size = shape === "box" ? [width || diameter, height || diameter] : diameter;
  const what = shape === "box" ? `${g(size[0])}×${g(size[1])} mm 方孔` : `直徑 ${g(diameter)} mm 圓孔`;
  return boolOp(parts, prim(shape, size, depth || span, pt, axis), true, `在 (${fmtAt(pt)}) 鑽 ${what}${depth ? `，深 ${g(depth)} mm` : "（貫穿）"}`);
}
function boss(parts, sel, { at: a = null, diameter = 8, height = 5, axis = "z", shape = "circle", width = null } = {}) {
  need(parts);
  const pt = at(parts, sel, a), size = shape === "box" ? [width || diameter, width || diameter] : diameter;
  return boolOp(parts, prim(shape, size, height, pt, axis), false, `在 (${fmtAt(pt)}) 加${shape === "box" ? "方塊" : "圓柱"}凸台，高 ${g(height)} mm`);
}

// ====================================================================== Bambu 多色 3MF（移植 bambu_studio_ai/color/bambu_3mf.py）
const NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"';
const OBJ_PATH = "3D/Objects/object_1.model", REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel";
const xesc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
export const paintCode = (f) => ({ 1: "4", 2: "8" })[f] || (f - 3).toString(16).toUpperCase() + "C";
let TEMPLATE = null;
async function template() {
  if (!TEMPLATE) {
    const base = new URL("./bambu/", import.meta.url);
    const [s, k] = await Promise.all([fetch(new URL("project_settings.config", base)).then((r) => r.json()), fetch(new URL("per_filament_keys.json", base)).then((r) => r.json())]);
    TEMPLATE = { settings: s, perFilament: k };
  }
  return TEMPLATE;
}
export function setTemplate(t) { TEMPLATE = t; }
const rels = (target) => `<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n <Relationship Target="${target}" Id="rel-1" Type="${REL}"/>\n</Relationships>\n`;

/** 有指定耗材顏色的區塊 → Bambu Studio 多色專案 3MF（每個三角面塗上耗材，AMS 直接用）。回傳 [bytes, 顏色清單] */
export async function writePainted3MF(parts, name = "模型") {
  const p = need(parts), cols = [], filOf = [];
  for (const n of p.labelNames) {
    let c = p.colors[n] ?? (Object.keys(p.colors).length ? "#FFFFFF" : PALETTE[0]);
    c = c.toUpperCase(); if (!cols.includes(c)) cols.push(c);
    filOf.push(cols.indexOf(c));
  }
  const colours = cols.slice(0, 16), count = colours.length, T = await template();
  const s = JSON.parse(JSON.stringify(T.settings));
  for (const k of T.perFilament) s[k] = Array(count).fill(s[k][0]);
  const flush = []; for (let r = 0; r < count; r++) for (let c = 0; c < count; c++) flush.push(r === c ? "0" : "280");
  Object.assign(s, { filament_colour: colours, filament_self_index: colours.map((_, i) => String(i + 1)), filament_map: Array(count).fill("1"),
    filament_nozzle_map: Array(count).fill("1"), filament_volume_map: Array(count).fill("0"), flush_volumes_matrix: flush,
    flush_volumes_vector: Array(2 * count).fill("140"), different_settings_to_system: Array(count + 2).fill(""), inherits_group: Array(count + 2).fill("") });
  const pts = s.printable_area.map((q) => q.split("x").map(Number));
  const back = Math.max(...pts.map((q) => q[1]));
  s.wipe_tower_y = [String(+Math.min(Number(s.wipe_tower_y[0]), back - 66).toFixed(6))];
  const bx = (Math.min(...pts.map((q) => q[0])) + Math.max(...pts.map((q) => q[0]))) / 2, by = (Math.min(...pts.map((q) => q[1])) + back) / 2;
  const [lo, hi] = bbox(p.pos), cen = lo.map((x, j) => (x + hi[j]) / 2);
  const codes = colours.map((_, i) => paintCode(i + 1));
  const vx = [], tx = [];
  for (let i = 0; i < p.pos.length; i += 3) vx.push(`     <vertex x="${(p.pos[i] - cen[0]).toFixed(5)}" y="${(p.pos[i + 1] - cen[1]).toFixed(5)}" z="${(p.pos[i + 2] - cen[2]).toFixed(5)}"/>`);
  for (let f = 0; f < p.labels.length; f++) tx.push(`     <triangle v1="${p.idx[f * 3]}" v2="${p.idx[f * 3 + 1]}" v3="${p.idx[f * 3 + 2]}" paint_color="${codes[Math.min(filOf[p.labels[f]], 15)]}"/>`);
  const obj = ['<?xml version="1.0" encoding="UTF-8"?>', `<model unit="millimeter" xml:lang="en-US" ${NS}>`, ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
    " <resources>", '  <object id="1" p:UUID="00010000-81cb-4c03-9d28-80fed5dfa1dc" type="model">', "   <mesh>", "    <vertices>", ...vx, "    </vertices>",
    "    <triangles>", ...tx, "    </triangles>", "   </mesh>", "  </object>", " </resources>", " <build/>", "</model>", ""].join("\n");
  const root = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" ${NS}>
 <metadata name="Application">BambuStudio-02.07.01.62</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Title">${xesc(name)}</metadata>
 <resources>
  <object id="2" p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">
   <components>
    <component p:path="/${OBJ_PATH}" objectid="1" p:UUID="00010000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
   </components>
  </object>
 </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
  <item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 ${bx.toFixed(4)} ${by.toFixed(4)} ${((hi[2] - lo[2]) / 2).toFixed(4)}" printable="1"/>
 </build>
</model>
`;
  const v = `"${xesc(name)}"`;
  const ms = `<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value=${v}/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="${p.labels.length}"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value=${v}/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="1"/>
    </model_instance>
  </plate>
</config>
`;
  const ct = '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n <Default Extension="png" ContentType="image/png"/>\n</Types>';
  const bytes = zipSync({ "[Content_Types].xml": strToU8(ct), "_rels/.rels": strToU8(rels("/3D/3dmodel.model")), "3D/3dmodel.model": strToU8(root),
    "3D/_rels/3dmodel.model.rels": strToU8(rels("/" + OBJ_PATH)), [OBJ_PATH]: strToU8(obj), "Metadata/model_settings.config": strToU8(ms),
    "Metadata/project_settings.config": strToU8(JSON.stringify(s, null, 4)) }, { level: 6 });
  return [bytes, colours];
}
export const hasFilaments = (parts) => hasRegions(parts) && Object.keys(parts[0].colors || {}).length > 0;
