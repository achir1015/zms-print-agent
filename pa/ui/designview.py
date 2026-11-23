"""零件設計：選零件種類 → 調整參數（即時重建模型） → 檢查 → Bambu Studio／存設計庫。"""
import threading

import flet as ft

from .. import mesh3d, recipes
from . import theme as T
from .workbench import ModelPanel

I = ft.Icons
CAT_TONE = {"收納": "amber", "外殼": "blue", "基本": "slate", "五金": "violet", "壁掛": "teal", "桌面": "rose",
            "居家": "green", "工坊": "orange", "機構": "pink"}


class DesignScreen(ft.Row):
    def __init__(self, ctx, recipe=None, design=None, **kw):
        self.ctx = ctx
        self.rid = recipe or "storage_box"
        self.values = {}
        self.inputs = {}
        self._timer = None
        self._gen = 0
        self.cat = None
        self.panel = ModelPanel(ctx, height=430)
        self.gallery = ft.ListView(expand=True, spacing=4)
        self.cats = ft.Row(wrap=True, spacing=6, run_spacing=6)
        self.form = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self.form_head = ft.Column(spacing=4)
        left = T.card(ft.Column([ft.Text("零件庫", size=15, weight=ft.FontWeight.W_700), self.cats, self.gallery],
                                spacing=8, expand=True), padding=12, width=250)
        mid = T.card(ft.Column([self.form_head, ft.Divider(height=1, color=T.LINE), self.form,
                                ft.Row([T.btn("回到預設值", I.RESTART_ALT, lambda e: self.pick(self.rid), kind="ghost")])],
                               spacing=8, expand=True), padding=14, width=360)
        right = T.card(self.panel, padding=12, expand=True)
        super().__init__([left, mid, right], spacing=12, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.render_gallery()
        if design:
            self.load_design(int(design))
        else:
            self.pick(self.rid)

    # ------------------------------------------------------------------ 零件庫
    def render_gallery(self):
        self.cats.controls = [T.color_chip("全部", T.PRIMARY, selected=self.cat is None,
                                           on_click=lambda e: self.set_cat(None))] + [
            T.color_chip(c, T.TONES.get(CAT_TONE.get(c, "blue"))[1], selected=self.cat == c,
                         on_click=lambda e, c=c: self.set_cat(c)) for c in recipes.CATEGORIES]
        items = []
        for r in recipes.RECIPES:
            if self.cat and r.category != self.cat:
                continue
            sel = r.id == self.rid
            items.append(ft.Container(ft.Row([
                T.icon_tile(getattr(I, r.icon, I.VIEW_IN_AR), CAT_TONE.get(r.category, "blue"), 34),
                ft.Column([ft.Text(r.name, size=13, weight=ft.FontWeight.W_700 if sel else ft.FontWeight.W_500),
                           T.muted(r.category, 11)], spacing=0, expand=True)], spacing=10),
                padding=8, border_radius=10, ink=True, bgcolor="#E3ECF8" if sel else None,
                on_click=lambda e, i=r.id: self.pick(i)))
        self.gallery.controls = items

    def set_cat(self, c):
        self.cat = c
        self.render_gallery()
        T.safe_update(self)

    def pick(self, rid, values=None):
        r = recipes.BY_ID[rid]
        self.rid = rid
        self.values = r.clean(values or {})
        self.panel.design_id = None if values is None else self.panel.design_id
        self.panel.title.value = r.name if values is None else self.panel.title.value
        self.form_head.controls = [ft.Row([T.icon_tile(getattr(I, r.icon, I.VIEW_IN_AR), CAT_TONE.get(r.category, "blue"), 40),
                                           ft.Column([ft.Text(r.name, size=18, weight=ft.FontWeight.W_800),
                                                      T.chip(r.category, CAT_TONE.get(r.category, "blue"))],
                                                     spacing=2, expand=True)]),
                                   T.muted(r.desc, 12)]
        self.inputs = {}
        rows = []
        for p in r.params:
            rows.append(self._param_row(p))
        self.form.controls = rows
        self.render_gallery()
        self.rebuild(now=True)
        T.safe_update(self)

    def _param_row(self, p):
        v = self.values[p.key]
        if p.kind == "bool":
            sw = T.switch(p.label, v, on_change=lambda e, k=p.key: self.changed(k, e.control.value))
            self.inputs[p.key] = sw
            return sw
        val = ft.TextField(value="%g" % v, width=86, dense=True, text_align=ft.TextAlign.RIGHT, suffix=p.unit or None,
                           border_radius=8, text_size=13, on_submit=lambda e, k=p.key: self.typed(k, e.control.value),
                           on_blur=lambda e, k=p.key: self.typed(k, e.control.value))
        steps = int(round((p.hi - p.lo) / p.step)) if p.step else None
        sl = ft.Slider(value=float(v), min=float(p.lo), max=float(p.hi), divisions=steps if steps and steps <= 400 else None,
                       expand=True, active_color=T.PRIMARY,
                       on_change=lambda e, k=p.key, t=val, pp=p: self._slide(pp, t, e.control.value),
                       on_change_end=lambda e, k=p.key: self.changed(k, e.control.value))
        self.inputs[p.key] = (sl, val)
        return ft.Column([ft.Row([ft.Text(p.label, size=13, weight=ft.FontWeight.W_600, expand=True),
                                  ft.Text("%g～%g" % (p.lo, p.hi), size=11, color=T.MUTED)]),
                          ft.Row([sl, val], spacing=4)] + ([T.muted(p.doc, 11)] if p.doc else []), spacing=0)

    def _slide(self, p, tf, v):
        v = round(round(v / p.step) * p.step, 3) if p.step else v
        tf.value = "%g" % (int(v) if p.kind == "int" else v)
        tf.update()

    def typed(self, key, text):
        try:
            v = float(text)
        except (TypeError, ValueError):
            self.ctx.toast("請輸入數字", True)
            return
        self.changed(key, v)

    def changed(self, key, v):
        r = recipes.BY_ID[self.rid]
        self.values[key] = v
        self.values = r.clean(self.values)
        x = self.inputs.get(key)
        if isinstance(x, tuple):
            x[0].value = float(self.values[key])
            x[1].value = "%g" % self.values[key]
        self.rebuild()
        T.safe_update(self)

    # ------------------------------------------------------------------ 建模（背景、只保留最新一次）
    def rebuild(self, now=False):
        self._gen += 1
        gen = self._gen
        rid, vals = self.rid, dict(self.values)

        def job():
            try:
                v, parts = recipes.build(rid, vals)
                m = mesh3d.from_manifold(parts, "recipe:" + rid)
            except Exception as e:
                self.ctx.toast("這組參數做不出零件：%s" % e, True)
                return
            if gen != self._gen:
                return
            self.panel.set_model(m, self.panel.title.value or recipes.BY_ID[rid].name, (rid, v), kind="RECIPE",
                                 keep_view=not now)
        threading.Thread(target=job, daemon=True).start()

    def load_design(self, did):
        import json
        b = self.ctx.books
        try:
            d = b.design(did)
            rev = b.revisions(did)[0]
        except Exception as e:
            self.ctx.toast(str(e), True)
            self.pick(self.rid)
            return
        if not d["recipe_id"] or d["recipe_id"] not in recipes.BY_ID:
            self.ctx.toast("這個設計不是參數化零件，改到「模型檢查與修復」開啟", True)
            self.pick(self.rid)
            return
        self.panel.design_id = did
        self.panel.title.value = d["title"]
        self.pick(d["recipe_id"], json.loads(rev["params"] or "{}"))
