"""設計庫、版本（檔案＋SHA-256）、核准凍結、切片紀錄、代理人對話、印表機。

構想參考 Form Studio：每次修改存一個新版本；核准後檔案與雜湊凍結，之後只能另開新版本，
輸出的檔案只有在雜湊和核准時一致才有效。檔案以 zlib 壓縮存在資料庫，備份資料庫就等於備份所有模型。
"""
import hashlib
import json
import os
import zlib

from . import mesh3d
from .core import BizError

MAX_FILE = 120 * 1024 * 1024


class DesignMixin:
    # ================================================================ 設計
    def _can_edit(self, d):
        if not d:
            raise BizError("找不到這個設計")
        if d["owner"] != self.uid and not self.can("APPROVE", 2):
            raise BizError("這是別人的設計，需要「核准設計」權限才能修改")

    def designs(self, q="", status="", mine=False, limit=500):
        self.need("DESIGN", 1)
        where, args = [], []
        if not self.can("APPROVE", 1) or mine:
            where.append("owner=%s")
            args.append(self.uid)
        if status:
            where.append("status=%s")
            args.append(status)
        if q:
            where.append("(title LIKE %s OR note LIKE %s OR recipe_id LIKE %s)")
            args += ["%" + q + "%"] * 3
        sql = ("SELECT id, title, kind, recipe_id, category, owner, status, cur_rev, printer, material, score, size_mm, "
               "weight_g, created_at, updated_at, thumb FROM pa_design%s ORDER BY updated_at DESC LIMIT %%s"
               % ((" WHERE " + " AND ".join(where)) if where else ""))
        return self.db.rows(sql, tuple(args) + (limit,))

    def design(self, did):
        self.need("DESIGN", 1)
        d = self.db.row("SELECT * FROM pa_design WHERE id=%s", (did,))
        if not d:
            raise BizError("找不到這個設計")
        if d["owner"] != self.uid and not self.can("APPROVE", 1):
            raise BizError("沒有權限查看別人的設計")
        return d

    def revisions(self, did):
        self.design(did)
        return self.db.rows("SELECT design_id, rev, params, change_note, file_name, file_ext, file_size, file_sha256, "
                            "score, created_by, created_at FROM pa_revision WHERE design_id=%s ORDER BY rev DESC", (did,))

    def save_design(self, model, title, kind="RECIPE", recipe_id="", params=None, report=None, thumb=None,
                    printer="", material="", note="", design_id=None, change_note="", category="", src_path=None):
        """存成新設計，或在既有設計加一個新版本。回傳 (design_id, rev)。"""
        self.need("DESIGN", 2)
        title = (title or "").strip()[:120] or "未命名設計"
        ext = ".3mf"
        if src_path and os.path.isfile(src_path):          # 保留原始檔（例如 Bambu 多色 3MF、有紋理的 GLB）
            ext = os.path.splitext(src_path)[1].lower() or ".3mf"
            with open(src_path, "rb") as f:
                data = f.read()
        else:
            data = _model_bytes(model, title)
        if len(data) > MAX_FILE:
            raise BizError("模型檔太大（%.0f MB），請先在 Bambu Studio 簡化模型" % (len(data) / 1e6))
        sha = hashlib.sha256(data).hexdigest()
        info = model.info()
        size = "×".join("%g" % x for x in info["size"])
        score = report["score"] if report else None
        weight = (report or {}).get("weight_g") or model.weight_g()
        with self.db.transaction():
            if design_id:
                d = self.db.row("SELECT * FROM pa_design WHERE id=%s", (design_id,))
                self._can_edit(d)
                if d["status"] == "VOID":
                    raise BizError("已作廢的設計不能再修改")
                rev = int(d["cur_rev"]) + 1
                self.db.exec("UPDATE pa_design SET title=%s, cur_rev=%s, status='DRAFT', score=%s, size_mm=%s, weight_g=%s, "
                            "thumb=COALESCE(%s, thumb), printer=%s, material=%s, approved_by='', approved_at=NULL "
                            "WHERE id=%s", (title, rev, score, size, weight, thumb, printer, material, design_id))
                did = design_id
            else:
                did = self.db.exec("INSERT INTO pa_design (title, kind, recipe_id, category, owner, cur_rev, printer, material, "
                            "score, size_mm, weight_g, note, thumb) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)",
                            (title, kind, recipe_id or "", category or "", self.uid, printer, material, score, size, weight,
                             note or "", thumb))
                rev = 1
            self.db.exec("INSERT INTO pa_revision (design_id, rev, params, change_note, file_name, file_ext, file_size, "
                        "file_sha256, file_data, check_json, score, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (did, rev, json.dumps(params or {}, ensure_ascii=False), change_note[:200],
                         _safe(title) + ext, ext, len(data), sha, zlib.compress(data, 6),
                         json.dumps(report, ensure_ascii=False, default=str) if report else None, score, self.uid))
        self.log("design_save", did, "rev %d %s" % (rev, sha[:12]))
        return did, rev

    def revision_file(self, did, rev=None):
        """取回某版本的 3MF bytes（並驗證雜湊）。"""
        d = self.design(did)
        rev = rev or d["cur_rev"]
        r = self.db.row("SELECT file_data, file_sha256, file_name FROM pa_revision WHERE design_id=%s AND rev=%s", (did, rev))
        if not r or not r["file_data"]:
            raise BizError("找不到這個版本的檔案")
        data = zlib.decompress(r["file_data"])
        if hashlib.sha256(data).hexdigest() != r["file_sha256"]:
            raise BizError("檔案內容和當初存的雜湊不一致（資料可能已損毀）")
        return data, r["file_name"], r["file_sha256"]

    def load_revision(self, did, rev=None, out_dir=None):
        data, name, _ = self.revision_file(did, rev)
        from .settings import data_dir
        out_dir = out_dir or os.path.join(data_dir(), "work")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "design%d_%s" % (did, name))
        with open(path, "wb") as f:
            f.write(data)
        return path

    def export_revision(self, did, rev, path):
        data, _, sha = self.revision_file(did, rev)
        with open(path, "wb") as f:
            f.write(data)
        self.log("design_export", did, "rev %s → %s" % (rev, os.path.basename(path)))
        return sha

    def set_status(self, did, status):
        d = self.design(did)
        if status == "APPROVED":
            self.need("APPROVE", 2)
            r = self.db.row("SELECT score FROM pa_revision WHERE design_id=%s AND rev=%s", (did, d["cur_rev"]))
            if r and r["score"] is not None and float(r["score"]) <= 4:
                raise BizError("列印前檢查只有 %s 分（有嚴重問題），請先修正再核准" % r["score"])
            self.revision_file(did)          # 核准前驗證檔案完整
            self.db.exec("UPDATE pa_design SET status='APPROVED', approved_by=%s, approved_at=NOW() WHERE id=%s",
                         (self.uid, did))
        elif status in ("DRAFT", "PRINTED", "VOID"):
            self._can_edit(d)
            if status == "DRAFT" and d["status"] == "APPROVED":
                self.need("APPROVE", 2)
            self.db.exec("UPDATE pa_design SET status=%s WHERE id=%s", (status, did))
        else:
            raise BizError("狀態不正確")
        self.log("design_status", did, status)

    def rename_design(self, did, title, note=None):
        d = self.design(did)
        self._can_edit(d)
        self.db.exec("UPDATE pa_design SET title=%s, note=COALESCE(%s, note) WHERE id=%s",
                     ((title or "").strip()[:120] or d["title"], note, did))

    def delete_design(self, did):
        d = self.design(did)
        self._can_edit(d)
        if d["status"] == "APPROVED":
            raise BizError("已核准的設計不能刪除，請改為作廢")
        with self.db.transaction():
            self.db.exec("DELETE FROM pa_revision WHERE design_id=%s", (did,))
            self.db.exec("DELETE FROM pa_slice WHERE design_id=%s", (did,))
            self.db.exec("UPDATE pa_chat SET design_id=NULL WHERE design_id=%s", (did,))
            self.db.exec("DELETE FROM pa_design WHERE id=%s", (did,))
        self.log("design_delete", did, d["title"])

    def design_stats(self):
        mine = "" if self.can("APPROVE", 1) else " WHERE owner=%s"
        args = () if not mine else (self.uid,)
        r = self.db.row("SELECT COUNT(*) n, SUM(status='APPROVED') appr, SUM(status='DRAFT') draft, "
                        "SUM(status='PRINTED') printed, SUM(weight_g) grams FROM pa_design" + mine, args) or {}
        r["slices"] = self.db.value("SELECT COUNT(*) FROM pa_slice")
        r["chats"] = self.db.value("SELECT COUNT(*) FROM pa_chat WHERE uid=%s", (self.uid,))
        return r

    # ================================================================ 切片紀錄
    def log_slice(self, did, rev, printer, material, quality, data):
        self.db.exec("INSERT INTO pa_slice (design_id, rev, printer, material, quality, print_s, grams, profile, uid) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (did, rev, printer, material, quality, int(data.get("print_time_s") or 0),
                      float(data.get("filament_g") or 0), str(data.get("process_profile") or "")[:120], self.uid))

    def slices(self, did):
        return self.db.rows("SELECT * FROM pa_slice WHERE design_id=%s ORDER BY id DESC", (did,))

    # ================================================================ 代理人對話
    def chats(self, limit=60):
        self.need("AGENT", 1)
        return self.db.rows("SELECT id, title, engine, design_id, updated_at FROM pa_chat WHERE uid=%s "
                            "ORDER BY updated_at DESC LIMIT %s", (self.uid, limit))

    def chat(self, cid):
        c = self.db.row("SELECT * FROM pa_chat WHERE id=%s AND uid=%s", (cid, self.uid))
        if not c:
            raise BizError("找不到這段對話")
        c["msgs"] = self.db.rows("SELECT * FROM pa_chat_msg WHERE chat_id=%s ORDER BY seq", (cid,))
        return c

    def chat_add(self, cid, role, text, tools="", raw=None, engine=None, title=None):
        self.need("AGENT", 1)
        if not cid:
            self.db.exec("INSERT INTO pa_chat (uid, title, engine) VALUES (%s, %s, %s)",
                         (self.uid, (title or text or "新對話").strip().replace("\n", " ")[:120], engine or "LOCAL"))
            cid = self.db.value("SELECT LAST_INSERT_ID()")
        seq = (self.db.value("SELECT MAX(seq) FROM pa_chat_msg WHERE chat_id=%s", (cid,)) or 0) + 1
        self.db.exec("INSERT INTO pa_chat_msg (chat_id, seq, role, text, tools) VALUES (%s,%s,%s,%s,%s)",
                     (cid, seq, role, text, (tools or "")[:255]))
        sets, args = ["updated_at=NOW()"], []
        if raw is not None:
            sets.append("raw=%s")
            args.append(json.dumps(raw, ensure_ascii=False, default=str))
        if engine:
            sets.append("engine=%s")
            args.append(engine)
        self.db.exec("UPDATE pa_chat SET %s WHERE id=%%s" % ", ".join(sets), tuple(args) + (cid,))
        return cid

    def chat_link_design(self, cid, did):
        if cid:
            self.db.exec("UPDATE pa_chat SET design_id=%s WHERE id=%s AND uid=%s", (did, cid, self.uid))

    def delete_chat(self, cid):
        self.db.exec("DELETE FROM pa_chat_msg WHERE chat_id=%s", (cid,))
        self.db.exec("DELETE FROM pa_chat WHERE id=%s AND uid=%s", (cid, self.uid))

    # ================================================================ 印表機
    def printers(self):
        return self.db.rows("SELECT * FROM pa_printer ORDER BY is_default DESC, id")

    def default_printer(self):
        return self.db.row("SELECT * FROM pa_printer ORDER BY is_default DESC, id LIMIT 1")

    def save_printer(self, pid, name, model, ip="", serial="", is_default=False, note=""):
        self.need("PRINT", 2)
        if not (name or "").strip() or not model:
            raise BizError("名稱與型號必填")
        if is_default:
            self.db.exec("UPDATE pa_printer SET is_default=0")
        if pid:
            self.db.exec("UPDATE pa_printer SET name=%s, model=%s, ip=%s, serial=%s, is_default=%s, note=%s WHERE id=%s",
                         (name.strip(), model, ip.strip(), serial.strip().upper(), int(bool(is_default)), note, pid))
        else:
            first = not self.db.value("SELECT COUNT(*) FROM pa_printer")
            self.db.exec("INSERT INTO pa_printer (name, model, ip, serial, is_default, note) VALUES (%s,%s,%s,%s,%s,%s)",
                         (name.strip(), model, ip.strip(), serial.strip().upper(), int(bool(is_default) or first), note))
            pid = self.db.value("SELECT LAST_INSERT_ID()")
        self.log("printer_save", pid, "%s %s %s" % (name, model, ip))
        return pid

    def delete_printer(self, pid):
        self.need("PRINT", 2)
        self.db.exec("DELETE FROM pa_printer WHERE id=%s", (pid,))
        self.log("printer_delete", pid)


def _model_bytes(model, title):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".3mf")
    os.close(fd)
    try:
        mesh3d.export(model, tmp, title)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _safe(name):
    import re
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:60] or "model"
