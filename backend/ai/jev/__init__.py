"""Jev（TypeSafe System One）。**評価専用の明示的な境界。**

`generate_structured` には押し込まない。分類・採点しか返さず、自由文を
作れないため、同じ入口にすると「作れない欄を空で埋める」ことになる。

計測とエラー処理は LLM 側と揃える（`ai/cost.py` の Jev 専用の欄）。
"""

from ai.jev.client import (
    JevAnswer,
    JevClient,
    JevConfigError,
    JevError,
    JevResponse,
    close_client,
    get_client,
)

__all__ = [
    "JevAnswer",
    "JevClient",
    "JevConfigError",
    "JevError",
    "JevResponse",
    "close_client",
    "get_client",
]
