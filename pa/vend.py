"""把隨附的第三方程式（vendor/）加進匯入路徑。

* vendor/bsa：bambu-studio-ai（MIT，Yixuan He）— 模型檢查與修復、搜尋、AI 生成、切片估算、印表機狀態、彩色化。
* vendor/b3g：bambu-3mf-to-glb（AGPL-3.0，kylertran）— 把 Bambu Studio 多色 3MF 轉成 GLB。
設定與金鑰放在本程式的資料夾（BAMBU_STUDIO_AI_HOME），不放使用者家目錄。
"""
import os
import sys

from .settings import data_dir, resource_dir

_done = False


def setup():
    global _done
    if _done:
        return
    base = os.path.join(resource_dir(), "vendor")
    for sub in ("bsa", "b3g"):
        p = os.path.join(base, sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    home = os.path.join(data_dir(), "bambu")
    os.makedirs(home, exist_ok=True)
    os.environ.setdefault("BAMBU_STUDIO_AI_HOME", home)
    os.environ.setdefault("BAMBU_OUTPUT_DIR", os.path.join(home, "output"))
    _done = True
