"""Jina Reader で本文を取得する。**実験用。既定値にはしない。**

公式（https://jina.ai/reader/）で確認した仕様:

  - `https://r.jina.ai/<対象URL>` に GET すると、本文を Markdown で返す
  - **API キー無しでも使える**（20 RPM）。キーがあると 500 RPM
  - 新規キーには 10M トークンの無料枠が付く
  - 課金はトークン量に応じる（本文が長いほど高い）

**キー無しで動くことが、実験用にこれを選んだ理由。** 新規契約や支払いを
発生させずに「Serper 検索＋本文取得」の形を試せる。

## 気をつけること

**全文が取れたことと、期限が確認できたことは別。** 募集要項が申込先の
別ドメイン（Google Form、Peatix など）にしか無いページがある。取得成功を
「受付状況を確認できた」とは扱わない。

**返る本文はキャッシュのことがある。** Jina 側の取得時刻はこちらから
制御できない。`availability_checked_at` はこちらが確認した時刻であって、
ページが更新された時刻ではない。

**切り詰めで募集要項が落ちうる。** `MAX_CONTENT_CHARS` は安全側の歯止めで、
末尾にある締切表記を落とす可能性がある。落とした事実は failed ではなく
本文の欠落として残るため、期限が無いことを終了の根拠にしない。
"""

from __future__ import annotations

from typing import Any

import httpx

from ai.concurrency import map_parallel
from config import Settings, get_settings
from logging_config import get_logger
from tools.fetch.base import PageContent, PageFetcher

logger = get_logger(__name__)

JINA_READER_BASE = "https://r.jina.ai/"
DEFAULT_TIMEOUT_SECONDS = 30.0

# 再試行する価値がある HTTP ステータス。401 / 422 は再試行しても同じ。
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# **キー無しは 20 RPM。** 並列度を上げると 429 を踏むだけで速くならない。
# キーがあれば 500 RPM なので、その場合だけ上げる。
_WORKERS_ANONYMOUS = 2
_WORKERS_WITH_KEY = 5


class JinaReaderFetcher(PageFetcher):
    name = "jina"

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
    def workers(self) -> int:
        return _WORKERS_WITH_KEY if self._settings.jina_api_key else _WORKERS_ANONYMOUS

    def fetch(self, urls: list[str]) -> tuple[list[PageContent], list[str]]:
        if not urls:
            return [], []

        results = map_parallel(urls, self._one, workers=self.workers)

        pages = [p for p in results if p is not None]
        failed = [u for u, p in zip(urls, results, strict=True) if p is None]
        logger.info("fetch.jina ok=%d failed=%d", len(pages), len(failed))
        return pages, failed

    def _one(self, url: str) -> PageContent | None:
        """1 件取得する。**失敗は None を返し、例外にしない。**

        他の URL はまだ取れる。1 件の失敗で全体を捨てない。
        """
        headers = {"Accept": "application/json"}
        if self._settings.jina_api_key:
            headers["Authorization"] = f"Bearer {self._settings.jina_api_key}"

        try:
            res = self._client.get(JINA_READER_BASE + url, headers=headers)
        except httpx.HTTPError as exc:
            # 例外メッセージに URL とヘッダを含めない（Secret 混入を防ぐ）
            logger.warning("fetch.jina.error kind=%s", type(exc).__name__)
            return None

        if res.status_code != 200:
            logger.warning(
                "fetch.jina.status code=%d retryable=%s",
                res.status_code,
                res.status_code in _RETRYABLE_STATUS,
            )
            return None

        return _parse(res, url)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _parse(res: httpx.Response, requested_url: str) -> PageContent | None:
    try:
        body: Any = res.json()
    except ValueError:
        logger.warning("fetch.jina.bad_json")
        return None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        logger.warning("fetch.jina.unexpected_shape")
        return None

    content = data.get("content")
    if not content:
        # HTTP 200 だが本文が無い。取れなかった事実として扱う。
        return None

    # **url は要求したものを使う。** 応答に入る url は Jina 側が正規化した
    # 値で、呼び出し元が持つ候補の URL と一致しないことがある。一致しないと
    # 「要求した URL が pages にも failed にも現れない」状態になる。
    return PageContent(url=requested_url, title=data.get("title") or "", content=content)
