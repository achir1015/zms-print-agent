"""外部能力：Bambu Studio（開啟、無頭切片估算）、印表機狀態（區網 MQTT，唯讀）、MakerWorld／Printables 搜尋、
AI 文字／圖片轉 3D（Meshy、Tripo、Rodin，要自己的金鑰）、紋理模型轉 AMS 多色 3MF。

都呼叫 bambu-studio-ai（MIT）的程式，在同一個行程裡執行（打包成 exe 後也能用），用 --json 取回結果。
印表機的存取碼、AI 金鑰只放在本機 secrets.json（見 secrets.py），呼叫時用環境變數傳給它。
"""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import threading

from . import secrets, vend

vend.setup()

_lock = threading.Lock()
PROVIDERS = {"meshy": "Meshy", "tripo": "Tripo", "rodin": "Rodin (Hyper3D)"}
SEARCH_SITES = {"makerworld": "MakerWorld", "printables": "Printables"}


class ToolError(Exception):
    pass


def _env(extra):
    keys = {"BAMBU_MODEL": "", "BAMBU_IP": "", "BAMBU_SERIAL": "", "BAMBU_ACCESS_CODE": "",
            "BAMBU_3D_PROVIDER": "", "BAMBU_3D_API_KEY": ""}
    keys.update({k: v for k, v in extra.items() if v is not None})
    return keys


def run_script(module, argv, env=None, timeout_note=""):
    """在同一行程執行 vendor 腳本的 main(argv)，回傳 (結束碼, JSON 或文字)。一次只跑一支（它們會改環境變數）。"""
    with _lock:
        old = {k: os.environ.get(k) for k in (env or {})}
        out, err = io.StringIO(), io.StringIO()
        try:
            for k, v in (env or {}).items():
                if v:
                    os.environ[k] = str(v)
                else:
                    os.environ.pop(k, None)
            mod = importlib.import_module(module)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = mod.main(list(argv))
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 1
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    text = out.getvalue().strip()
    data = None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except ValueError:
                pass
    if data is None and text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            pass
    return int(code or 0), data if data is not None else {"text": text, "stderr": err.getvalue().strip()}


# ====================================================================== Bambu Studio
BAMBU_PATHS = [r"C:\Program Files\Bambu Studio\bambu-studio.exe", r"C:\Program Files (x86)\Bambu Studio\bambu-studio.exe",
               "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"]


def find_bambu_studio(custom=""):
    if custom and os.path.isfile(custom):
        return custom
    for p in BAMBU_PATHS:
        if os.path.isfile(p):
            return p
    try:
        import common
        cmd = common.find_bambu_studio()
        if cmd:
            return cmd[-1] if isinstance(cmd, (list, tuple)) else cmd
    except Exception:
        pass
    return ""


def open_in_bambu(path, custom=""):
    """在 Bambu Studio 開啟（不等待）。請使用者自己檢查、切片、按列印 — 本程式不會啟動列印。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ToolError("找不到檔案：%s" % path)
    exe = find_bambu_studio(custom)
    if not exe:
        raise ToolError("找不到 Bambu Studio，請先安裝（bambulab.com/zh-tw/download/studio），或在「AI 與印表機設定」指定路徑")
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "darwin" and ".app" in exe:
        app = exe[:exe.index(".app") + 4]          # 用 open -a 交給已開啟的 Bambu Studio，不另開新實例
        subprocess.Popen(["open", "-a", app, path], **kw)
    else:
        if os.name == "nt":
            kw["creationflags"] = 0x00000008       # DETACHED_PROCESS：關掉本程式也不影響 Bambu Studio
        subprocess.Popen([exe, path], **kw)
    return exe


def slice_estimate(path, printer="A1", material="PLA", quality="standard", nozzle=0.4):
    """用 Bambu Studio 自己的切片引擎與設定檔無頭切片 → 列印時間與耗材克數（只是估算，不會列印）。"""

    out = os.path.splitext(path)[0] + "_sliced.3mf"
    code, data = run_script("slice", [path, "--printer", printer, "--material", material, "--quality", quality,
                                      "--nozzle", str(nozzle), "-o", out, "--json"])
    if code != 0 or "print_time_s" not in data:
        raise ToolError(_slice_error(data))
    return data


def _slice_error(data):
    msg = data.get("error") or data.get("message") or data.get("text") or data.get("stderr") or "切片失敗"
    if "not found" in str(msg).lower() or "install" in str(msg).lower():
        return "需要先安裝 Bambu Studio 才能切片估算"
    return "切片失敗：%s" % msg


def fmt_duration(seconds):
    m = max(1, round(float(seconds) / 60))
    h, mm = divmod(m, 60)
    return ("%d 小時 %d 分" % (h, mm)) if h else ("%d 分鐘" % mm)


# ====================================================================== 印表機（唯讀）
def printer_env(pr):
    sec = secrets.get("printer_code_%s" % (pr.get("serial") or ""), "")
    return _env({"BAMBU_MODEL": pr.get("model") or "", "BAMBU_IP": pr.get("ip") or "",
                 "BAMBU_SERIAL": pr.get("serial") or "", "BAMBU_ACCESS_CODE": sec})


def printer_status(pr):
    """讀印表機狀態（區網 MQTT，唯讀：不能開始、暫停、改列印）。pr＝{model, ip, serial}。"""
    if not (pr.get("ip") and pr.get("serial")):
        raise ToolError("請先設定印表機的 IP 與序號")
    if not secrets.get("printer_code_%s" % pr["serial"]):
        raise ToolError("請先輸入印表機的區網存取碼（印表機螢幕：設定 → 網路 → 存取碼）")
    code, data = run_script("bambu", ["status", "--json"], env=printer_env(pr))
    if code != 0 or "state" not in json.dumps(data):
        raise ToolError(_printer_error(data))
    return data.get("status", data)


def _printer_error(data):
    m = str(data.get("error") or data.get("message") or data.get("text") or data.get("stderr") or "")
    low = m.lower()
    if "auth" in low or "access code" in low:
        return "存取碼錯誤，請確認印表機螢幕上的區網存取碼"
    if "timed out" in low or "connect" in low or "unreachable" in low:
        return "連不上印表機：請確認在同一個區域網路、IP 正確、印表機已開機"
    return "讀取印表機狀態失敗：%s" % (m or "未知錯誤")


STATE_ZH = {"IDLE": "閒置", "PREPARE": "準備中", "RUNNING": "列印中", "PAUSE": "已暫停", "FINISH": "已完成",
            "FAILED": "失敗", "SLICING": "切片中", "UNKNOWN": "未知"}


# ====================================================================== 搜尋
def search_models(query, limit=12, sort="downloads", sites=("makerworld", "printables")):
    from bambu_studio_ai.search import search
    rep = search(query, sites=tuple(sites), limit=max(1, min(int(limit), 30)), sort=sort)
    rows = [r.to_dict() if hasattr(r, "to_dict") else dict(r.__dict__) for r in rep.results]
    return {"results": rows, "failed": [str(f) for f in rep.failed_sites]}


# ====================================================================== AI 生成（要金鑰、會扣點數）
def ai_key(provider):
    return secrets.get("ai3d_%s" % provider, "")


def generate(kind, prompt_or_image, provider="meshy", height=None, timeout=600, extra_prompt=""):
    """文字或圖片 → 3D（有紋理的 GLB，已轉成 Z 朝上並縮放到指定高度）。會花費供應商的點數。"""
    key = ai_key(provider)
    if not key:
        raise ToolError("尚未設定 %s 的 API 金鑰（AI 與印表機設定）" % PROVIDERS.get(provider, provider))
    argv = [kind, prompt_or_image, "--provider", provider, "--wait", "--json", "--timeout", str(int(timeout))]
    if height:
        argv += ["--height", "%g" % float(height)]
    if kind == "image" and extra_prompt:
        argv += ["--prompt", extra_prompt]
    code, data = run_script("generate", argv, env=_env({"BAMBU_3D_PROVIDER": provider, "BAMBU_3D_API_KEY": key}))
    if code != 0 or not data.get("output_file"):
        if data.get("task_id") and data.get("status") in ("queued", "running", "submitted"):
            raise ToolError("生成還沒完成（工作編號 %s），稍後到「AI 生成」按「繼續下載」，不會重複扣點" % data["task_id"])
        raise ToolError("AI 生成失敗：%s" % (data.get("message") or data.get("error") or data.get("text") or data))
    return data


def colorize(glb, out=None, max_colors=4, height=None):
    """有紋理的 GLB → Bambu 多色 3MF（每個三角面塗上耗材，最多 8 色），並對應最接近的拓竹耗材。"""
    argv = [glb, "--max-colors", str(int(max_colors)), "--json"]
    if out:
        argv += ["-o", out]
    if height:
        argv += ["--height", "%g" % float(height)]
    code, data = run_script("colorize.__main__", argv)
    if code != 0 or not (data.get("output_file") or data.get("output")):
        raise ToolError("多色轉換失敗：%s" % (data.get("error") or data.get("message") or data.get("text") or data))
    return data
