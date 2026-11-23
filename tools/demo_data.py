r"""開發用：在開發資料庫（data/）建立 admin/admin123、設計師 designer/design1，並存幾個示範設計。
用法：python tools/demo_data.py [--reset]"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from pa import checks, mesh3d, recipes, render  # noqa: E402
from pa.biz import Biz  # noqa: E402
from pa.database import DB  # noqa: E402
from pa.dbserver import LocalDatabaseServer  # noqa: E402
from pa.seed import ROLES  # noqa: E402
from pa.settings import Settings  # noqa: E402

st = Settings.load()
srv = LocalDatabaseServer(st)
srv.start()
try:
    db = DB(st)
    if "--reset" in sys.argv:
        c = db.connect(use_db=False)
        with c.cursor() as cur:
            cur.execute("DROP DATABASE IF EXISTS `%s`" % st.database)
        c.close()
    db.prepare()
    st.save()
    b = Biz(db)
    if not b.has_users():
        b.create_first_admin("admin", "系統管理員", "admin123")
    b.login("admin", "admin123")
    b.save_company(name="資料助秘創客工作室", default_printer="A1", default_material="PLA")
    if not db.value("SELECT 1 FROM sys_user WHERE uid='designer'"):
        b.save_user("designer", "林設計", "設計師", False, True, ROLES["設計師"], pw="design1", is_new=True)
    if not db.value("SELECT COUNT(*) FROM pa_design"):
        for rid, vals, title in (("enclosure", {"inner_w": 60, "inner_d": 40, "inner_h": 30}, "Arduino 電子盒"),
                                 ("storage_box", {"width": 80, "depth": 50, "height": 35}, "零件收納盒"),
                                 ("phone_stand", {}, "手機支架"), ("vase", {"twist": 90}, "扭轉花瓶"),
                                 ("gear", {"teeth": 24}, "24 齒齒輪")):
            v, parts = recipes.build(rid, vals)
            m = mesh3d.from_manifold(parts)
            rep = checks.check(m, "A1", "PLA")
            thumb = render.Scene(*m.arrays(), plate=(256, 256)).draw(-35, 28, 1.0, size=256)
            did, _ = b.save_design(m, title, "RECIPE", rid, v, rep, thumb, "A1", "PLA",
                                   category=recipes.BY_ID[rid].category)
        b.set_status(1, "APPROVED")
    print("ok", b.design_stats())
finally:
    db.close()
    srv.stop()
