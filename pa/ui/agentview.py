"""AI 代理人：用一句話描述要印的東西 → 代理人設計、檢查、搜尋、估算，右邊即時顯示模型。"""
import threading

import flet as ft

from .. import ctxstore, secrets
from ..agent import Agent, MODEL
from . import theme as T
from .workbench import ModelPanel

I = ft.Icons

EXAMPLES = ["設計一個尺寸為 60×40×30 毫米、帶蓋的電子元件盒", "做一個 M3 螺絲用的 L 型支架，寬 30",
            "縮放到 12 公分高，檢查是否適合我的 A1 Mini", "在 MakerWorld 幫我找好用的電線整理器",
            "設計桌下耳機掛鉤，桌板下方要留 35 mm", "設計額溫槍外殼，用 GOOUUU ESP32-S3 開發板", "我的列印完成了嗎？還剩多久？"]


class AgentScreen(ft.Row):
    def __init__(self, ctx, chat=None, text=None, **kw):
        self.ctx = ctx
        b = ctx.books
        self.cid = None
        self.busy = False
        self.image = None
        self.panel = ModelPanel(ctx, title_field=True, height=360, compact=True,
                                on_saved=lambda did, rev: b.chat_link_design(self.cid, did))
        pr = b.default_printer()
        ctxstore.set_printer(pr)
        if pr:
            self.panel.ws.printer = pr["model"]
            self.panel.printer.value = pr["model"]
        self.agent = self._new_agent()
        self.msgs = ft.ListView(expand=True, spacing=10, auto_scroll=True, padding=ft.Padding.only(right=8))
        self.inp = ft.TextField(hint_text="描述您要印的東西，例如：設計一個 60×40×30 mm 帶蓋的盒子（Enter 送出，Shift+Enter 換行）",
                                multiline=True, min_lines=1, max_lines=5, shift_enter=True, expand=True,
                                border_radius=14, border_color="#CBD5E1", focused_border_color=T.PRIMARY, text_size=14,
                                on_submit=lambda e: self.send(), bgcolor="#FFFFFF")
        self.status = ft.Text("", size=12, color=T.ACCENT)
        self.ring = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.img_chip = ft.Container(visible=False)
        claude = Agent.use_claude()
        engine = T.chip("Claude %s" % MODEL, "violet", I.AUTO_AWESOME) if claude else \
            T.chip("本機規則（免費）", "teal", I.MEMORY)
        self.history = ft.ListView(expand=True, spacing=2)
        left = T.card(ft.Column([
            ft.Row([ft.Text("對話紀錄", size=14, weight=ft.FontWeight.W_700, expand=True),
                    ft.IconButton(I.ADD_COMMENT, tooltip="新對話", on_click=lambda e: self.new_chat())]),
            self.history], spacing=4, expand=True), padding=10, width=210)
        chat_card = T.card(ft.Column([
            ft.Row([T.icon_tile(I.SMART_TOY, "violet", 36), ft.Column([
                ft.Text("3D 列印 AI 代理人", size=17, weight=ft.FontWeight.W_800),
                T.muted("描述 → 零件 → 檢查 → Bambu Studio（列印一律由您自己按）", 12)], spacing=0, expand=True),
                engine, ft.IconButton(I.SETTINGS, tooltip="AI 與印表機設定", on_click=lambda e: ctx.app.go("aiset"))]),
            ft.Divider(height=1, color=T.LINE),
            self.msgs,
            ft.Row([self.ring, self.status], spacing=6),
            self.img_chip,
            ft.Row([ft.IconButton(I.ADD_PHOTO_ALTERNATE, tooltip="附加照片或草圖（Claude 會看圖）",
                                  on_click=lambda e: self.page.run_task(self.attach), disabled=not claude),
                    ft.IconButton(I.UPLOAD_FILE, tooltip="匯入現成模型（STL、OBJ、FBX、Maya .ma…），再請代理人分區修改",
                                  on_click=lambda e: self.page.run_task(self.import_file)),
                    self.inp, ft.IconButton(I.SEND_ROUNDED, icon_color=ft.Colors.WHITE, bgcolor=T.PRIMARY,
                                            tooltip="送出", on_click=lambda e: self.send())],
                   vertical_alignment=ft.CrossAxisAlignment.END)], spacing=8, expand=True), padding=14, expand=5)
        right = T.card(self.panel, padding=12, expand=4)
        super().__init__([left, chat_card, right], spacing=12, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.load_history()
        if chat:
            self.open_chat(int(chat))
        else:
            self.welcome()
        if text:
            self.inp.value = text

    def _new_agent(self, history=None):
        return Agent(self.panel.ws, on_model=self._on_model, on_status=self._on_status, confirm=self._confirm,
                     history=history)

    # ------------------------------------------------------------------ 畫面
    def welcome(self):
        self.msgs.controls = [bubble("agent", (
            "您好！我是 3D 列印 AI 代理人。用一句話告訴我想印什麼、大概多大，我會設計零件、做七項列印前檢查，"
            "滿意後幫您開在 Bambu Studio（列印由您自己按）。\n\n"
            + ("目前使用 Claude，可以自由描述，也可以附照片或草圖。" if Agent.use_claude() else
               "目前用的是免費的本機規則；到「AI 與印表機設定」填入 Claude API 金鑰，就能理解更自由的描述。"))),
            ft.Row([ft.Container(ft.Text(x, size=12, color=T.PRIMARY), padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                                 border=ft.Border.all(1, "#C7D4E8"), border_radius=16, ink=True,
                                 on_click=lambda e, x=x: self.send(x)) for x in EXAMPLES], wrap=True, spacing=6,
                   run_spacing=6)]

    def load_history(self):
        rows = self.ctx.books.chats()
        self.history.controls = [
            ft.Container(ft.Column([ft.Text(r["title"], size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                            weight=ft.FontWeight.W_700 if r["id"] == self.cid else None),
                                    T.muted(T.show(r["updated_at"]) + (" · Claude" if r["engine"] == "CLAUDE" else ""), 11)],
                                   spacing=0), padding=8, border_radius=8, ink=True,
                         bgcolor="#E8F0FB" if r["id"] == self.cid else None,
                         on_click=lambda e, i=r["id"]: self.open_chat(i)) for r in rows] or [T.muted("還沒有對話", 12)]

    def new_chat(self):
        self.cid = None
        self.agent = self._new_agent()
        self.welcome()
        self.load_history()
        T.safe_update(self)

    def open_chat(self, cid):
        import json
        try:
            c = self.ctx.books.chat(cid)
        except Exception as e:
            self.ctx.toast(str(e), True)
            return
        self.cid = cid
        hist = []
        if c.get("raw"):
            try:
                hist = json.loads(c["raw"])
            except ValueError:
                hist = []
        self.agent = self._new_agent(hist)
        self.msgs.controls = [bubble(m["role"], m["text"], m["tools"]) for m in c["msgs"]]
        if c.get("design_id"):
            try:
                from .. import mesh3d
                d = self.ctx.books.design(c["design_id"])
                p = self.ctx.books.load_revision(d["id"])
                self.panel.design_id = d["id"]
                self.panel.set_model(mesh3d.load(p), d["title"], src_path=p)
            except Exception:
                pass
        self.load_history()
        T.safe_update(self)

    async def import_file(self):
        from .. import mesh3d
        from .toolsview import pick_path
        path = await pick_path(self.ctx, "匯入現成模型", mesh3d.OPEN_FILTER)
        if path:
            self.send("匯入 %s" % path)

    async def attach(self):
        name, data = await self.ctx.pick_bytes("選擇照片或草圖", ["png", "jpg", "jpeg", "webp"])
        if not data:
            return
        import os
        import tempfile
        p = os.path.join(tempfile.gettempdir(), "pa_attach_" + name)
        with open(p, "wb") as f:
            f.write(data)
        self.image = p
        self.img_chip.content = ft.Row([ft.Image(src=data, width=48, height=48, fit=ft.BoxFit.COVER, border_radius=6),
                                        T.muted(name, 12), ft.IconButton(I.CLOSE, icon_size=16,
                                                                          on_click=lambda e: self._clear_img())])
        self.img_chip.visible = True
        T.safe_update(self)

    def _clear_img(self):
        self.image = None
        self.img_chip.visible = False
        T.safe_update(self)

    # ------------------------------------------------------------------ 對話
    def send(self, text=None):
        text = (text or self.inp.value or "").strip()
        if not text or self.busy:
            return
        if not self.ctx.books.can("AGENT", 1):
            self.ctx.toast("沒有使用 AI 代理人的權限", True)
            return
        self.inp.value = ""
        if self.msgs.controls and isinstance(self.msgs.controls[-1], ft.Row) and not self.cid:
            self.msgs.controls.pop()                      # 收起範例
        self.msgs.controls.append(bubble("user", text, image=self.image))
        img, self.image = self.image, None
        self.img_chip.visible = False
        self.busy = True
        self.ring.visible = True
        self.status.value = "思考中…"
        T.safe_update(self)
        b = self.ctx.books
        engine = "CLAUDE" if Agent.use_claude() else "LOCAL"
        self.cid = b.chat_add(self.cid, "user", text, engine=engine)

        def go():
            try:
                reply, tools = self.agent.ask(text, img)
            except Exception as e:
                import logging
                logging.getLogger("pa").exception("agent")
                reply, tools = "⚠️ %s" % e, []
            tl = "、".join(dict.fromkeys(tools))
            self.msgs.controls.append(bubble("agent", reply, tl))
            try:
                b.chat_add(self.cid, "agent", reply, tl, raw=self.agent.messages if engine == "CLAUDE" else None)
            except Exception:
                pass
            self.busy = False
            self.ring.visible = False
            self.status.value = ""
            self.load_history()
            try:
                T.safe_update(self)
            except Exception:
                pass
            if secrets.get("speak_replies") == "1":
                self.ctx.say_text(reply[:300])
        threading.Thread(target=go, daemon=True).start()

    # ------------------------------------------------------------------ 代理人回呼（背景執行緒）
    def _on_model(self, model, title):
        rec = self.agent.ws.recipe
        self.panel.kind = "AGENT"
        self.panel.set_model(model, title, rec, report=self.agent.ws.report)

    def _on_status(self, text):
        self.status.value = text
        try:
            T.safe_update(self)
        except Exception:
            pass

    def _confirm(self, question):
        ev, ans = threading.Event(), [False]

        def yes():
            ans[0] = True
            ev.set()

        def no(e=None):
            self.page.pop_dialog()
            ev.set()
        self.ctx.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("需要您確認", size=18, weight=ft.FontWeight.W_700),
            content=ft.Text(question, size=14),
            actions=[T.btn("取消", kind="ghost", on_click=no),
                     T.btn("確定（會扣點數）", on_click=lambda e: (self.page.pop_dialog(), yes()))]))
        ev.wait(600)
        return ans[0]


def bubble(role, text, tools="", image=None):
    me = role == "user"
    body = [ft.Markdown(text, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        on_tap_link=lambda e: e.page.run_task(ft.UrlLauncher().launch_url, e.data))]
    if image:
        body.insert(0, ft.Image(src=image, height=120, fit=ft.BoxFit.CONTAIN, border_radius=8))
    if tools:
        body.append(T.muted("🛠 " + tools, 11))
    box = ft.Container(ft.Column(body, spacing=4, tight=True), padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                       bgcolor="#1E4D8C" if me else "#F1F5FB", border_radius=14,
                       border=None if me else ft.Border.all(1, T.LINE))
    if me:
        box.content.controls[-1 if not image else 1].md_style_sheet = ft.MarkdownStyleSheet(
            p_text_style=ft.TextStyle(color=ft.Colors.WHITE, size=14))
    avatar = T.icon_tile(I.PERSON if me else I.SMART_TOY, "blue" if me else "violet", 30, radius=15)
    row = [ft.Container(expand=1), ft.Container(box, expand=6), avatar] if me else \
        [avatar, ft.Container(box, expand=8), ft.Container(expand=1)]
    return ft.Row(row, vertical_alignment=ft.CrossAxisAlignment.START, spacing=8)
