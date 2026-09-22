"""Serper provider。**比較用（#65）。既定値にはしない。**

## 公式で確認できたこと（https://serper.dev/）

  - 無料枠 2,500 クエリ、クレジットカード不要
  - 返るのは **title / link / snippet**（+ knowledge graph などの付随情報）
  - **本文は返らない。** `supports_extract` は False のまま

## 未確認

  - **単価。** 検索結果には「$0.30 / 1,000 クエリ」とあったが、公式の料金
    ページを取得できなかった。**確定値として扱わない。**
  - リクエスト/レスポンスの細部（パラメータ名、organic 以外のブロック）。
    公式ドキュメントのホストを解決できなかったため、実キーでの実測で確かめる。

実装は広く使われている形（`POST https://google.serper.dev/search`、
`X-API-KEY` ヘッダ）に合わせてある。**実キーで一度確認するまでは
「動くはず」の状態**で、そのつもりで扱う。

## Tavily との決定的な違い

Tavily は検索結果に 800〜1500 文字の本文抜粋（`content`）を載せる。
現行の Opportunity Extraction はそれを入力にしている。Serper の snippet は
それよりはるかに短い。**Serper に差し替えるだけでは抽出の入力が痩せる。**
本文取得（`tools/fetch/`）を別に選ぶ必要がある。
"""

from __future__ import annotations

from typing import Any

import httpx

from config import Settings, get_settings
from logging_config import get_logger
from tools.search.base import SearchError, SearchProvider, SearchResult

logger = get_logger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
DEFAULT_TIMEOUT_SECONDS = 30.0

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

MAX_SEARCH_RESULTS = 20
MAX_QUERY_CHARS = 400


class SerperProvider(SearchProvider):
    name = "serper"
    # **本文は返らない。** 持つふりをさせない。
    supports_extract = False

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.serper_api_key)

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        if not self._settings.serper_api_key:
            raise SearchError("SERPER_API_KEY が設定されていません")

        query = query.strip()
        if not query:
            raise SearchError("検索クエリが空です")
        if len(query) > MAX_QUERY_CHARS:
            logger.warning("search.query_truncated len=%d", len(query))
            query = query[:MAX_QUERY_CHARS]

        limit = max(1, min(limit, MAX_SEARCH_RESULTS))

        payload: dict[str, Any] = {
            "q": query,
            "num": limit,
            # 日本語のイベント・ハッカソンを探す用途なので、地域と言語を指定する。
            # 既定を英語圏のままにすると Tavily との比較が用途とずれる。
            "gl": self._settings.serper_gl,
            "hl": self._settings.serper_hl,
        }
        headers = {
            "X-API-KEY": self._settings.serper_api_key,
            "Content-Type": "application/json",
        }

        try:
            res = self._client.post(SERPER_SEARCH_URL, json=payload, headers=headers)
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
        except ValueError as exc:
            raise SearchError("検索 API のレスポンス形式が想定と違います", retryable=True) from exc

        raw = body.get("organic") if isinstance(body, dict) else None
        if raw is None:
            # organic が無いのは「0 件」ではなく「想定と違う形」。区別する。
            raise SearchError("検索 API のレスポンス形式が想定と違います", retryable=True)
        if not isinstance(raw, list):
            raise SearchError("検索 API のレスポンス形式が想定と違います", retryable=True)

        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = item.get("link")
            if not url:
                continue
            snippet = item.get("snippet") or ""
            results.append(
                SearchResult(
                    title=item.get("title") or "",
                    url=url,
                    snippet=snippet[:300],
                    # **本文は無い。** snippet を content に流用しない。
                    # 流用すると抽出側が「本文がある」と誤認する。
                    content=None,
                    # Serper が返すのは掲載順で、関連度スコアではない。
                    # 順位付けの主軸にしないため score には入れない。
                    score=None,
                )
            )

        # クエリ本文は Log へ出さない（プロフィール由来の内容が含まれうる）。
        logger.info("search.serper results=%d query_len=%d", len(results), len(query))
        return results

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
