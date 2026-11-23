"""每個畫面都要能在沒有視窗的情況下建立（抓 Flet API 用錯、變數名稱衝突這類錯誤）。"""
import types

import pytest

from pa.ui import shell
from pa.ui import theme as T


class FakePage:
    web = False
    route = ""

    def run_task(self, *a, **k):
        pass

    def show_dialog(self, *a, **k):
        pass

    def update(self, *a, **k):
        pass


@pytest.fixture()
def ctx(biz):
    from pa.settings import Settings
    app = types.SimpleNamespace(page=FakePage(), books=biz, reports=biz, mobile=False, go=lambda *a, **k: None, st=Settings(), update_info=None,
                                find=lambda sid: True)
    c = T.Ctx(app)
    app.ctx = c
    return c


SCREENS = [it[0] for g in shell.menu() for it in g[3]]


@pytest.mark.parametrize("sid", SCREENS)
def test_screen_builds(ctx, sid):
    assert shell.build_screen(sid, ctx) is not None


def test_screen_args(ctx, biz):
    from pa import checks, mesh3d, recipes
    v, parts = recipes.build("block")
    m = mesh3d.from_manifold(parts)
    did, _ = biz.save_design(m, "方塊", recipe_id="block", params=v, report=checks.check(m))
    shell.build_screen("design", ctx, design=did)
    shell.build_screen("library", ctx, design=did)
    shell.build_screen("check", ctx, design=did)
    shell.build_screen("agent", ctx, text="設計一個方塊")
    cid = biz.chat_add(None, "user", "hi")
    shell.build_screen("agent", ctx, chat=cid)
    for lesson in ("intro", "agent", "library"):
        shell.build_screen("help", ctx, lesson=lesson)


def test_menu_and_help_consistent():
    import flet as ft
    from pa.help_text import LESSONS, PAGES
    sids = set(SCREENS)
    for lesson in LESSONS:
        for icon, tone, text, sid in lesson["steps"]:
            assert sid in sids, sid
            assert getattr(ft.Icons, icon)
    assert set(PAGES) <= sids
