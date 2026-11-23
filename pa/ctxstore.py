"""執行期共用狀態（畫面與代理人之間）：目前選用的印表機。"""
_printer = None


def set_printer(pr):
    global _printer
    _printer = dict(pr) if pr else None


def current_printer():
    return _printer
