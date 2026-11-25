"""其他 3D 格式的讀取：FBX（二進位 7.x）、Maya ASCII（.ma）。全部自己寫，不需要 Autodesk SDK 或 Blender。

回傳 [(零件名, vertices (N,3) mm Z 朝上, faces (M,3), 每面群組名或 None)]，群組（材質）會變成「分區」。
* Maya .mb 是 Autodesk 的封閉二進位格式，沒有公開規格 → 請在 Maya 另存成 .ma／.fbx／.obj。
* .mtl 只是 OBJ 的材質表：和同名 .obj 放在同一個資料夾，開 .obj 時會一起讀。
"""
import math
import re
import struct
import zlib

import numpy as np

UNIT_MM = {"mm": 1.0, "millimeter": 1.0, "cm": 10.0, "centimeter": 10.0, "m": 1000.0, "meter": 1000.0,
           "in": 25.4, "inch": 25.4, "ft": 304.8, "foot": 304.8, "yd": 914.4, "yard": 914.4}


class ImportError3D(Exception):
    pass


def triangulate(poly):
    """多邊形（頂點索引串）→ 扇形三角形。"""
    return [(poly[0], poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]


def euler_xyz(rx, ry, rz):
    """Maya／FBX 預設旋轉順序 XYZ（度）→ 3×3（作用在欄向量：先 X 再 Y 再 Z）。"""
    rx, ry, rz = (math.radians(a) for a in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Z @ Y @ X


Y_UP_TO_Z_UP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)


# ====================================================================== Maya ASCII
def load_ma(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    unit = re.search(r'currentUnit\s+-l\s+(\w+)', text)
    scale = UNIT_MM.get(unit.group(1), 10.0) if unit else 10.0          # Maya 預設公分
    up_z = bool(re.search(r'upAxis\s+"?z', text, re.I))
    # 依 createNode 切成節點區塊
    blocks = re.split(r'\ncreateNode ', text)
    transforms, out = {}, []
    for b in blocks[1:]:
        head = b.split("\n", 1)[0]
        kind = head.split()[0]
        name = (re.search(r'-n\s+"([^"]+)"', head) or [None, ""])[1]
        parent = (re.search(r'-p\s+"([^"]+)"', head) or [None, ""])[1]
        if kind == "transform":
            tf = {"t": (0, 0, 0), "r": (0, 0, 0), "s": (1, 1, 1), "parent": parent}
            for key in ("t", "r", "s"):
                m = re.search(r'setAttr "\.%s" -type "double3" ([-\d.e+ ]+);' % key, b)
                if m:
                    tf[key] = tuple(float(x) for x in m.group(1).split())
            transforms[name] = tf
        elif kind == "mesh":
            if re.search(r'setAttr "\.io" yes', b):          # 中間物件（建模歷程），不是顯示的網格
                continue
            out.append((name, parent, b))
    if not out:
        raise ImportError3D("Maya 檔裡沒有多邊形網格（mesh）")
    parts = []
    for name, parent, b in out:
        verts = _ma_array(b, "vt", 3)
        edges = _ma_array(b, "ed", 3).astype(np.int64)
        faces_raw = _ma_faces(b)
        if not len(verts) or not faces_raw:
            continue
        # 材質群組：.iog[0].og[k].gcl "f[a:b]" ...；名稱＝連到這個群組的材質（Body、screen、button…）
        group_of, og_name = {}, {}
        short = name.split("|")[-1]
        sg_of = {}
        for k, sg in re.findall(r'connectAttr "([^".]+)\.mwc" "[^"]*%s\.iog\.og\[(\d+)\]\.gco"' % re.escape(short), text):
            sg_of[int(sg)] = k
        for k, sg in re.findall(r'connectAttr "[^"]*%s\.iog\.og\[(\d+)\]" "([^".]+)\.dsm"' % re.escape(short), text):
            sg_of.setdefault(int(k), sg)
        mat_of = {sg: mat for mat, sg in re.findall(r'connectAttr "([^".]+)\.(?:oc|out|outColor)" "([^".]+)\.ss"', text)}
        for k, sg in sg_of.items():
            og_name[k] = mat_of.get(sg) or re.sub(r"SG$", "", sg)
        for k, comps in re.findall(r'\.iog\[0\]\.og\[(\d+)\]\.gcl" -type "componentList" \d+ ((?:"[^"]*"\s*)+);', b):
            for a, c in re.findall(r'"f\[(\d+)(?::(\d+))?\]"', comps):
                for fi in range(int(a), int(c or a) + 1):
                    group_of[fi] = og_name.get(int(k), "區塊 %d" % (int(k) + 1))
        tris, tgroups = [], []
        for fi, elist in enumerate(faces_raw):
            poly = []
            for e in elist:
                if e >= 0:
                    poly.append(int(edges[e][0]))
                else:
                    poly.append(int(edges[-e - 1][1]))
            for t in triangulate(poly):
                tris.append(t)
                tgroups.append(group_of.get(fi))
        v = verts.astype(np.float64)
        # 套用父節點（一路往上）的平移、旋轉、縮放
        p = parent
        while p and p in transforms:
            tf = transforms[p]
            v = (v * np.array(tf["s"])) @ euler_xyz(*tf["r"]).T + np.array(tf["t"])
            p = tf["parent"]
        v = v * scale
        if not up_z:
            v = v @ Y_UP_TO_Z_UP.T
        parts.append((name or "Maya 網格", v, np.array(tris, dtype=np.int64), tgroups))
    if not parts:
        raise ImportError3D("Maya 網格沒有面")
    return parts


def _ma_array(block, attr, width):
    vals = []
    for m in re.finditer(r'setAttr "\.%s\[\d+(?::\d+)?\]"\s+([^;]*);' % attr, block):
        vals += m.group(1).replace("\n", " ").split()
    # vt 可能加 -type "float3"；ed 每組三個數字
    nums = [float(x) for x in vals if re.fullmatch(r'[-+]?\d*\.?\d+(?:e[-+]?\d+)?', x, re.I)]
    n = len(nums) // width
    return np.array(nums[:n * width], dtype=np.float64).reshape(n, width) if n else np.zeros((0, width))


def _ma_faces(block):
    faces = []
    for m in re.finditer(r'setAttr "\.fc\[\d+(?::\d+)?\]"(?:\s+-type "polyFaces")?\s+([^;]*);', block):
        toks = m.group(1).split()
        i = 0
        while i < len(toks):
            t = toks[i]
            if t == "f":
                n = int(toks[i + 1])
                faces.append([int(x) for x in toks[i + 2:i + 2 + n]])
                i += 2 + n
            elif t == "h":               # 洞（3D 列印外殼很少用）→ 略過
                n = int(toks[i + 1])
                i += 2 + n
            elif t in ("mu", "mc"):
                n = int(toks[i + 2])
                i += 3 + n
            elif t == "fc":
                n = int(toks[i + 1])
                i += 2 + n
            else:
                i += 1
    return faces


# ====================================================================== FBX（二進位）
class _Node:
    __slots__ = ("name", "props", "children")

    def __init__(self, name, props, children):
        self.name, self.props, self.children = name, props, children

    def get(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def all(self, name):
        return [c for c in self.children if c.name == name]


def _read_node(buf, pos, wide):
    if wide:
        end, nprops, _plen = struct.unpack_from("<QQQ", buf, pos)
        pos += 24
    else:
        end, nprops, _plen = struct.unpack_from("<III", buf, pos)
        pos += 12
    nlen = buf[pos]
    pos += 1
    if end == 0:
        return None, pos + nlen
    name = buf[pos:pos + nlen].decode("ascii", "replace")
    pos += nlen
    props = []
    for _ in range(nprops):
        t = chr(buf[pos])
        pos += 1
        if t in "YCIFDL":
            fmt = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}[t]
            props.append(struct.unpack_from(fmt, buf, pos)[0])
            pos += struct.calcsize(fmt)
        elif t in "fdlib":
            n, enc, clen = struct.unpack_from("<III", buf, pos)
            pos += 12
            raw = buf[pos:pos + clen]
            pos += clen
            if enc == 1:
                raw = zlib.decompress(raw)
            dt = {"f": "<f4", "d": "<f8", "l": "<i8", "i": "<i4", "b": "<u1"}[t]
            props.append(np.frombuffer(raw, dtype=dt, count=n))
        elif t in "SR":
            n = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
            data = bytes(buf[pos:pos + n])
            pos += n
            props.append(data.decode("utf-8", "replace") if t == "S" else data)
        else:
            raise ImportError3D("FBX 屬性型別無法辨識：%r" % t)
    children = []
    while pos < end:
        child, pos = _read_node(buf, pos, wide)
        if child is None:
            break
        children.append(child)
    return _Node(name, props, children), end


def load_fbx(path):
    buf = open(path, "rb").read()
    if not buf.startswith(b"Kaydara FBX Binary"):
        raise ImportError3D("只支援二進位 FBX（ASCII FBX 請在 3D 軟體另存成二進位或 OBJ）")
    version = struct.unpack_from("<I", buf, 23)[0]
    wide = version >= 7500
    pos, top = 27, []
    while pos < len(buf) - 160:
        node, pos = _read_node(buf, pos, wide)
        if node is None:
            break
        top.append(node)
    root = _Node("", [], top)
    # 單位與上方向
    scale_cm, up = 1.0, 1
    gs = root.get("GlobalSettings")
    p70 = gs.get("Properties70") if gs else None
    for p in (p70.children if p70 else []):
        if p.props and p.props[0] == "UnitScaleFactor":
            scale_cm = float(p.props[-1])
        if p.props and p.props[0] == "UpAxis":
            up = int(p.props[-1])
    mm = scale_cm * 10.0                                       # FBX 單位＝公分 × UnitScaleFactor
    objs = root.get("Objects")
    if objs is None:
        raise ImportError3D("FBX 裡沒有物件")
    geoms, models, mats = {}, {}, {}
    for n in objs.children:
        oid = n.props[0] if n.props else None
        nm = (n.props[1] if len(n.props) > 1 else "").split("\x00")[0]
        if n.name == "Geometry" and len(n.props) > 2 and n.props[2] == "Mesh":
            geoms[oid] = (nm, n)
        elif n.name == "Model":
            tf = {"t": (0, 0, 0), "r": (0, 0, 0), "s": (1, 1, 1), "name": nm}
            pp = n.get("Properties70")
            for p in (pp.children if pp else []):
                key = p.props[0] if p.props else ""
                if key in ("Lcl Translation", "Lcl Rotation", "Lcl Scaling"):
                    tf[{"Lcl Translation": "t", "Lcl Rotation": "r", "Lcl Scaling": "s"}[key]] = tuple(float(x) for x in p.props[-3:])
            models[oid] = tf
        elif n.name == "Material":
            mats[oid] = nm
    parent = {}                     # 子物件 → 父物件（Geometry → Model、Model → Model）
    mat_of_model = {}
    conns = root.get("Connections")
    for c in (conns.children if conns else []):
        if len(c.props) >= 3 and c.props[0] == "OO":
            ch, pa = c.props[1], c.props[2]
            if ch in mats and pa in models:
                mat_of_model.setdefault(pa, []).append(mats[ch])
            else:
                parent.setdefault(ch, pa)
    parts = []
    for gid, (gname, g) in geoms.items():
        vnode, inode = g.get("Vertices"), g.get("PolygonVertexIndex")
        if vnode is None or inode is None:
            continue
        v = np.asarray(vnode.props[0], dtype=np.float64).reshape(-1, 3)
        idx = np.asarray(inode.props[0], dtype=np.int64)
        polys, cur = [], []
        for i in idx:
            if i < 0:
                cur.append(int(~i))
                polys.append(cur)
                cur = []
            else:
                cur.append(int(i))
        pmat = None
        lem = g.get("LayerElementMaterial")
        if lem is not None and lem.get("Materials") is not None:
            arr = np.asarray(lem.get("Materials").props[0])
            mode = lem.get("MappingInformationType").props[0] if lem.get("MappingInformationType") else ""
            pmat = arr if (mode == "ByPolygon" and len(arr) == len(polys)) else (np.full(len(polys), int(arr[0])) if len(arr) else None)
        mid = parent.get(gid)
        mnames = mat_of_model.get(mid, [])
        tris, groups = [], []
        for pi, poly in enumerate(polys):
            gname_ = None
            if pmat is not None and mnames:
                k = int(pmat[pi])
                gname_ = mnames[k] if 0 <= k < len(mnames) else None
            for t in triangulate(poly):
                tris.append(t)
                groups.append(gname_)
        m = mid
        while m in models:
            tf = models[m]
            v = (v * np.array(tf["s"])) @ euler_xyz(*tf["r"]).T + np.array(tf["t"])
            m = parent.get(m)
        v = v * mm
        if up == 1:
            v = v @ Y_UP_TO_Z_UP.T
        name = models.get(mid, {}).get("name") or gname or "FBX 網格"
        parts.append((name, v, np.array(tris, dtype=np.int64), groups))
    if not parts:
        raise ImportError3D("FBX 裡沒有多邊形網格")
    return parts


# ====================================================================== OBJ（依 usemtl 分組）
def load_obj_groups(path):
    """OBJ 自己讀：每個面記住 usemtl 材質名（和 .mtl 檔名對不對得上無關）。
    Maya／3ds Max 匯出的 OBJ 註明公分 → ×10，且 Maya 是 Y 朝上 → 轉成 Z 朝上。"""
    verts, tris, groups, cur = [], [], [], None
    head = ""
    with open(path, encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            if i < 5:
                head += line.lower()
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("usemtl"):
                cur = line.split(None, 1)[1].strip() if len(line.split()) > 1 else None
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    k = int(tok.split("/")[0])
                    idx.append(k - 1 if k > 0 else len(verts) + k)
                for t in triangulate(idx):
                    tris.append(t)
                    groups.append(re.sub(r"SG$", "", cur) if cur else None)
    if not tris:
        raise ImportError3D("OBJ 裡沒有面")
    v = np.array(verts, dtype=np.float64)
    maya = "centimeter" in head
    if maya:
        v = (v * 10.0) @ Y_UP_TO_Z_UP.T
    return [("模型", v, np.array(tris, dtype=np.int64), groups)], maya
