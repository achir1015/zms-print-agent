"""列印前檢查（七項）、修復、自動擺放、縮放 — 包裝 bambu-studio-ai 的網格分析（MIT），訊息改成中文。

七項：網格完整、列印範圍、懸空零件、懸垂、壁厚、底面接觸、材料適用；滿分 10 分。
"""
import math
import threading

from . import mesh3d, vend

vend.setup()
from bambu_studio_ai import hardware  # noqa: E402
from bambu_studio_ai.mesh import thickness  # noqa: E402
from bambu_studio_ai.mesh import (MaterialProfile, PrinterProfile, analyze, diagnose,  # noqa: E402
                                  keep_largest_body, orient_for_printing, repair_mesh)

STATUS = {"pass": ("通過", "green"), "warn": ("注意", "amber"), "fail": ("不合格", "rose"), "skipped": ("略過", "slate")}
CHECK_NAMES = {"mesh": "網格完整性", "build_volume": "列印範圍", "floating_parts": "懸空零件", "overhangs": "懸垂角度",
               "wall_thickness": "壁厚", "bed_contact": "底面接觸", "material": "材料適用"}
PURPOSES = {"general": "一般", "decorative": "裝飾擺件", "functional": "功能零件"}


def printer_keys():
    return list(hardware.printers().keys())


def printer_label(key):
    try:
        p = hardware.printers()[key]
        x, y, z = p.build_volume_mm
        return "%s（%g×%g×%g）" % (key, x, y, z)
    except Exception:
        return key


def material_keys():
    return [k for k in hardware.materials().keys() if not k.startswith("Support")]


def printer_profile(key):
    if not key:
        return None
    try:
        p = hardware.printer(key)
    except Exception:
        return None
    vol = hardware.usable_volume(p)
    return PrinterProfile(p.key, tuple(float(v) for v in vol), p.enclosed, p.max_nozzle_c >= 350)


def material_profile(key):
    try:
        m = hardware.materials()[key]
    except KeyError:
        m = hardware.materials()["PLA"]
    return MaterialProfile(name=m.key, min_wall_mm=float(m.min_wall_mm), nozzle_min_c=int(m.nozzle_c[0]),
                           nozzle_max_c=int(m.nozzle_c[1]), bed_c=int(m.bed_c), infill_decorative_pct=15,
                           infill_functional_pct=30, needs_enclosure=bool(m.needs_enclosure))


def material_info(key):
    m = hardware.materials().get(key) or hardware.materials()["PLA"]
    return {"name": m.key, "nozzle": "%d～%d °C" % m.nozzle_c, "bed": "%d °C" % m.bed_c,
            "enclosure": m.needs_enclosure, "ams": m.ams_compatible, "abrasive": m.abrasive}


# ====================================================================== 中文訊息
def _zh(cid, r, printer, material):
    s = r.status
    if cid == "mesh":
        d = r._diag
        if s == "pass":
            return "封閉實體、法線方向一致，可以直接切片。"
        bits = []
        if d.boundary_edges:
            bits.append("%d 條破洞邊" % d.boundary_edges)
        if d.nonmanifold_edges:
            bits.append("%d 條非流形邊" % d.nonmanifold_edges)
        if d.degenerate_faces:
            bits.append("%d 個退化面" % d.degenerate_faces)
        if d.inside_out:
            bits.append("內外顛倒")
        return ("網格沒有封閉（%s），切片軟體可能補錯或漏掉部分。" if s == "fail" else "大致封閉，但有 %s。") % "、".join(bits or ["小問題"])
    if cid == "build_volume":
        if r.fits is None:
            return "未指定印表機，沒有檢查列印範圍。"
        u = " × ".join("%g" % v for v in (r.usable_mm or ()))
        if r.fits:
            return "放得進 %s（可用範圍 %s mm）%s。" % (printer, u, "，需要在板上轉 90°" if r.rotate_on_plate else "")
        return "超出 %s 的可用範圍（%s mm）；最多縮放到 %s%% 或分割模型。" % (
            printer, u, "%g" % (math.floor((r.max_scale_pct or 0) * 10) / 10))
    if cid == "floating_parts":
        if s == "pass":
            return "一個實體、平放在列印板上。" if r.bodies <= 1 else "全部 %d 個實體都放在板上或其他零件上。" % r.bodies
        return "%d 個實體中有 %d 個懸在半空（最低離板 %.1f mm），要加支撐或移除。" % (
            r.bodies, r.floating, r.lowest_floating_gap_mm or 0)
    if cid == "overhangs":
        if r.area_pct <= 0:
            return "沒有超過 %g° 的懸垂面，不需要支撐。" % r.limit_deg
        return "%g%% 的表面（%.1f cm²）懸垂超過 %g°%s。" % (r.area_pct, r.area_mm2 / 100, r.limit_deg,
                                                    "，建議開啟支撐" if s != "pass" else "，影響不大")
    if cid == "wall_thickness":
        if s == "skipped" or r.min_mm is None:
            return "網格沒有封閉，無法量測壁厚。"
        if s == "pass":
            return "沒有薄於 %g mm 的牆（95%% 的表面至少 %g mm）。" % (r.min_wall_mm, r.p5_mm or 0)
        return "%g%% 的表面薄於 %g mm（最薄 %g mm），可能印不出來或很脆。" % (r.thin_area_pct or 0, r.min_wall_mm, r.min_mm or 0)
    if cid == "bed_contact":
        if s == "fail" or r.contact_mm2 < 1:
            return "只有點或線接觸列印板，請加寬邊（brim）、支撐或換個方向擺放。"
        return "%.0f mm² 平貼在列印板上（佔底面範圍 %g%%）%s。" % (r.contact_mm2, r.contact_pct,
                                                        "，接觸面偏小，建議加寬邊" if s == "warn" else "")
    if cid == "material":
        if s == "skipped":
            return "未指定印表機，沒有檢查材料。"
        if s == "pass":
            return "%s 適合 %s。" % (material, printer)
        return "%s 不適合 %s：%s" % (material, printer, "；".join(_zh_problem(p) for p in r.problems) or r.summary)
    return r.summary


def _zh_problem(p):
    p = str(p)
    if "enclosed" in p:
        return "需要封閉式印表機（開放式機種容易翹曲、有氣味）"
    if "hotter" in p:
        return "需要的噴嘴溫度超過這台印表機"
    return p


def _settings_zh(ps, material, purpose):
    layer = ps.layer_height.replace(" (small model, finer detail)", "（小模型，細節較好）").replace(
        " (large model, faster)", "（大模型，較快）")
    infill = ps.infill.replace(" (depends on what the part is for)", "（依用途）")
    return [("層高", layer), ("填充", infill), ("牆數", ps.walls.replace(">=", "至少") + " 圈"),
            ("頂底層", ps.top_layers.replace(">=", "至少") + " 層"),
            ("噴嘴溫度", ps.nozzle_temp.replace("-", "～").replace(" C", " °C")),
            ("熱床溫度", ps.bed_temp.replace(" C", " °C")),
            ("支撐", "大概不需要" if "not needed" in ps.supports else "懸垂處需要支撐")]


# ====================================================================== 主流程
_lock = threading.Lock()


def check(model, printer="A1", material="PLA", purpose="general", quick=True):
    """對模型（所有零件合併）做七項檢查，回傳中文報告 dict。
    quick：壁厚取樣 700 點（約 1 秒，畫面上調參數用）；False 用原本的 2000 點（約 5 秒）。"""
    mesh = model.combined()
    pp, mp = printer_profile(printer), material_profile(material)
    with _lock:
        thickness.SAMPLES = 700 if quick else 2000
        a = analyze(mesh, material=mp, printer=pp, purpose=purpose if purpose in PURPOSES else "general")
    items = []
    for cid, _name, r in a.checks():
        if cid == "mesh":
            r = _MeshWrap(r, a.diagnosis)
        st, tone = STATUS.get(r.status, (r.status, "slate"))
        items.append({"id": cid, "name": CHECK_NAMES.get(cid, cid), "status": r.status, "status_zh": st, "tone": tone,
                      "text": _zh(cid, r, printer, mp.name), "en": r.summary})
    g = a.geometry
    sugg = []
    for s in a.suggestions:
        if "slender" in s:
            sugg.append("模型細高，列印時容易晃動：加寬邊或和其他零件一起印。")
        elif "triangles" in s:
            sugg.append("三角面很多，Bambu Studio 若變慢可用「簡化模型」。")
        elif "Functional" in s:
            sugg.append("功能零件：建議 4 圈牆；零件互相配合處留約 0.2 mm 間隙。")
        else:
            sugg.append(s)
    return {
        "score": float(a.score.value),
        "printer": printer, "material": mp.name, "purpose": purpose,
        "size": [round(float(x), 2) for x in g.dimensions_mm],
        "volume_cm3": None if g.volume_cm3 is None else round(float(g.volume_cm3), 2),
        "triangles": int(g.triangles), "bodies": int(g.bodies),
        "items": items,
        "settings": _settings_zh(a.print_settings, mp.name, purpose),
        "suggestions": sugg,
        "repair_tier": a.diagnosis.repair_tier,
        "weight_g": model.weight_g(),
    }


class _MeshWrap:
    def __init__(self, r, d):
        self.status, self.summary, self._diag = r.status, r.summary, d


def prepare(model, height=None, repair=True, thorough=False, orient=False, keep_main=False, unit_scale=1.0):
    """依序：單位換算／縮放到指定高度 → 修復 → 只保留最大實體 → 自動擺放。回傳 (新模型, 步驟說明)。
    多零件模型合併成一個網格處理（顏色會保留在每個面上）。"""
    steps = []
    mesh = model.combined()
    rgb = None
    if any(p.face_rgb is not None for p in model.parts):
        _, _, rgb = model.arrays()
    if unit_scale and not math.isclose(unit_scale, 1.0):
        mesh.apply_scale(unit_scale)
        steps.append("單位換算 ×%g" % unit_scale)
    if height and mesh.extents[2] > 0.01:
        f = float(height) / float(mesh.extents[2])
        if not math.isclose(f, 1.0, rel_tol=1e-4):
            mesh.apply_scale(f)
            steps.append("等比例縮放 ×%.4g（高度 %g mm）" % (f, height))
    tier = diagnose(mesh).repair_tier
    if repair and tier != "none":
        mesh, rr = repair_mesh(mesh, thorough=thorough or tier == "major")
        rgb = None if len(mesh.faces) != (0 if rgb is None else len(rgb)) else rgb
        if rr.changed:
            steps.append("修復：" + "；".join(_zh_step(s) for s in rr.steps))
        for n in rr.notes:
            steps.append("仍有問題：" + _zh_step(n))
    if keep_main:
        mesh, kept = keep_largest_body(mesh)
        if kept.removed:
            rgb = None
            steps.append("只保留最大的實體（移除 %d 個碎片）" % kept.removed)
        else:
            steps.append("沒有明顯的碎片可移除")
    if orient:
        mesh, o = orient_for_printing(mesh)
        if o.rotated:
            steps.append("自動擺放：轉到平底朝下（接觸面 %.0f → %.0f mm²）" % (o.contact_before_mm2, o.contact_after_mm2))
        elif o.moved:
            steps.append("自動擺放：放到列印板上")
        else:
            steps.append("自動擺放：原本已平穩放在板上，不需要轉")
    # 置中、底面貼板
    lo, hi = mesh.bounds
    mesh.apply_translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
    name = model.parts[0].name if len(model.parts) == 1 else "模型"
    if rgb is not None and len(rgb) != len(mesh.faces):
        rgb = None
    new = mesh3d.Model([mesh3d.Part(name, mesh, rgb)], model.source, palette=model.palette)
    return new, steps


def _zh_step(s):
    s = str(s)
    rep = [("removed", "移除"), ("degenerate or duplicate faces", "個退化或重複的面"), ("filled holes", "補洞"),
           ("hole edges", "條破洞邊"), ("non-manifold edges", "條非流形邊"), ("fixed winding", "修正面方向"),
           ("flipped normals", "翻轉法線"), ("remain", "仍存在")]
    for a, b in rep:
        s = s.replace(a, b)
    return s


def scale(model, factor=None, target=None, axis=2):
    """等比例縮放：factor 倍，或讓某一軸變成 target mm。"""
    mesh = model.combined()
    if target:
        cur = float(mesh.extents[axis])
        factor = float(target) / cur if cur > 0 else 1.0
    factor = float(factor or 1.0)
    out = []
    for p in model.parts:
        m = p.mesh.copy()
        m.apply_scale(factor)
        out.append(mesh3d.Part(p.name, m, p.face_rgb))
    new = mesh3d.Model(out, model.source, palette=model.palette)
    lo = new.combined().bounds[0]
    for p in new.parts:
        p.mesh.apply_translation((0, 0, -lo[2]))
    return new, factor


def unit_guess(model):
    """判斷檔案單位：最大邊小於 0.5 多半是公尺（×1000）；小於 5 可能是公分或英吋。"""
    ext = float(max(model.combined().extents))
    if ext < 0.5:
        return 1000.0, "模型最大邊只有 %.3g，判斷單位是公尺，已換算成 mm（×1000）" % ext
    if ext < 5:
        return 1.0, "模型最大邊只有 %.3g mm，可能是公分或英吋，請確認尺寸" % ext
    return 1.0, ""
