"""線上版（docs/app 的 JavaScript）和電腦版（Python）要算出一樣的零件與檢查結果。需要 Node 22，沒有就略過。"""
import json
import os
import subprocess

import pytest

from pa import checks, mesh3d, recipes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(HERE, "docs", "app")
NODE = os.path.expandvars(r"%LOCALAPPDATA%\nvm\v22.22.3\node.exe") if os.name == "nt" else "node"


def _node(script):
    if os.name == "nt" and not os.path.isfile(NODE):
        pytest.skip("沒有 Node 22")
    if not os.path.isfile(os.path.join(APP, "lib", "manifold.js")):
        pytest.skip("沒有 docs/app/lib（python tools/make_pages.py --libs）")
    out = subprocess.run([NODE, os.path.join(HERE, "tools", "webref", script), APP.replace("\\", "/")],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_parts_match_python():
    js = _node("parts.mjs")
    for r in recipes.RECIPES:
        if r.id not in js:                 # 還沒移植到線上版的新零件
            continue
        _, p = recipes.build(r.id)
        info = mesh3d.from_manifold(p).info()
        assert abs(info["volume_cm3"] - js[r.id]["vol"]) < 0.01 * max(1, info["volume_cm3"]), r.id
        assert all(abs(a - b) < 0.05 for a, b in zip(info["size"], js[r.id]["size"])), r.id


def test_checks_match_python():
    js = _node("checks.mjs")
    for r in recipes.RECIPES:
        if r.id not in js:
            continue
        _, p = recipes.build(r.id)
        rep = checks.check(mesh3d.from_manifold(p), "A1 Mini", "PETG", "functional", quick=False)
        assert "".join(i["status"][0] for i in rep["items"]) == js[r.id]["st"], r.id
        assert abs(rep["score"] - js[r.id]["score"]) <= 0.3, r.id


def test_regions_match_python(tmp_path):
    """線上版匯入（FBX／MA／OBJ 材質群組）與分區編輯，和電腦版一致。"""
    from pa import segment
    import trimesh
    base = os.path.dirname(HERE)
    files = [os.path.join(base, "數位溫度計3D模型." + e) for e in ("fbx", "ma")]
    files = [f for f in files if os.path.isfile(f)]
    if os.name == "nt" and not os.path.isfile(NODE):
        pytest.skip("沒有 Node 22")
    out = subprocess.run([NODE, os.path.join(HERE, "tools", "webref", "regions.mjs"), APP.replace("\\", "/")] + [f.replace("\\", "/") for f in files],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    js = json.loads(out.strip().splitlines()[-1])
    for f in files:
        m = mesh3d.load(f)
        w = js["files"][f.replace("\\", "/")]
        assert w["names"] == [r["name"] for r in segment.regions(m)], f
        assert all(abs(a - b) < 0.05 for a, b in zip(m.combined().extents, w["size"])), f
    v, parts = recipes.build("block", {"width": 40, "depth": 40, "height": 20})
    s = segment.segment(mesh3d.from_manifold(parts), "surface", target=6)
    assert js["ops"]["surface"] == len(segment.regions(s))
    for op, kw, ids in (("hole", {"at": [0, 0, 10], "diameter": 8}, None), ("cut", {"axis": "z", "value": 10, "keep": "both"}, None),
                        ("boss", {"diameter": 6, "height": 5}, [2])):
        m2, _ = segment.edit(s, op, ids, **kw)
        assert all(abs(a - b) < 0.05 for a, b in zip(m2.combined().extents, js["ops"][op])), op
