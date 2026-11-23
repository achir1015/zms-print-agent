"""第一次使用的預設資料：權限功能與角色。"""

# 權限功能：(代號, 名稱, 說明)；等級 0 無、1 查詢、2 維護
FUNCS = [
    ("AGENT", "AI 代理人", "用文字描述請代理人設計、檢查、搜尋模型；等級 2 可以存成設計"),
    ("DESIGN", "零件設計與設計庫", "參數化零件設計、我的設計庫；等級 2 可新增修改自己的設計"),
    ("TOOL", "模型工具", "模型檢查修復、3MF 轉 GLB、模型搜尋、AI 生成（AI 生成要等級 2）"),
    ("PRINT", "印表機與切片", "切片估算、開啟 Bambu Studio、查看印表機狀態；等級 2 可設定印表機"),
    ("APPROVE", "核准設計", "核准設計（凍結檔案與雜湊）、修改或刪除別人的設計、看全部設計"),
    ("SYS", "系統管理", "使用者與權限、單位設定、備份還原、版本更新、操作紀錄"),
]
FUNC_NAMES = {f[0]: f[1] for f in FUNCS}
LEVEL_NAMES = {0: "無", 1: "查詢", 2: "維護"}


def _r(**kw):
    return {f[0]: kw.get(f[0], 0) for f in FUNCS}


ROLES = {
    "系統管理員": {f[0]: 2 for f in FUNCS},
    "設計主管": _r(AGENT=2, DESIGN=2, TOOL=2, PRINT=2, APPROVE=2),
    "設計師": _r(AGENT=2, DESIGN=2, TOOL=2, PRINT=1),
    "操作員": _r(AGENT=1, DESIGN=1, TOOL=1, PRINT=2),
    "訪客": _r(DESIGN=1, TOOL=1),
}

STATUS = {"DRAFT": ("草稿", "amber"), "APPROVED": ("已核准", "green"), "PRINTED": ("已列印", "blue"),
          "VOID": ("作廢", "slate")}
KINDS = {"RECIPE": "參數化零件", "FILE": "匯入檔案", "AI": "AI 生成", "AGENT": "AI 代理人"}


def seed_all(db, first=False):
    """每次開啟都會補上缺的參考資料（INSERT IGNORE，不覆蓋使用者修改過的內容）。"""
    db.exec("INSERT IGNORE INTO sys_company (id, name) VALUES (1, '')")
