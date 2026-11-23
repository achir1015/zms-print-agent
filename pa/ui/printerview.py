"""印表機狀態（區網唯讀）與 AI、Bambu Studio 設定。"""
import threading

import flet as ft

from .. import checks, ctxstore, secrets, tools3d
from . import theme as T

I = ft.Icons


# ====================================================================== 印表機
class Printers(ft.Row):
    def __init__(self, ctx, **kw):
        self.ctx = ctx
        self.sel = None
        self.list = ft.Column(spacing=8)
        self.status = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self.busy = ft.ProgressBar(visible=False, color=T.ACCENT)
        can = ctx.books.can("PRINT", 2)
        left = ft.Column([
            T.page_header(I.PRINT, "印表機", "區網唯讀：看進度、溫度、AMS 耗材；不能開始、暫停或改變列印", "green",
                          [T.btn("新增", I.ADD, lambda e: self.edit(None))] if can else []),
            T.card(ft.Column([self.list], scroll=ft.ScrollMode.AUTO), padding=12, expand=True),
            T.card(ft.Column([ft.Text("怎麼找到 IP、序號、存取碼？", size=13, weight=ft.FontWeight.W_700),
                              T.muted("印表機螢幕：設定 → 網路（WLAN）可以看到 IP 與「區網模式存取碼」；"
                                      "序號在 設定 → 裝置資訊。印表機維持一般模式，Bambu Handy 與雲端列印照常使用。"
                                      "存取碼只存在這台電腦，不會寫進資料庫或備份。", 12)], spacing=4), padding=12)],
            width=380, spacing=12)
        super().__init__([left, T.card(ft.Column([self.busy, self.status], expand=True), padding=16, expand=True)],
                         spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.reload(refresh=False)

    def reload(self, refresh=True):
        rows = self.ctx.books.printers()
        self.list.controls = [ft.Container(ft.Row([
            T.icon_tile(I.PRINT, "green" if r["is_default"] else "slate", 38),
            ft.Column([ft.Text(r["name"], size=14, weight=ft.FontWeight.W_700),
                       T.muted("%s · %s%s" % (r["model"], r["ip"] or "未設定 IP", " · 預設" if r["is_default"] else ""), 12)],
                      spacing=0, expand=True),
            ft.IconButton(I.EDIT, icon_size=18, on_click=lambda e, r=r: self.edit(r)) if self.ctx.books.can("PRINT", 2)
            else ft.Container()]), padding=8, border_radius=12, ink=True,
            bgcolor="#E3ECF8" if self.sel and self.sel["id"] == r["id"] else "#F7F9FC",
            on_click=lambda e, r=r: self.query(r)) for r in rows] or [T.muted("還沒有設定印表機", 13)]
        if not self.status.controls:
            self.status.controls = [T.empty_state(I.PRINT, "點選印表機讀取狀態")]
        if refresh:
            T.safe_update(self)

    def query(self, r):
        self.sel = r
        ctxstore.set_printer(r)
        self.reload(refresh=False)
        self.busy.visible = True
        self.status.controls = [T.muted("連線到 %s（%s）…" % (r["name"], r["ip"]), 13)]
        T.safe_update(self)

        def go():
            try:
                s = tools3d.printer_status(r)
                self.status.controls = status_view(r, s)
            except Exception as e:
                self.status.controls = [T.empty_state(I.WIFI_OFF, "讀不到印表機狀態", str(e))]
            self.busy.visible = False
            try:
                T.safe_update(self)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def edit(self, r):
        new = r is None
        r = r or {"id": None, "name": "", "model": "A1", "ip": "", "serial": "", "is_default": 0, "note": ""}
        name = T.field("名稱", r["name"], hint_text="例如：工作室 A1")
        model = T.dropdown("型號", [(k, checks.printer_label(k)) for k in checks.printer_keys()], r["model"],
                           filterable=False)
        ip = T.field("區網 IP", r["ip"], hint_text="192.168.1.50")
        serial = T.field("序號", r["serial"])
        has = secrets.has("printer_code_%s" % (r["serial"] or ""))
        code = T.field("區網存取碼" + ("（已設定，留白＝不變）" if has else ""), "", password=True, can_reveal_password=True)
        dflt = T.switch("設為預設印表機", r["is_default"])

        def save(e):
            pid = self.ctx.guard(self.ctx.books.save_printer, r["id"], name.value, model.value, ip.value, serial.value,
                                 dflt.value, r.get("note") or "")
            if not pid:
                return
            sn = (serial.value or "").strip().upper()
            if code.value:
                secrets.put("printer_code_%s" % sn, code.value.strip())
            self.ctx.close()
            self.ctx.toast("已儲存印表機")
            self.reload()

        def delete(e):
            self.ctx.close()
            if self.ctx.guard(self.ctx.books.delete_printer, r["id"], ok="已刪除"):
                secrets.put("printer_code_%s" % (r["serial"] or ""), "")
                self.reload()
        acts = [T.btn("取消", kind="ghost", on_click=lambda e: self.ctx.close())]
        if not new:
            acts.insert(0, T.btn("刪除", I.DELETE, delete, kind="danger"))
        acts.append(T.btn("儲存", I.SAVE, save))
        self.ctx.dialog("新增印表機" if new else "修改印表機", ft.Column([name, model, ip, serial, code, dflt],
                                                                    tight=True, spacing=12), acts, icon=I.PRINT,
                        tone="green", width=440)


def status_view(pr, s):
    st = str(s.get("state") or "UNKNOWN")
    tone = {"RUNNING": "blue", "FINISH": "green", "FAILED": "rose", "PAUSE": "amber"}.get(st, "slate")
    out = [ft.Row([T.icon_tile(I.PRINT, tone, 52), ft.Column([
        ft.Text(pr["name"], size=20, weight=ft.FontWeight.W_800),
        ft.Row([T.chip(tools3d.STATE_ZH.get(st, st), tone), T.muted(s.get("file") or "", 12)])], spacing=4, expand=True)])]
    if s.get("progress_pct") is not None and st in ("RUNNING", "PAUSE", "PREPARE"):
        out += [ft.ProgressBar(value=(s["progress_pct"] or 0) / 100, height=10, border_radius=5, color=T.ACCENT),
                ft.Text("%s%% · 剩餘約 %s 分鐘 · 第 %s／%s 層" % (s["progress_pct"], s.get("remaining_min"), s.get("layer"),
                                                         s.get("total_layers")), size=14)]
    temps = []
    for lab, a, b in (("噴嘴", "nozzle_temp", "nozzle_target"), ("熱床", "bed_temp", "bed_target"),
                      ("機箱", "chamber_temp", None)):
        if s.get(a) is not None:
            temps.append(T.kpi(lab, "%.0f °C" % s[a], I.THERMOSTAT, "orange",
                               "目標 %s °C" % s.get(b) if b and s.get(b) else ""))
    if temps:
        out.append(T.kpis(temps))
    trays = s.get("trays") or []
    if trays:
        out.append(ft.Text("耗材（AMS／外掛料架）", size=14, weight=ft.FontWeight.W_700))
        out.append(ft.Row([ft.Container(ft.Column([
            ft.Container(width=46, height=46, border_radius=23, bgcolor=t.get("color") or "#DDDDDD",
                         border=ft.Border.all(3, T.ACCENT if t.get("active") else T.LINE)),
            ft.Text(t.get("name") or t.get("material") or "空", size=12, weight=ft.FontWeight.W_600),
            T.muted(("AMS%d-%d" % (t["unit"] + 1, t["slot"] + 1)) if t.get("unit") is not None else "外掛", 11),
            T.muted("剩 %s%%" % t["remaining_pct"] if t.get("remaining_pct") is not None else "", 11)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2), padding=8) for t in trays], wrap=True))
    if s.get("print_error"):
        out.append(T.chip("錯誤代碼 %s" % s["print_error"], "rose", I.ERROR))
    for h in s.get("hms") or []:
        out.append(T.chip("HMS %s" % h, "amber", I.WARNING_AMBER))
    out.append(T.muted("暫停、取消請在印表機螢幕或 Bambu Handy 操作。", 12))
    return out


# ====================================================================== AI 與印表機設定
class AISettings(ft.Column):
    def __init__(self, ctx, **kw):
        self.ctx = ctx
        b = ctx.books
        c = b.company()
        self.claude = T.field("Claude API 金鑰（%s）" % (secrets.masked("claude_key") or "未設定"), "", password=True,
                              can_reveal_password=True, expand=True, hint_text="sk-ant-…（留白＝不變）")
        self.keys = {k: T.field("%s API 金鑰（%s）" % (n, secrets.masked("ai3d_%s" % k) or "未設定"), "", password=True,
                                can_reveal_password=True, expand=True) for k, n in tools3d.PROVIDERS.items()}
        self.prov = T.dropdown("預設 AI 3D 供應商", list(tools3d.PROVIDERS.items()), secrets.get("ai3d_provider", "meshy"),
                               width=220, filterable=False)
        self.speak = T.switch("代理人回覆時朗讀", secrets.get("speak_replies") == "1")
        found = tools3d.find_bambu_studio(secrets.get("bambu_path", ""))
        self.bambu = T.field("Bambu Studio 程式位置", secrets.get("bambu_path", "") or found, expand=True,
                             helper="找到：%s" % found if found else "尚未找到 Bambu Studio，請安裝或指定 bambu-studio.exe")
        self.company = T.field("公司、學校或工作室名稱", c.get("name") or "", expand=True)
        self.printer = T.dropdown("預設印表機型號", [(k, checks.printer_label(k)) for k in checks.printer_keys()],
                                  c.get("default_printer") or "A1", width=260, filterable=False)
        self.material = T.dropdown("預設耗材", [(k, k) for k in checks.material_keys()], c.get("default_material") or "PLA",
                                   width=160, filterable=False)
        sys_ = b.can("SYS", 2)
        super().__init__([
            T.page_header(I.TUNE, "AI 與印表機設定", "金鑰只存在這台電腦（不進資料庫、不進備份）", "pink",
                          [T.btn("儲存", I.SAVE, lambda e: self.save())]),
            T.card(ft.Column([
                ft.Row([T.icon_tile(I.AUTO_AWESOME, "violet", 36), ft.Text("AI 代理人（Claude）", size=16, weight=ft.FontWeight.W_700)]),
                T.muted("沒有金鑰時代理人改用免費的本機規則（看得懂常見說法：尺寸、零件種類、縮放、搜尋、印表機狀態）。"
                        "有金鑰時使用 claude-opus-5-5，可以自由描述、看照片與草圖；費用由您的 Anthropic 帳戶計算。", 12),
                ft.Row([self.claude, T.btn("清除", I.DELETE_OUTLINE, lambda e: self.clear("claude_key"), kind="ghost")]),
                ft.Row([T.btn("測試 Claude 連線", I.WIFI_TETHERING, lambda e: self.test(), kind="outline"), self.speak])],
                spacing=10)),
            T.card(ft.Column([
                ft.Row([T.icon_tile(I.VIEW_IN_AR, "amber", 36), ft.Text("AI 文字／照片轉 3D", size=16, weight=ft.FontWeight.W_700)]),
                T.muted("Meshy（meshy.ai）、Tripo（tripo3d.ai）、Rodin（hyper3d.ai）擇一申請 API 金鑰即可；每次生成會扣該服務的點數。", 12),
                *[ft.Row([f, T.btn("清除", I.DELETE_OUTLINE, lambda e, k=k: self.clear("ai3d_%s" % k), kind="ghost")])
                  for k, f in self.keys.items()], self.prov], spacing=10)),
            T.card(ft.Column([
                ft.Row([T.icon_tile(I.PRINT, "green", 36), ft.Text("Bambu Studio 與預設值", size=16, weight=ft.FontWeight.W_700)]),
                self.bambu,
                ft.Row([self.printer, self.material]) if sys_ else T.muted("預設印表機與耗材由系統管理員設定", 12),
                self.company if sys_ else ft.Container(),
                ft.Row([T.btn("設定印表機連線（IP、序號、存取碼）", I.ROUTER, lambda e: ctx.app.go("printers"), kind="outline")])],
                spacing=10))], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    def clear(self, key):
        secrets.put(key, "")
        self.ctx.toast("已清除")
        self.ctx.app.go("aiset")

    def save(self):
        if self.claude.value.strip():
            secrets.put("claude_key", self.claude.value.strip())
        for k, f in self.keys.items():
            if f.value.strip():
                secrets.put("ai3d_%s" % k, f.value.strip())
        secrets.put("ai3d_provider", self.prov.value or "meshy")
        secrets.put("speak_replies", "1" if self.speak.value else "")
        secrets.put("bambu_path", (self.bambu.value or "").strip() if (self.bambu.value or "").strip() !=
                    tools3d.find_bambu_studio() else "")
        if self.ctx.books.can("SYS", 2):
            self.ctx.guard(self.ctx.books.save_company, name=self.company.value, default_printer=self.printer.value,
                           default_material=self.material.value)
        self.ctx.books.log("ai_settings", "", "keys updated")
        self.ctx.toast("已儲存設定")
        self.ctx.app.go("aiset")

    def test(self):
        key = self.claude.value.strip() or secrets.get("claude_key")
        if not key:
            self.ctx.toast("請先輸入 Claude API 金鑰", True)
            return
        self.ctx.toast("測試中…")

        def go():
            import anthropic
            from ..agent import MODEL
            try:
                r = anthropic.Anthropic(api_key=key, max_retries=1, timeout=60).messages.create(
                    model=MODEL, max_tokens=200, output_config={"effort": "low"},
                    messages=[{"role": "user", "content": "用繁體中文回一句：連線成功"}])
                t = next((x.text for x in r.content if x.type == "text"), "")
                self.ctx.toast("Claude 連線成功：%s" % t[:40])
            except anthropic.AuthenticationError:
                self.ctx.toast("金鑰無效", True)
            except Exception as e:
                self.ctx.toast("連線失敗：%s" % e, True)
        threading.Thread(target=go, daemon=True).start()
