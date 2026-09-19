"""API 共通のレスポンス封筒。

成功: {"success": true, "data": ...}
失敗: {"success": false, "error": {"code": "...", "message": "..."}}
"""

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiSuccess[T](BaseModel):
    success: bool = True
    data: T


class ApiError(BaseModel):
    success: bool = False
    error: ErrorBody


def ok[T](data: T) -> dict:
    return {"success": True, "data": data}


def err(code: str, message: str) -> dict:
    return {"success": False, "error": {"code": code, "message": message}}
