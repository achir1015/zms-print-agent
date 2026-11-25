"""模型工作區（AI 代理人、零件設計、模型檢查共用）：3D 預覽＋列印前檢查＋切片估算＋開啟 Bambu Studio＋存設計庫＋匯出。"""
import os
import threading

import flet as ft

from .. import checks, mesh3d, secrets, tools3d
from ..agent import Workspace
from ..core import BizError
from . import theme as T
from .viewer import Viewer

I = ft.Icons
STATUS_ICON = {"pass": (I.CHECK_CIRCLE, T.SUCCESS), "warn": (I.WARNING_AMBER, T.WARN), "fail": (I.CANCEL, T.DANGER),
               "skipped": (I.REMOVE_CIRCLE_OUTLINE, T.MUTED)}


def score_badge(score):
    if score is None:
        return T.chip("未檢查", "slate")
    tone = "green" if score >= 8 else "amber" if score > 4 else "rose"
    return T.chip("%.1f／10 分" % float(score), tone, I.VERIFIED)


def report_view(rep, compact=False):
    if not rep:
        return T.muted("尚未檢查")
    rows = [ft.Row([score_badge(rep["score"]),
                    T.muted("%s · %s · %s mm%s" % (rep["printer"], rep["material"],
                                                  " × ".join("%g" % x for x in rep["size"]),
                                                  " · 約 %g g" % rep["weight_g"] if rep.get("weight_g") else ""), 12)],
                   spacing=8, wrap=True)]
    for it in rep["items"]:
        if compact and it["status"] == "pass":
            continue
        ic, col = STATUS_ICON.get(it["status"], STATUS_ICON["skipped"])
        rows.append(ft.Row([ft.Icon(ic, color=col, size=17),
                            ft.Text(it["name"], size=13, weight=ft.FontWeight.W_600, width=74),
                            ft.Text(it["text"], size=12, color=T.TEXT, expand=True, selectable=True)],
                           vertical_alignment=ft.CrossAxisAlignment.START, spacing=6))
    if compact and all(i["status"] == "pass" for i in rep["items"]):
        rows.append(ft.Row([ft.Icon(I.CHECK_CIRCLE, color=T.SUCCESS, size=17), ft.Text("七項檢查都通過", size=13)]))
    if not compact:
        rows.append(ft.Divider(height=8, color=T.LINE))
        rows.append(ft.Row([T.chip("%s：%s" % (k, v), "blue") for k, v in rep["settings"]], wrap=True, spacing=6,
                           run_spacing=6))
        for s in rep.get("suggestions") or []:
            rows.append(ft.Row([ft.Icon(I.LIGHTBULB_OUTLINE, size=16, color=T.GOLD), ft.Text(s, size=12, expand=True)]))
    return ft.Column(rows, spacing=6)


class ModelPanel(ft.Column):
    """右側面板。on_change(ws) 在模型換了之後呼叫。"""

    def __init__(self, ctx, ws=None, title_field=True, height=None, on_saved=None, compact=False):
        self.ctx = ctx
        b = ctx.books
        comp = b.company()
        self.ws = ws or Workspace(comp.get("default_printer") or "A1", comp.get("default_material") or "PLA")
        self.kind = "RECIPE"
        self.src_path = None
        self.design_id = None
        self.on_saved = on_saved
        self.compact = compact
        self.viewer = Viewer(ctx, height=height or 380)
        self.title = T.field("設計名稱", "", expand=True) if title_field else None
        self.printer = T.dropdown("印表機", [(k, k) for k in checks.printer_keys()],
                                  self.ws.printer, width=200, on_select=lambda e: self._opt(), filterable=False)
        self.material = T.dropdown("耗材", [(k, k) for k in checks.material_keys()], self.ws.material, width=120,
                                   on_select=lambda e: self._opt(), filterable=False)
        self.purpose = T.dropdown("用途", list(checks.PURPOSES.items()), "general", width=110,
                                  on_select=lambda e: self._opt(), filterable=False)
        self.report_box = ft.Container(T.muted("尚未檢查"), padding=ft.Padding.only(top=4))
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        self.est = ft.Text("", size=12, color=T.PRIMARY, weight=ft.FontWeight.W_600)
        p = b.can("PRINT", 1)
        acts = [T.btn("Bambu Studio", I.OPEN_IN_NEW, lambda e: self.open_bambu(), bgcolor="#00AE42",
                      tooltip="存成 3MF 並在 Bambu Studio 開啟，由您檢查、切片、按列印")] if p else []
        acts += [T.btn("切片估算", I.TIMER, lambda e: self.slice(), kind="outline",
                       tooltip="用 Bambu Studio 的切片引擎估算時間與克數（約 30 秒）")] if p else []
        if b.can("DESIGN", 2):
            acts.append(T.btn("存到設計庫", I.SAVE, lambda e: self.save(), kind="outline"))
        if b.can("TOOL", 1):
            acts.append(T.btn("分區編輯", I.DASHBOARD_CUSTOMIZE, lambda e: self.to_regions(), kind="outline",
                              tooltip="把這個模型分成區塊，一塊一塊修改（刪除、縮放、上色、鑽孔…）"))
        acts.append(ft.PopupMenuButton(content=T.btn("匯出", I.DOWNLOAD, None, kind="outline"), items=[
            ft.PopupMenuItem(n, on_click=lambda e, x=x: self.page.run_task(self.export, x))
            for x, n in ((".3mf", "3MF（Bambu Studio）"), (".stl", "STL"), (".glb", "GLB（Windows 3D 檢視器、Blender、網頁）"),
                         (".obj", "OBJ"))]))
        top = [ft.Row([self.title], spacing=8)] if self.title else []
        super().__init__(top + [
            self.viewer,
            ft.Row([self.printer, self.material, self.purpose,
                    ft.IconButton(I.FACT_CHECK, tooltip="重新檢查", on_click=lambda e: self.recheck())], spacing=8, wrap=True),
            ft.Row(acts, spacing=8, wrap=True), self.busy, self.est,
            ft.Container(self.report_box, expand=True)], spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)

    # ------------------------------------------------------------------ 模型
    def set_model(self, model, title="", recipe=None, kind=None, src_path=None, report=None, keep_view=False):
        self.ws.set_model(model, title or self.ws.title, recipe)
        if model is not None:
            try:
                self.ctx.app.last_model = (model, self.ws.title)       # 給「匯入與分區編輯」接手
            except Exception:
                pass
        if kind:
            self.kind = kind
        self.src_path = src_path
        if self.title is not None and title:
            self.title.value = title
        self.viewer.set_model(model, keep_view=keep_view)
        self.est.value = ""
        if report:
            self.ws.report = report
            self.report_box.content = report_view(report, self.compact)
            self._upd()
        elif model is not None:
            self.recheck()
        else:
            self.report_box.content = T.muted("尚未檢查")
            self._upd()

    def to_regions(self):
        if not self._need():
            return
        self.ctx.app.handoff = (self.ws.model, self._name())
        self.ctx.app.go("regions")

    def _opt(self):
        self.ws.printer = self.printer.value
        self.ws.material = self.material.value
        if self.ws.model is not None:
            self.recheck()

    def recheck(self):
        if self.ws.model is None:
            return

        def job():
            rep = checks.check(self.ws.model, self.printer.value, self.material.value, self.purpose.value)
            self.ws.report = rep
            self.report_box.content = report_view(rep, self.compact)
        self.run(job, "檢查中…")

    # ------------------------------------------------------------------ 背景工作
    def run(self, job, msg="", done=None):
        self.busy.visible = True
        if msg:
            self.est.value = msg
        self._upd()

        def go():
            try:
                r = job()
                if msg and self.est.value == msg:
                    self.est.value = ""
                if done:
                    done(r)
            except (tools3d.ToolError, BizError, ValueError) as e:
                self.est.value = ""
                self.ctx.toast(str(e), True)
            except Exception as e:
                import logging
                logging.getLogger("pa").exception("workbench")
                self.est.value = ""
                self.ctx.toast("發生錯誤：%s" % e, True)
            finally:
                self.busy.visible = False
                self._upd()
        threading.Thread(target=go, daemon=True).start()

    def _upd(self):
        try:
            T.safe_update(self)
        except Exception:
            pass

    def _need(self):
        if self.ws.model is None:
            self.ctx.toast("目前沒有模型", True)
            return False
        return True

    def _name(self):
        return (self.title.value if self.title else "") or self.ws.title or "模型"

    # ------------------------------------------------------------------ 動作
    def open_bambu(self):
        if not self._need():
            return
        self.ws.title = self._name()

        def job():
            path = self.src_path if (self.src_path and self.src_path.lower().endswith(".3mf")) else self.ws.save(".3mf")
            tools3d.open_in_bambu(path, secrets.get("bambu_path", ""))
            self.ctx.books.log("open_bambu", self.ws.title, path)
            self.ctx.toast("已在 Bambu Studio 開啟：請檢查尺寸與懸空部分、切片（Ctrl+R），再自己按列印")
        self.run(job, "開啟 Bambu Studio…")

    def slice(self):
        if not self._need():
            return
        self.ws.title = self._name()

        def job():
            path = self.ws.save(".3mf")
            q = "standard"
            d = tools3d.slice_estimate(path, self.printer.value, self.material.value, q)
            self.est.value = "⏱ 約 %s · %.1f g %s · %s" % (tools3d.fmt_duration(d["print_time_s"]), d["filament_g"],
                                                         self.material.value, d.get("process_profile") or "")
            if self.design_id:
                self.ctx.books.log_slice(self.design_id, self.ctx.books.design(self.design_id)["cur_rev"],
                                         self.printer.value, self.material.value, q, d)
        self.run(job, "Bambu Studio 切片估算中（約 30 秒）…")

    def save(self, title=None):
        if not self._need():
            return
        name = title or self._name()

        def job():
            thumb = self.viewer.snapshot(256)
            params = self.ws.recipe[1] if self.ws.recipe else {}
            rid = self.ws.recipe[0] if self.ws.recipe else ""
            did, rev = self.ctx.books.save_design(
                self.ws.model, name, self.kind, rid, params, self.ws.report, thumb, self.printer.value,
                self.material.value, design_id=self.design_id, src_path=self.src_path,
                change_note="修改參數" if self.design_id else "")
            self.design_id = did
            self.ctx.toast("已存到設計庫：#%d「%s」第 %d 版" % (did, name, rev))
            if self.on_saved:
                self.on_saved(did, rev)
        self.run(job, "儲存中…")

    async def export(self, ext):
        if not self._need():
            return
        name = self._name()
        path = await self.ctx.save_as(name, ext.lstrip("."))
        if not path:
            return

        def job():
            if self.src_path and self.src_path.lower().endswith(ext):
                import shutil
                shutil.copyfile(self.src_path, path)
            else:
                mesh3d.export(self.ws.model, path, name)
            self.ctx.books.log("export", name, os.path.basename(path))
            self.ctx.toast("已匯出：%s" % os.path.basename(path))
        self.run(job, "匯出中…")
