"""共通の依存性。"""

from fastapi import Header

from api.errors import ApiError
from models import DEFAULT_USER_ID

# この画面（frontend/src/api/client.ts）だけが付けるヘッダーの値。
PAGE_REQUEST_HEADER_VALUE = "opportunity-agent"


def current_user_id() -> str:
    """現在のユーザー ID。

    MVP は認証なしの単一ユーザー運用なので固定値を返す。
    認証を入れるときはここだけ差し替える。
    """
    return DEFAULT_USER_ID


def require_page_request(x_requested_with: str | None = Header(default=None)) -> None:
    """この画面から送られた要求だけを通す（CSRF 対策）。

    body の無い POST は、別サイトの form からも送れてしまう。
    独自ヘッダーの付いた要求はブラウザが事前に確認（preflight）し、
    許可していない Origin からのものは CORS で止まる。
    そのため、このヘッダーがあれば画面から送られたとみなせる。

    **状態を変える API（POST / PUT）すべてに付ける（#80）。** 探索の開始は
    LLM の費用がかかり、別サイトを開いただけで走らせられては困る。
    Calendar への書き込みは、これに加えてユーザーの承認として扱う。
    """
    if x_requested_with != PAGE_REQUEST_HEADER_VALUE:
        raise ApiError(
            "FORBIDDEN",
            "このアプリの画面以外からの操作は受け付けていません",
            status_code=403,
        )
