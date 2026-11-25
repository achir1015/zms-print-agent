"""匯入現成模型（OBJ／FBX／MA）、分區、逐區修改、額溫槍外殼零件、代理人分區指令。"""
import os

import numpy as np
import pytest
import trimesh

from pa import agent, checks, importers, mesh3d, recipes, segment

HERE = os.path.dirname(__file__)
USER = [os.path.join(os.path.expanduser("~"), "Downloads", "數位溫度計3D模型." + e) for e in ("fbx", "ma", "obj")]


def _two_part_obj(tmp_path, maya=False):
    """兩個材質群組的 OBJ：底座方塊＋上面的圓柱。"""
    a = trimesh.creation.box((40, 30, 10))
    a.apply_translation((0, 0, 5))
    b = trimesh.creation.cylinder(radius=6, height=12, sections=24)
    b.apply_translation((0, 0, 16))
    lines = ["# Maya OBJ export, units centimeter"] if maya else []
    off = 1
    for name, m in (("baseSG", a), ("knob", b)):
        v = m.vertices / (10 if maya else 1)
        if maya:
            v = v[:, [0, 2, 1]] * [1, 1, -1]
        lines += ["usemtl %s" % name] + ["v %.5f %.5f %.5f" % tuple(x) for x in v]
        lines += ["f %d %d %d" % tuple(f + off) for f in m.faces]
        off += len(v)
    p = tmp_path / ("parts_maya.obj" if maya else "parts.obj")
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def test_grouped_single_mesh_gets_region_colors(tmp_path):
    """單一網格本身有材質群組（FBX／MA 常見）→ 預覽要依區塊上不同顏色。"""
    from pa import importers
    a = trimesh.creation.box((20, 20, 20))
    b = trimesh.creation.box((5, 5, 5))
    b.apply_translation((0, 0, 12.5))
    v = np.vstack([a.vertices, b.vertices])
    f = np.vstack([a.faces, b.faces + len(a.vertices)])
    groups = ["Body"] * len(a.faces) + ["button"] * len(b.faces)
    orig = importers.load_fbx
    importers.load_fbx = lambda path: [("mesh", v, f, groups)]
    try:
        p = tmp_path / "x.fbx"
        p.write_bytes(b"")
        m = mesh3d.load(str(p))
    finally:
        importers.load_fbx = orig
    _, _, c = m.arrays()
    assert len(np.unique(c, axis=0)) == 2


def test_obj_groups_and_maya_units(tmp_path):
    for maya in (False, True):
        m = mesh3d.load(_two_part_obj(tmp_path, maya))
        regs = segment.regions(m)
        assert [r["name"] for r in regs] == ["base", "knob"]
        size = m.combined().extents
        assert np.allclose(size, (40, 30, 22), atol=0.2), size


def test_region_edits_keep_solid(tmp_path):
    m = mesh3d.load(_two_part_obj(tmp_path))
    m2, msg = segment.edit(m, "color", ["knob"], color="黑")
    assert m2.region_colors == {"knob": "#212121"}
    m3, _ = segment.edit(m2, "scale", [2], factor=1.5)
    assert m3.combined().extents[2] > 22
    m4, _ = segment.edit(m2, "delete", [2])
    assert len(segment.regions(m4)) == 1 and m4.combined().extents[2] == pytest.approx(10, abs=0.1)
    m5, _ = segment.edit(m2, "rename", [1], name="底座")
    assert segment.regions(m5)[0]["name"] == "底座"
    # 一體成形的方塊：分區、鑽孔、切半
    box = mesh3d.from_trimesh(trimesh.creation.box((40, 40, 20)).apply_translation((0, 0, 10))) \
        if hasattr(mesh3d, "from_trimesh") else None
    if box is None:
        v, parts = recipes.build("block", {"width": 40, "depth": 40, "height": 20})
        box = mesh3d.from_manifold(parts)
    s = segment.segment(box, "surface", target=6)
    assert len(segment.regions(s)) == 6
    h, _ = segment.edit(s, "hole", None, at=[0, 0, 10], diameter=8)
    assert h.parts[0].mesh.is_watertight and h.parts[0].mesh.volume < s.parts[0].mesh.volume
    c, _ = segment.edit(s, "cut", None, axis="z", value=10, keep="both")
    assert c.parts[0].mesh.is_watertight and c.combined().extents[2] == pytest.approx(10, abs=0.1)


def test_painted_3mf_roundtrip(tmp_path):
    m = mesh3d.load(_two_part_obj(tmp_path))
    m, _ = segment.edit(m, "color", [1], color="#FFFFFF")
    m, _ = segment.edit(m, "color", [2], color="紅")
    out = str(tmp_path / "painted.3mf")
    mesh3d.export(m, out)
    back = mesh3d.load(out)
    assert np.allclose(back.combined().extents, (40, 30, 22), atol=0.2)


def test_mb_gives_friendly_error(tmp_path):
    p = tmp_path / "x.mb"
    p.write_bytes(b"FOR4\0\0\0\0")
    with pytest.raises(Exception) as e:
        mesh3d.load(str(p))
    assert ".ma" in str(e.value)


@pytest.mark.skipif(not all(os.path.isfile(p) for p in USER), reason="沒有使用者的溫度計範例檔")
def test_user_thermometer_files():
    for p in USER:
        m = mesh3d.load(p)
        assert len(segment.regions(m)) == 5
        assert np.allclose(sorted(m.combined().extents), sorted((20.8, 26.2, 76.5)), atol=0.5)
    names = [r["name"] for r in segment.regions(mesh3d.load(USER[0]))]
    assert {"Body", "screen", "button"} <= set(names)


@pytest.mark.parametrize("vals", [{}, {"split": False}, {"style": 2}, {"style": 2, "split": False}])
def test_thermo_gun_recipe(vals):
    v, parts = recipes.build("thermo_gun", vals)
    m = mesh3d.from_manifold(parts)
    assert all(p.mesh.is_watertight for p in m.parts)
    rep = checks.check(m, "A1", "PLA")
    assert rep["score"] >= 5
    if v["split"]:
        assert len(m.parts) == 2


def test_thermo_gun_board_fits():
    """GOOUUU ESP32-S3 42 pin 開發板放得進握把（內徑要比板寬＋公差大）。"""
    v, _ = recipes.build("thermo_gun", {})
    assert v["handle_w"] - 2 * v["wall"] > v["board_w"]
    assert v["board_l"] == pytest.approx(63.5) and v["board_w"] == pytest.approx(28)


def test_local_agent_region_commands(tmp_path):
    ws = agent.Workspace(out_dir=str(tmp_path))
    L = agent.LocalAgent(agent.Agent(ws))
    path = _two_part_obj(tmp_path)
    assert "已匯入" in L.reply("匯入 " + path)
    assert "knob" in L.reply("有哪些區")
    assert "改成" in L.reply("第 2 區塗黑色")
    assert ws.model.region_colors == {"knob": "#212121"}
    assert "縮放" in L.reply("第 2 區放大 1.2 倍")
    assert "移動" in L.reply("第 1 區往上 3 mm")
    assert "切成兩半" in L.reply("沿 Z 切兩半")
    r = L.reply("設計額溫槍外殼，直棒型，電池長 40")
    assert "額溫槍" in r and ws.recipe[1]["style"] == 2 and ws.recipe[1]["battery_l"] == 40
    assert "分成" in L.reply("分成 6 區")


def test_importers_triangulate():
    tri = importers.triangulate([0, 1, 2, 3, 4])
    assert len(tri) == 3


def test_explode_view_moves_outer_regions(tmp_path):
    m = mesh3d.load(_two_part_obj(tmp_path))
    v0 = segment.explode_view(m, 0).combined().extents
    v1 = segment.explode_view(m, 1).combined().extents
    assert np.allclose(v0, m.combined().extents, atol=0.01)
    assert v1[2] > v0[2] + 5                       # 上面的圓柱往上拆開
    assert len(segment.explode_view(m, 1).parts[0].mesh.faces) == len(m.parts[0].mesh.faces)
    assert m.combined().extents[2] == pytest.approx(22, abs=0.2)   # 原模型沒被改
