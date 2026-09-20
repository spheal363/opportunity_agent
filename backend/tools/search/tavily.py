"""Tavily provider。MVP で使う検索 provider。

検索結果とあわせて本文の抜粋（`content`）が返るため、Page Reader（#17）を
薄くでき、Opportunity Extraction（#18）の入力も良質になる。

実測で確認した挙動:

  - 認証は `Authorization: Bearer <key>`
  - `results[]` の各要素は title / url / content / score / raw_content / id
  - `content` は 800〜1500 文字程度の本文抜粋
  - `include_raw_content=true` にすると `raw_content` にページ全文が入る
    （3,500〜17,800 文字。トークンを食うので既定では取らない）
  - 不正なキー -> 401、query 欠落 -> 422
"""

from __future__ import annotations

from typing import Any

import httpx

from config import Settings, get_settings
from logging_config import get_logger
from tools.search.base import SearchError, SearchProvider, SearchResult

logger = get_logger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 30.0

# 再試行する価値がある HTTP ステータス。401 / 422 は再試行しても同じ。
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        # 遅延生成にすると BackgroundTask の同時実行で二重生成される。最初に作る。
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.search_api_key)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        include_raw_content: bool = False,
    ) -> list[SearchResult]:
        if not self._settings.search_api_key:
            raise SearchError("SEARCH_API_KEY が設定されていません")

        payload: dict[str, Any] = {
            "query": query,
            "max_results": limit,
            "include_raw_content": include_raw_content,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.search_api_key}",
            "Content-Type": "application/json",
        }

        try:
            res = self._client.post(TAVILY_URL, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchError("検索がタイムアウトしました", retryable=True) from exc
        except httpx.HTTPError as exc:
            # 例外メッセージに URL とヘッダを含めない（Secret 混入を防ぐ）
            raise SearchError("検索 API への接続に失敗しました", retryable=True) from exc

        if res.status_code != 200:
            raise SearchError(
                f"検索 API がエラーを返しました (HTTP {res.status_code})",
                status_code=res.status_code,
                retryable=res.status_code in _RETRYABLE_STATUS,
            )

        return self._parse(res, query)

    def _parse(self, res: httpx.Response, query: str) -> list[SearchResult]:
        try:
            body = res.json()
            raw_results = body["results"]
        except (ValueError, KeyError) as exc:
            raise SearchError("検索 API のレスポンス形式が想定と違います", retryable=True) from exc

        results: list[SearchResult] = []
        for item in raw_results:
            url = item.get("url")
            if not url:
                continue
            content = item.get("raw_content") or item.get("content") or None
            results.append(
                SearchResult(
                    title=item.get("title") or "",
                    url=url,
                    # Tavily の content は本文抜粋。snippet としても使う。
                    snippet=(item.get("content") or "")[:300],
                    content=content,
                    score=item.get("score"),
                )
            )

        # クエリ本文は Log へ出さない（プロフィール由来の内容が含まれうる）。
        logger.info("search.tavily results=%d query_len=%d", len(results), len(query))
        return results

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
