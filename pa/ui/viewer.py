"""3D 預覽元件：拖曳旋轉、滾輪縮放、預設視角；背景執行緒繪圖（拖曳中用快速小圖，放開後畫高畫質）。"""
import threading
import time

import flet as ft

from .. import render
from . import theme as T

VIEWS = {"iso": (-35.0, 28.0), "front": (0.0, 5.0), "side": (-90.0, 5.0), "top": (0.0, 89.0)}


class Viewer(ft.Container):
    def __init__(self, ctx=None, height=420, plate=(256, 256), hint=True, toolbar=True, size=620):
        self.ctx = ctx
        self.plate = plate
        self.size_px = size
        self.yaw, self.pitch, self.zoom = VIEWS["iso"][0], VIEWS["iso"][1], 1.0
        self.scene = None
        self.model = None
        self._want = None
        self._ev = threading.Event()
        self._busy = False
        self._alive = True
        self.img = ft.Image(src=_EMPTY, fit=ft.BoxFit.CONTAIN, gapless_playback=True, expand=True)
        self.info = ft.Text("", size=12, color=T.MUTED)
        self.empty = ft.Container(T.empty_state(ft.Icons.VIEW_IN_AR, "還沒有模型", "設計零件、開啟檔案或請 AI 代理人產生"),
                                  alignment=ft.Alignment.CENTER, expand=True)
        self.spinner = ft.ProgressRing(width=22, height=22, stroke_width=2.5, visible=False)
        gd = ft.GestureDetector(
            content=ft.Stack([ft.Container(self.img, alignment=ft.Alignment.CENTER, expand=True), self.empty],
                             expand=True),
            on_pan_update=self._pan, on_pan_end=self._pan_end, on_scroll=self._scroll,
            on_double_tap=lambda e: self.view("iso"), drag_interval=30, expand=True,
            mouse_cursor=ft.MouseCursor.MOVE)
        bar = ft.Row([
            *[ft.IconButton(ic, tooltip=tip, icon_size=18, on_click=lambda e, k=k: self.view(k))
              for k, ic, tip in (("iso", ft.Icons.VIEW_IN_AR, "立體視角"), ("front", ft.Icons.CROP_PORTRAIT, "正面"),
                                 ("side", ft.Icons.CROP_LANDSCAPE, "側面"), ("top", ft.Icons.GRID_VIEW, "上方"))],
            ft.IconButton(ft.Icons.ZOOM_IN, tooltip="放大", icon_size=18, on_click=lambda e: self._zoom_by(1.2)),
            ft.IconButton(ft.Icons.ZOOM_OUT, tooltip="縮小", icon_size=18, on_click=lambda e: self._zoom_by(1 / 1.2)),
            ft.Container(expand=True), self.spinner, self.info], spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER) if toolbar else None
        col = [ft.Container(gd, expand=True, border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE,
                            bgcolor="#EEF3F9")]
        if bar:
            col.append(bar)
        if hint:
            col.append(T.muted("拖曳旋轉 · 滾輪縮放 · 點兩下回到立體視角", 11))
        super().__init__(ft.Column(col, spacing=2, expand=True), height=height, expand=height is None)
        threading.Thread(target=self._worker, daemon=True).start()

    # ------------------------------------------------------------------ 模型
    def set_model(self, model, keep_view=False):
        self.model = model
        if model is None:
            self.scene = None
            self.empty.visible = True
            self.img.src = _EMPTY
            self.info.value = ""
            self._safe_update()
            return
        self.empty.visible = False
        self.spinner.visible = True
        self._safe_update()

        def build():
            v, f, c = model.arrays()
            v, f, c = render.decimate(v, f, c, 90000)
            self.scene = render.Scene(v, f, c, plate=self.plate)
            i = model.info()
            self.info.value = "%s mm · %s 面" % (" × ".join("%g" % round(x, 1) for x in i["size"]),
                                               "{:,}".format(i["triangles"]))
            if not keep_view:
                self.yaw, self.pitch, self.zoom = VIEWS["iso"][0], VIEWS["iso"][1], 1.0
            self._request(False)
        threading.Thread(target=build, daemon=True).start()

    def snapshot(self, size=256):
        """縮圖 PNG（存設計庫用）。"""
        if not self.scene:
            return None
        return self.scene.draw(VIEWS["iso"][0], VIEWS["iso"][1], 1.0, size=size)

    # ------------------------------------------------------------------ 互動
    def view(self, key):
        self.yaw, self.pitch = VIEWS[key]
        self.zoom = 1.0
        self._request(False)

    def _zoom_by(self, f):
        self.zoom = max(0.3, min(self.zoom * f, 8.0))
        self._request(False)

    def _pan(self, e):
        d = e.local_delta
        if d is None:
            return
        self.yaw -= d.x * 0.45
        self.pitch = max(-15.0, min(89.0, self.pitch + d.y * 0.35))
        self._request(True)

    def _pan_end(self, e):
        self._request(False)

    def _scroll(self, e):
        dy = getattr(e.scroll_delta, "y", 0) if e.scroll_delta else 0
        self._zoom_by(1.12 if dy < 0 else 1 / 1.12)

    # ------------------------------------------------------------------ 繪圖執行緒
    def _request(self, fast):
        if not self.scene:
            return
        self._want = (self.yaw, self.pitch, self.zoom, fast)
        self._ev.set()

    def _worker(self):
        while self._alive:
            self._ev.wait(1.0)
            if not self._ev.is_set():
                continue
            self._ev.clear()
            want, self._want = self._want, None
            if not want or not self.scene:
                continue
            yaw, pitch, zoom, fast = want
            try:
                t = time.time()
                png = self.scene.draw(yaw, pitch, zoom, size=(360 if fast else self.size_px), fast=fast)
                self.img.src = png
                self.spinner.visible = False
                self._safe_update()
                if fast and time.time() - t < 0.03:
                    time.sleep(0.02)
            except Exception:
                import logging
                logging.getLogger("pa").exception("render")

    def _safe_update(self):
        try:
            T.safe_update(self)
        except Exception:
            pass

    def will_unmount(self):
        self._alive = False
        self._ev.set()


# 1×1 透明 PNG
_EMPTY = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                       "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
