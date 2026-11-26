// 資料助秘3D列印AI代理人工具 — 線上版主程式（畫面、路由、設計庫 IndexedDB、語音教學）。
import { DATA } from "./data.js";
import { initEngine, build, RECIPES, BY_ID, clean } from "./engine.js";
import { check } from "./checks.js";
import * as MS from "./mesh.js";
import { Viewer } from "./viewer.js";
import { Agent, MODEL, translateQuery, searchLinks } from "./agent.js";
import * as RG from "./regions.js";

const $ = (s, el = document) => el.querySelector(s);
const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const store = { get: (k, d = "") => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set: (k, v) => { try { if (v === "" || v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* 私密模式 */ } } };
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = err ? "err" : ""; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => { t.style.display = "none"; }, err ? 4500 : 2400);
}
const IOS = window.ZMSIOS, AND = window.ZMSAndroid;
async function download(name, data, type = "application/octet-stream") {
  if (IOS || AND) {                              // App 裡：交給 App 的分享面板／存檔
    const u8 = data instanceof Uint8Array ? data : typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(data);
    let b = ""; for (let i = 0; i < u8.length; i += 0x8000) b += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    try {
      if (IOS) await window.webkit.messageHandlers.zms.postMessage({ cmd: "save_file", args: [name, btoa(b)] });
      else AND.saveFile(name, btoa(b));
    } catch (e) { toast("存檔失敗：" + e, true); }
    return;
  }
  const url = URL.createObjectURL(new Blob([data], { type })), a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
}
const safeName = (s) => String(s || "model").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 50);

// ====================================================================== 設計庫（IndexedDB：每台裝置自己的資料）
const DB = {
  db: null,
  async open() {
    if (this.db) return this.db;
    this.db = await new Promise((ok, no) => {
      const r = indexedDB.open("zms-print-agent", 1);
      r.onupgradeneeded = () => { r.result.createObjectStore("designs", { keyPath: "id", autoIncrement: true }); };
      r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
    });
    return this.db;
  },
  async tx(mode, fn) {
    const db = await this.open();
    return new Promise((ok, no) => { const t = db.transaction("designs", mode), s = t.objectStore("designs"), r = fn(s); t.oncomplete = () => ok(r && r.result); t.onerror = () => no(t.error); });
  },
  all() { return this.tx("readonly", (s) => s.getAll()).then((x) => (x || []).sort((a, b) => b.updated - a.updated)); },
  get(id) { return this.tx("readonly", (s) => s.get(id)); },
  put(d) { return this.tx("readwrite", (s) => s.put(d)); },
  del(id) { return this.tx("readwrite", (s) => s.delete(id)); },
};
/** 3MF：有指定耗材顏色的區塊 → Bambu 多色專案，否則一般 3MF。 */
async function to3MF(ws) { return RG.hasFilaments(ws.parts) ? (await RG.writePainted3MF(ws.parts, ws.title))[0] : MS.write3MF(ws.parts, ws.title); }
async function saveDesign(ws, thumb, designId) {
  const bytes = await to3MF(ws), sha = await MS.sha256(bytes);
  let d = designId ? await DB.get(designId) : null;
  const rev = { rev: d ? d.revs.length + 1 : 1, at: Date.now(), params: ws.recipe ? ws.recipe[1] : {}, sha, size: bytes.length,
    file: bytes, score: ws.report?.score ?? null, report: ws.report };
  if (d) { d.revs.push(rev); Object.assign(d, { title: ws.title, updated: Date.now(), thumb, score: rev.score, status: "DRAFT" }); }
  else d = { title: ws.title, kind: ws.kind || "RECIPE", recipe: ws.recipe ? ws.recipe[0] : "", created: Date.now(), updated: Date.now(),
    thumb, score: rev.score, status: "DRAFT", printer: ws.printer, material: ws.material, revs: [rev] };
  const id = await DB.put(d);
  return [d.id || id, rev.rev, sha];
}

// ====================================================================== 工作區
class Workspace {
  constructor() { this.parts = null; this.title = ""; this.recipe = null; this.report = null; this.kind = "RECIPE";
    this.printer = store.get("pa_printer", "A1"); this.material = store.get("pa_material", "PLA"); this.purpose = "general"; this.designId = null; }
  set(parts, title, recipe) { this.parts = parts; this.title = title || this.title; this.recipe = recipe; this.report = null; }
}

// ====================================================================== 模型面板（各畫面共用）
const STATUS_IC = { pass: ["✔", "var(--ok)"], warn: ["⚠", "var(--warn)"], fail: ["✖", "var(--bad)"], skipped: ["–", "var(--muted)"] };
function reportHTML(rep) {
  if (!rep) return '<p class="muted">尚未檢查</p>';
  const tone = rep.score >= 8 ? "green" : rep.score > 4 ? "amber" : "rose";
  return `<div class="report"><div class="row"><span class="chip t-${tone}">✔ ${rep.score.toFixed(1)}／10 分</span>
    <span class="muted">${rep.printer} · ${rep.material} · ${rep.size.map((x) => +x.toFixed(1)).join(" × ")} mm${rep.weight_g ? " · 約 " + rep.weight_g + " g" : ""}</span></div>
    ${rep.items.map((i) => `<div class="it"><b style="color:${STATUS_IC[i.status][1]}">${STATUS_IC[i.status][0]}</b><b>${i.name}</b><span>${esc(i.text)}</span></div>`).join("")}
    <div class="row" style="margin-top:6px;gap:6px">${rep.settings.map(([k, v]) => `<span class="chip t-blue">${k}：${esc(v)}</span>`).join("")}</div>
    ${rep.suggestions.map((s) => `<p class="muted">💡 ${esc(s)}</p>`).join("")}</div>`;
}
class ModelPanel {
  constructor(ws, opts = {}) {
    this.ws = ws;
    this.el = h(`<div class="card panel" style="height:100%">
      <input class="title" type="text" placeholder="設計名稱">
      <div class="viewer"><div class="empty">🧊<br>還沒有模型<br><small>設計零件、開啟檔案或請 AI 代理人產生</small></div></div>
      <div class="vbar"><button data-v="iso">立體</button><button data-v="front">正面</button><button data-v="side">側面</button><button data-v="top">上方</button>
        <span class="grow"></span><span class="info"></span></div>
      <div class="row">
        <select class="pr">${Object.keys(DATA.printers).map((k) => `<option ${k === ws.printer ? "selected" : ""}>${k}</option>`).join("")}</select>
        <select class="mat">${Object.keys(DATA.materials).map((k) => `<option ${k === ws.material ? "selected" : ""}>${k}</option>`).join("")}</select>
        <select class="pur">${Object.entries(DATA.purposes).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
      </div>
      <div class="row">
        <button class="btn green dl3mf" title="下載 3MF，在 Bambu Studio 開啟、切片、自己按列印">⬇ 3MF（Bambu Studio）</button>
        <button class="btn outline save">💾 存到設計庫</button>
        <select class="exp btn outline" style="padding:8px"><option value="">匯出其他格式…</option><option value="stl">STL</option><option value="glb">GLB（彩色）</option><option value="obj">OBJ</option></select>
      </div>
      <div class="busy bar" style="display:none"></div>
      <div class="rep"></div></div>`);
    if (opts.noTitle) $(".title", this.el).style.display = "none";
    this.viewer = null;
    this.el.querySelectorAll("[data-v]").forEach((b) => b.onclick = () => this.viewer && this.viewer.view(b.dataset.v));
    $(".title", this.el).oninput = (e) => { ws.title = e.target.value; };
    const opt = () => { ws.printer = $(".pr", this.el).value; ws.material = $(".mat", this.el).value; ws.purpose = $(".pur", this.el).value;
      store.set("pa_printer", ws.printer); store.set("pa_material", ws.material); this.recheck(); };
    $(".pr", this.el).onchange = opt; $(".mat", this.el).onchange = opt; $(".pur", this.el).onchange = opt;
    $(".dl3mf", this.el).onclick = async () => this.need() && download(safeName(ws.title) + ".3mf", await to3MF(ws));
    $(".save", this.el).onclick = () => this.save();
    $(".exp", this.el).onchange = async (e) => {
      const x = e.target.value; e.target.value = ""; if (!x || !this.need()) return;
      if (x === "stl") download(safeName(ws.title) + ".stl", MS.writeSTL(ws.parts));
      if (x === "obj") download(safeName(ws.title) + ".obj", MS.writeOBJ(ws.parts));
      if (x === "glb") download(safeName(ws.title) + ".glb", await MS.writeGLB(ws.parts, "m"), "model/gltf-binary");
    };
  }
  mount() { if (!this.viewer) this.viewer = new Viewer($(".viewer", this.el)); }
  need() { if (!this.ws.parts) { toast("目前沒有模型", true); return false; } return true; }
  show(keepView = false) {
    const ws = this.ws;
    this.mount();
    $(".empty", this.el).style.display = ws.parts ? "none" : "";
    $(".title", this.el).value = ws.title || "";
    this.viewer.setParts(ws.parts, keepView);
    if (ws.parts) {
      const [lo, hi] = MS.bounds(ws.parts);
      $(".info", this.el).textContent = hi.map((v, k) => +(v - lo[k]).toFixed(1)).join(" × ") + " mm · " +
        ws.parts.reduce((s, p) => s + p.idx.length / 3, 0).toLocaleString() + " 面";
    }
    if (ws.parts && !ws.report) this.recheck(); else $(".rep", this.el).innerHTML = reportHTML(ws.report);
  }
  recheck() {
    if (!this.ws.parts) return;
    $(".busy", this.el).style.display = "";
    setTimeout(() => {
      try { this.ws.report = check(this.ws.parts, this.ws.printer, this.ws.material, this.ws.purpose); }
      catch (e) { toast("檢查失敗：" + e.message, true); }
      $(".busy", this.el).style.display = "none";
      $(".rep", this.el).innerHTML = reportHTML(this.ws.report);
    }, 20);
  }
  async save() {
    if (!this.need()) return;
    this.ws.title = $(".title", this.el).value || this.ws.title || "未命名設計";
    const [id, rev, sha] = await saveDesign(this.ws, this.viewer.snapshot(256), this.ws.designId);
    this.ws.designId = id;
    toast(`已存到設計庫：#${id}「${this.ws.title}」第 ${rev} 版（SHA-256 ${sha.slice(0, 10)}…）`);
  }
}

// ====================================================================== 畫面
const MENU = [
  ["總覽", [["home", "首頁", "🏠"]]],
  ["AI 代理人", [["agent", "AI 代理人", "🤖"]]],
  ["設計", [["design", "零件設計", "📐"], ["library", "設計庫", "📚"]]],
  ["模型工具", [["regions", "匯入與分區編輯", "🧩"], ["check", "檢查與修復", "🩺"], ["convert", "格式轉換（3MF→GLB）", "🔄"], ["search", "搜尋現成模型", "🔎"]]],
  ["設定與說明", [["aiset", "設定", "⚙️"], ["help", "語音動態教學", "🔊"]]],
];
const TITLES = Object.fromEntries(MENU.flatMap(([, it]) => it.map(([k, t]) => [k, t])));
const ws = new Workspace();
const S = {};
let current = "home";

function nav() {
  $("#nav").innerHTML = MENU.map(([g, it]) => `<div class="grp">${g}</div>` + it.map(([k, t, ic]) =>
    `<a href="#${k}" class="${k === current ? "on" : ""}"><span class="ic">${ic}</span>${t}</a>`).join("")).join("");
}
function go(sid, arg) {
  if (!TITLES[sid]) sid = "home";
  stopVoice();
  current = sid; nav();
  $("#crumb").textContent = TITLES[sid];
  $("#side").classList.remove("open");
  const v = $("#view"); v.innerHTML = "";
  try { (S[sid] || S.home)(v, arg); } catch (e) { console.error(e); v.innerHTML = `<p class="muted">畫面載入失敗：${esc(e.message)}</p>`; }
}
addEventListener("hashchange", () => { const [s, a] = decodeURIComponent(location.hash.slice(1)).split(":"); go(s || "home", a); });

// ---------------------------------------------------------------- 首頁
S.home = async (v) => {
  v.append(h(`<div class="col">
    <div class="hero"><div style="flex:1"><h2>從一句描述到可以列印的零件</h2>
      <p>描述 → 零件 → 七項列印前檢查 → 下載 3MF 到 Bambu Studio（列印由您自己按）</p>
      <div class="ask"><input id="ask" type="text" placeholder="例如：設計一個 60×40×30 mm 帶蓋的電子元件盒"><button class="btn gold" id="askBtn">問代理人</button></div></div>
      <img src="icon.png" alt=""></div>
    <div class="ways">
      ${[["agent", "🤖", "AI 代理人", "用說的：描述與尺寸"], ["design", "📐", "零件設計", RECIPES.length + " 種參數化零件"], ["regions", "🧩", "匯入與分區編輯", "FBX／OBJ／Maya 分區逐一修改"], ["check", "🩺", "檢查與修復", "STL／3MF／GLB 七項檢查"],
        ["search", "🔎", "搜尋現成模型", "MakerWorld、Printables"], ["convert", "🔄", "3MF → GLB", "多色專案轉通用格式"]].map(([k, ic, t, s]) =>
        `<div class="card way" data-go="${k}"><div class="big">${ic}</div><b>${t}</b><span class="muted">${s}</span></div>`).join("")}</div>
    <div class="card"><div class="row"><h3 style="flex:1">最近的設計</h3><a class="btn ghost small" href="#library">設計庫 →</a></div><div class="grid" id="recent" style="margin-top:10px"></div></div>
    <div class="card"><h3>線上版與電腦版</h3><p class="muted">線上版不用安裝、不用登入，設計存在這台裝置的瀏覽器裡。要連 Bambu Studio 一鍵開啟與切片估算、讀印表機狀態、
      搜尋結果直接列出、AI 文字／照片轉 3D、多人帳號與權限，請下載 <a href="https://github.com/${DATA.repo}/releases/latest" target="_blank">Windows／macOS 電腦版</a>。</p></div></div>`));
  v.querySelectorAll("[data-go]").forEach((c) => c.onclick = () => { location.hash = c.dataset.go; });
  const ask = () => { store.set("pa_pending", $("#ask").value); location.hash = "agent"; };
  $("#askBtn").onclick = ask; $("#ask").onkeydown = (e) => { if (e.key === "Enter") ask(); };
  const ds = (await DB.all()).slice(0, 8);
  $("#recent").innerHTML = ds.length ? ds.map(cardHTML).join("") : '<p class="muted">還沒有設計。試試上面的輸入框，或到「零件設計」挑一個零件。</p>';
  bindCards($("#recent"));
};
const STATUS = { DRAFT: ["草稿", "amber"], APPROVED: ["已核准", "green"], PRINTED: ["已列印", "blue"] };
function cardHTML(d) {
  const [s, t] = STATUS[d.status] || STATUS.DRAFT;
  return `<div class="card" data-id="${d.id}" style="padding:8px;cursor:pointer"><div class="thumb">${d.thumb ? `<img src="${d.thumb}">` : "🧊"}</div>
    <b style="display:block;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(d.title)}</b>
    <span class="chip t-${t}">${s}</span> <span class="muted">v${d.revs.length}${d.score != null ? " · " + d.score + " 分" : ""}</span></div>`;
}
function bindCards(el) { el.querySelectorAll("[data-id]").forEach((c) => c.onclick = () => { location.hash = "library:" + c.dataset.id; }); }

// ---------------------------------------------------------------- AI 代理人
let agent = null, chatLog = [];
S.agent = (v) => {
  const panel = new ModelPanel(ws);
  agent = agent || new Agent(ws, {});
  agent.hooks = {
    onModel: () => panel.show(true), onStatus: (t) => { $("#st").textContent = t; },
    onDownload: async (w) => download(safeName(w.title) + ".3mf", await to3MF(w)),
    onLinks: (q, L) => addMsg("ai", `🔎 搜尋「${q}」：`, "", [["MakerWorld", L.makerworld], ["Printables", L.printables]]),
  };
  const claude = agent.useClaude();
  const ex = ["設計一個尺寸為 60×40×30 毫米、帶蓋的電子元件盒", "做一個 M3 螺絲用的 L 型支架，寬 30", "縮放到 12 公分高，檢查是否適合我的 A1 Mini",
    "在 MakerWorld 幫我找好用的電線整理器", "設計額溫槍外殼，用 GOOUUU ESP32-S3 開發板", "設計桌下耳機掛鉤，下垂高度 35", "正齒輪 齒數 30 模數 2"];
  const box = h(`<div class="split"><div class="card panel">
      <div class="row"><h3 style="flex:1">🤖 3D 列印 AI 代理人</h3><span class="chip ${claude ? "t-violet" : "t-teal"}">${claude ? "Claude " + MODEL : "本機規則（免費）"}</span>
        <label class="btn ghost small" title="匯入現成模型（STL、OBJ、FBX、Maya .ma、3MF、GLB）再分區修改">📂 匯入模型<input type="file" id="impModel" accept=".stl,.obj,.fbx,.ma,.mb,.mtl,.3mf,.glb,.gltf,.ply" hidden></label>
        <button class="btn ghost small" id="newChat">新對話</button></div>
      <div class="chat" id="chat"></div><div class="muted" id="st"></div>
      <div class="composer"><textarea id="inp" rows="2" placeholder="描述您要印的東西，例如：設計一個 60×40×30 mm 帶蓋的盒子（Enter 送出，Shift+Enter 換行）"></textarea>
        <button class="btn" id="send">送出</button></div></div></div>`);
  box.append(panel.el); v.append(box); panel.mount();
  const chat = $("#chat");
  function addMsg(role, text, tools = "", links = null, store_ = true) {
    const m = h(`<div class="msg ${role === "me" ? "me" : "ai"}"></div>`);
    m.textContent = text;
    if (links) { const r = h('<div class="row" style="margin-top:6px"></div>'); links.forEach(([t, u]) => r.append(h(`<a class="btn small outline" target="_blank" rel="noopener" href="${esc(u)}">${t} ↗</a>`))); m.append(r); }
    if (tools) m.append(h(`<div class="tools">🛠 ${esc(tools)}</div>`));
    chat.append(m); chat.scrollTop = chat.scrollHeight;
    if (store_) chatLog.push([role, text, tools, links]);
  }
  const welcome = () => {
    chat.innerHTML = "";
    addMsg("ai", "您好！我是 3D 列印 AI 代理人。用一句話告訴我想印什麼、大概多大，我會設計零件、做七項列印前檢查，滿意後下載 3MF 到 Bambu Studio（列印由您自己按）。\n\n" +
      (claude ? "目前使用 Claude，可以自由描述。" : "目前用免費的本機規則；到「設定」填入 Claude API 金鑰，就能理解更自由的描述。"), "", null, false);
    const e = h('<div class="examples"></div>');
    ex.forEach((x) => { const b = h(`<button>${x}</button>`); b.onclick = () => send(x); e.append(b); });
    chat.append(e);
  };
  if (chatLog.length) chatLog.forEach(([r, t, tl, l]) => addMsg(r, t, tl, l, false)); else welcome();
  if (ws.parts) panel.show(true);
  let busy = false;
  async function send(text) {
    text = (text ?? $("#inp").value).trim(); if (!text || busy) return;
    $("#inp").value = ""; const e = $(".examples", chat); if (e) e.remove();
    addMsg("me", text); busy = true; $("#st").textContent = "思考中…";
    try { const [reply, tools] = await agent.ask(text); addMsg("ai", reply, [...new Set(tools)].join("、")); }
    catch (err) { addMsg("ai", "⚠️ " + (err.message || err)); }
    busy = false; $("#st").textContent = "";
  }
  $("#send").onclick = () => send();
  $("#inp").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#newChat").onclick = () => { chatLog = []; agent.messages = []; welcome(); };
  $("#impModel").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = ""; if (!f || busy) return;
    const e2 = $(".examples", chat); if (e2) e2.remove();
    addMsg("me", "匯入 " + f.name);
    try { addMsg("ai", await agent.importFile(f.name, await f.arrayBuffer()), "匯入模型"); }
    catch (err) { addMsg("ai", "⚠️ 匯入失敗：" + (err.message || err)); }
  };
  const pend = store.get("pa_pending"); if (pend) { store.set("pa_pending", ""); send(pend); }
};

// ---------------------------------------------------------------- 零件設計
S.design = async (v, arg) => {
  let rid = BY_ID[arg] ? arg : (ws.recipe ? ws.recipe[0] : "storage_box"), vals = ws.recipe && ws.recipe[0] === rid ? { ...ws.recipe[1] } : clean(rid, {});
  let cat = null;
  const panel = new ModelPanel(ws);
  const box = h(`<div class="split3"><div class="card panel"><h3>零件庫</h3><div class="row" id="cats" style="gap:4px"></div><div class="list" id="rlist"></div></div>
    <div class="card panel"><div id="rhead"></div><div class="col" id="form" style="overflow:auto"></div><button class="btn ghost small" id="reset">↺ 回到預設值</button></div></div>`);
  box.append(panel.el); v.append(box); panel.mount();
  function list() {
    $("#cats").innerHTML = ["全部", ...DATA.categories].map((c) => `<button class="chip ${(c === "全部" ? !cat : cat === c) ? "t-blue" : "t-slate"}" style="border:0;cursor:pointer" data-c="${c}">${c}</button>`).join("");
    $("#cats").querySelectorAll("button").forEach((b) => b.onclick = () => { cat = b.dataset.c === "全部" ? null : b.dataset.c; list(); });
    $("#rlist").innerHTML = RECIPES.filter((r) => !cat || r.category === cat).map((r) => `<div class="item ${r.id === rid ? "on" : ""}" data-r="${r.id}">${r.name}<span class="muted" style="margin-left:auto">${r.category}</span></div>`).join("");
    $("#rlist").querySelectorAll("[data-r]").forEach((it) => it.onclick = () => { rid = it.dataset.r; vals = clean(rid, {}); ws.designId = null; ws.title = BY_ID[rid].name; form(); list(); rebuild(false); });
  }
  function form() {
    const r = BY_ID[rid];
    $("#rhead").innerHTML = `<h3>${r.name} <span class="chip t-amber">${r.category}</span></h3><p class="muted">${esc(r.desc)}</p>`;
    $("#form").innerHTML = "";
    for (const p of r.params) {
      if (p.kind === "bool") {
        const el = h(`<label class="row" style="font-size:14px"><input type="checkbox" ${vals[p.key] ? "checked" : ""}> ${p.label}</label>`);
        $("input", el).onchange = (e) => { vals[p.key] = e.target.checked; rebuild(true); };
        $("#form").append(el); continue;
      }
      const el = h(`<div class="param"><div class="lab"><span>${p.label}</span><span class="muted">${p.min}～${p.max} ${p.unit}</span></div>
        <input type="range" min="${p.min}" max="${p.max}" step="${p.step}" value="${vals[p.key]}"><input type="number" min="${p.min}" max="${p.max}" step="${p.step}" value="${vals[p.key]}">
        ${p.doc ? `<div class="doc">${esc(p.doc)}</div>` : ""}</div>`);
      const [rg, nb] = el.querySelectorAll("input");
      rg.oninput = () => { nb.value = rg.value; vals[p.key] = Number(rg.value); rebuild(true); };
      nb.onchange = () => { vals = clean(rid, { ...vals, [p.key]: nb.value }); rg.value = nb.value = vals[p.key]; rebuild(true); };
      $("#form").append(el);
    }
  }
  let timer = null;
  function rebuild(keep) {
    clearTimeout(timer);
    timer = setTimeout(() => {
      try { const res = build(rid, vals); ws.set(res.parts, ws.title || BY_ID[rid].name, [rid, res.params]); ws.kind = "RECIPE"; panel.show(keep); }
      catch (e) { toast("這組參數做不出零件：" + e.message, true); }
    }, keep ? 120 : 0);
  }
  $("#reset").onclick = () => { vals = clean(rid, {}); form(); rebuild(true); };
  if (!ws.title || !ws.recipe || ws.recipe[0] !== rid) ws.title = BY_ID[rid].name;
  list(); form(); rebuild(false);
};

// ---------------------------------------------------------------- 設計庫
S.library = async (v, arg) => {
  const box = h(`<div class="split"><div class="col"><div class="row"><h2 style="flex:1">📚 設計庫</h2><a class="btn small" href="#design">＋ 新設計</a></div>
    <p class="muted">存在這台裝置的瀏覽器（IndexedDB）；每次儲存一版，附 3MF 檔與 SHA-256。清除瀏覽器資料會一起刪除，重要的請匯出。</p>
    <div class="grid" id="lib"></div></div><div class="card" id="det"><p class="muted">點選左邊的設計查看明細</p></div></div>`);
  v.append(box);
  const ds = await DB.all();
  $("#lib").innerHTML = ds.length ? ds.map(cardHTML).join("") : '<p class="muted">還沒有設計。到「零件設計」或「AI 代理人」做一個，按「存到設計庫」。</p>';
  bindCards($("#lib"));
  if (arg) show(Number(arg));
  async function show(id) {
    const d = await DB.get(id); if (!d) return;
    const [s, t] = STATUS[d.status] || STATUS.DRAFT, cur = d.revs[d.revs.length - 1];
    $("#det").innerHTML = `<div class="col"><div class="row"><h2 style="flex:1">${esc(d.title)}</h2><span class="chip t-${t}">${s}</span></div>
      ${d.thumb ? `<div class="thumb" style="height:200px"><img src="${d.thumb}"></div>` : ""}
      <div class="row"><button class="btn" id="edit">✏️ 繼續編輯</button><button class="btn green" id="dl">⬇ 3MF（Bambu Studio）</button>
        <button class="btn outline" id="appr">${d.status === "APPROVED" ? "↺ 改回草稿" : "✔ 核准（凍結）"}</button><button class="btn outline" id="printed">🖨 標記已列印</button>
        <button class="btn danger" id="del">🗑 刪除</button></div>
      <p class="muted">#${d.id} · 建立 ${new Date(d.created).toLocaleString()} · ${d.printer || ""} ${d.material || ""}</p>
      <h3>列印前檢查（目前版本）</h3>${reportHTML(cur.report)}
      <h3>版本</h3>${[...d.revs].reverse().map((r) => `<div class="card" style="padding:8px"><b>v${r.rev}</b> <span class="muted">${new Date(r.at).toLocaleString()} · ${(r.size / 1024).toFixed(1)} KB</span>
        <button class="btn ghost small" data-rev="${r.rev}">⬇ 下載</button><div class="muted" style="word-break:break-all;font-size:11px">SHA-256 ${r.sha}</div></div>`).join("")}</div>`;
    $("#det").querySelectorAll("[data-rev]").forEach((b) => b.onclick = () => { const r = d.revs[Number(b.dataset.rev) - 1]; download(`${safeName(d.title)}_v${r.rev}.3mf`, r.file); });
    $("#dl").onclick = () => download(safeName(d.title) + ".3mf", cur.file);
    $("#edit").onclick = () => {
      const r = MS.parse3MF(cur.file); MS.placeOnPlate(r.parts);
      ws.set(r.parts, d.title, d.recipe && BY_ID[d.recipe] ? [d.recipe, cur.params] : null); ws.designId = d.id; ws.report = cur.report;
      location.hash = d.recipe && BY_ID[d.recipe] ? "design:" + d.recipe : "check";
    };
    $("#appr").onclick = async () => {
      if (d.status !== "APPROVED" && cur.score != null && cur.score <= 4) return toast(`列印前檢查只有 ${cur.score} 分，請先修正再核准`, true);
      if (d.status !== "APPROVED" && (await MS.sha256(cur.file)) !== cur.sha) return toast("檔案與雜湊不一致", true);
      d.status = d.status === "APPROVED" ? "DRAFT" : "APPROVED"; d.updated = Date.now(); await DB.put(d); go("library", d.id);
    };
    $("#printed").onclick = async () => { d.status = "PRINTED"; await DB.put(d); go("library", d.id); };
    $("#del").onclick = async () => {
      if (d.status === "APPROVED") return toast("已核准的設計不能刪除", true);
      if (confirm(`確定要刪除「${d.title}」和它的所有版本嗎？`)) { await DB.del(d.id); go("library"); }
    };
  }
};

// ---------------------------------------------------------------- 匯入與分區編輯（移植 pa/ui/regionview.py）
const RS = { history: [], sel: new Set(), explode: 0, log: [] };
S.regions = (v) => {
  const panel = new ModelPanel(ws);
  const colors = ["紅", "橙", "黃", "綠", "藍", "淺藍", "紫", "粉紅", "黑", "白", "灰", "金", "咖啡"];
  const box = h(`<div class="split3 regions">
    <div class="card col" style="overflow:auto">
      <h3>1. 匯入模型</h3><p class="muted">STL、OBJ（有材質群組會自動分區）、FBX、Maya .ma、3MF、GLB、PLY。Maya .mb 請先在 Maya 另存成 .ma 或匯出 .fbx。檔案只在這台裝置處理。</p>
      <div class="row"><label class="btn">📂 開啟檔案<input type="file" id="rfile" accept=".stl,.obj,.fbx,.ma,.mb,.mtl,.3mf,.glb,.gltf,.ply" hidden></label>
        <button class="btn outline" id="rcur" title="把零件設計或 AI 代理人剛做好的模型拿來分區">用目前的模型</button></div>
      <h3>2. 分區</h3>
      <label class="fld">分區方法<select id="rmeth">${Object.entries(RG.METHODS).map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>
      <label class="fld">最多幾區<input type="number" id="rtarget" value="8" min="2" max="16" style="width:90px"></label>
      <div class="row"><button class="btn accent" id="rseg">🧩 分區</button><button class="btn ghost" id="rundo">↶ 復原上一步</button></div>
      <h3>拆開／組裝檢視</h3><p class="muted">每個區塊從物件中心往各自的方向拆開，看清楚每一塊；只影響畫面，不會改到模型。</p>
      <div class="row"><button class="btn outline" id="rexp">↔ 拆開</button><button class="btn outline" id="rasm">→← 組裝</button></div>
      <input type="range" id="rslide" min="0" max="1" step="0.05" value="${RS.explode}" style="accent-color:var(--primary)">
      <div class="busy bar" id="rbusy" style="display:none"></div>
      <h3>處理紀錄</h3><div id="rlog" class="col" style="gap:2px;font-size:12px"></div></div>
    <div class="card col" style="overflow:auto">
      <div class="row"><h3 style="flex:1">3. 區塊</h3><button class="btn ghost small" id="rall">全選</button><button class="btn ghost small" id="rnone">清除</button></div>
      <div class="list" id="rlist2" style="max-height:300px"></div>
      <h3>修改勾選的區塊</h3>
      <div class="row"><button class="btn danger small" data-op="delete">🗑 刪除</button><button class="btn outline small" data-op="keep">只保留</button><button class="btn outline small" data-op="merge">合併</button></div>
      <div class="row"><input type="number" id="rx" value="0" style="width:70px" title="X mm"><input type="number" id="ry" value="0" style="width:70px" title="Y mm"><input type="number" id="rz" value="0" style="width:70px" title="Z mm"><button class="btn outline small" data-op="move">✥ 移動（X Y Z mm）</button></div>
      <div class="row"><input type="number" id="rfac" value="1.2" step="0.1" style="width:70px" title="倍數"><button class="btn outline small" data-op="scale">縮放</button>
        <select id="rax"><option value="x">X</option><option value="y">Y</option><option value="z" selected>Z</option></select><input type="number" id="rdeg" value="90" style="width:70px" title="角度"><button class="btn outline small" data-op="rotate">↻ 旋轉</button></div>
      <div class="row"><select id="rcol">${colors.map((c) => `<option ${c === "黑" ? "selected" : ""}>${c}</option>`).join("")}</select><button class="btn outline small" data-op="color">🎨 上色（耗材）</button><button class="btn ghost small" data-op="uncolor">取消顏色</button></div>
      <div class="row"><input type="text" id="rname" placeholder="新名稱" style="width:150px"><button class="btn outline small" data-op="rename">改名</button></div>
      <h3>整個模型</h3>
      <div class="row"><select id="rshape"><option value="circle">圓形</option><option value="box">方形</option></select>
        <label class="fld">直徑 mm<input type="number" id="rdia" value="3" step="0.1" style="width:80px"></label><label class="fld">深度／高 mm<input type="number" id="rdep" value="0" step="0.5" style="width:90px"></label></div>
      <p class="muted" style="margin:0">鑽孔：深度 0＝貫穿；加凸台：填高度（0＝5 mm）；方向用上面的軸。</p>
      <div class="row"><button class="btn outline small" id="rhole">⭘ 在勾選區中心鑽孔</button><button class="btn outline small" id="rboss">⊕ 在勾選區中心加凸台</button></div>
      <div class="row"><button class="btn outline small" data-cut="x">✂ 沿 X 切兩半</button><button class="btn outline small" data-cut="y">✂ 沿 Y 切兩半</button><button class="btn outline small" data-cut="z">✂ 沿 Z 切兩半</button></div>
    </div></div>`);
  box.append(panel.el); v.append(box); panel.mount();
  const log = (t, warn = false) => { RS.log.push([t, warn]); RS.log = RS.log.slice(-40); drawLog(); };
  const drawLog = () => { $("#rlog").innerHTML = RS.log.map(([t, w]) => `<div style="color:${w ? "var(--warn)" : "var(--text)"}">${w ? "⚠️" : "✔"} ${esc(t)}</div>`).join(""); };
  const num = (id) => { const x = Number($(id).value); if (!Number.isFinite(x)) throw new RG.EditError("請填數字"); return x; };
  function draw() {
    const rs = ws.parts ? RG.regions(ws.parts) : [];
    RS.sel = new Set([...RS.sel].filter((i) => i <= rs.length));
    $("#rlist2").innerHTML = rs.length ? rs.map((r) => `<label class="item ${RS.sel.has(r.id) ? "on" : ""}" style="font-weight:400">
        <input type="checkbox" data-id="${r.id}" ${RS.sel.has(r.id) ? "checked" : ""}>
        <span style="width:16px;height:16px;border-radius:8px;flex:none;background:${r.color};${r.filament ? "outline:2px solid var(--text)" : ""}"></span>
        <span style="min-width:0"><b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${r.id}. ${esc(r.name)}</b>
        <span class="muted" style="font-size:11px">${r.faces.toLocaleString()} 面 · ${r.size_mm.join("×")} mm · 中心 (${r.center_mm.join(", ")})</span></span></label>`).join("")
      : `<p class="muted">${ws.parts ? "還沒分區：選分區方法後按「分區」" : "請先匯入模型"}</p>`;
    $("#rlist2").querySelectorAll("[data-id]").forEach((c) => c.onchange = () => { const i = +c.dataset.id; if (c.checked) RS.sel.add(i); else RS.sel.delete(i); draw(); });
    highlight();
  }
  function highlight() {
    if (!ws.parts) return;
    if (!RG.hasRegions(ws.parts) || (!RS.sel.size && RS.explode <= 0)) { panel.viewer.setParts(ws.parts, true); $(".info", panel.el).dataset.note = ""; return; }
    const rgb = RG.dimmed(ws.parts, [...RS.sel]);
    const shown = RS.explode > 0 ? RG.explodeView(ws.parts, RS.explode, rgb) : [{ ...ws.parts[0], rgb }];
    panel.viewer.setParts(shown, true);
    const [lo, hi] = MS.bounds(ws.parts);
    $(".info", panel.el).textContent = hi.map((x, k) => +(x - lo[k]).toFixed(1)).join(" × ") + " mm · " + (ws.parts[0].idx.length / 3).toLocaleString() + " 面" +
      (RS.explode > 0 ? "（拆開檢視，實際尺寸見下方）" : "");
  }
  function set(parts, title, msg, push) {
    if (push && ws.parts) { RS.history.push([ws.parts, ws.title]); RS.history = RS.history.slice(-20); }
    ws.set(parts, title || ws.title, null); ws.kind = "FILE";
    panel.show(!!push);
    if (msg) log(msg);
    draw();
  }
  const busy = (on) => { $("#rbusy").style.display = on ? "" : "none"; };
  const run = (fn) => {
    if (!ws.parts) return toast("請先匯入模型", true);
    busy(true);
    setTimeout(() => {
      try { const [p2, msg] = fn(); set(p2, null, msg, true); }
      catch (e) { toast(e instanceof RG.EditError ? e.message : "處理失敗：" + e.message, true); console.error(e); }
      busy(false);
    }, 30);
  };
  const needSel = () => { if (!RS.sel.size) throw new RG.EditError("請先在區塊清單勾選要修改的區塊"); return [...RS.sel].sort((a, b) => a - b); };
  const guard = (f) => () => { try { f(); } catch (e) { toast(e.message, true); } };
  $("#rfile").onchange = async (e) => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    busy(true);
    try {
      const r = await MS.loadFile(f.name, await f.arrayBuffer());
      MS.placeOnPlate(r.parts);
      RS.history = []; RS.sel.clear(); RS.log = []; RS.explode = 0; $("#rslide").value = 0;
      const [lo, hi] = MS.bounds(r.parts), size = hi.map((x, k) => +(x - lo[k]).toFixed(1));
      set(r.parts, f.name.replace(/\.[^.]+$/, ""), null, false); ws.designId = null;
      log(`匯入：${f.name}（${r.parts.reduce((s, p) => s + p.idx.length / 3, 0).toLocaleString()} 面，${size.join("×")} mm${RG.hasRegions(r.parts) ? `，已有 ${RG.regions(r.parts).length} 個區塊` : ""}）`);
      (r.notes || []).forEach((n) => log(n, true));
      if (Math.max(...size) < 5) log(`模型只有 ${Math.max(...size).toFixed(2)} mm 大，單位可能是公分或公尺：用「縮放」把全部區塊放大 10 或 1000 倍`, true);
    } catch (err) { toast("讀取失敗：" + err.message, true); }
    busy(false);
  };
  $("#rcur").onclick = () => { if (!ws.parts) return toast("目前沒有模型；請先在零件設計或 AI 代理人做一個，或直接開啟檔案", true); RS.history = []; set(ws.parts, ws.title, "使用目前的模型：" + ws.title, false); };
  $("#rseg").onclick = () => { const meth = $("#rmeth").value, n = Math.round(Number($("#rtarget").value) || 8);
    run(() => { const p2 = RG.segment(ws.parts, meth, n); RS.sel.clear(); return [p2, `分區（${RG.METHODS[meth]}）：${RG.regions(p2).length} 區`]; }); };
  $("#rundo").onclick = () => { if (!RS.history.length) return toast("沒有可以復原的步驟", true); const [p, t] = RS.history.pop(); set(p, t, "已復原上一步", false); };
  $("#rall").onclick = () => { RS.sel = new Set(RG.regions(ws.parts || []).map((r) => r.id)); draw(); };
  $("#rnone").onclick = () => { RS.sel.clear(); draw(); };
  box.querySelectorAll("[data-op]").forEach((b) => b.onclick = guard(() => {
    const op = b.dataset.op, sel = needSel(), kw = {};
    if (op === "move") Object.assign(kw, { dx: num("#rx"), dy: num("#ry"), dz: num("#rz") });
    if (op === "scale") kw.factor = num("#rfac");
    if (op === "rotate") Object.assign(kw, { axis: $("#rax").value, degrees: num("#rdeg") });
    if (op === "color") kw.color = $("#rcol").value;
    if (op === "rename") kw.name = $("#rname").value;
    if (op === "delete") RS.sel.clear();
    run(() => RG.edit(ws.parts, op, sel, kw));
  }));
  $("#rhole").onclick = guard(() => { const sel = needSel(), d = num("#rdia"), dep = num("#rdep");
    run(() => RG.edit(ws.parts, "hole", sel, { diameter: d, width: d, height: d, depth: dep || null, axis: $("#rax").value, shape: $("#rshape").value })); });
  $("#rboss").onclick = guard(() => { const sel = needSel(), d = num("#rdia"), hh = num("#rdep") || 5;
    run(() => RG.edit(ws.parts, "boss", sel, { diameter: d, width: d, height: hh, axis: $("#rax").value, shape: $("#rshape").value })); });
  box.querySelectorAll("[data-cut]").forEach((b) => b.onclick = () => run(() => RG.edit(RG.toSingle(ws.parts), "cut", null, { axis: b.dataset.cut })));
  const needRegions = () => { if (!ws.parts || !RG.hasRegions(ws.parts)) { toast("請先分區，才能拆開檢視", true); $("#rslide").value = 0; return false; } return true; };
  $("#rslide").oninput = () => { if (!needRegions()) return; RS.explode = Number($("#rslide").value); highlight(); };
  let anim = null;
  const animate = (target) => {
    if (!needRegions()) return;
    clearInterval(anim);
    const start = RS.explode, steps = 10; let i = 0;
    anim = setInterval(() => {
      i++; const t = i / steps;
      RS.explode = start + (target - start) * (1 - (1 - t) ** 2); $("#rslide").value = RS.explode; highlight();
      if (i >= steps) { clearInterval(anim); RS.explode = target; highlight(); }
    }, 60);
  };
  $("#rexp").onclick = () => animate(1); $("#rasm").onclick = () => animate(0);
  drawLog();
  if (ws.parts) { panel.show(true); draw(); } else draw();
};

// ---------------------------------------------------------------- 檢查與修復
let orig = null;
S.check = (v) => {
  const panel = new ModelPanel(ws);
  const box = h(`<div class="split"><div class="card col">
      <h3>1. 開啟模型</h3><p class="muted">STL、3MF（含 Bambu 多色）、OBJ、GLB、PLY；檔案只在這台裝置處理，不會上傳。</p>
      <div class="row"><label class="btn">📂 開啟檔案<input type="file" id="file" accept=".stl,.3mf,.obj,.glb,.gltf,.ply" hidden></label><button class="btn ghost" id="revert">↺ 還原</button></div>
      <h3>2. 調整（下載或 AI 產生的模型建議都做）</h3>
      <label class="fld">檔案單位<select id="unit"><option value="1">mm（一般）</option><option value="10">公分 ×10</option><option value="25.4">英吋 ×25.4</option><option value="1000">公尺 ×1000</option></select></label>
      <label class="fld">縮放到高度（mm，空白＝不變）<input type="number" id="hgt" min="1"></label>
      <label class="row"><input type="checkbox" id="ori" checked> 自動擺放（平底朝下）</label>
      <button class="btn accent" id="apply">✨ 套用並重新檢查</button>
      <h3>處理紀錄</h3><div id="notes" class="col muted"></div></div></div>`);
  box.append(panel.el); v.append(box); panel.mount();
  if (ws.parts) panel.show(true);
  const note = (t) => $("#notes").append(h(`<div>${esc(t)}</div>`));
  $("#file").onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const r = await MS.loadFile(f.name, await f.arrayBuffer());
      MS.placeOnPlate(r.parts); orig = MS.clone(r.parts);
      ws.set(r.parts, f.name.replace(/\.[^.]+$/, ""), null); ws.kind = "FILE"; ws.designId = null;
      $("#notes").innerHTML = ""; note(`開啟：${f.name}（${r.parts.reduce((s, p) => s + p.idx.length / 3, 0).toLocaleString()} 面${r.palette.length ? "、多色 " + r.palette.length + " 種耗材" : ""}）`);
      r.notes.forEach((n) => note("⚠️ " + n));
      const ext = MS.extent(r.parts);
      if (ext < 5) note(`⚠️ 模型最大邊只有 ${ext.toPrecision(3)} mm，可能是公分、英吋或公尺，請選擇檔案單位`);
      panel.show(false);
    } catch (err) { toast("讀取失敗：" + err.message, true); }
  };
  $("#revert").onclick = () => { if (orig) { ws.set(MS.clone(orig), ws.title, null); panel.show(true); note("已還原成原始檔案"); } };
  $("#apply").onclick = () => {
    if (!orig) { if (!ws.parts) return toast("請先開啟模型", true); orig = MS.clone(ws.parts); }
    const p = MS.clone(orig), u = Number($("#unit").value);
    if (u !== 1) { MS.scaleParts(p, u); note(`單位換算 ×${u}`); }
    const hh = Number($("#hgt").value);
    if (hh > 0) { const [lo, hi] = MS.bounds(p), f = hh / (hi[2] - lo[2]); MS.scaleParts(p, f); note(`等比例縮放 ×${f.toPrecision(4)}（高度 ${hh} mm）`); }
    if ($("#ori").checked) note("自動擺放：" + MS.orient(p)); else MS.placeOnPlate(p);
    ws.set(p, ws.title, null); panel.show(true);
  };
};

// ---------------------------------------------------------------- 3MF → GLB
S.convert = (v) => {
  const box = h(`<div class="split"><div class="card col"><h3>🎨 Bambu Studio 多色 3MF → GLB</h3>
      <p class="muted">重建 Bambu 的上色筆刷（paint_color），每種耗材一個材質；Blender、Unity、three.js、Windows 3D 檢視器都能開。檔案只在這台裝置處理。</p>
      <div class="row"><label class="btn">📂 選擇 3MF（可多選）<input type="file" id="f3" accept=".3mf" multiple hidden></label>
        <select id="units"><option value="m">公尺（glTF 標準）</option><option value="mm">毫米（1 單位＝1 mm）</option></select></div>
      <div id="out" class="col"></div><div id="legend" class="row"></div>
      <p class="muted">解碼器移植自 bambu-3mf-to-glb（AGPL-3.0），原為 PrusaSlicer／Bambu Studio 的 TriangleSelector。</p></div>
      <div class="card panel"><div class="viewer" id="cv"><div class="empty">選擇 3MF 後在這裡預覽</div></div></div></div>`);
  v.append(box);
  const viewer = new Viewer($("#cv"));
  $("#f3").onchange = async (e) => {
    $("#out").innerHTML = "";
    for (const f of e.target.files) {
      try {
        const r = MS.parse3MF(await f.arrayBuffer()); MS.placeOnPlate(r.parts);
        const glb = await MS.writeGLB(r.parts, $("#units").value), name = f.name.replace(/\.3mf$/i, "") + ".glb";
        download(name, glb, "model/gltf-binary");
        $("#out").append(h(`<div>✔ ${esc(f.name)} → ${esc(name)}（${(glb.byteLength / 1e6).toFixed(2)} MB）</div>`));
        viewer.setParts(r.parts); $("#cv .empty").style.display = "none";
        $("#legend").innerHTML = Object.entries(r.stats).sort().map(([k, n]) => `<span class="chip" style="background:${r.palette[k - 1] || "#888"};color:#fff;text-shadow:0 0 2px #000">耗材 ${k} · ${n.toLocaleString()} 面</span>`).join("");
      } catch (err) { $("#out").append(h(`<div style="color:var(--bad)">✖ ${esc(f.name)}：${esc(err.message)}</div>`)); }
    }
  };
};

// ---------------------------------------------------------------- 搜尋
S.search = (v, arg) => {
  v.append(h(`<div class="col"><h2>🔎 搜尋現成模型</h2>
    <p class="muted">日常用品先找現成設計：很多人列印、驗證過，通常比自動產生的好。線上版會開啟 MakerWorld 與 Printables 的搜尋頁（網站不允許其他網頁直接查詢）；電腦版可以直接列出結果與下載數。</p>
    <div class="row"><input type="text" id="q" style="flex:1" placeholder="例如：手機架、cable organizer、vase"><button class="btn" id="go">搜尋</button></div>
    <div id="res" class="row"></div>
    <div class="card"><h3>常用搜尋</h3><div class="examples" id="pop"></div></div></div>`));
  const run = (q) => {
    q = translateQuery(q || $("#q").value); if (!q) return toast("請輸入要找的東西", true);
    const L = searchLinks(q);
    $("#res").innerHTML = `<span class="muted">「${esc(q)}」：</span><a class="btn green" target="_blank" rel="noopener" href="${L.makerworld}">MakerWorld ↗</a><a class="btn accent" target="_blank" rel="noopener" href="${L.printables}">Printables ↗</a>`;
  };
  $("#go").onclick = () => run(); $("#q").onkeydown = (e) => { if (e.key === "Enter") run(); };
  for (const x of ["手機架", "理線", "筆筒", "掛鉤", "花瓶", "鑰匙", "杯墊", "工具", "門擋", "名片"]) {
    const b = h(`<button>${x}</button>`); b.onclick = () => { $("#q").value = x; run(x); }; $("#pop").append(b);
  }
  if (arg) { $("#q").value = arg; run(arg); }
};

// ---------------------------------------------------------------- 設定
S.aiset = (v) => {
  const k = store.get("pa_claude_key");
  v.append(h(`<div class="col" style="max-width:760px"><h2>⚙️ 設定</h2>
    <div class="card col"><h3>🤖 AI 代理人（Claude）</h3>
      <p class="muted">沒有金鑰時用免費的本機規則。填入 Claude API 金鑰後使用 ${MODEL}，可以自由描述；費用由您的 Anthropic 帳戶計算。
      金鑰只存在這台裝置的瀏覽器（localStorage），由瀏覽器直接傳給 Anthropic，不經過其他伺服器。共用電腦請不要儲存金鑰。</p>
      <label class="fld">Claude API 金鑰（${k ? "已設定 " + k.slice(0, 7) + "…" + k.slice(-4) : "未設定"}）<input type="password" id="key" placeholder="sk-ant-…（留白＝不變）"></label>
      <div class="row"><button class="btn" id="saveKey">儲存</button><button class="btn outline" id="test">測試連線</button><button class="btn danger" id="clr">清除金鑰</button></div></div>
    <div class="card col"><h3>🖨 預設印表機與耗材</h3><div class="row">
      <select id="pr">${Object.entries(DATA.printers).map(([kk, p]) => `<option value="${kk}" ${kk === ws.printer ? "selected" : ""}>${kk}（${p.volume.join("×")}）</option>`).join("")}</select>
      <select id="mat">${Object.keys(DATA.materials).map((kk) => `<option ${kk === ws.material ? "selected" : ""}>${kk}</option>`).join("")}</select></div></div>
    <div class="card col"><h3>💾 設計庫</h3><p class="muted">設計存在這台裝置的瀏覽器裡。</p>
      <div class="row"><button class="btn outline" id="exp">匯出全部設計（.json）</button><label class="btn outline">匯入<input type="file" id="imp" accept=".json" hidden></label></div></div></div>`));
  $("#saveKey").onclick = () => { const x = $("#key").value.trim(); if (x) { store.set("pa_claude_key", x); toast("已儲存金鑰"); go("aiset"); } };
  $("#clr").onclick = () => { store.set("pa_claude_key", ""); toast("已清除"); go("aiset"); };
  $("#pr").onchange = (e) => { ws.printer = e.target.value; store.set("pa_printer", ws.printer); toast("已設定預設印表機"); };
  $("#mat").onchange = (e) => { ws.material = e.target.value; store.set("pa_material", ws.material); toast("已設定預設耗材"); };
  $("#test").onclick = async () => {
    const key = $("#key").value.trim() || store.get("pa_claude_key"); if (!key) return toast("請先輸入金鑰", true);
    toast("測試中…");
    try {
      const r = await fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers: { "content-type": "application/json", "x-api-key": key,
        "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" },
        body: JSON.stringify({ model: MODEL, max_tokens: 200, output_config: { effort: "low" }, messages: [{ role: "user", content: "用繁體中文回一句：連線成功" }] }) });
      const j = await r.json();
      if (!r.ok) throw new Error(r.status === 401 ? "金鑰無效" : (j.error?.message || r.status));
      toast("Claude 連線成功：" + (j.content.find((b) => b.type === "text")?.text || "").slice(0, 30));
    } catch (e) { toast("連線失敗：" + e.message, true); }
  };
  $("#exp").onclick = async () => {
    const ds = await DB.all();
    const json = JSON.stringify(ds, (k, val) => val instanceof Uint8Array ? { $b64: btoa(Array.from(val, (c) => String.fromCharCode(c)).join("")) } : val);
    download("3D列印設計庫.json", json, "application/json");
  };
  $("#imp").onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const ds = JSON.parse(await f.text(), (k, val) => val && val.$b64 ? Uint8Array.from(atob(val.$b64), (c) => c.charCodeAt(0)) : val);
    for (const d of ds) { delete d.id; await DB.put(d); }
    toast(`已匯入 ${ds.length} 個設計`);
  };
};

// ---------------------------------------------------------------- 語音教學
const audio = new Audio();
function stopVoice() { audio.pause(); clearInterval(audio._t); }
function play(src, onTick) {
  stopVoice(); audio.src = src; audio.play().catch(() => toast("無法播放語音（請先點一下畫面）", true));
  if (onTick) audio._t = setInterval(() => { if (audio.duration) onTick(audio.currentTime / audio.duration); if (audio.ended) clearInterval(audio._t); }, 200);
}
S.help = (v, arg) => {
  let key = DATA.lessons.some((l) => l.key === arg) ? arg : "intro";
  const box = h(`<div class="split" style="grid-template-columns:260px 1fr"><div class="card list" id="les"></div><div class="card col" id="stage"></div></div>`);
  v.append(box);
  const show = (k, auto) => {
    key = k; const L = DATA.lessons.find((l) => l.key === k), i = DATA.lessons.indexOf(L);
    $("#les").innerHTML = DATA.lessons.map((l, n) => `<div class="item ${l.key === k ? "on" : ""}" data-k="${l.key}">${n + 1}. ${l.title}</div>`).join("");
    $("#les").querySelectorAll("[data-k]").forEach((it) => it.onclick = () => show(it.dataset.k, true));
    $("#stage").innerHTML = `<p class="muted">第 ${i + 1} 課，共 ${DATA.lessons.length} 課</p><div class="row"><h2 style="flex:1">${L.title}</h2>
      <button class="btn" id="play">▶ 播放語音教學</button><button class="btn outline" id="stop">■ 停止</button></div>
      <div class="steps">${L.steps.map((s, n) => `<div class="step" data-n="${n}"><div class="n">${n + 1}</div><div>${esc(s.text)}</div>
        ${TITLES[s.page] ? `<a href="#${s.page}" class="btn ghost small">👉 跟著做</a>` : '<span class="muted">（電腦版）</span>'}</div>`).join("")}</div>
      <div class="card" style="background:#F7F9FC;line-height:1.8">${esc(L.voice)}</div>
      <div class="row"><button class="btn outline" id="prev" ${i === 0 ? "disabled" : ""}>‹ 上一課</button><button class="btn" id="next" ${i === DATA.lessons.length - 1 ? "disabled" : ""}>下一課 ›</button></div>`;
    const steps = $("#stage").querySelectorAll(".step");
    $("#play").onclick = () => play(`../voice/${k}.mp3`, (x) => steps.forEach((s, n) => s.classList.toggle("lit", n === Math.min(steps.length - 1, Math.floor(x * steps.length)))));
    $("#stop").onclick = () => { stopVoice(); steps.forEach((s) => s.classList.remove("lit")); };
    $("#prev").onclick = () => show(DATA.lessons[i - 1].key, true); $("#next").onclick = () => show(DATA.lessons[i + 1].key, true);
    if (auto) $("#play").click();
  };
  show(key, false);
};
$("#speakBtn").onclick = () => { if (!audio.paused) return stopVoice(); if (DATA.pages[current]) { play(`../voice/page_${current}.mp3`); toast("🔊 正在播放：" + DATA.pages[current].title); } };
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");

// ====================================================================== 啟動
$("#ver").textContent = "v" + DATA.version;
// iPhone／iPad、Android App：顯示 App 版本，查 GitHub 最新版，有新版就在上方顯示「有新版」
const newer = (a, b) => { const x = a.split(".").map(Number), y = b.split(".").map(Number); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
const APPVER = IOS ? IOS.version : AND ? (AND.getVersion ? AND.getVersion() : "0") : "";
let updAsset = null;
async function checkUpdate(manual) {
  if (!IOS && !AND) return;
  const suffix = IOS ? "ZMSPrintAgent-ios.ipa" : "-android.apk";
  try {
    const r = await fetch(`https://api.github.com/repos/${DATA.repo}/releases/latest`), j = await r.json();
    const latest = (j.tag_name || "").replace(/^v/, ""), asset = (j.assets || []).find((x) => x.name.endsWith(suffix));
    if (latest && asset && newer(latest, APPVER)) {
      updAsset = { url: asset.browser_download_url, ver: latest };
      $("#upd").textContent = `⬆ 有新版 v${latest}`; $("#upd").classList.add("show");
      if (manual) $("#upd").click();
    } else if (manual) toast("已經是最新版 v" + APPVER);
  } catch (e) { if (manual) toast("檢查更新需要網路", true); }
}
if (IOS || AND) {
  document.documentElement.classList.add(IOS ? "ios-app" : "android-app", "ios-app");
  $("#edition").textContent = IOS ? "iPhone／iPad 版" : "Android 版"; $("#ver").textContent = "v" + APPVER;
  $("#upd").onclick = () => {
    if (IOS) { location.href = "https://achir1015.github.io/zms-print-agent/ios/"; return; }
    if (updAsset && confirm(`下載並安裝新版 v${updAsset.ver}（目前 v${APPVER}）？
設計庫與設定都會保留。`)) {
      const r = JSON.parse(AND.installUpdate(updAsset.url, updAsset.ver));
      toast(r.status === "ok" ? "開始下載新版，完成後會跳出安裝畫面（第一次要允許「安裝未知應用程式」）" : "更新失敗：" + r.message, r.status !== "ok");
    }
  };
  $("#chkUpd").style.display = ""; $("#chkUpd").onclick = () => checkUpdate(true);
  setTimeout(() => checkUpdate(false), 2000);
}
// Android 返回鍵：不在首頁就回首頁（回傳 true＝已處理）
window.__zmsBack = () => {
  if ($("#side").classList.contains("open")) { $("#side").classList.remove("open"); return true; }
  if (current !== "home") { location.hash = "home"; return true; }
  return false;
};
(async () => {
  try { await initEngine(); }
  catch (e) { $("#loading p").textContent = "建模引擎載入失敗（瀏覽器需要支援 WebAssembly）：" + e.message; return; }
  $("#loading").remove();
  const [s, a] = decodeURIComponent(location.hash.slice(1)).split(":");
  go(s || "home", a);
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("../sw.js").catch(() => {});
})();

