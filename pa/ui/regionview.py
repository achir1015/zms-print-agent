"""匯入與分區編輯：開啟現成模型（STL／OBJ＋MTL／FBX／MA／3MF／GLB…）→ 分區 → 勾選區塊逐一修改 → 存設計庫／送 Bambu Studio。

零件庫沒有的東西（例如額溫槍外殼）可以先找現成的模型匯入，再一塊一塊改：刪除、移動、縮放、旋轉、上色（多色 3MF）、
沿平面切開、鑽孔、加凸台。每一步都可以「復原」。AI 代理人也能用同樣的工具（說「分區」「第 3 區刪掉」…）。
"""
import os

import flet as ft

from .. import mesh3d, segment as S
from . import theme as T
from .toolsview import _bg, pick_path
from .workbench import ModelPanel

I = ft.Icons


class RegionScreen(ft.Row):
    def __init__(self, ctx, path=None, **kw):
        self.ctx = ctx
        self.panel = ModelPanel(ctx, height=480)
        self.panel.kind = "FILE"
        self.history = []
        self.sel = set()
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        self.method = T.dropdown("分區方法", list(S.METHODS.items()), "auto", width=290, filterable=False)
        self.target = T.field("最多幾區", "8", width=100)
        self.list = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self.log = ft.Column(spacing=2)
        # 修改參數
        self.f_x, self.f_y, self.f_z = (T.field(a, "0", width=78) for a in ("X mm", "Y mm", "Z mm"))
        self.f_factor = T.field("倍數", "1.2", width=78)
        self.f_deg = T.field("角度", "90", width=78)
        self.f_axis = T.dropdown("軸", [("x", "X"), ("y", "Y"), ("z", "Z")], "z", width=78, filterable=False)
        self.f_color = T.dropdown("顏色", [(k, k) for k in ("紅", "橙", "黃", "綠", "藍", "淺藍", "紫", "粉紅", "黑", "白", "灰", "金", "咖啡")],
                                  "黑", width=100, filterable=False)
        self.f_d = T.field("直徑 mm", "3", width=100)
        self.f_depth = T.field("深度／高 mm", "0", width=120)
        self.f_shape = T.dropdown("形狀", [("circle", "圓形"), ("box", "方形")], "circle", width=124, filterable=False)
        self.f_name = T.field("新名稱", "", width=150)

        def act(label, icon, fn, kind="outline", tip=None):
            return T.btn(label, icon, lambda e: fn(), kind=kind, tooltip=tip)
        ops = ft.Column([
            ft.Text("修改勾選的區塊", size=14, weight=ft.FontWeight.W_700),
            ft.Row([act("刪除", I.DELETE, lambda: self.do("delete"), "danger"), act("只保留", I.FILTER_CENTER_FOCUS, lambda: self.do("keep")),
                    act("合併", I.MERGE, lambda: self.do("merge"))], wrap=True, spacing=6),
            ft.Row([self.f_x, self.f_y, self.f_z, act("移動", I.OPEN_WITH, lambda: self.do("move", dx=self.num(self.f_x),
                                                                                         dy=self.num(self.f_y), dz=self.num(self.f_z)))],
                   wrap=True, spacing=6),
            ft.Row([self.f_factor, act("縮放", I.ZOOM_OUT_MAP, lambda: self.do("scale", factor=self.num(self.f_factor))),
                    self.f_axis, self.f_deg, act("旋轉", I.ROTATE_RIGHT, lambda: self.do("rotate", axis=self.f_axis.value,
                                                                                    degrees=self.num(self.f_deg)))],
                   wrap=True, spacing=6),
            ft.Row([self.f_color, act("上色（耗材）", I.FORMAT_PAINT, lambda: self.do("color", color=self.f_color.value)),
                    act("取消顏色", I.FORMAT_COLOR_RESET, lambda: self.do("uncolor"), "ghost")], wrap=True, spacing=6),
            ft.Row([self.f_name, act("改名", I.DRIVE_FILE_RENAME_OUTLINE, lambda: self.do("rename", name=self.f_name.value))],
                   spacing=6),
            ft.Divider(height=8, color=T.LINE),
            ft.Text("整個模型", size=14, weight=ft.FontWeight.W_700),
            ft.Row([self.f_shape, self.f_d, self.f_depth], wrap=True, spacing=6),
            T.muted("鑽孔：深度 0＝貫穿；加凸台：填高度（0＝5 mm）。", 11),
            ft.Row([act("在勾選區中心鑽孔", I.RADIO_BUTTON_UNCHECKED, lambda: self.hole()),
                    act("在勾選區中心加凸台", I.ADD_CIRCLE_OUTLINE, lambda: self.boss())], wrap=True, spacing=6),
            ft.Row([act("沿 X 切兩半", I.CONTENT_CUT, lambda: self.cut("x")), act("沿 Y 切兩半", I.CONTENT_CUT, lambda: self.cut("y")),
                    act("沿 Z 切兩半", I.CONTENT_CUT, lambda: self.cut("z"))], wrap=True, spacing=6),
        ], spacing=8)
        left = T.card(ft.Column([
            ft.Text("1. 匯入模型", size=15, weight=ft.FontWeight.W_700),
            T.muted("STL、OBJ（＋同名 MTL）、FBX、Maya .ma、3MF、GLB、PLY。Maya .mb 請先在 Maya 另存成 .ma 或匯出 .fbx。", 12),
            ft.Row([T.btn("開啟檔案", I.FOLDER_OPEN, lambda e: self.page.run_task(self.open_file)),
                    T.btn("用目前的模型", I.INPUT, lambda e: self.from_current(), kind="outline",
                          tooltip="把零件設計或 AI 代理人剛做好的模型拿來分區")], wrap=True),
            ft.Divider(height=10, color=T.LINE),
            ft.Text("2. 分區", size=15, weight=ft.FontWeight.W_700),
            ft.Row([self.method, self.target], wrap=True),
            ft.Row([T.btn("分區", I.DASHBOARD_CUSTOMIZE, lambda e: self.segment(), kind="accent"),
                    T.btn("復原上一步", I.UNDO, lambda e: self.undo(), kind="ghost")]),
            self.busy,
            ft.Text("處理紀錄", size=13, weight=ft.FontWeight.W_700), self.log], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=14, width=330)
        mid = T.card(ft.Column([
            ft.Row([ft.Text("3. 區塊", size=15, weight=ft.FontWeight.W_700, expand=True),
                    T.btn("全選", I.SELECT_ALL, lambda e: self.select_all(True), kind="ghost"),
                    T.btn("清除", I.DESELECT, lambda e: self.select_all(False), kind="ghost")]),
            ft.Container(self.list, height=300), ft.Divider(height=8, color=T.LINE), ops],
            spacing=8, scroll=ft.ScrollMode.AUTO, expand=True), padding=14, width=430)
        super().__init__([left, mid, T.card(self.panel, padding=12, expand=True)], spacing=12, expand=True,
                         vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        handed = getattr(ctx.app, "handoff", None)
        if path:
            self.load(path)
        elif handed:
            ctx.app.handoff = None
            self.set(handed[0], handed[1], log="從其他畫面帶過來：%s" % handed[1])

    # ------------------------------------------------------------------ 共用
    @staticmethod
    def num(f):
        try:
            return float(f.value)
        except (TypeError, ValueError):
            raise S.EditError("「%s」要是數字" % f.label)

    def note(self, text, warn=False):
        self.log.controls.append(ft.Text(("⚠️ " if warn else "✔ ") + text, size=12, color=T.WARN if warn else T.TEXT))
        self.log.controls[:] = self.log.controls[-40:]

    def set(self, model, title=None, log=None, push=False):
        if push and self.panel.ws.model is not None:
            self.history.append((self.panel.ws.model, self.panel.ws.title))
            self.history[:] = self.history[-20:]
        self.sel &= set(range(1, len(S.regions(model)) + 1))
        self.panel.set_model(model, title or self.panel.ws.title, kind="FILE", keep_view=bool(push))
        if log:
            self.note(log)
        self.render_list()
        T.safe_update(self)

    def render_list(self):
        rs = S.regions(self.panel.ws.model) if self.panel.ws.model is not None else []
        if not rs:
            self.list.controls = [T.muted("還沒分區：選分區方法後按「分區」" if self.panel.ws.model is not None else "請先匯入模型", 12)]
            return
        self.list.controls = [ft.Container(ft.Row([
            ft.Checkbox(value=r["id"] in self.sel, on_change=lambda e, i=r["id"]: self.toggle(i, e.control.value)),
            ft.Container(width=18, height=18, border_radius=9, bgcolor=r["color"], border=ft.Border.all(2, T.TEXT) if r["filament"] else None),
            ft.Column([ft.Text("%d. %s" % (r["id"], r["name"]), size=13, weight=ft.FontWeight.W_600, max_lines=1,
                               overflow=ft.TextOverflow.ELLIPSIS),
                       T.muted("%s 面 · %s mm · 中心 (%s)" % ("{:,}".format(r["faces"]), "×".join("%g" % x for x in r["size_mm"]),
                                                          ", ".join("%g" % x for x in r["center_mm"])), 11)], spacing=0, expand=True)],
            spacing=8), padding=ft.Padding.symmetric(horizontal=6, vertical=2), border_radius=8,
            bgcolor="#E3ECF8" if r["id"] in self.sel else None) for r in rs]

    def toggle(self, i, on):
        (self.sel.add if on else self.sel.discard)(i)
        self.render_list()
        self.highlight()
        T.safe_update(self)

    def select_all(self, on):
        rs = S.regions(self.panel.ws.model) if self.panel.ws.model is not None else []
        self.sel = {r["id"] for r in rs} if on else set()
        self.render_list()
        self.highlight()
        T.safe_update(self)

    def highlight(self):
        """勾選的區塊保留顏色，其他變灰，方便看清楚選了哪裡（只影響畫面）。"""
        m = self.panel.ws.model
        if m is None or not S.has_regions(m):
            return
        import numpy as np
        p = m.parts[0]
        view = mesh3d.Model([mesh3d.Part(p.name, p.mesh, p.face_rgb.copy() if p.face_rgb is not None else None)])
        if self.sel and view.parts[0].face_rgb is not None:
            dim = ~np.isin(p.labels, [i - 1 for i in self.sel])
            view.parts[0].face_rgb[dim] = (view.parts[0].face_rgb[dim] * 0.25 + 190 * 0.75).astype(np.uint8)
        self.panel.viewer.set_model(view, keep_view=True)

    # ------------------------------------------------------------------ 動作
    async def open_file(self):
        p = await pick_path(self.ctx, "匯入 3D 模型", mesh3d.OPEN_FILTER)
        if p:
            self.load(p)

    def load(self, path):
        def job():
            m = mesh3d.load(path)
            _place(m)
            return m

        def done(m):
            self.history.clear()
            self.sel.clear()
            self.log.controls.clear()
            name = os.path.splitext(os.path.basename(path))[0]
            i = m.info()
            self.note("匯入：%s（%s 面，%s mm%s）" % (os.path.basename(path), "{:,}".format(i["triangles"]),
                                                  "×".join("%g" % x for x in i["size"]), "，已有 %d 個區塊" % len(S.regions(m))
                                                  if S.has_regions(m) else ""))
            for n in m.notes:
                self.note(n, warn=True)
            if max(i["size"]) < 5:
                self.note("模型只有 %.2f mm 大，單位可能是公分或公尺：用「縮放」把全部區塊放大 10 或 1000 倍" % max(i["size"]), True)
            self.set(m, name)
            self.ctx.books.log("import_model", name, path)
        _bg(self.ctx, job, done, self.busy)

    def from_current(self):
        src = getattr(self.ctx.app, "last_model", None)
        if not src:
            self.ctx.toast("目前沒有其他畫面的模型；請先在零件設計或 AI 代理人做一個，或直接開啟檔案", True)
            return
        self.history.clear()
        self.set(src[0], src[1], log="使用目前的模型：%s" % src[1])

    def segment(self):
        m = self.panel.ws.model
        if m is None:
            self.ctx.toast("請先匯入模型", True)
            return
        try:
            target = int(float(self.target.value or 8))
        except ValueError:
            target = 8
        method = self.method.value or "auto"

        def job():
            return S.segment(m, method, target=target)

        def done(m2):
            self.sel.clear()
            self.set(m2, log="分區（%s）：%d 區" % (S.METHODS.get(method, method), len(S.regions(m2))), push=True)
        _bg(self.ctx, job, done, self.busy)

    def run(self, fn, *a, **kw):
        m = self.panel.ws.model
        if m is None:
            self.ctx.toast("請先匯入模型", True)
            return

        def job():
            return fn(m, *a, **kw)

        def done(r):
            m2, msg = r
            self.set(m2, log=msg, push=True)
        _bg(self.ctx, job, done, self.busy)

    def need_sel(self):
        if not self.sel:
            raise S.EditError("請先在區塊清單勾選要修改的區塊")
        return sorted(self.sel)

    def do(self, op, **kw):
        try:
            ids = self.need_sel()
        except S.EditError as e:
            self.ctx.toast(str(e), True)
            return
        if op == "delete":
            self.sel.clear()
        self.run(S.edit, op, ids, **kw)

    def hole(self):
        try:
            ids = self.need_sel()
            d, depth = self.num(self.f_d), self.num(self.f_depth)
        except S.EditError as e:
            self.ctx.toast(str(e), True)
            return
        self.run(S.edit, "hole", ids, diameter=d, width=d, height=d, depth=depth or None, axis=self.f_axis.value,
                 shape=self.f_shape.value)

    def boss(self):
        try:
            ids = self.need_sel()
            d, h = self.num(self.f_d), self.num(self.f_depth) or 5
        except S.EditError as e:
            self.ctx.toast(str(e), True)
            return
        self.run(S.edit, "boss", ids, diameter=d, width=d, height=h, axis=self.f_axis.value, shape=self.f_shape.value)

    def cut(self, axis):
        m = self.panel.ws.model
        if m is not None and not S.has_regions(m):
            m = S.to_single(m)
            self.panel.ws.model = m
        self.run(S.edit, "cut", None, axis=axis)

    def undo(self):
        if not self.history:
            self.ctx.toast("沒有可以復原的步驟", True)
            return
        m, title = self.history.pop()
        self.set(m, title, log="已復原上一步")


def _place(model):
    """放到列印板中央（保留分區）。"""
    import numpy as np
    lo, hi = model.combined().bounds
    d = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    for p in model.parts:
        p.mesh.apply_translation(d)
