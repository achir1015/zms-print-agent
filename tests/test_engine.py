"""3D 引擎：每種參數化零件都要封閉、可匯出、可讀回；檢查與本機代理人。"""
import os

import pytest

from pa import agent, checks, mesh3d, recipes, render


@pytest.mark.parametrize("rid", [r.id for r in recipes.RECIPES])
def test_every_recipe_is_watertight(rid):
    v, parts = recipes.build(rid)
    m = mesh3d.from_manifold(parts)
    info = m.info()
    assert info["watertight"], rid
    assert info["volume_cm3"] > 0
    assert min(info["size"]) > 0
    assert render.Scene(*m.arrays()).draw(size=120, fast=True)[:4] == b"\x89PNG"


def test_params_clamped():
    r = recipes.BY_ID["storage_box"]
    v = r.clean({"width": 9999, "wall": "abc", "finger": "否"})
    assert v["width"] == 250 and v["wall"] == 2.0 and v["finger"] is False


def test_export_roundtrip(tmp_path):
    _, parts = recipes.build("enclosure")
    m = mesh3d.from_manifold(parts)
    for ext in (".stl", ".3mf", ".glb", ".obj"):
        p = os.path.join(tmp_path, "x" + ext)
        mesh3d.export(m, p, "盒")
        back = mesh3d.load(p)
        assert [round(x) for x in back.info()["size"]] == [round(x) for x in m.info()["size"]], ext


def test_check_and_prepare():
    _, parts = recipes.build("vase")
    m = mesh3d.from_manifold(parts)
    rep = checks.check(m, "A1 Mini", "PLA")
    assert rep["score"] >= 9 and len(rep["items"]) == 7
    m2, steps = checks.prepare(m, height=60, orient=True)
    assert abs(m2.info()["size"][2] - 60) < 0.01
    big, _ = checks.scale(m, target=500)
    assert checks.check(big, "A1 Mini", "PLA")["score"] <= 4


def test_bambu_3mf_to_glb(tmp_path):
    _, parts = recipes.build("storage_box")
    m = mesh3d.from_manifold(parts)
    src = os.path.join(tmp_path, "a.3mf")
    mesh3d.export(m, src)
    res = mesh3d.bambu_3mf_to_glb(src, os.path.join(tmp_path, "a.glb"))
    assert os.path.getsize(res["output"]) > 1000


def test_local_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("PA_DATA_DIR", str(tmp_path))
    ws = agent.Workspace(out_dir=str(tmp_path))
    a = agent.Agent(ws)
    text, _ = a.ask("設計一個 60×40×30 毫米、帶蓋的電子元件盒")
    assert ws.recipe[0] == "enclosure" and ws.recipe[1]["inner_w"] == 60
    a.ask("壁厚改成 2.4")
    assert ws.recipe[1]["wall"] == 2.4 and ws.recipe[1]["inner_w"] == 60
    a.ask("縮放到 5 公分高")
    assert abs(ws.model.info()["size"][2] - 50) < 0.01
    assert agent._printer_key("a1 mini") == "A1 Mini" and agent._printer_key("H2D Pro") == "H2D Pro"
    assert agent.translate_query("手機架") == "phone stand"
