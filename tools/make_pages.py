"""產生線上版（GitHub Pages：docs/）需要的資料與檔案。

* docs/app/data.js：印表機（可用列印範圍）、耗材、參數化零件的參數表、語音教學課程與各頁說明 — 都從 Python 程式產生，
  兩個版本共用同一份定義（零件的建模程式在 docs/app/engine.js，要和 pa/recipes.py 一起改）。
* docs/voice/：語音教學 MP3（從 assets/voice 複製）。
* docs/icon.png、docs/app/icon.png。
* docs/app/lib/：three.js、manifold-3d（wasm）— 用 --libs 從 npm 下載（需要 Node 22）。

用法：python tools/make_pages.py [--libs]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from pa import APP_NAME, APP_VERSION, GITHUB_REPO, checks, recipes  # noqa: E402
from pa.help_text import LESSONS, PAGES  # noqa: E402
from bambu_studio_ai import hardware  # noqa: E402

DOCS = os.path.join(HERE, "docs")
APP = os.path.join(DOCS, "app")
NODE = os.path.expandvars(r"%LOCALAPPDATA%\nvm\v22.22.3")
LIBS = {  # npm 套件版本固定
    "manifold-3d": "3.5.5", "three": "0.180.0",
}
# 只有電腦版能做的畫面：線上版另外處理
WEB_PAGES = ("home", "agent", "design", "library", "check", "convert", "search", "aiset", "help")


def data():
    prs = {}
    for k, p in hardware.printers().items():
        u = hardware.usable_volume(p)
        prs[k] = {"name": p.name, "usable": [float(x) for x in u], "volume": [float(x) for x in p.build_volume_mm],
                  "enclosed": bool(p.enclosed), "high_temp": p.max_nozzle_c >= 350}
    mats = {}
    for k in checks.material_keys():
        m = hardware.materials()[k]
        mats[k] = {"nozzle": list(m.nozzle_c), "bed": m.bed_c, "min_wall": m.min_wall_mm,
                   "enclosure": bool(m.needs_enclosure), "high_temp": m.nozzle_c[0] > 300}
    recs = []
    for r in recipes.RECIPES:
        recs.append({"id": r.id, "name": r.name, "category": r.category, "icon": r.icon, "desc": r.desc,
                     "keywords": list(r.keywords),
                     "params": [{"key": p.key, "label": p.label, "default": p.default, "min": p.lo, "max": p.hi,
                                 "step": p.step, "unit": p.unit, "doc": p.doc, "kind": p.kind} for p in r.params]})
    lessons = [{"key": x["key"], "title": x["title"], "voice": x["voice"],
                "steps": [{"icon": s[0], "tone": s[1], "text": s[2], "page": s[3]} for s in x["steps"]]}
               for x in LESSONS]
    pages = {k: {"title": v[0], "voice": v[1]} for k, v in PAGES.items() if k in WEB_PAGES}
    return {"app": APP_NAME, "version": APP_VERSION, "repo": GITHUB_REPO, "printers": prs, "materials": mats,
            "recipes": recs, "categories": recipes.CATEGORIES, "lessons": lessons, "pages": pages,
            "purposes": checks.PURPOSES}


def write_data():
    os.makedirs(APP, exist_ok=True)
    with open(os.path.join(APP, "data.js"), "w", encoding="utf-8") as f:
        f.write("// 由 tools/make_pages.py 產生，請勿手動修改\nexport const DATA = ")
        json.dump(data(), f, ensure_ascii=False, indent=1)
        f.write(";\n")
    vo = os.path.join(DOCS, "voice")
    os.makedirs(vo, exist_ok=True)
    for n in os.listdir(os.path.join(HERE, "assets", "voice")):
        if n.endswith(".mp3"):
            shutil.copyfile(os.path.join(HERE, "assets", "voice", n), os.path.join(vo, n))
    for d in (DOCS, APP):
        shutil.copyfile(os.path.join(HERE, "assets", "icon.png"), os.path.join(d, "icon.png"))
    print("ok data.js、voice、icon")


def fetch_libs():
    lib = os.path.join(APP, "lib")
    tmp = tempfile.mkdtemp(prefix="pa-weblibs-")
    npm = os.path.join(NODE, "npm.cmd")
    subprocess.run([npm, "init", "-y"], cwd=tmp, check=True, capture_output=True, shell=False)
    subprocess.run([npm, "install", "--silent"] + ["%s@%s" % kv for kv in LIBS.items()], cwd=tmp, check=True)
    nm = os.path.join(tmp, "node_modules")
    shutil.rmtree(lib, ignore_errors=True)
    os.makedirs(lib)
    for n in ("manifold.js", "manifold.wasm", "LICENSE"):
        shutil.copyfile(os.path.join(nm, "manifold-3d", n), os.path.join(lib, "manifold" + ("" if n != "LICENSE" else "-LICENSE") + (os.path.splitext(n)[1] if n != "LICENSE" else ".txt")))
    t = os.path.join(nm, "three")
    shutil.copyfile(os.path.join(t, "build", "three.module.min.js"), os.path.join(lib, "three.module.min.js"))
    shutil.copyfile(os.path.join(t, "build", "three.core.min.js"), os.path.join(lib, "three.core.min.js"))
    shutil.copyfile(os.path.join(t, "LICENSE"), os.path.join(lib, "three-LICENSE.txt"))
    jsm = os.path.join(t, "examples", "jsm")
    for rel in ("controls/OrbitControls.js", "loaders/GLTFLoader.js", "loaders/STLLoader.js", "loaders/OBJLoader.js",
                "loaders/3MFLoader.js", "loaders/PLYLoader.js", "exporters/GLTFExporter.js", "utils/BufferGeometryUtils.js",
                "libs/fflate.module.js"):
        dst = os.path.join(lib, "jsm", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(jsm, rel), dst)
    shutil.rmtree(tmp, ignore_errors=True)
    print("ok lib/", sorted(os.listdir(lib)))


if __name__ == "__main__":
    if "--libs" in sys.argv:
        fetch_libs()
    write_data()
