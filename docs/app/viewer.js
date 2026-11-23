// 3D 預覽（three.js）：拖曳旋轉、滾輪或兩指縮放、列印板格線；每個面的顏色（多色 3MF）或每個零件一種顏色。
import * as THREE from "./lib/three.module.min.js";
import { OrbitControls } from "./lib/jsm/controls/OrbitControls.js";
import { PART_COLORS, bounds } from "./mesh.js";

export class Viewer {
  constructor(el) {
    this.el = el;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xeef3f9);
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(-1, -1.5, 2); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6); fill.position.set(1.5, 1, 0.8); this.scene.add(fill);
    this.group = new THREE.Group(); this.scene.add(this.group);
    this.grid = null;
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
    const loop = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); this._raf = requestAnimationFrame(loop); };
    loop();
  }
  resize() {
    const w = this.el.clientWidth || 400, h = this.el.clientHeight || 300;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%"; this.renderer.domElement.style.height = "100%";
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }
  setParts(parts, keepView = false) {
    this.group.clear();
    if (!parts || !parts.length) return;
    parts.forEach((p, n) => {
      const nf = p.idx.length / 3, pos = new Float32Array(nf * 9), col = new Float32Array(nf * 9);
      const base = PART_COLORS[n % PART_COLORS.length], c = new THREE.Color();
      for (let f = 0; f < nf; f++) {
        const rgb = p.rgb ? [p.rgb[f * 3], p.rgb[f * 3 + 1], p.rgb[f * 3 + 2]] : (parts.length > 1 ? base : PART_COLORS[0]);
        c.setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
        for (let k = 0; k < 3; k++) {
          const v = p.idx[f * 3 + k] * 3;
          pos.set([p.pos[v], p.pos[v + 1], p.pos[v + 2]], f * 9 + k * 3);
          col.set([c.r, c.g, c.b], f * 9 + k * 3);
        }
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      g.computeVertexNormals();
      this.group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.65, metalness: 0, flatShading: true, side: THREE.DoubleSide })));
    });
    const [lo, hi] = bounds(parts), size = Math.max(...hi.map((h, k) => h - lo[k]));
    if (this.grid) this.scene.remove(this.grid);
    const step = size < 150 ? 10 : 20, half = Math.ceil((size * 0.9 + 20) / step) * step;
    this.grid = new THREE.GridHelper(half * 2, half * 2 / step, 0xaab6c8, 0xc6cfdc);
    this.grid.rotation.x = Math.PI / 2; this.grid.position.z = lo[2] - 0.01;
    this.scene.add(this.grid);
    if (!keepView || !this._box) this.fit(lo, hi);
  }
  fit(lo, hi, dir = [-0.55, -0.8, 0.55]) {
    lo = lo || bounds(this._parts || [])[0];
    const c = new THREE.Vector3((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
    const r = Math.max(new THREE.Vector3(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]).length() / 2, 5);
    const d = r / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * 1.05;
    const v = new THREE.Vector3(...dir).normalize();
    this.camera.position.copy(c).addScaledVector(v, d);
    this.camera.near = d / 100; this.camera.far = d * 20; this.camera.updateProjectionMatrix();
    this.controls.target.copy(c); this.controls.update();
    this._box = [lo, hi];
  }
  view(kind) {
    if (!this._box) return;
    const dirs = { iso: [-0.55, -0.8, 0.55], front: [0, -1, 0.05], side: [-1, 0, 0.05], top: [0, -0.001, 1] };
    this.fit(this._box[0], this._box[1], dirs[kind] || dirs.iso);
  }
  snapshot(size = 256) {
    this.renderer.render(this.scene, this.camera);
    const src = this.renderer.domElement, cv = document.createElement("canvas");
    const s = Math.min(src.width, src.height); cv.width = cv.height = size;
    cv.getContext("2d").drawImage(src, (src.width - s) / 2, (src.height - s) / 2, s, s, 0, 0, size, size);
    return cv.toDataURL("image/png");
  }
}
