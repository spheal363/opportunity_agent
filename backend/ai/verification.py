"""⑦ Verification。

TOP3 の公式ページを取りに行き、抽出済みの情報と突き合わせる。

検索結果の抜粋（800〜1500 文字）から抽出した情報は、古いページや
まとめ記事由来のことがある。**ユーザーに推薦する前に公式ページを見に行く。**

実測で、検索結果に締切の過ぎたイベントが混ざることを確認している。
"""

from datetime import UTC, date, datetime

from ai.llm import LLMError, generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import verification as prompt
from ai.schemas.extraction import MAX_PAGE_CONTENT_CHARS
from ai.schemas.verification import VerificationOutput
from logging_config import get_logger
from tools.search.base import SearchError

logger = get_logger(__name__)

VERIFICATION_MAX_TOKENS = 8192


def verify(
    *,
    opportunity: dict,
    page_content: str,
    source_url: str,
    today: date | None = None,
    tier: ModelTier = ModelTier.STANDARD,
) -> VerificationOutput:
    """1 件を公式ページと突き合わせる。"""
    result = generate_structured(
        schema=VerificationOutput,
        system=prompt.SYSTEM,
        user=prompt.build_user(
            opportunity=opportunity,
            page_content=page_content[:MAX_PAGE_CONTENT_CHARS],
            today=(today or date.today()).isoformat(),
        ),
        tier=tier,
        max_tokens=VERIFICATION_MAX_TOKENS,
    )
    out = result.data
    # 検証できた場合だけ日時と取得元を埋める。LLM の申告をそのまま信じない。
    if out.verified:
        out.verified_at = datetime.now(UTC)
        out.verification_source = source_url
    else:
        out.verified_at = None
        out.verification_source = None
    return out


def unverified(reason: str) -> VerificationOutput:
    """確認できなかったときの結果。

    **確認できなかったことを隠さない。** run は落とさず、
    「確認できていない」という事実を残して先へ進む。
    """
    return VerificationOutput(verified=False, changes_detected=False, warnings=[reason])


def verify_with_page(
    *,
    opportunity: dict,
    url: str | None,
    fetch_page,
    today: date | None = None,
) -> VerificationOutput:
    """公式ページを取得してから検証する。

    `fetch_page` は URL を受け取り本文（無ければ None）を返す呼び出し可能。
    Tool に直接依存させないことで、テストから差し替えられる。
    """
    if not url:
        return unverified("公式ページのURLが分からないため確認できませんでした")

    try:
        content = fetch_page(url)
    except SearchError as exc:
        logger.warning("verification.fetch_failed url=%s reason=%s", url, exc)
        return unverified("公式ページを取得できませんでした")

    if not content:
        return unverified("公式ページの内容を読み取れませんでした")

    try:
        return verify(opportunity=opportunity, page_content=content, source_url=url, today=today)
    except LLMError as exc:
        logger.warning("verification.failed url=%s reason=%s", url, exc)
        return unverified("公式ページの内容を確認できませんでした")
