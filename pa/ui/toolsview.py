"""模型工具：檢查與修復（開檔）、Bambu 3MF → GLB、MakerWorld／Printables 搜尋、AI 文字／圖片轉 3D。"""
import os
import threading

import flet as ft

from .. import checks, mesh3d, secrets, tools3d
from . import theme as T
from .workbench import ModelPanel

I = ft.Icons


def _bg(ctx, job, done=None, busy=None):
    if busy:
        busy.visible = True
        T.safe_update(busy)

    def go():
        try:
            r = job()
            if done:
                done(r)
        except (tools3d.ToolError, ValueError) as e:
            ctx.toast(str(e), True)
        except Exception as e:
            import logging
            logging.getLogger("pa").exception("tool")
            ctx.toast("發生錯誤：%s" % e, True)
        finally:
            if busy:
                busy.visible = False
                T.safe_update(busy)
    threading.Thread(target=go, daemon=True).start()


async def pick_path(ctx, title, exts, multiple=False):
    files = await ft.FilePicker().pick_files(dialog_title=title, allowed_extensions=exts, allow_multiple=multiple)
    out = []
    for f in files or []:
        if f.path and os.path.isfile(f.path):
            out.append(f.path)
    return out if multiple else (out[0] if out else None)


# ====================================================================== 模型檢查與修復
class CheckScreen(ft.Row):
    def __init__(self, ctx, path=None, design=None, **kw):
        self.ctx = ctx
        self.panel = ModelPanel(ctx, height=470)
        self.panel.kind = "FILE"
        self.orig = None
        self.notes = ft.Column(spacing=4)
        self.height_f = T.field("縮放到高度", "", width=130, suffix="mm")
        self.unit = T.dropdown("檔案單位", [("1", "mm（一般）"), ("10", "公分 ×10"), ("25.4", "英吋 ×25.4"),
                                          ("1000", "公尺 ×1000")], "1", width=150, filterable=False)
        self.sw_repair = T.switch("修復破洞與翻面", True)
        self.sw_orient = T.switch("自動擺放（平底朝下）", True)
        self.sw_main = T.switch("只保留最大實體（移除碎片）", False)
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        left = T.card(ft.Column([
            ft.Text("1. 開啟模型", size=15, weight=ft.FontWeight.W_700),
            T.muted("STL、3MF（含 Bambu 多色）、OBJ、GLB、PLY", 12),
            ft.Row([T.btn("開啟檔案", I.FOLDER_OPEN, lambda e: self.page.run_task(self.open_file)),
                    T.btn("還原", I.UNDO, lambda e: self.revert(), kind="ghost")]),
            ft.Divider(height=12, color=T.LINE),
            ft.Text("2. 調整（下載或 AI 產生的模型建議都做）", size=15, weight=ft.FontWeight.W_700),
            self.unit, self.height_f, self.sw_repair, self.sw_orient, self.sw_main,
            T.btn("套用並重新檢查", I.AUTO_FIX_HIGH, lambda e: self.apply(), kind="accent"),
            self.busy, ft.Divider(height=12, color=T.LINE),
            ft.Text("處理紀錄", size=13, weight=ft.FontWeight.W_700), self.notes],
            spacing=8, scroll=ft.ScrollMode.AUTO, expand=True), padding=14, width=320)
        super().__init__([left, T.card(self.panel, padding=12, expand=True)], spacing=12, expand=True,
                         vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        if design:
            self.load_design(int(design))
        elif path:
            self.load(path)

    async def open_file(self):
        p = await pick_path(self.ctx, "開啟 3D 模型", mesh3d.OPEN_FILTER)
        if p:
            self.load(p)

    def load(self, path):
        def job():
            m = mesh3d.load(path)
            scale, note = checks.unit_guess(m)
            return m, scale, note

        def done(r):
            m, scale, note = r
            self.orig = m
            name = os.path.splitext(os.path.basename(path))[0]
            self.notes.controls = [T.muted("開啟：%s（%s 面%s）" % (os.path.basename(path), "{:,}".format(m.info()["triangles"]),
                                                              "、多色" if m.info()["colored"] else ""), 12)]
            for n in m.notes + ([note] if note else []):
                self.notes.controls.append(ft.Text("⚠️ " + n, size=12, color=T.WARN))
            self.unit.value = "1000" if scale == 1000 else "1"
            self.panel.design_id = None
            self.panel.set_model(m, name, kind="FILE", src_path=path)
            if scale != 1:
                self.apply()
            self.ctx.books.log("open_model", name, path)
            T.safe_update(self)
        _bg(self.ctx, job, done, self.busy)

    def revert(self):
        if self.orig:
            self.panel.set_model(self.orig, self.panel.ws.title, src_path=self.orig.source)
            self.notes.controls.append(T.muted("已還原成原始檔案", 12))
            T.safe_update(self)

    def apply(self):
        if not self.orig:
            self.ctx.toast("請先開啟模型", True)
            return
        try:
            h = float(self.height_f.value) if (self.height_f.value or "").strip() else None
        except ValueError:
            self.ctx.toast("高度要是數字", True)
            return

        def job():
            return checks.prepare(self.orig, height=h, repair=self.sw_repair.value, orient=self.sw_orient.value,
                                  keep_main=self.sw_main.value, unit_scale=float(self.unit.value or 1))

        def done(r):
            m, steps = r
            self.panel.set_model(m, self.panel.ws.title, src_path=None, keep_view=True)
            for s in steps or ["沒有需要調整的地方"]:
                self.notes.controls.append(ft.Text("✔ " + s, size=12))
            T.safe_update(self)
        _bg(self.ctx, job, done, self.busy)

    def load_design(self, did):
        b = self.ctx.books
        try:
            d = b.design(did)
            p = b.load_revision(did)
        except Exception as e:
            self.ctx.toast(str(e), True)
            return
        self.load(p)
        self.panel.design_id = did
        self.panel.kind = d["kind"]


# ====================================================================== 3MF → GLB
class ConvertScreen(ft.Column):
    def __init__(self, ctx, **kw):
        self.ctx = ctx
        self.files = []
        self.units = T.dropdown("輸出單位", [("m", "公尺（glTF 標準，預設）"), ("mm", "毫米（1 單位＝1 mm）")], "m",
                                width=230, filterable=False)
        self.out_dir = T.field("輸出資料夾（空白＝與原檔同一個資料夾）", "", expand=True)
        self.list = ft.Column(spacing=6)
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        from .viewer import Viewer
        self.viewer = Viewer(ctx, height=360)
        self.legend = ft.Row(wrap=True, spacing=6)
        conv = T.card(ft.Column([
            ft.Row([T.icon_tile(I.PALETTE, "violet", 40), ft.Column([
                ft.Text("Bambu Studio 多色 3MF → GLB", size=16, weight=ft.FontWeight.W_700),
                T.muted("重建 Bambu 的上色筆刷（paint_color），每種耗材一個材質；Blender、Unity、three.js、Windows 3D 檢視器都能開", 12)],
                spacing=0, expand=True)]),
            ft.Row([T.btn("選擇 3MF（可多選）", I.FOLDER_OPEN, lambda e: self.page.run_task(self.pick)),
                    T.btn("選擇輸出資料夾", I.DRIVE_FOLDER_UPLOAD, lambda e: self.page.run_task(self.pick_dir), kind="outline"),
                    self.units]),
            self.out_dir, self.list,
            ft.Row([T.btn("開始轉換", I.TRANSFORM, lambda e: self.convert(), kind="accent")]), self.busy,
            T.muted("解碼器來自 bambu-3mf-to-glb（AGPL-3.0），重新實作 PrusaSlicer／Bambu Studio 的 TriangleSelector。", 11)],
            spacing=10), expand=5)
        cz = T.card(ft.Column([
            ft.Row([T.icon_tile(I.COLOR_LENS, "amber", 40), ft.Column([
                ft.Text("有紋理的模型 → AMS 多色 3MF", size=16, weight=ft.FontWeight.W_700),
                T.muted("AI 生成或下載的彩色 GLB／OBJ：偵測顏色、塗到每個三角面，並配對最接近的拓竹耗材（最多 8 色）", 12)],
                spacing=0, expand=True)]),
            ft.Row([T.btn("選擇 GLB／OBJ 並轉換", I.AUTO_AWESOME, lambda e: self.page.run_task(self.colorize), kind="outline")]),
            self.legend], spacing=10), expand=4)
        super().__init__([
            T.page_header(I.SYNC_ALT, "格式轉換", "多色 3MF 與 GLB 互轉，預覽顏色", "violet"),
            ft.Row([ft.Column([conv, cz], spacing=12, expand=5),
                    T.card(self.viewer, padding=12, expand=4)], spacing=12, expand=True,
                   vertical_alignment=ft.CrossAxisAlignment.START)], spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)

    async def pick(self):
        ps = await pick_path(self.ctx, "選擇 Bambu Studio 3MF", ["3mf"], multiple=True)
        if ps:
            self.files = ps
            self.list.controls = [ft.Row([ft.Icon(I.INSERT_DRIVE_FILE, size=16, color=T.MUTED),
                                          ft.Text(os.path.basename(p), size=13)]) for p in ps]
            T.safe_update(self)

    async def pick_dir(self):
        d = await ft.FilePicker().get_directory_path(dialog_title="輸出資料夾")
        if d:
            self.out_dir.value = d
            T.safe_update(self)

    def convert(self):
        if not self.files:
            self.ctx.toast("請先選擇 3MF 檔", True)
            return
        files, units, out = list(self.files), self.units.value or "m", (self.out_dir.value or "").strip()

        def job():
            res = []
            for i, p in enumerate(files):
                dst = os.path.join(out or os.path.dirname(p), os.path.splitext(os.path.basename(p))[0] + ".glb")
                r = mesh3d.bambu_3mf_to_glb(p, dst, units)
                res.append((p, r))
                self.list.controls[i] = ft.Row([ft.Icon(I.CHECK_CIRCLE, size=16, color=T.SUCCESS),
                                                ft.Text("%s → %s（%.1f MB）" % (os.path.basename(p), os.path.basename(dst),
                                                                               os.path.getsize(dst) / 1e6), size=13)])
                T.safe_update(self)
            return res

        def done(res):
            p, r = res[-1]
            self.viewer.set_model(mesh3d.load(r["output"]))
            stats = r.get("stats") or {}
            pal = r.get("palette") or []
            self.legend.controls = [T.color_chip("耗材 %d · %s 面" % (k, "{:,}".format(v)),
                                                 pal[k - 1] if 0 < k <= len(pal) else "#808080")
                                    for k, v in sorted(stats.items())]
            self.ctx.books.log("convert_glb", os.path.basename(p), "%d 個檔案" % len(res))
            self.ctx.toast("完成 %d 個檔案" % len(res))
            if not out:
                from .theme import open_file
                open_file(os.path.dirname(r["output"]))
            T.safe_update(self)
        _bg(self.ctx, job, done, self.busy)

    async def colorize(self):
        p = await pick_path(self.ctx, "選擇有紋理的模型", ["glb", "gltf", "obj"])
        if not p:
            return

        def job():
            out = os.path.splitext(p)[0] + "_multicolor.3mf"
            d = tools3d.colorize(p, out, 4)
            return d

        def done(d):
            f = d.get("output_file") or d.get("output")
            cols = d.get("colors") or d.get("filaments") or []
            chips = []
            for c in cols:
                if not isinstance(c, dict):
                    continue
                sf = c.get("suggested_filament") or {}
                chips.append(T.color_chip("耗材 %s：%s %s（%s%%）" % (c.get("filament"), sf.get("line", ""), sf.get("name", c.get("hex")),
                                                                 c.get("area_pct")), c.get("hex") or "#888"))
            self.legend.controls = chips or [T.muted("完成：%s" % f, 12)]
            self.viewer.set_model(mesh3d.load(f))
            self.ctx.toast("已產生多色 3MF：%s" % os.path.basename(f))
            T.safe_update(self)
        _bg(self.ctx, job, done, self.busy)


# ====================================================================== 模型搜尋
class SearchScreen(ft.Column):
    def __init__(self, ctx, q="", **kw):
        self.ctx = ctx
        self.q = T.field("搜尋（英文效果最好，例如 cable organizer、phone stand）", q, expand=True,
                         prefix_icon=I.SEARCH, on_submit=lambda e: self.search())
        self.sort = T.dropdown("排序", [("downloads", "下載數"), ("likes", "按讚數"), ("newest", "最新"),
                                      ("relevance", "相關度")], "downloads", width=130, filterable=False)
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        self.grid = ft.GridView(expand=True, max_extent=270, child_aspect_ratio=0.78, spacing=12, run_spacing=12)
        super().__init__([
            T.page_header(I.TRAVEL_EXPLORE, "模型搜尋", "日常用品先找現成設計：經過很多人列印驗證，通常比自動產生的好", "teal"),
            ft.Row([self.q, self.sort, T.btn("搜尋", I.SEARCH, lambda e: self.search())]),
            T.muted("同時搜尋 MakerWorld 與 Printables，只傳送搜尋字詞。下載檔案請到網站上（多半要登入）；要販售列印品請注意授權。", 12),
            self.busy, self.grid], spacing=10, expand=True)
        if q:
            self.search()

    def search(self):
        from ..agent import translate_query
        q = translate_query((self.q.value or "").strip())
        if not q:
            self.ctx.toast("請輸入要找的東西", True)
            return

        def job():
            return tools3d.search_models(q, 24, self.sort.value or "downloads")

        def done(r):
            self.grid.controls = [self._card(x) for x in r["results"]] or [T.empty_state(I.SEARCH_OFF, "找不到結果")]
            if r["failed"]:
                self.ctx.toast("部分網站沒有回應：%s" % "、".join(r["failed"]), True)
            self.ctx.books.log("search", q, "%d 筆" % len(r["results"]))
            T.safe_update(self)
        _bg(self.ctx, job, done, self.busy)

    def _card(self, x):
        site = tools3d.SEARCH_SITES.get(x.get("site"), x.get("site"))
        img = ft.Image(src=x["thumbnail"], height=150, fit=ft.BoxFit.COVER, border_radius=10,
                       error_content=ft.Container(ft.Icon(I.IMAGE_NOT_SUPPORTED, color=T.MUTED), height=150,
                                                  alignment=ft.Alignment.CENTER)) if x.get("thumbnail") else \
            ft.Container(ft.Icon(I.VIEW_IN_AR, size=48, color=T.MUTED), height=150, alignment=ft.Alignment.CENTER)
        return ft.Container(ft.Column([
            img, ft.Text(x["title"], size=13, weight=ft.FontWeight.W_700, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Row([T.chip(site, "green" if x.get("site") == "makerworld" else "orange"),
                    T.muted("⬇ %s" % "{:,}".format(x.get("downloads") or 0), 11),
                    T.muted("♥ %s" % "{:,}".format(x.get("likes") or 0), 11)], spacing=6),
            T.muted("%s · %s" % (x.get("author") or "", x.get("license") or "未標示授權"), 11)], spacing=4),
            padding=10, bgcolor=T.CARD, border_radius=14, border=ft.Border.all(1, T.LINE), ink=True,
            on_click=lambda e, u=x["url"]: self.ctx.open_url(u), tooltip="到網站查看與下載")


# ====================================================================== AI 生成
class AIGenScreen(ft.Row):
    def __init__(self, ctx, **kw):
        self.ctx = ctx
        self.panel = ModelPanel(ctx, height=430)
        self.panel.kind = "AI"
        self.mode = ft.RadioGroup(value="text", content=ft.Row([ft.Radio(value="text", label="文字轉 3D"),
                                                               ft.Radio(value="image", label="照片轉 3D")]),
                                  on_change=lambda e: self._mode())
        self.prompt = T.field("描述（英文較準確，主體在前，再寫造型與細節）", "", multiline=True, min_lines=3,
                              hint_text="a cute sitting cat figurine, chibi style, smooth surfaces, no thin parts")
        self.image = None
        self.img_btn = T.btn("選擇照片（單一物件、乾淨背景）", I.ADD_PHOTO_ALTERNATE,
                             lambda e: self.page.run_task(self.pick_img), kind="outline", visible=False)
        self.height_f = T.field("高度", "60", width=110, suffix="mm")
        prov = secrets.get("ai3d_provider", "meshy")
        self.provider = T.dropdown("AI 供應商", list(tools3d.PROVIDERS.items()), prov, width=200, filterable=False)
        self.colors = T.switch("產生 AMS 多色 3MF（依紋理顏色）", False)
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        self.msg = ft.Text("", size=12, color=T.MUTED)
        keys = [n for k, n in tools3d.PROVIDERS.items() if tools3d.ai_key(k)]
        left = T.card(ft.Column([
            ft.Text("AI 文字／照片轉 3D", size=16, weight=ft.FontWeight.W_700),
            T.muted("適合人物、動物、擺件等有機造型。需要您自己的 Meshy、Tripo 或 Rodin 金鑰，每次生成會扣點數、約 1～5 分鐘。"
                    "功能性零件請用「零件設計」（免費、精確）。", 12),
            ft.Container(T.chip("已設定金鑰：%s" % "、".join(keys), "green", I.KEY) if keys else
                         T.chip("尚未設定金鑰 → AI 與印表機設定", "rose", I.KEY_OFF),
                         on_click=lambda e: ctx.app.go("aiset")),
            self.mode, self.prompt, self.img_btn, ft.Row([self.height_f, self.provider]), self.colors,
            T.btn("開始生成", I.AUTO_AWESOME, lambda e: self.generate(), kind="accent"),
            self.busy, self.msg], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True), padding=14, width=360)
        super().__init__([left, T.card(self.panel, padding=12, expand=True)], spacing=12, expand=True,
                         vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    def _mode(self):
        img = self.mode.value == "image"
        self.img_btn.visible = img
        self.prompt.label = "補充說明（只有 Rodin 會用到）" if img else "描述（英文較準確，主體在前，再寫造型與細節）"
        T.safe_update(self)

    async def pick_img(self):
        p = await pick_path(self.ctx, "選擇照片", ["png", "jpg", "jpeg", "webp"])
        if p:
            self.image = p
            self.img_btn.text = os.path.basename(p)
            T.safe_update(self)

    def generate(self):
        b = self.ctx.books
        if not b.can("TOOL", 2):
            self.ctx.toast("沒有使用 AI 生成的權限", True)
            return
        try:
            h = float(self.height_f.value)
        except (TypeError, ValueError):
            self.ctx.toast("請先決定高度（mm）：AI 最常弄錯的就是大小", True)
            return
        kind = self.mode.value
        src = self.image if kind == "image" else (self.prompt.value or "").strip()
        if not src:
            self.ctx.toast("請輸入描述或選擇照片", True)
            return
        prov = self.provider.value or "meshy"
        if not tools3d.ai_key(prov):
            self.ctx.toast("尚未設定 %s 的金鑰" % tools3d.PROVIDERS[prov], True)
            return

        def go():
            self.msg.value = "%s 生成中，約需 1～5 分鐘（可以先做別的事，完成後會出現在右邊）…" % tools3d.PROVIDERS[prov]

            def job():
                d = tools3d.generate(kind, src, prov, h, extra_prompt=(self.prompt.value or "") if kind == "image" else "")
                path = d["output_file"]
                if self.colors.value:
                    c = tools3d.colorize(path, None, 4, h)
                    path = c.get("output_file") or c.get("output") or path
                m = mesh3d.load(path)
                m, steps = checks.prepare(m, height=h, orient=True)
                return m, path, d

            def done(r):
                m, path, d = r
                self.msg.value = "完成：%s（工作編號 %s）。AI 模型是草稿，請在右邊檢查後再送 Bambu Studio。" % (
                    os.path.basename(path), d.get("task_id"))
                self.panel.set_model(m, (self.prompt.value or os.path.basename(path))[:40], kind="AI",
                                     src_path=path if path.lower().endswith(".3mf") else None)
                b.log("ai_generate", prov, d.get("task_id") or "")
                T.safe_update(self)
            _bg(self.ctx, job, done, self.busy)
            T.safe_update(self)
        self.ctx.confirm("確認 AI 生成", "要用 %s 產生「%s」、高 %g mm 嗎？\n這會花費您在 %s 的點數。" % (
            tools3d.PROVIDERS[prov], os.path.basename(src) if kind == "image" else src[:60], h, tools3d.PROVIDERS[prov]),
            go, yes="開始生成", danger=False)


