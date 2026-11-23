import { pathToFileURL } from "node:url";
const app = process.argv[2];
const E = await import(pathToFileURL(app + "/engine.js").href);
await E.initEngine({ locateFile: (p) => app + "/lib/" + p });
const out = {};
for (const r of E.RECIPES) {
  const t = Date.now();
  const res = E.build(r.id, {});
  let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  for (const p of res.parts) for (let i = 0; i < p.pos.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p.pos[i + k]); hi[k] = Math.max(hi[k], p.pos[i + k]); }
  out[r.id] = { vol: res.parts.reduce((s, p) => s + p.volume, 0) / 1000, size: hi.map((h, k) => +(h - lo[k]).toFixed(2)), tris: res.parts.reduce((s, p) => s + p.idx.length / 3, 0), ms: Date.now() - t };
}
console.log(JSON.stringify(out));
