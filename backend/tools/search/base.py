"""検索 Provider の共通インターフェース。

Tavily 固有のレスポンス形式を Agent Loop 側へ漏らさないための薄い層。
provider を差し替えられれば十分で、プラグイン機構のようなものは作らない。

コスト最適化（provider の比較、多段絞り込み、計測）は
Search Cost Optimization（P2 / Stretch Goal）で扱う。ここでは扱わない。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PageContent:
    """URL から取得したページ本文。

    Verification（公式ページの再確認）と、検索の抜粋では足りない場合に使う。
    """

    url: str
    title: str
    content: str


@dataclass(frozen=True)
class SearchResult:
    """1 件の検索結果。

    Agent Loop と Opportunity Extraction（#18）はこの形だけを見る。
    provider の生 JSON を先へ渡さない。
    """

    title: str
    url: str
    snippet: str
    # provider が本文を返さない場合は None（Brave / Serper など）。
    # その場合は Page Reader Tool（#17）で別途取得する。
    content: str | None = None
    # provider が付けた関連度。無い provider もあるので順位付けの主軸にしない。
    score: float | None = None


class SearchError(Exception):
    """検索の失敗。

    retryable が True のものだけ再試行の対象にする。
    """

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SearchProvider(ABC):
    """検索 provider。

    `search()` は必須。`extract()` は provider による（Tavily は持つが、
    Brave / Serper は検索のみ）。持たない provider に差し替えたときは
    `supports_extract` が False になり、呼び出し側が別手段へ切り替えられる。
    """

    name: str
    supports_extract: bool = False

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]: ...

    def extract(self, urls: list[str]) -> tuple[list[PageContent], list[str]]:
        """URL からページ本文を取得する。

        戻り値は (取得できたもの, 取得できなかった URL)。
        **一部が失敗しても例外にしない。** 5 件中 1 件が落ちたときに
        残り 4 件を捨てるのは Agent の探索として不適切なため。
        """
        raise SearchError(f"{self.name} はページ取得に対応していません")

    def close(self) -> None:
        """接続の後片付け。持たない provider は何もしなくてよい。"""
        return None
