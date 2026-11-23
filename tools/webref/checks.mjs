import { pathToFileURL } from "node:url";
const app = process.argv[2];
const E = await import(pathToFileURL(app + "/engine.js").href);
const C = await import(pathToFileURL(app + "/checks.js").href);
await E.initEngine({ locateFile: (p) => app + "/lib/" + p });
const out = {};
for (const r of E.RECIPES) {
  const t = Date.now(); const res = E.build(r.id, {});
  const rep = C.check(res.parts, "A1 Mini", "PETG", "functional");
  out[r.id] = { score: rep.score, st: rep.items.map((i) => i.status[0]).join(""), w: rep.weight_g, ms: Date.now() - t };
}
console.log(JSON.stringify(out));
