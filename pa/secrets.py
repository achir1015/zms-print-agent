"""金鑰與存取碼：只存在這台電腦的資料夾（secrets.json，僅目前使用者可讀），不進資料庫、不進備份。

存的內容：Claude API 金鑰、AI 3D 供應商金鑰、印表機區網存取碼。
"""
import json
import os

from .settings import data_dir


def _path():
    return os.path.join(data_dir(), "secrets.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get(key, default=""):
    return _load().get(key, default)


def has(key):
    return bool(_load().get(key))


def put(key, value):
    d = _load()
    if value:
        d[key] = value
    else:
        d.pop(key, None)
    p = _path()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def masked(key):
    v = get(key)
    if not v:
        return ""
    return v[:4] + "…" + v[-4:] if len(v) > 10 else "已設定"
