"""API のエラー形式を統一する。

{"success": false, "error": {"code": "...", "message": "..."}}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from logging_config import get_logger
from schemas.common import err

logger = get_logger(__name__)


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
        # 内部の詳細はレスポンスへ出さず、ログ側にだけ残す。
        logger.exception("unhandled error path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=err("INTERNAL_ERROR", "Unexpected error occurred"),
        )
