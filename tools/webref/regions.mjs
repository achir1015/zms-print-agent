// 線上版分區編輯（docs/app/regions.js）的參考輸出：tests/test_web_parity.py 和電腦版比對。
import { pathToFileURL } from "node:url";
import fs from "node:fs";
const app = process.argv[2], files = process.argv.slice(3);
const E = await import(pathToFileURL(app + "/engine.js").href);
await E.initEngine({ locateFile: (p) => app + "/lib/" + p });
const R = await import(pathToFileURL(app + "/regions.js").href);
const size = (parts) => { let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9]; for (const p of parts) for (let i = 0; i < p.pos.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p.pos[i + k]); hi[k] = Math.max(hi[k], p.pos[i + k]); } return hi.map((h, k) => +(h - lo[k]).toFixed(2)); };
const out = { files: {} };
for (const f of files) {
  const r = R.loadGrouped(f, fs.readFileSync(f));
  out.files[f] = { names: R.regions(r.parts).map((x) => x.name), size: size(r.parts), faces: r.parts[0].idx.length / 3 };
}
const box = E.build("block", { width: 40, depth: 40, height: 20 }).parts, s = R.segment(box, "surface", 6);
const ops = { surface: R.regions(s).length };
ops.hole = size(R.edit(s, "hole", null, { at: [0, 0, 10], diameter: 8 })[0]);
ops.cut = size(R.edit(s, "cut", null, { axis: "z", value: 10, keep: "both" })[0]);
ops.boss = size(R.edit(s, "boss", [2], { diameter: 6, height: 5 })[0]);
ops.explode0 = size(R.explodeView(s, 0));
out.ops = ops;
console.log(JSON.stringify(out));
