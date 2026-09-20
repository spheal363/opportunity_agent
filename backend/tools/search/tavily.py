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

`/extract` の挙動:

  - `urls` は配列。複数 URL を 1 リクエストで取れる
  - 成功は `results[]`（url / title / raw_content / images）、
    失敗は `failed_results[]`（url / error）に分かれて返る
  - **一部が失敗しても HTTP 200。** 例外にせず、失敗した URL を返す
  - `urls` が空 -> 400
"""

from __future__ import annotations

from typing import Any

import httpx

from config import Settings, get_settings
from logging_config import get_logger
from tools.search.base import PageContent, SearchError, SearchProvider, SearchResult

logger = get_logger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
DEFAULT_TIMEOUT_SECONDS = 30.0

# 再試行する価値がある HTTP ステータス。401 / 422 は再試行しても同じ。
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class TavilyProvider(SearchProvider):
    name = "tavily"
    supports_extract = True

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
            res = self._client.post(TAVILY_SEARCH_URL, json=payload, headers=headers)
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

    def extract(self, urls: list[str]) -> tuple[list[PageContent], list[str]]:
        """URL からページ本文を取得する。

        Tavily は一部が失敗しても HTTP 200 で返し、失敗分を `failed_results`
        に入れる。取れたものだけ返し、落ちた URL は呼び出し元へ渡す。
        """
        if not self._settings.search_api_key:
            raise SearchError("SEARCH_API_KEY が設定されていません")
        if not urls:
            return [], []

        headers = {
            "Authorization": f"Bearer {self._settings.search_api_key}",
            "Content-Type": "application/json",
        }
        try:
            res = self._client.post(TAVILY_EXTRACT_URL, json={"urls": urls}, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchError("ページ取得がタイムアウトしました", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SearchError("ページ取得 API への接続に失敗しました", retryable=True) from exc

        if res.status_code != 200:
            raise SearchError(
                f"ページ取得 API がエラーを返しました (HTTP {res.status_code})",
                status_code=res.status_code,
                retryable=res.status_code in _RETRYABLE_STATUS,
            )

        try:
            body = res.json()
        except ValueError as exc:
            raise SearchError(
                "ページ取得 API のレスポンス形式が想定と違います", retryable=True
            ) from exc

        pages: list[PageContent] = []
        for item in body.get("results") or []:
            url = item.get("url")
            content = item.get("raw_content")
            if not url or not content:
                continue
            pages.append(PageContent(url=url, title=item.get("title") or "", content=content))

        failed = [f.get("url") for f in (body.get("failed_results") or []) if f.get("url")]
        # 取得した URL の一覧は残すが、本文は Log へ出さない。
        logger.info("search.tavily.extract ok=%d failed=%d", len(pages), len(failed))
        return pages, failed

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
