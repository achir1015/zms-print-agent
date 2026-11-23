import { pathToFileURL } from "node:url"; import fs from "node:fs";
const app = process.argv[2];
const M = await import(pathToFileURL(app + "/mesh.js").href);
for (const f of process.argv.slice(3)) {
  const r = M.parse3MF(fs.readFileSync(f));
  console.log(f.split(/[\/]/).pop(), r.bambu, r.stats, r.palette.slice(0, 3), r.parts.map((p) => [p.name, p.idx.length / 3]));
  const out = M.write3MF(r.parts, "x"); const back = M.parse3MF(out); console.log("  roundtrip tris", back.parts.reduce((s, p) => s + p.idx.length / 3, 0), M.bounds(back.parts).map((v) => v.map((x) => +x.toFixed(1))));
}
