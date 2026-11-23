"""首頁：一句話開始、四種做法、設計統計、最近的設計。"""
import datetime as dt

import flet as ft

from .. import rocdate
from ..agent import Agent
from ..seed import STATUS
from . import theme as T

I = ft.Icons


def greet():
    h = dt.datetime.now().hour
    return "早安" if h < 11 else "午安" if h < 14 else "下午好" if h < 18 else "晚安"


class Dashboard(ft.Column):
    def __init__(self, ctx, **kw):
        self.ctx = ctx
        b = ctx.books
        app = ctx.app
        u = b.user
        comp = b.company()
        st = b.design_stats() if b.can("DESIGN", 1) else {}
        ask = ft.TextField(hint_text="一句話告訴代理人要印什麼，例如：設計一個 60×40×30 mm 帶蓋的電子元件盒",
                           expand=True, border_radius=14, bgcolor="#FFFFFF", border_color="#FFFFFF", text_size=15,
                           on_submit=lambda e: app.go("agent", text=e.control.value))
        hero = ft.Container(ft.Row([
            ft.Column([ft.Text("%s，%s" % (u["name"], greet()), size=24, weight=ft.FontWeight.W_800,
                               color=ft.Colors.WHITE),
                       ft.Text(((comp.get("name") or "") + "　").lstrip("　") +
                               "從一句描述到可以列印的零件：設計 → 檢查 → Bambu Studio", size=14, color="#DCE6F5"),
                       ft.Row([hero_chip(I.CALENDAR_TODAY, rocdate.show(rocdate.today())),
                               hero_chip(I.AUTO_AWESOME, "Claude" if Agent.use_claude() else "本機規則（免費）"),
                               hero_chip(I.PRINT, comp.get("default_printer") or "A1"),
                               hero_chip(I.LAYERS, comp.get("default_material") or "PLA")], spacing=8, wrap=True),
                       ft.Row([ask, T.btn("問代理人", I.SEND_ROUNDED, lambda e: app.go("agent", text=ask.value),
                                          bgcolor=T.GOLD)], spacing=8)],
                      spacing=10, expand=True),
            ft.Image(src="icon.png", width=120, height=120)], spacing=20), padding=24, border_radius=20,
            gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                       colors=[T.SIDEBAR_TOP, "#1E4D8C", "#0FA294"]))
        ways = ft.Row([
            way(I.SMART_TOY, "violet", "AI 代理人", "用說的：描述、照片、草圖", lambda e: app.go("agent")),
            way(I.ARCHITECTURE, "blue", "零件設計", "18 種參數化零件，精確到 0.1 mm", lambda e: app.go("design")),
            way(I.FACT_CHECK, "teal", "檢查與修復", "STL／3MF／GLB 七項列印前檢查", lambda e: app.go("check")),
            way(I.TRAVEL_EXPLORE, "green", "搜尋現成模型", "MakerWorld、Printables", lambda e: app.go("search")),
            way(I.SYNC_ALT, "amber", "3MF → GLB", "多色專案轉成通用 3D 格式", lambda e: app.go("convert"))],
            spacing=12)
        ks = T.kpis([
            T.kpi("我的設計", str(int(st.get("n") or 0)), I.COLLECTIONS_BOOKMARK, "blue", "設計庫", lambda e: app.go("library")),
            T.kpi("草稿", str(int(st.get("draft") or 0)), I.EDIT_NOTE, "amber", "還在修改", lambda e: app.go("library")),
            T.kpi("已核准", str(int(st.get("appr") or 0)), I.VERIFIED, "green", "檔案已凍結", lambda e: app.go("library")),
            T.kpi("已列印", str(int(st.get("printed") or 0)), I.PRINT, "teal", "標記為已列印", lambda e: app.go("library")),
            T.kpi("耗材估計", "%.0f g" % float(st.get("grams") or 0), I.SCALE, "rose", "全部設計合計")]) if st else ft.Container()
        recent = []
        if b.can("DESIGN", 1):
            for r in b.designs(limit=8):
                s, tone = STATUS.get(r["status"], ("?", "slate"))
                recent.append(ft.Container(ft.Column([
                    ft.Container(ft.Image(src=bytes(r["thumb"]), height=110, fit=ft.BoxFit.CONTAIN) if r.get("thumb") else
                                 ft.Icon(I.VIEW_IN_AR, size=40, color=T.MUTED), height=110, bgcolor="#EEF3F9",
                                 border_radius=10, alignment=ft.Alignment.CENTER),
                    ft.Text(r["title"], size=13, weight=ft.FontWeight.W_700, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([T.chip(s, tone), T.muted(T.show(r["updated_at"])[:10], 11)], spacing=6)], spacing=4),
                    width=170, padding=8, border_radius=14, bgcolor=T.CARD, border=ft.Border.all(1, T.LINE), ink=True,
                    on_click=lambda e, i=r["id"]: app.go("library", design=i)))
        rec = T.card(ft.Column([
            ft.Row([T.icon_tile(I.HISTORY, "blue", 32), ft.Text("最近的設計", size=16, weight=ft.FontWeight.W_700, expand=True),
                    T.btn("設計庫", I.ARROW_FORWARD, lambda e: app.go("library"), kind="ghost")]),
            ft.Row(recent, scroll=ft.ScrollMode.AUTO, spacing=10) if recent else
            T.muted("還沒有設計。試試在上面輸入一句話，或到「零件設計」挑一個零件。")], spacing=10))
        tips = T.card(ft.Column([
            ft.Row([T.icon_tile(I.TIPS_AND_UPDATES, "amber", 32), ft.Text("每個物件用對的方法", size=16, weight=ft.FontWeight.W_700)]),
            tip("日常用品", "先搜尋 MakerWorld 與 Printables：很多人印過、驗證過的設計比自動產生的好。"),
            tip("功能性零件", "用參數化零件：精確到毫米，螺絲孔與配合間隙都算好。"),
            tip("人物、角色、照片", "用 AI 文字／照片轉 3D（Meshy、Tripo、Rodin），產生後一定先檢查。"),
            tip("列印前", "每個模型都做七項檢查：網格、範圍、懸空、懸垂、壁厚、底面、材料；列印永遠由您自己在 Bambu Studio 按。")],
            spacing=8))
        super().__init__([hero, ways, ks, rec, tips], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)


def hero_chip(icon, text):
    return ft.Container(ft.Row([ft.Icon(icon, size=14, color="#DCE6F5"), ft.Text(text, size=12, color="#F1F5FB")],
                               spacing=4, tight=True), bgcolor="#33FFFFFF", border_radius=20,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4))


def way(icon, tone, title, sub, on_click):
    return ft.Container(ft.Column([T.icon_tile(icon, tone, 44), ft.Text(title, size=15, weight=ft.FontWeight.W_700),
                                   T.muted(sub, 12)], spacing=6), padding=16, bgcolor=T.CARD, border_radius=16,
                        border=ft.Border.all(1, T.LINE), expand=True, ink=True, on_click=on_click)


def tip(title, text):
    return ft.Row([ft.Icon(I.CHECK_CIRCLE_OUTLINE, size=18, color=T.ACCENT),
                   ft.Text(title, size=13, weight=ft.FontWeight.W_700, width=110), ft.Text(text, size=13, expand=True)],
                  vertical_alignment=ft.CrossAxisAlignment.START)
