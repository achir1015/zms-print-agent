"""服務層：把各功能模組組成一個物件（畫面、日後手機 API 都透過它存取資料）。"""
from .core import Base, BizError  # noqa: F401
from .designbiz import DesignMixin


class Biz(Base, DesignMixin):
    pass
