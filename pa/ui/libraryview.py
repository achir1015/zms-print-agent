"""設計庫：縮圖清單、版本與 SHA-256、核准凍結、切片紀錄、匯出、繼續編輯。"""
import json

import flet as ft

from .. import recipes
from ..seed import KINDS, STATUS
from . import theme as T
from .workbench import report_view, score_badge

I = ft.Icons


class Library(ft.Row):
    def __init__(self, ctx, design=None, **kw):
        self.ctx = ctx
        self.sel = None
        self.q = T.field("搜尋名稱、備註", "", expand=True, prefix_icon=I.SEARCH, on_submit=lambda e: self.reload())
        self.status = T.dropdown("狀態", [(k, v[0]) for k, v in STATUS.items()], "", width=130, blank="全部",
                                 filterable=False, on_select=lambda e: self.reload())
        self.grid = ft.GridView(expand=True, max_extent=210, child_aspect_ratio=0.74, spacing=10, run_spacing=10)
        self.detail = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        b = ctx.books
        acts = []
        if b.can("DESIGN", 2):
            acts.append(T.btn("新設計", I.ADD, lambda e: ctx.app.go("design")))
        left = ft.Column([
            T.page_header(I.COLLECTIONS_BOOKMARK, "設計庫", "每次修改存一版；核准後檔案與 SHA-256 凍結" +
                          ("（全部人的設計）" if b.can("APPROVE", 1) else "（我的設計）"), "blue", acts),
            ft.Row([self.q, self.status, ft.IconButton(I.REFRESH, on_click=lambda e: self.reload())]),
            self.grid], spacing=10, expand=3)
        super().__init__([left, T.card(self.detail, padding=16, expand=2)], spacing=14, expand=True,
                         vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.reload(refresh=False)
        if design:
            self.show(int(design), refresh=False)
        else:
            self.detail.controls = [T.empty_state(I.TOUCH_APP, "點選左邊的設計查看明細")]

    def reload(self, refresh=True):
        rows = self.ctx.books.designs(self.q.value or "", self.status.value or "")
        self.grid.controls = [self._card(r) for r in rows] or [
            T.empty_state(I.INVENTORY_2, "還沒有設計", "到「零件設計」或「AI 代理人」做一個，按「存到設計庫」")]
        if refresh:
            T.safe_update(self)

    def _card(self, r):
        st, tone = STATUS.get(r["status"], ("?", "slate"))
        thumb = ft.Image(src=bytes(r["thumb"]), height=130, fit=ft.BoxFit.CONTAIN) if r.get("thumb") else \
            ft.Container(ft.Icon(I.VIEW_IN_AR, size=50, color=T.MUTED), height=130, alignment=ft.Alignment.CENTER)
        return ft.Container(ft.Column([
            ft.Container(thumb, bgcolor="#EEF3F9", border_radius=10),
            ft.Text(r["title"], size=13, weight=ft.FontWeight.W_700, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Row([T.chip(st, tone), T.muted("v%d" % r["cur_rev"], 11),
                    T.muted("%s 分" % r["score"] if r["score"] is not None else "", 11)], spacing=6),
            T.muted("#%d · %s" % (r["id"], T.show(r["updated_at"])), 11)], spacing=4),
            padding=8, border_radius=14, bgcolor=T.CARD, ink=True,
            border=ft.Border.all(2 if r["id"] == self.sel else 1, T.PRIMARY if r["id"] == self.sel else T.LINE),
            on_click=lambda e, i=r["id"]: self.show(i))

    def show(self, did, refresh=True):
        b = self.ctx.books
        try:
            d = b.design(did)
            revs = b.revisions(did)
        except Exception as e:
            self.ctx.toast(str(e), True)
            return
        self.sel = did
        st, tone = STATUS.get(d["status"], ("?", "slate"))
        cur = revs[0] if revs else None
        rep = None
        if cur:
            r = b.db.row("SELECT check_json FROM pa_revision WHERE design_id=%s AND rev=%s", (did, cur["rev"]))
            if r and r["check_json"]:
                try:
                    rep = json.loads(r["check_json"])
                except ValueError:
                    rep = None
        mine = d["owner"] == b.uid or b.can("APPROVE", 2)
        acts = []
        recipe = d["recipe_id"] in recipes.BY_ID
        if mine and d["status"] != "VOID":
            acts.append(T.btn("繼續編輯", I.EDIT, lambda e: self.ctx.app.go("design" if recipe else "check", design=did)))
        acts.append(T.btn("開到 Bambu Studio", I.OPEN_IN_NEW, lambda e: self.open_bambu(did), bgcolor="#00AE42"))
        acts.append(T.btn("匯出檔案", I.DOWNLOAD, lambda e: self.page.run_task(self.export, did, d["cur_rev"]), kind="outline"))
        if b.can("APPROVE", 2) and d["status"] in ("DRAFT", "PRINTED"):
            acts.append(T.btn("核准（凍結）", I.VERIFIED, lambda e: self.status_to(did, "APPROVED"), kind="accent"))
        more = []
        if mine:
            more += [ft.PopupMenuItem("改名稱與備註", icon=I.DRIVE_FILE_RENAME_OUTLINE, on_click=lambda e: self.rename(d)),
                     ft.PopupMenuItem("標記為已列印", icon=I.PRINT, on_click=lambda e: self.status_to(did, "PRINTED")),
                     ft.PopupMenuItem("作廢", icon=I.BLOCK, on_click=lambda e: self.status_to(did, "VOID"))]
            if d["status"] == "APPROVED" and b.can("APPROVE", 2):
                more.append(ft.PopupMenuItem("取消核准（改回草稿）", icon=I.UNDO, on_click=lambda e: self.status_to(did, "DRAFT")))
            if d["status"] != "APPROVED":
                more.append(ft.PopupMenuItem("刪除", icon=I.DELETE, on_click=lambda e: self.delete(d)))
        slices = b.slices(did)
        self.detail.controls = [
            ft.Row([ft.Column([ft.Text(d["title"], size=20, weight=ft.FontWeight.W_800),
                               ft.Row([T.chip(st, tone), T.chip(KINDS.get(d["kind"], d["kind"]), "blue"),
                                       score_badge(float(d["score"]) if d["score"] is not None else None)], spacing=6)],
                              spacing=4, expand=True),
                    ft.PopupMenuButton(items=more) if more else ft.Container()]),
            ft.Image(src=bytes(d["thumb"]), height=210, fit=ft.BoxFit.CONTAIN) if d.get("thumb") else ft.Container(),
            ft.Row(acts, wrap=True, spacing=8, run_spacing=8),
            T.muted("#%d · 建立人 %s · %s · %s mm%s%s" % (
                did, d["owner"], T.show(d["created_at"]), d["size_mm"],
                " · 約 %s g" % d["weight_g"] if d["weight_g"] is not None else "",
                " · 核准：%s %s" % (d["approved_by"], T.show(d["approved_at"])) if d["approved_by"] else ""), 12),
            ft.Text(d["note"] or "", size=13) if d.get("note") else ft.Container(),
            ft.Text("列印前檢查（目前版本）", size=14, weight=ft.FontWeight.W_700),
            report_view(rep) if rep else T.muted("沒有檢查紀錄"),
            ft.Text("版本", size=14, weight=ft.FontWeight.W_700),
            *[ft.Container(ft.Column([
                ft.Row([ft.Text("v%d" % r["rev"], weight=ft.FontWeight.W_700), T.muted(T.show(r["created_at"]), 12),
                        T.muted(r["created_by"], 12), T.muted(r["change_note"], 12),
                        ft.Container(expand=True),
                        ft.IconButton(I.DOWNLOAD, icon_size=18, tooltip="匯出這一版",
                                      on_click=lambda e, rv=r["rev"]: self.page.run_task(self.export, did, rv))]),
                ft.Text("%s · %.1f KB · SHA-256 %s" % (r["file_name"], r["file_size"] / 1024, r["file_sha256"]),
                        size=11, color=T.MUTED, selectable=True)], spacing=0),
                padding=8, border_radius=10, bgcolor="#F7F9FC") for r in revs],
            ft.Text("切片估算紀錄", size=14, weight=ft.FontWeight.W_700) if slices else ft.Container(),
            *[T.muted("%s · v%d · %s %s · 約 %s · %.1f g" % (T.show(s["at"]), s["rev"], s["printer"], s["material"],
                                                            _dur(s["print_s"]), float(s["grams"])), 12) for s in slices]]
        self.reload(refresh=False)
        if refresh:
            T.safe_update(self)

    def status_to(self, did, st):
        if self.ctx.guard(self.ctx.books.set_status, did, st, ok="已更新狀態"):
            self.show(did)

    def open_bambu(self, did):
        from .. import secrets, tools3d
        try:
            p = self.ctx.books.load_revision(did)
            tools3d.open_in_bambu(p, secrets.get("bambu_path", ""))
            self.ctx.toast("已在 Bambu Studio 開啟，請檢查、切片後自己按列印")
        except Exception as e:
            self.ctx.toast(str(e), True)

    async def export(self, did, rev):
        b = self.ctx.books
        try:
            _, name, _ = b.revision_file(did, rev)
        except Exception as e:
            self.ctx.toast(str(e), True)
            return
        ext = name.rsplit(".", 1)[-1]
        path = await self.ctx.save_as(name.rsplit(".", 1)[0] + "_v%d" % rev, ext)
        if path:
            sha = b.export_revision(did, rev, path)
            self.ctx.toast("已匯出（SHA-256 %s…）" % sha[:12])

    def rename(self, d):
        t = T.field("名稱", d["title"])
        n = T.field("備註", d["note"] or "", multiline=True, min_lines=2)

        def save(e):
            if self.ctx.guard(self.ctx.books.rename_design, d["id"], t.value, n.value):
                self.ctx.close()
                self.show(d["id"])
        self.ctx.dialog("修改名稱與備註", ft.Column([t, n], tight=True, spacing=12),
                        [T.btn("取消", kind="ghost", on_click=lambda e: self.ctx.close()), T.btn("儲存", I.SAVE, save)],
                        icon=I.EDIT, width=460)

    def delete(self, d):
        def go():
            if self.ctx.guard(self.ctx.books.delete_design, d["id"], ok="已刪除"):
                self.sel = None
                self.detail.controls = [T.empty_state(I.TOUCH_APP, "點選左邊的設計查看明細")]
                self.reload()
        self.ctx.confirm("刪除設計", "確定要刪除「%s」和它的所有版本嗎？刪除後無法復原（可從備份還原）。" % d["title"], go, yes="刪除")


def _dur(s):
    m = max(1, round((s or 0) / 60))
    h, mm = divmod(m, 60)
    return ("%d 小時 %d 分" % (h, mm)) if h else ("%d 分鐘" % mm)
