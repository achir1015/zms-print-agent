"""3D 預覽繪圖（numpy＋Pillow，不需要顯示卡）。

z-buffer 光柵化參考 bambu-studio-ai 的軟體繪圖器（MIT），改成每面一色、用排序取代 ufunc.at（快好幾倍）；
另外加上拖曳旋轉的視角、列印板格線、快速模式（拖曳中用小圖、免超取樣）。
"""
import io
import math

import numpy as np
from PIL import Image, ImageDraw

_CHUNK = 1_500_000


def _rasterize(tri, inv_depth, size):
    """(F,3,2) 螢幕座標三角形 → 每個像素最前面的面編號（-1＝空白），攤平成一維。"""
    x, y = tri[:, :, 0], tri[:, :, 1]
    area = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    x0 = np.clip(np.ceil(x.min(axis=1) - 0.5), 0, size).astype(np.int64)
    x1 = np.clip(np.floor(x.max(axis=1) - 0.5), -1, size - 1).astype(np.int64)
    y0 = np.clip(np.ceil(y.min(axis=1) - 0.5), 0, size).astype(np.int64)
    y1 = np.clip(np.floor(y.max(axis=1) - 0.5), -1, size - 1).astype(np.int64)
    width = np.maximum(x1 - x0 + 1, 0)
    height = np.maximum(y1 - y0 + 1, 0)
    counts = width * height
    live = np.flatnonzero((counts > 0) & (np.abs(area) > 1e-12))
    zbuf = np.zeros(size * size)
    face_buf = np.full(size * size, -1, dtype=np.int64)
    if not len(live):
        return face_buf
    batch = np.cumsum(counts[live]) // _CHUNK
    for faces in np.split(live, np.flatnonzero(np.diff(batch)) + 1):
        n = counts[faces]
        owner = np.repeat(faces, n)
        local = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
        wo = width[owner]
        px = x0[owner] + local % wo
        py = y0[owner] + local // wo
        cx, cy = px + 0.5, py + 0.5
        tx, ty = x[owner], y[owner]
        ar = area[owner]
        w0 = ((tx[:, 1] - cx) * (ty[:, 2] - cy) - (tx[:, 2] - cx) * (ty[:, 1] - cy)) / ar
        w1 = ((tx[:, 2] - cx) * (ty[:, 0] - cy) - (tx[:, 0] - cx) * (ty[:, 2] - cy)) / ar
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        owner, pixel = owner[inside], (py * size + px)[inside]
        idp = inv_depth[owner]
        near = w0[inside] * idp[:, 0] + w1[inside] * idp[:, 1] + w2[inside] * idp[:, 2]
        order = np.lexsort((-near, pixel))
        ps = pixel[order]
        first = np.ones(len(ps), dtype=bool)
        first[1:] = ps[1:] != ps[:-1]
        win = order[first]
        pix, nr = pixel[win], near[win]
        better = nr > zbuf[pix]
        zbuf[pix[better]] = nr[better]
        face_buf[pix[better]] = owner[win][better]
    return face_buf

BASE_RGB = (0.36, 0.61, 0.84)
BG_TOP, BG_BOTTOM = (246, 249, 253), (220, 229, 241)


class Scene:
    """把模型攤平成陣列（一次），之後從任何角度畫。"""

    def __init__(self, vertices, faces, face_rgb=None, plate=None):
        self.v = np.asarray(vertices, dtype=np.float64)
        self.f = np.asarray(faces, dtype=np.int64)
        n = len(self.f)
        if face_rgb is None:
            self.rgb = np.broadcast_to(np.array(BASE_RGB), (n, 3)).copy()
        else:
            c = np.asarray(face_rgb, dtype=np.float64)
            self.rgb = c / 255.0 if c.size and c.max() > 1.0 else c
        if n:
            # 光柵化以每個三角形的外框為單位：細長的大三角形（平板、方塊）會非常慢 → 先切小
            span = float(np.linalg.norm(self.v.max(axis=0) - self.v.min(axis=0))) or 1.0
            try:
                import trimesh
                v2, f2, idx = trimesh.remesh.subdivide_to_size(self.v, self.f, max_edge=span / 14, max_iter=8,
                                                               return_index=True)
                if len(f2) <= 400000:
                    self.v, self.f, self.rgb = np.asarray(v2), np.asarray(f2), self.rgb[idx]
            except Exception:
                pass
        tri = self.v[self.f]
        nm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(nm, axis=1, keepdims=True)
        self.normals = nm / np.where(ln == 0, 1.0, ln)
        self.centroids = tri.mean(axis=1)
        if len(self.v):
            lo, hi = self.v.min(axis=0), self.v.max(axis=0)
        else:
            lo, hi = np.zeros(3), np.ones(3)
        self.lo, self.hi = lo, hi
        self.center = (lo + hi) / 2
        self.radius = max(float(np.linalg.norm(hi - lo)) / 2, 1.0)
        self.plate = plate            # (寬, 深) mm：畫列印板格線

    # ------------------------------------------------------------------ 相機
    def _camera(self, yaw, pitch):
        yaw, pitch = math.radians(yaw), math.radians(pitch)
        back = np.array([math.cos(pitch) * math.sin(yaw), -math.cos(pitch) * math.cos(yaw), math.sin(pitch)])
        up0 = np.array([0.0, 0.0, 1.0])
        right = np.cross(up0, back)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0, 0])
        right /= np.linalg.norm(right)
        up = np.cross(back, right)
        return right, up, back

    def draw(self, yaw=-35.0, pitch=28.0, zoom=1.0, size=520, fast=False, width=None, height=None):
        """回傳 PNG bytes。"""
        w = width or size
        h = height or size
        ss = 1 if fast else 2
        W, H = w * ss, h * ss
        right, up, back = self._camera(yaw, pitch)
        tan_half = 0.36
        dist = self.radius / tan_half / 0.9 / max(zoom, 0.05) * max(1.0, H / W)
        eye = self.center + back * dist
        img = _background(W, H)
        scale = (min(W, H) / 2) / tan_half

        def project(pts):
            rel = pts - eye
            depth = -(rel @ back)
            depth = np.where(depth < 1e-3, 1e-3, depth)
            return np.stack([W / 2 + (rel @ right) / depth * scale, H / 2 - (rel @ up) / depth * scale], axis=1), depth

        if self.plate:
            self._draw_plate(img, project, ss)
        if len(self.f):
            scr, depth = project(self.v)
            # _rasterize 要正方形畫布：取較大邊，再裁切
            S = max(W, H)
            off = np.array([(S - W) / 2, (S - H) / 2])
            face_buf = _rasterize(scr[self.f] + off, 1.0 / depth[self.f], S)
            face_buf = face_buf.reshape(S, S)[int(off[1]):int(off[1]) + H, int(off[0]):int(off[0]) + W].reshape(-1)
            covered = np.flatnonzero(face_buf >= 0)
            hit = face_buf[covered]
            shade = self._shade(eye, right, up, back)[hit]
            col = np.minimum(self.rgb[hit] * shade[:, None], 1.0)
            arr = np.array(img).reshape(-1, 3)
            arr[covered] = np.round(col * 255).astype(np.uint8)
            img = Image.fromarray(arr.reshape(H, W, 3), "RGB")
        if ss > 1:
            img = img.resize((w, h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=False)
        return buf.getvalue()

    def _shade(self, eye, right, up, back):
        towards = (self.normals * (eye - self.centroids)).sum(axis=1)
        n = self.normals * np.where(towards < 0, -1.0, 1.0)[:, None]
        key = _unit(-0.45 * right + 0.65 * up + 0.6 * back)
        fill = _unit(0.7 * right + 0.1 * up + 0.7 * back)
        return 0.34 + 0.58 * np.maximum(n @ key, 0) + 0.22 * np.maximum(n @ fill, 0) + 0.10 * np.maximum(n[:, 2], 0)

    def _draw_plate(self, img, project, ss):
        """列印板格線：只畫模型周圍（太遠的格線投影後座標極大，畫起來很慢），並裁切到畫布內。"""
        pw, pd = self.plate
        span = float(max(self.hi[0] - self.lo[0], self.hi[1] - self.lo[1]))
        step = 10.0 if span < 150 else 20.0
        hx = min(pw / 2, math.ceil((span * 0.9 + 20) / step) * step)
        hy = min(pd / 2, math.ceil((span * 0.9 + 20) / step) * step)
        W, H = img.size
        d = ImageDraw.Draw(img)
        corners = np.array([[-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0]], dtype=float)
        pts, dep = project(corners)
        if (dep > 1).all() and np.abs(pts).max() < 20000:
            d.polygon([tuple(p) for p in pts], fill=(232, 236, 242))
        lines = [((x, -hy), (x, hy), abs(x) % (step * 5) < 1e-6) for x in np.arange(-hx, hx + 0.01, step)]
        lines += [((-hx, y), (hx, y), abs(y) % (step * 5) < 1e-6) for y in np.arange(-hy, hy + 0.01, step)]
        for a, b, major in lines:
            q, dep = project(np.array([[a[0], a[1], 0], [b[0], b[1], 0]], dtype=float))
            if (dep <= 1).any():
                continue
            seg = _clip(q[0], q[1], W, H)
            if seg:
                d.line(seg, fill=(170, 182, 200) if major else (198, 207, 220), width=ss)


def _clip(p, q, W, H):
    """Liang–Barsky 線段裁切到畫布。"""
    x0, y0 = float(p[0]), float(p[1])
    dx, dy = float(q[0]) - x0, float(q[1]) - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0), (dx, W - 1 - x0), (-dy, y0), (dy, H - 1 - y0)):
        if pp == 0:
            if qq < 0:
                return None
            continue
        r = qq / pp
        if pp < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return [(x0 + dx * t0, y0 + dy * t0), (x0 + dx * t1, y0 + dy * t1)]


def _unit(v):
    return v / np.linalg.norm(v)


_bg_cache = {}


def _background(w, h):
    key = (w, h)
    if key not in _bg_cache:
        t = np.linspace(0, 1, h)[:, None]
        top, bot = np.array(BG_TOP), np.array(BG_BOTTOM)
        rows = (top * (1 - t) + bot * t).astype(np.uint8)
        _bg_cache[key] = Image.fromarray(np.repeat(rows[:, None, :], w, axis=1).reshape(h, w, 3), "RGB")
    return _bg_cache[key].copy()


def decimate(vertices, faces, face_rgb=None, target=60000):
    """預覽用的快速減面（頂點格點合併）：只影響畫面，不改模型檔。"""
    v, f = np.asarray(vertices), np.asarray(faces)
    if len(f) <= target:
        return v, f, face_rgb
    lo, hi = v.min(axis=0), v.max(axis=0)
    span = float((hi - lo).max()) or 1.0
    cells = max(int(math.sqrt(target) * 1.6), 40)
    for _ in range(6):
        q = np.floor((v - lo) / span * cells).astype(np.int64)
        key = q[:, 0] * cells * cells * 4 + q[:, 1] * cells * 2 + q[:, 2]
        uniq, inv = np.unique(key, return_inverse=True)
        nf = inv[f]
        ok = (nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])
        if ok.sum() <= target * 1.15 or cells < 30:
            break
        cells = int(cells * 0.8)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv, v)
    cnt = np.bincount(inv, minlength=len(uniq))[:, None]
    nv = sums / np.maximum(cnt, 1)
    rgb = None if face_rgb is None else np.asarray(face_rgb)[ok]
    return nv, nf[ok], rgb
