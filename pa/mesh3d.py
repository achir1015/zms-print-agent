"""模型讀寫：參數化零件 → trimesh、讀入 STL／3MF／OBJ／GLB（含顏色）、匯出各種格式。

座標一律 Z 朝上、單位 mm（Bambu Studio 的慣例）。glTF（GLB）規定 Y 朝上、單位公尺：
讀入時轉回 Z 朝上，匯出時再轉成 Y 朝上（Windows 3D 檢視器、Blender、three.js 都能正確顯示）。
"""
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field

import numpy as np
import trimesh

from . import vend

vend.setup()

FORMATS = {".stl": "STL", ".3mf": "3MF", ".obj": "OBJ", ".glb": "GLB", ".gltf": "glTF", ".ply": "PLY", ".off": "OFF",
           ".fbx": "FBX", ".ma": "Maya ASCII"}
OPEN_FILTER = ["stl", "3mf", "obj", "mtl", "fbx", "ma", "mb", "glb", "gltf", "ply", "off"]
Y_UP_TO_Z_UP = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)
Z_UP_TO_Y_UP = np.linalg.inv(Y_UP_TO_Z_UP)
PART_COLORS = [(91, 155, 213), (244, 177, 66), (112, 190, 124), (229, 115, 115), (171, 134, 214), (96, 196, 196)]


@dataclass
class Part:
    name: str
    mesh: trimesh.Trimesh
    face_rgb: object = None         # (F,3) uint8；None＝單色
    labels: object = None          # 每個面的區塊編號（分區後才有）
    label_names: object = None


@dataclass
class Model:
    parts: list
    source: str = ""
    notes: list = field(default_factory=list)
    palette: list = field(default_factory=list)       # 3MF 的耗材顏色
    region_colors: dict = field(default_factory=dict)  # 區塊名 → 使用者指定的耗材顏色

    # ---------------------------------------------------------------- 合併資訊
    def combined(self):
        meshes = [p.mesh for p in self.parts]
        return meshes[0].copy() if len(meshes) == 1 else trimesh.util.concatenate(meshes)

    def arrays(self):
        """(vertices, faces, face_rgb) 給預覽用。"""
        vs, fs, cs, off = [], [], [], 0
        many = len(self.parts) > 1
        for i, p in enumerate(self.parts):
            vs.append(np.asarray(p.mesh.vertices))
            fs.append(np.asarray(p.mesh.faces) + off)
            off += len(p.mesh.vertices)
            if p.face_rgb is not None:
                cs.append(np.asarray(p.face_rgb, dtype=np.uint8))
            else:
                base = PART_COLORS[i % len(PART_COLORS)] if many else PART_COLORS[0]
                cs.append(np.tile(np.array(base, dtype=np.uint8), (len(p.mesh.faces), 1)))
        if not vs:
            return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), None
        return np.vstack(vs), np.vstack(fs), np.vstack(cs)

    def info(self):
        m = self.combined()
        lo, hi = m.bounds if len(m.faces) else (np.zeros(3), np.zeros(3))
        size = hi - lo
        vol = None
        if m.is_watertight:
            try:
                vol = abs(float(m.volume)) / 1000.0
            except Exception:
                vol = None
        return {"size": [round(float(x), 2) for x in size], "triangles": int(len(m.faces)),
                "parts": [p.name for p in self.parts], "volume_cm3": None if vol is None else round(vol, 2),
                "watertight": bool(m.is_watertight), "colored": any(p.face_rgb is not None for p in self.parts),
                "colors": len(self.palette)}

    def weight_g(self, density=1.24, infill=0.15, walls_mm=0.8):
        """粗估耗材重量（g）：外殼＋內部填充。"""
        m = self.combined()
        if not m.is_watertight:
            return None
        vol = abs(float(m.volume))
        shell = min(vol, float(m.area) * walls_mm)
        return round((shell + (vol - shell) * infill) / 1000.0 * density, 1)


# ====================================================================== 由參數化零件產生
def from_manifold(parts, source=""):
    out = []
    for name, man in parts:
        mm = man.to_mesh()
        v = np.asarray(mm.vert_properties)[:, :3].astype(np.float64)
        f = np.asarray(mm.tri_verts).astype(np.int64)
        out.append(Part(name, trimesh.Trimesh(v, f, process=False)))
    return Model(out, source)


# ====================================================================== 讀檔
def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mb":
        raise ValueError("Maya .mb 是 Autodesk 的封閉二進位格式，沒有公開規格無法讀取。請在 Maya 用「另存新檔」存成 "
                         ".ma（Maya ASCII），或「匯出」成 .fbx／.obj 再開啟")
    if ext == ".mtl":                       # 材質表本身沒有形狀：改開同名的 .obj
        obj = os.path.splitext(path)[0] + ".obj"
        if not os.path.isfile(obj):
            raise ValueError(".mtl 只是 OBJ 的材質（顏色）表，沒有形狀。請開啟同名的 .obj（兩個檔案放在同一個資料夾）")
        path, ext = obj, ".obj"
    if ext == ".3mf":
        return _load_3mf(path)
    if ext in (".fbx", ".ma"):
        return _load_grouped(path, ext)
    if ext == ".obj" and _obj_has_groups(path):
        return _load_grouped(path, ext)
    loaded = trimesh.load(path, force=None)
    yup = ext in (".glb", ".gltf") and not _already_upright(loaded)
    parts = _scene_parts(loaded, yup)
    if not parts:
        raise ValueError("檔案裡沒有任何三角面")
    model = Model(parts, path)
    if ext == ".obj":
        try:
            head = open(path, encoding="utf-8", errors="ignore").read(400).lower()
        except OSError:
            head = ""
        if "centimeter" in head or "units: cm" in head:          # Maya／3ds Max 匯出的 OBJ 註明公分
            for pt in parts:
                pt.mesh.apply_scale(10.0)
            model.notes.append("OBJ 註明單位是公分，已換算成 mm（×10）")
    if ext == ".obj" and len(parts) > 1:      # OBJ 依材質分成好幾塊 → 合成一個網格，材質變成「區塊」
        from . import segment
        names = [_short(getattr(p, "mat_name", None) or p.name, path) for p in parts]
        for p, n in zip(parts, names):
            p.name = n
        model = segment.to_single(model)
        model.notes.append("OBJ 有 %d 個材質群組，已變成 %d 個區塊（可以在「分區」逐區修改）" % (len(parts), len(parts)))
    if ext in (".glb", ".gltf"):
        ext_max = float(max(model.combined().extents))
        if 0 < ext_max < 0.5:                      # glTF 規定單位是公尺 → 換成 mm
            for pt in model.parts:
                pt.mesh.apply_scale(1000.0)
            model.notes.append("GLB 單位是公尺，已換算成 mm")
    return model


def _obj_has_groups(path):
    seen = set()
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("usemtl"):
                    seen.add(line.strip())
                    if len(seen) > 1:
                        return True
    except OSError:
        pass
    return False


def _short(name, path):
    base = os.path.basename(path)
    n = str(name)
    for x in (base + "_", base, os.path.splitext(base)[0] + "_"):
        if n.startswith(x):
            n = n[len(x):]
    return n or "材質 1"


def _load_grouped(path, ext):
    """FBX／Maya ASCII：自己寫的讀取器（pa/importers.py），材質群組變成「區塊」。"""
    from . import importers, segment
    try:
        maya = False
        if ext == ".obj":
            got, maya = importers.load_obj_groups(path)
        else:
            got = importers.load_fbx(path) if ext == ".fbx" else importers.load_ma(path)
    except importers.ImportError3D as e:
        raise ValueError(str(e)) from e
    parts = []
    for name, v, t, groups in got:
        mesh = trimesh.Trimesh(v, t, process=False)
        p = Part(name, mesh)
        names = []
        for g in groups:
            g = g or name
            if g not in names:
                names.append(g)
        if len(names) > 1:
            p.labels = np.array([names.index(g or name) for g in groups], dtype=np.int64)
            p.label_names = names
        parts.append(p)
    model = segment.to_single(Model(parts, path))
    if maya:
        model.notes.append("OBJ 是 Maya 匯出（公分、Y 朝上），已換算成 mm 並轉成 Z 朝上")
    n = len(model.parts[0].label_names)
    if n > 1:
        model.notes.append("讀到 %d 個材質群組，已變成區塊：%s" % (n, "、".join(model.parts[0].label_names[:8])))
    return model


def _already_upright(loaded):
    try:
        return any("Y-up to Z-up" in str(n) for n in loaded.graph.nodes)
    except Exception:
        return False


def _scene_parts(loaded, yup):
    meshes = []
    if isinstance(loaded, trimesh.Scene):
        for node in loaded.graph.nodes_geometry:
            tf, gname = loaded.graph[node]
            g = loaded.geometry[gname]
            if not isinstance(g, trimesh.Trimesh) or not len(g.faces):
                continue
            g = g.copy()
            g.apply_transform(tf)
            meshes.append((str(node), g))
    elif isinstance(loaded, trimesh.Trimesh):
        meshes.append(("模型", loaded))
    parts = []
    for name, g in meshes:
        if yup:
            g.apply_transform(Y_UP_TO_Z_UP)
        part = Part(name, trimesh.Trimesh(g.vertices, g.faces, process=False), _face_rgb(g, linear=yup))
        part.mat_name = re.sub(r"SG$", "", str(getattr(getattr(g.visual, "material", None), "name", "") or "")) or None
        parts.append(part)
    return parts


def _face_rgb(g, linear=False):
    """每個面的顯示顏色（sRGB）。glTF 的頂點色與材質色是線性值 → 轉回 sRGB；貼圖本身就是 sRGB。"""
    c = _face_rgb_raw(g)
    if c is None or not linear or getattr(g.visual, "kind", "") == "texture" and _has_texture(g):
        return c
    return (np.power(np.asarray(c, dtype=np.float64) / 255.0, 1 / 2.2) * 255.0).round().astype(np.uint8)


def _has_texture(g):
    mat = getattr(g.visual, "material", None)
    return (getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)) is not None


def _face_rgb_raw(g):
    vis = g.visual
    try:
        if vis.kind == "texture":
            mat = vis.material
            uv = getattr(vis, "uv", None)
            img = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
            if img is not None and uv is not None:
                cols = np.asarray(mat.to_color(uv), dtype=np.uint8)[:, :3]
                return cols[g.faces].mean(axis=1).astype(np.uint8)
            c = np.asarray(mat.main_color, dtype=np.uint8)[:3]
            return np.tile(c, (len(g.faces), 1))
        if vis.kind == "vertex":
            c = np.asarray(vis.vertex_colors, dtype=np.uint8)[:, :3]
            return c[g.faces].mean(axis=1).astype(np.uint8)
        if vis.kind == "face":
            return np.asarray(vis.face_colors, dtype=np.uint8)[:, :3]
    except Exception:
        return None
    return None


def _load_3mf(path):
    """3MF：先試 Bambu 多色解碼（含上色筆刷），失敗就用一般讀法（單色）。"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            bambu = any(n.lower().startswith("metadata/project_settings") or n.lower().endswith("model_settings.config")
                        for n in z.namelist())
    except zipfile.BadZipFile as e:
        raise ValueError("不是有效的 3MF 檔") from e
    if not bambu:                                   # 一般 3MF（沒有耗材設定）→ 每個零件用不同顏色顯示
        parts = _scene_parts(trimesh.load(path), False)
        if not parts:
            raise ValueError("檔案裡沒有任何三角面")
        for pt in parts:
            pt.face_rgb = None
        return Model(parts, path)
    try:
        import bambu3mf_to_glb as b3g
        fd, tmp = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        try:
            res = b3g.convert(path, tmp, units="mm", keep_position=True, verbose=False)
            model = load(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        model.source = path
        model.palette = list(res.get("palette") or [])
        return model
    except Exception as e:
        loaded = trimesh.load(path)
        parts = _scene_parts(loaded, False)
        if not parts:
            raise ValueError("檔案裡沒有任何三角面") from e
        return Model(parts, path, notes=["多色解碼失敗，以單色顯示：%s" % e])


# ====================================================================== 存檔
def export(model, path, name=""):
    """依副檔名存檔。STL 會把所有零件合併；3MF／GLB 保留每個零件（Bambu Studio 會分成多個物件）。"""
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if ext == ".stl":
        model.combined().export(path)
    elif ext == ".3mf":
        if getattr(model, "region_colors", None):           # 有指定耗材顏色的區塊 → Bambu 多色專案 3MF
            from . import segment
            segment.export_painted(model, path, name or "模型")
        else:
            write_3mf(model, path, name)
    elif ext in (".glb", ".gltf"):
        scene = trimesh.Scene()
        for i, p in enumerate(model.parts):
            m = p.mesh.copy()
            rgb = p.face_rgb if p.face_rgb is not None else np.tile(
                np.array(PART_COLORS[i % len(PART_COLORS)], dtype=np.uint8), (len(m.faces), 1))
            lin = (np.power(np.asarray(rgb, dtype=np.float64) / 255.0, 2.2) * 255.0).round().astype(np.uint8)  # glTF 顏色是線性
            m.visual = trimesh.visual.ColorVisuals(m, face_colors=np.hstack([lin, np.full((len(lin), 1), 255, np.uint8)]))
            m.apply_transform(Z_UP_TO_Y_UP)
            m.apply_scale(0.001)                      # glTF 單位是公尺
            scene.add_geometry(m, node_name=p.name, geom_name=p.name)
        scene.export(path)
    elif ext in (".obj", ".ply", ".off"):
        model.combined().export(path)
    else:
        raise ValueError("不支援的格式：%s" % ext)
    return path


def write_3mf(model, path, title=""):
    """寫 3MF（核心規格；每個零件一個物件，並排在列印板上）。Bambu Studio、PrusaSlicer、Orca 都能開。"""
    import zipfile
    from xml.sax.saxutils import escape
    objs, items = [], []
    for i, p in enumerate(model.parts, start=1):
        v = np.asarray(p.mesh.vertices)
        f = np.asarray(p.mesh.faces)
        vx = "".join('<vertex x="%.5f" y="%.5f" z="%.5f"/>' % tuple(r) for r in v)
        tx = "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % tuple(r) for r in f)
        objs.append('<object id="%d" name="%s" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles>'
                    '</mesh></object>' % (i, escape(p.name), vx, tx))
        items.append('<item objectid="%d" transform="1 0 0 0 1 0 0 0 1 128 128 0"/>' % i)
    model_xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<model unit="millimeter" xml:lang="zh-TW" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                 '<metadata name="Title">%s</metadata><metadata name="Application">資料助秘3D列印AI代理人工具</metadata>'
                 '<resources>%s</resources><build>%s</build></model>' % (escape(title or "model"), "".join(objs), "".join(items)))
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model_xml)
    return path


def bambu_3mf_to_glb(src, dst, units="m", palette=None):
    """多色 3MF → GLB（每種耗材一個材質）。回傳 {stats, palette, output}。"""
    import bambu3mf_to_glb as b3g
    lines = []
    res = b3g.convert(src, dst, units=units, keep_position=False, palette_override=palette or None,
                      verbose=False, log_fn=lines.append)
    res["log"] = lines
    return res


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def params_json(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)
