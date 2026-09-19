"""共通の依存性。"""

from models import DEFAULT_USER_ID


def current_user_id() -> str:
    """現在のユーザー ID。

    MVP は認証なしの単一ユーザー運用なので固定値を返す。
    認証を入れるときはここだけ差し替える。
    """
    return DEFAULT_USER_ID
