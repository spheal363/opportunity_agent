"""③ Opportunity Extraction。

検索結果とページ本文から、Opportunity の**事実**を構造化する。
score / reason などの評価は付けない（④ Evaluation の責務）。

入力は Web から取得した Untrusted Data。cheap モデルは Prompt Injection に
突破されうる（`ai/llm.py` の実測を参照）ため、**このステップでは
CHEAP を使わない**。
"""

from datetime import date

from ai.llm import LLMError, generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import extraction as prompt
from ai.schemas.extraction import MAX_PAGE_CONTENT_CHARS, ExtractedOpportunity
from logging_config import get_logger
from tools.search.base import PageContent, SearchResult

logger = get_logger(__name__)

# 既定の 2048 では JSON が途中で切れる。実測:
#
#   tier      入力      max_tokens  reasoning  結果
#   standard   4,000字   2048        1963      切れた
#   standard  12,000字   8192        2253      OK
#   powerful  12,000字   2048           0      OK
#
# gemini-2.5-flash は reasoning に 2,000 token 前後を使い、出力の分が残らない。
# 入力を減らしても reasoning は減らないため、上限側で確保する。
#
# POWERFUL なら reasoning 0 で通るが 1 回 4.5 秒かかる（#14 実測）。
# 1 run で何件も抽出するため STANDARD を使う。
EXTRACTION_MAX_TOKENS = 8192


def extract_opportunity(
    source_url: str,
    page_content: str,
    *,
    today: date | None = None,
    tier: ModelTier = ModelTier.STANDARD,
) -> ExtractedOpportunity:
    """1 ページから Opportunity の事実を抽出する。

    日時は UTC に揃えて返す。抽出できなかった項目は null のまま。
    """
    content = page_content[:MAX_PAGE_CONTENT_CHARS]
    result = generate_structured(
        schema=ExtractedOpportunity,
        system=prompt.SYSTEM,
        user=prompt.build_user(source_url, content, today=today),
        # Untrusted Data を読ませるため CHEAP は使わない
        tier=tier,
        max_tokens=EXTRACTION_MAX_TOKENS,
    )
    return result.data.to_utc()


def extract_many(
    sources: list[SearchResult | PageContent],
    *,
    today: date | None = None,
    tier: ModelTier = ModelTier.STANDARD,
) -> tuple[list[ExtractedOpportunity], list[str]]:
    """複数ページから抽出する。戻り値は (抽出できたもの, 失敗した URL)。

    **1 件の失敗で全体を捨てない。** 10 件中 2 件が壊れたページでも、
    残り 8 件は Opportunity として使えるため。
    """
    extracted: list[ExtractedOpportunity] = []
    failed: list[str] = []

    for src in sources:
        content = _content_of(src)
        if not content:
            failed.append(src.url)
            continue
        try:
            extracted.append(extract_opportunity(src.url, content, today=today, tier=tier))
        except LLMError as exc:
            # 例外メッセージにページ本文を載せない（_safe_reason 済みのものだけ）
            logger.warning("extraction.failed url=%s reason=%s", src.url, exc)
            failed.append(src.url)

    logger.info("extraction.done ok=%d failed=%d", len(extracted), len(failed))
    return extracted, failed


def _content_of(src: SearchResult | PageContent) -> str | None:
    """SearchResult と PageContent のどちらでも本文を取り出す。

    検索結果の `content`（Tavily は 800〜1500 文字の抜粋を返す）で足りる場合が
    多く、その場合は read_page を呼ばずに済む。
    """
    if isinstance(src, PageContent):
        return src.content or None
    return src.content or src.snippet or None
