"""API のエラー形式を統一する。

{"success": false, "error": {"code": "...", "message": "..."}}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from logging_config import describe_exception, get_logger
from schemas.common import err
from services.calendar_service import CalendarError

logger = get_logger(__name__)

# Calendar の失敗。Frontend は code で「未連携」「日時不明」「Google 側の失敗」を分けて出す。
# 表にない code（CALENDAR_ERROR）は Google 側の失敗として 502。
_CALENDAR_STATUS = {"CALENDAR_NOT_CONNECTED": 503, "SCHEDULE_UNKNOWN": 422}


class ApiError(Exception):
    """業務エラー。code は Frontend が分岐に使える安定した文字列にする。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFound(ApiError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__("NOT_FOUND", message, status_code=404)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message))

    @app.exception_handler(CalendarError)
    async def _calendar_error(_: Request, exc: CalendarError) -> JSONResponse:
        return JSONResponse(
            status_code=_CALENDAR_STATUS.get(exc.code, 502), content=err(exc.code, exc.message)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=err("VALIDATION_ERROR", "リクエストの形式が正しくありません"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=err(f"HTTP_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
        # 未実装の Tool / AI 処理。500 と区別できるようにしておく。
        return JSONResponse(
            status_code=501, content=err("NOT_IMPLEMENTED", str(exc) or "Not implemented")
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 内部の詳細はレスポンスへ出さない。ログにも例外の文字列は出さず、型と場所だけ残す
        # （例外の文字列には SQL のパラメータ、つまりプロフィール本文が入りうる）。
        logger.error("unhandled error path=%s %s", request.url.path, describe_exception(exc))
        return JSONResponse(
            status_code=500,
            content=err("INTERNAL_ERROR", "Unexpected error occurred"),
        )
