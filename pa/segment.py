"""模型分區與逐區修改：匯入現成的模型（STL／OBJ／FBX／MA…）後，把它分成幾個「區塊」，再一塊一塊改。

分區方法：
* groups   原檔的材質／群組（FBX、MA、OBJ 的 Body、screen、button…）；多零件模型＝每個零件一區
* bodies   互不相連的實體
* surface  依表面轉折（相鄰面夾角超過門檻就分開），再把太小的併到鄰居，直到不超過目標數量
* zones    空間分塊：依位置與朝向分成 N 塊（一體成形的曲面模型，例如槍頭、握把、扳機）
* height   由下往上切成幾層（同高度的部位一起改）

區塊修改：刪除、只保留、移動、縮放、旋轉、上色（指定耗材顏色 → Bambu 多色 3MF）、改名、合併、
沿平面切開、鑽孔（圓孔／方孔）、加凸台（圓柱／方塊）。鑽孔、加凸台用 manifold3d 布林運算，需要封閉實體。
修改後每個面仍記得自己屬於哪一區（布林運算後依最近的原始面推回去）。
"""
import math

import numpy as np
import trimesh

from . import mesh3d

PALETTE = ["#5B9BD5", "#F4B142", "#70BE7C", "#E57373", "#AB86D6", "#60C4C4", "#F28DB2", "#A1887F",
           "#9CCC65", "#FFB74D", "#4DB6AC", "#7986CB", "#E0E0E0", "#BA68C8", "#4FC3F7", "#DCE775"]
COLOR_NAMES = {"紅": "#E53935", "紅色": "#E53935", "橙": "#FB8C00", "橘": "#FB8C00", "黃": "#FDD835", "綠": "#43A047",
               "藍": "#1E88E5", "淺藍": "#4FC3F7", "深藍": "#1A237E", "紫": "#8E24AA", "粉紅": "#F06292", "黑": "#212121",
               "白": "#FAFAFA", "灰": "#9E9E9E", "銀": "#BDBDBD", "金": "#D4AF37", "咖啡": "#6D4C41", "棕": "#6D4C41",
               "透明": "#E3F2FD", "red": "#E53935", "orange": "#FB8C00", "yellow": "#FDD835", "green": "#43A047",
               "blue": "#1E88E5", "purple": "#8E24AA", "pink": "#F06292", "black": "#212121", "white": "#FAFAFA",
               "gray": "#9E9E9E", "grey": "#9E9E9E"}
METHODS = {"auto": "自動（有材質群組就用群組，否則依表面或空間分塊）", "groups": "原檔材質／群組",
           "bodies": "互不相連的實體", "surface": "表面轉折", "zones": "空間分塊（適合一體成形的曲面模型）",
           "height": "由下往上分層"}


class EditError(ValueError):
    pass


def hexrgb(h):
    h = str(h).strip()
    if h in COLOR_NAMES:
        h = COLOR_NAMES[h]
    h = h.lstrip("#")
    if len(h) != 6:
        raise EditError("顏色格式要像 #FF0000，或用中文：紅、橙、黃、綠、藍、紫、粉紅、黑、白、灰…")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ====================================================================== 合成單一網格（每個面帶區塊編號）
def to_single(model):
    """所有零件合併成一個網格（相同位置的頂點焊接起來 → 能判斷封閉），每個面帶區塊編號。"""
    if len(model.parts) == 1 and getattr(model.parts[0], "labels", None) is not None:
        return model
    vs, fs, labels, names, rgbs, off = [], [], [], [], [], 0
    for i, p in enumerate(model.parts):
        m = p.mesh
        vs.append(np.asarray(m.vertices))
        fs.append(np.asarray(m.faces) + off)
        off += len(m.vertices)
        if getattr(p, "labels", None) is not None:
            base = len(names)
            names += list(p.label_names)
            labels.append(np.asarray(p.labels) + base)
        else:
            labels.append(np.full(len(m.faces), len(names)))
            names.append(p.name)
        rgbs.append(p.face_rgb if p.face_rgb is not None else None)
    mesh = trimesh.Trimesh(np.vstack(vs), np.vstack(fs), process=False)
    mesh.merge_vertices()
    lab = np.concatenate(labels)
    rgb = None
    if any(r is not None for r in rgbs):
        rgb = np.vstack([r if r is not None else np.tile(np.array(mesh3d.PART_COLORS[0], np.uint8), (len(p.mesh.faces), 1))
                         for r, p in zip(rgbs, model.parts)])
    return _make(mesh, lab, names, model, rgb=rgb)


def _make(mesh, labels, names, like=None, colors=None, rgb=None):
    """重新編號（去掉沒有面的區塊）→ 單一零件的 Model。colors：{區塊名: #hex}（使用者指定的耗材顏色）。"""
    labels = np.asarray(labels, dtype=np.int64)
    used = [i for i in range(len(names)) if np.any(labels == i)]
    remap = {o: n for n, o in enumerate(used)}
    lab = np.array([remap[x] for x in labels], dtype=np.int64) if len(labels) else labels
    names = [names[i] for i in used]
    colors = dict(colors if colors is not None else getattr(like, "region_colors", {}) or {})
    colors = {k: v for k, v in colors.items() if k in names}
    part = mesh3d.Part("模型", mesh, rgb)
    part.labels, part.label_names = lab, names
    m = mesh3d.Model([part], getattr(like, "source", ""), list(getattr(like, "notes", []) or []))
    m.region_colors = colors
    _paint(m)
    return m


def _paint(model):
    """畫面顏色：使用者指定的耗材顏色優先，其餘用分區色盤。"""
    p = model.parts[0]
    cols = np.array([hexrgb(model.region_colors.get(n) or PALETTE[i % len(PALETTE)]) for i, n in enumerate(p.label_names)],
                    dtype=np.uint8)
    p.face_rgb = cols[p.labels] if len(p.labels) else None
    model.palette = [model.region_colors[n] for n in p.label_names if n in model.region_colors]


def has_regions(model):
    return len(model.parts) == 1 and getattr(model.parts[0], "labels", None) is not None


# ====================================================================== 分區
def segment(model, method="auto", target=8, angle=30.0, layers=4):
    single = to_single(model)
    p = single.parts[0]
    mesh, lab, names = p.mesh, p.labels, list(p.label_names)
    auto = method == "auto"
    if auto:
        method = "groups" if len(names) > 1 else ("bodies" if mesh.body_count > 1 else "surface")
    if method == "groups":
        if len(names) <= 1:
            raise EditError("這個檔案沒有材質或群組資料，請改用「表面轉折」或「分層」")
        new_lab, new_names = lab, names
    elif method == "bodies":
        comp = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
        order = np.argsort([-mesh.area_faces[comp == c].sum() for c in range(comp.max() + 1)])
        rank = np.empty_like(order)
        rank[order] = np.arange(len(order))
        new_lab = rank[comp]
        new_names = ["實體 %d" % (i + 1) for i in range(len(order))]
    elif method == "surface":
        new_lab = _surface_regions(mesh, target, angle)
        new_names = None
    elif method == "zones":
        new_lab = _zones(mesh, target)
        new_names = None
    elif method == "height":
        z = mesh.triangles_center[:, 2]
        lo, hi = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
        n = max(2, min(int(layers), 12))
        new_lab = np.minimum(((z - lo) / max(hi - lo, 1e-6) * n).astype(np.int64), n - 1)
        step = (hi - lo) / n
        new_names = ["第 %d 層（%.0f～%.0f mm）" % (i + 1, lo + i * step, lo + (i + 1) * step) for i in range(n)]
    else:
        raise EditError("沒有這種分區方法：%s" % method)
    if auto and method == "surface":
        a = np.bincount(new_lab, weights=mesh.area_faces)
        if len(a) < 3 or a.max() > 0.8 * a.sum():        # 一體成形的曲面：表面轉折分不出部位 → 改用空間分塊
            new_lab = _zones(mesh, target)
    if new_names is None:
        new_names = _describe(mesh, new_lab)
    return _make(mesh, new_lab, new_names, single, colors={})


def _surface_regions(mesh, target, angle):
    """表面轉折分區：夾角小於門檻的相鄰面連在一起；太小的區塊併到共用邊最長的鄰居，直到不超過 target 個。"""
    adj = mesh.face_adjacency
    ang = np.degrees(mesh.face_adjacency_angles)
    keep = adj[ang < angle]
    lab = trimesh.graph.connected_component_labels(keep, node_count=len(mesh.faces))
    area = mesh.area_faces
    total = float(area.sum()) or 1.0
    # 相鄰區塊之間的共用邊長
    edge_len = np.linalg.norm(mesh.vertices[mesh.face_adjacency_edges[:, 0]] - mesh.vertices[mesh.face_adjacency_edges[:, 1]], axis=1)
    target = max(2, int(target))
    for _ in range(200):
        n = lab.max() + 1
        rarea = np.bincount(lab, weights=area, minlength=n)
        alive = np.flatnonzero(rarea > 0)
        if len(alive) <= target and rarea[alive].min() >= total * 0.01:
            break
        small = alive[np.argmin(rarea[alive])]
        la, lb = lab[adj[:, 0]], lab[adj[:, 1]]
        m = (la == small) ^ (lb == small)
        if not m.any():                        # 孤立的小實體：併到最大的區塊
            lab[lab == small] = alive[np.argmax(rarea[alive])]
            continue
        other = np.where(la[m] == small, lb[m], la[m])
        shared = np.bincount(other, weights=edge_len[m], minlength=n)
        lab[lab == small] = int(np.argmax(shared))
    # 依面積由大到小重新編號
    uniq = np.unique(lab)
    rarea = np.array([area[lab == u].sum() for u in uniq])
    order = uniq[np.argsort(-rarea)]
    remap = {int(o): i for i, o in enumerate(order)}
    return np.array([remap[int(x)] for x in lab], dtype=np.int64)


def _zones(mesh, target):
    """空間分塊：面的中心位置（主）＋法線（次）做加權 k-means，再把每塊裡不相連的碎片併到鄰居。"""
    from scipy.cluster.vq import kmeans2
    k = max(2, min(int(target), 16))
    c = mesh.triangles_center
    size = np.maximum(mesh.extents, 1e-6)
    feat = np.hstack([(c - mesh.bounds[0]) / size.max(), mesh.face_normals * 0.15])
    rng = np.random.default_rng(7)
    # 面積加權：依面積抽樣初始中心
    pick = rng.choice(len(c), size=min(len(c), 4000), replace=False, p=mesh.area_faces / mesh.area_faces.sum())
    cent, _ = kmeans2(feat[pick], k, minit="++", seed=7)
    d = ((feat[:, None, :] - cent[None, :, :]) ** 2).sum(-1)
    lab = d.argmin(1)
    # 連通：每塊只留最大的連通片，其他碎片併到共用邊最多的鄰居
    adj = mesh.face_adjacency
    for _ in range(3):
        same = adj[lab[adj[:, 0]] == lab[adj[:, 1]]]
        comp = trimesh.graph.connected_component_labels(same, node_count=len(lab))
        area = np.bincount(comp, weights=mesh.area_faces)
        best = {}
        for ci in np.unique(comp):
            L = lab[np.flatnonzero(comp == ci)[0]]
            if L not in best or area[ci] > area[best[L]]:
                best[L] = ci
        stray = ~np.isin(comp, list(best.values()))
        if not stray.any():
            break
        for f in np.flatnonzero(stray):
            nb = np.concatenate([adj[adj[:, 0] == f, 1], adj[adj[:, 1] == f, 0]])
            nb = nb[~stray[nb]] if (~stray[nb]).any() else nb
            if len(nb):
                lab[f] = np.bincount(lab[nb]).argmax()
    uniq = np.unique(lab)
    area = np.array([mesh.area_faces[lab == u].sum() for u in uniq])
    order = uniq[np.argsort(-area)]
    remap = {int(o): i for i, o in enumerate(order)}
    return np.array([remap[int(x)] for x in lab], dtype=np.int64)


def _describe(mesh, lab):
    """自動命名：依位置（上／下／前／後／左／右）與朝向。"""
    lo, hi = mesh.bounds
    c0 = (lo + hi) / 2
    size = np.maximum(hi - lo, 1e-6)
    names = []
    for i in range(int(lab.max()) + 1):
        f = lab == i
        if not f.any():
            names.append("區塊 %d" % (i + 1))
            continue
        a = mesh.area_faces[f]
        c = (mesh.triangles_center[f] * a[:, None]).sum(0) / max(a.sum(), 1e-9)
        nrm = (mesh.face_normals[f] * a[:, None]).sum(0)
        nl = np.linalg.norm(nrm)
        rel = (c - c0) / size
        where = []
        if rel[2] > 0.25:
            where.append("上")
        elif rel[2] < -0.25:
            where.append("下")
        if rel[1] < -0.25:
            where.append("前")
        elif rel[1] > 0.25:
            where.append("後")
        if rel[0] < -0.25:
            where.append("左")
        elif rel[0] > 0.25:
            where.append("右")
        face = ""
        if nl > a.sum() * 0.6:                 # 大致朝同一方向的面
            d = nrm / nl
            k = int(np.argmax(np.abs(d)))
            face = {(0, 1): "右側面", (0, -1): "左側面", (1, 1): "背面", (1, -1): "正面", (2, 1): "頂面", (2, -1): "底面"}[
                (k, 1 if d[k] > 0 else -1)]
        names.append("區塊 %d %s%s" % (i + 1, "".join(where) or "中", face))
    return names


def regions(model):
    """每個區塊的資訊（給畫面與 AI 代理人）。"""
    if not has_regions(model):
        return []
    p = model.parts[0]
    mesh = p.mesh
    out = []
    for i, n in enumerate(p.label_names):
        f = p.labels == i
        tri = mesh.triangles[f]
        lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
        out.append({"id": i + 1, "name": n, "faces": int(f.sum()), "area_cm2": round(float(mesh.area_faces[f].sum()) / 100, 2),
                    "size_mm": [round(float(x), 1) for x in hi - lo], "center_mm": [round(float(x), 1) for x in (lo + hi) / 2],
                    "color": model.region_colors.get(n) or PALETTE[i % len(PALETTE)],
                    "filament": n in model.region_colors})
    return out


# ====================================================================== 區塊修改
def _ids(model, ids):
    p = model.parts[0]
    if isinstance(ids, (int, np.integer, str)):
        ids = [ids]
    out = []
    for x in ids or []:
        if isinstance(x, str) and not x.strip().isdigit():
            exact = [i for i, n in enumerate(p.label_names) if n == x.strip()]
            hit = exact or [i for i, n in enumerate(p.label_names) if x.strip() in n]
            if not hit:
                raise EditError("找不到區塊「%s」" % x)
            out += hit
        else:
            k = int(x) - 1
            if not 0 <= k < len(p.label_names):
                raise EditError("沒有第 %s 區（目前有 %d 區）" % (x, len(p.label_names)))
            out.append(k)
    if not out:
        raise EditError("請指定要修改的區塊")
    return sorted(set(out))


def _need(model):
    if not has_regions(model):
        raise EditError("請先分區")
    return model.parts[0]


def edit(model, op, ids=None, **kw):
    """回傳 (新模型, 說明文字)。op：delete keep move scale rotate color uncolor rename merge cut hole boss"""
    p = _need(model)
    mesh, lab, names = p.mesh, p.labels, list(p.label_names)
    colors = dict(model.region_colors)
    if op in ("cut", "hole", "boss"):
        return globals()["_" + op](model, ids, **kw)
    sel = _ids(model, ids)
    which = "、".join("%d" % (i + 1) for i in sel)
    fmask = np.isin(lab, sel)
    if op in ("delete", "keep"):
        keep = ~fmask if op == "delete" else fmask
        if not keep.any():
            raise EditError("不能把全部區塊都刪掉")
        m2 = mesh.submesh([np.flatnonzero(keep)], append=True)
        new = _make(m2, lab[keep], names, model, colors)
        return new, ("已刪除第 %s 區" if op == "delete" else "只保留第 %s 區") % which
    if op in ("move", "scale", "rotate"):
        v = mesh.vertices.copy()
        vid = np.unique(mesh.faces[fmask])
        pts = v[vid]
        c = (pts.min(0) + pts.max(0)) / 2
        if op == "move":
            d = np.array([kw.get("dx", 0), kw.get("dy", 0), kw.get("dz", 0)], dtype=float)
            v[vid] = pts + d
            msg = "第 %s 區移動 (%g, %g, %g) mm" % (which, *d)
        elif op == "scale":
            f = kw.get("factor")
            s = np.array([kw.get("sx") or f or 1, kw.get("sy") or f or 1, kw.get("sz") or f or 1], dtype=float)
            if (s <= 0).any() or (s > 20).any():
                raise EditError("縮放倍數要在 0～20 之間")
            v[vid] = (pts - c) * s + c
            msg = "第 %s 區縮放 ×%s" % (which, "×".join("%g" % x for x in s) if len(set(s)) > 1 else "%g" % s[0])
        else:
            ax = {"x": 0, "y": 1, "z": 2}[str(kw.get("axis", "z")).lower()]
            a = math.radians(float(kw.get("degrees", 90)))
            R = np.eye(3)
            i, j = [(1, 2), (2, 0), (0, 1)][ax]
            R[i, i], R[i, j], R[j, i], R[j, j] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
            v[vid] = (pts - c) @ R.T + c
            msg = "第 %s 區繞 %s 軸旋轉 %g°" % (which, "XYZ"[ax], kw.get("degrees", 90))
        if len(sel) < len(names) and np.isin(lab, sel, invert=True).any():
            msg += "（和相鄰區塊共用的邊會跟著拉動）"
        m2 = trimesh.Trimesh(v, mesh.faces.copy(), process=False)
        return _make(m2, lab, names, model, colors), msg
    if op in ("color", "uncolor"):
        for i in sel:
            if op == "color":
                h = kw.get("color", "")
                hexrgb(h)
                colors[names[i]] = COLOR_NAMES.get(h, h if h.startswith("#") else "#" + h).upper()
            else:
                colors.pop(names[i], None)
        new = _make(mesh, lab, names, model, colors)
        return new, ("第 %s 區改成 %s（會變成 Bambu 多色 3MF 的耗材）" % (which, kw.get("color")) if op == "color"
                     else "第 %s 區取消指定顏色" % which)
    if op == "rename":
        nm = str(kw.get("name") or "").strip()[:30]
        if not nm or len(sel) != 1:
            raise EditError("改名一次指定一個區塊與新名稱")
        old = names[sel[0]]
        names[sel[0]] = nm
        if old in colors:
            colors[nm] = colors.pop(old)
        return _make(mesh, lab, names, model, colors), "第 %s 區改名為「%s」" % (which, nm)
    if op == "merge":
        if len(sel) < 2:
            raise EditError("合併要指定兩個以上的區塊")
        lab2 = lab.copy()
        lab2[np.isin(lab, sel)] = sel[0]
        return _make(mesh, lab2, names, model, colors), "已把第 %s 區合併成一區" % which
    raise EditError("沒有這種修改：%s" % op)


def _cut(model, ids=None, axis="z", value=None, keep="both", gap=10.0, **kw):
    """沿平面切開（axis＝x/y/z，value＝座標 mm；不給就切在正中間）。keep：below／above／both（兩半分開擺放）。"""
    p = model.parts[0]
    mesh, lab, names = p.mesh, p.labels, list(p.label_names)
    ax = {"x": 0, "y": 1, "z": 2}[str(axis).lower()]
    lo, hi = mesh.bounds
    val = float(value) if value is not None else float((lo[ax] + hi[ax]) / 2)
    if not lo[ax] < val < hi[ax]:
        raise EditError("切面 %s=%g 不在模型範圍內（%.1f～%.1f mm）" % ("XYZ"[ax], val, lo[ax], hi[ax]))
    n = np.zeros(3)
    n[ax] = 1.0
    o = np.zeros(3)
    o[ax] = val
    pieces = []
    for side, sign in (("below", -1), ("above", 1)):
        if keep not in ("both", side):
            continue
        part = trimesh.intersections.slice_mesh_plane(mesh, n * sign, o, cap=mesh.is_watertight)
        if part is None or not len(part.faces):
            continue
        # 切面（蓋子）沒有原本的區塊：依最近的原始面推回去
        plab = _relabel(mesh, lab, part)
        pieces.append((part, plab, sign))
    if not pieces:
        raise EditError("切開後沒有留下任何東西")
    if keep == "both" and len(pieces) == 2:
        # 上半部翻面平放在下半部旁邊，兩個都能直接列印
        (a, la, _), (b, lb, _) = pieces
        b = b.copy()
        if ax == 2:
            b.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
        a = a.copy()
        a.apply_translation([0, 0, -a.bounds[0][2]])
        b.apply_translation([0, 0, -b.bounds[0][2]])
        b.apply_translation([a.bounds[1][0] - b.bounds[0][0] + gap, 0, 0])
        m2 = trimesh.util.concatenate([a, b])
        lab2 = np.concatenate([la, lb])
        msg = "沿 %s=%g mm 切成兩半（上半部翻面放在旁邊，兩塊都可以直接列印）" % ("XYZ"[ax], val)
    else:
        m2, lab2 = pieces[0][0], pieces[0][1]
        msg = "沿 %s=%g mm 切開，只保留%s半部" % ("XYZ"[ax], val, "下" if keep == "below" else "上")
    m2.apply_translation([0, 0, -m2.bounds[0][2]])
    return _make(m2, lab2, names, model), msg


def _relabel(old_mesh, old_lab, new_mesh):
    """新網格每個面 → 最近的原始面的區塊（布林運算、切開後保留分區）。"""
    from scipy.spatial import cKDTree
    tree = cKDTree(old_mesh.triangles_center)
    _, idx = tree.query(new_mesh.triangles_center)
    return np.asarray(old_lab)[idx]


def _bool(model, prim, subtract, msg):
    import manifold3d as mf
    p = model.parts[0]
    mesh = p.mesh
    if not mesh.is_watertight:
        raise EditError("鑽孔、加凸台需要封閉的實體：請先在「檢查與修復」修復網格")
    man = mf.Manifold(mf.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
                              tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    if man.status() != mf.Error.NoError:
        raise EditError("這個網格不是乾淨的實體（%s），無法做布林運算" % man.status())
    out = man - prim if subtract else man + prim
    mm = out.to_mesh()
    m2 = trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)
    if not len(m2.faces):
        raise EditError("運算後沒有留下任何東西")
    lab2 = _relabel(mesh, p.labels, m2)
    names = list(p.label_names)
    if not subtract:            # 新加的凸台自成一區
        new_faces = _new_faces(mesh, m2)
        if new_faces.any():
            names.append("新增凸台 %d" % (sum(n.startswith("新增凸台") for n in names) + 1))
            lab2 = lab2.copy()
            lab2[new_faces] = len(names) - 1
    return _make(m2, lab2, names, model), msg


def _new_faces(old, new):
    from scipy.spatial import cKDTree
    d, _ = cKDTree(old.triangles_center).query(new.triangles_center)
    return d > 0.5


def _prim(shape, size, depth, at, axis):
    import manifold3d as mf
    ax = {"x": 0, "y": 1, "z": 2}[str(axis).lower()]
    if shape == "box":
        w, d = (size if isinstance(size, (list, tuple)) else (size, size))[:2]
        prim = mf.Manifold.cube((float(w), float(d), float(depth)), True)
    else:
        prim = mf.Manifold.cylinder(float(depth), float(size) / 2, float(size) / 2, 64, True)
    if ax == 0:
        prim = prim.rotate((0, 90, 0))
    elif ax == 1:
        prim = prim.rotate((90, 0, 0))
    return prim.translate(tuple(float(x) for x in at))


def _hole(model, ids=None, at=None, diameter=5.0, depth=None, axis="z", shape="circle", width=None, height=None, **kw):
    """在 at=(x,y,z) 鑽孔：圓孔 diameter，或方孔 width×height；depth 不給＝貫穿。給 ids 時 at 預設為該區中心。"""
    p = _need(model)
    at = _at(model, ids, at)
    span = float(np.linalg.norm(p.mesh.extents)) * 2
    size = (width or diameter, height or diameter) if shape == "box" else diameter
    prim = _prim(shape, size, depth or span, at, axis)
    what = ("%g×%g mm 方孔" % size) if shape == "box" else ("直徑 %g mm 圓孔" % diameter)
    return _bool(model, prim, True, "在 (%s) 鑽 %s%s" % (", ".join("%.1f" % x for x in at), what,
                                                     "，深 %g mm" % depth if depth else "（貫穿）"))


def _boss(model, ids=None, at=None, diameter=8.0, height=5.0, axis="z", shape="circle", width=None, **kw):
    """在 at=(x,y,z) 加凸台（圓柱或方塊），例如螺絲柱、按鈕座。"""
    _need(model)
    at = _at(model, ids, at)
    size = (width or diameter, width or diameter) if shape == "box" else diameter
    prim = _prim(shape, size, height, at, axis)
    return _bool(model, prim, False, "在 (%s) 加%s凸台，高 %g mm" % (", ".join("%.1f" % x for x in at),
                                                                "方塊" if shape == "box" else "圓柱", height))


def _at(model, ids, at):
    if at is not None:
        if len(at) != 3:
            raise EditError("位置要給 x, y, z 三個數字（mm）")
        return [float(x) for x in at]
    if ids:
        info = regions(model)
        sel = _ids(model, ids)
        return info[sel[0]]["center_mm"]
    raise EditError("請指定位置（x, y, z）或區塊")


# ====================================================================== 多色 3MF
def export_painted(model, path, name="模型"):
    """有指定耗材顏色的區塊 → Bambu Studio 多色專案 3MF（每個三角面塗上耗材，AMS 直接用）。"""
    from . import vend
    vend.setup()
    from bambu_studio_ai.color.bambu_3mf import build_project
    p = _need(model)
    names = p.label_names
    cols = []
    fil_of = []
    for i, n in enumerate(names):
        c = model.region_colors.get(n)
        if c is None:
            c = "#FFFFFF" if model.region_colors else PALETTE[0]
        c = c.upper()
        if c not in cols:
            cols.append(c)
        fil_of.append(cols.index(c))
    labels = np.array(fil_of, dtype=np.int64)[p.labels]
    data = build_project(np.asarray(p.mesh.vertices, dtype=np.float64), np.asarray(p.mesh.faces, dtype=np.int64),
                         labels, cols[:16], name)
    with open(path, "wb") as f:
        f.write(data)
    return cols
