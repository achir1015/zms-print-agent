"""資料庫業務：設計存檔、版本雜湊、核准凍結、權限、代理人對話、印表機。"""
import pytest

from pa import checks, mesh3d, recipes
from pa.core import BizError
from pa.seed import ROLES


def _part(rid="block", **kw):
    v, parts = recipes.build(rid, kw)
    m = mesh3d.from_manifold(parts)
    return v, m, checks.check(m, "A1", "PLA")


def test_design_revisions_and_hash(biz):
    v, m, rep = _part("storage_box", width=70)
    did, rev = biz.save_design(m, "收納盒", recipe_id="storage_box", params=v, report=rep, printer="A1", material="PLA")
    assert rev == 1
    data, name, sha = biz.revision_file(did)
    assert name.endswith(".3mf") and len(sha) == 64
    v2, m2, rep2 = _part("storage_box", width=90)
    _, rev2 = biz.save_design(m2, "收納盒", recipe_id="storage_box", params=v2, report=rep2, design_id=did,
                              change_note="加寬")
    assert rev2 == 2
    revs = biz.revisions(did)
    assert [r["rev"] for r in revs] == [2, 1]
    assert revs[0]["file_sha256"] != revs[1]["file_sha256"]
    back = mesh3d.load(biz.load_revision(did, 2))
    assert abs(back.info()["size"][1] - 40) < 0.01


def test_approve_and_permissions(biz, db):
    from pa.biz import Biz
    biz.save_user("des", "設計師", "設計師", False, True, ROLES["設計師"], pw="des123", is_new=True)
    s = Biz(db)
    s.login("des", "des123")
    v, m, rep = _part()
    did, _ = s.save_design(m, "方塊", params=v, report=rep)
    with pytest.raises(BizError):
        s.set_status(did, "APPROVED")                 # 設計師不能核准
    biz.set_status(did, "APPROVED")
    with pytest.raises(BizError):
        s.delete_design(did)                          # 已核准不能刪
    assert [d["id"] for d in s.designs()] == [did]
    did2, _ = biz.save_design(m, "管理員的", params=v, report=rep)
    assert did2 not in [d["id"] for d in s.designs()]  # 看不到別人的
    with pytest.raises(BizError):
        s.design(did2)


def test_chat_and_printer(biz):
    cid = biz.chat_add(None, "user", "設計一個盒子", engine="LOCAL")
    biz.chat_add(cid, "agent", "好的", tools="make_part", raw=[{"role": "user", "content": "x"}])
    c = biz.chat(cid)
    assert [x["role"] for x in c["msgs"]] == ["user", "agent"] and c["title"] == "設計一個盒子"
    pid = biz.save_printer(None, "工作室 A1", "A1", "192.168.1.50", "01p00a000000000")
    assert biz.default_printer()["serial"] == "01P00A000000000"
    biz.delete_printer(pid)
    assert biz.default_printer() is None
