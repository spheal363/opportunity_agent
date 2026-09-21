"""抽出結果を、**実際に渡した入力と突き合わせる**。

## Schema の検査でできることと、できないこと

`ExtractedOpportunity` の検査は「**区分が正しく付いた場合に整合性を保つ**」
ものでしかない。

  is_date_only が true なら時刻を落とす
  cost_kind が free でなければ 0 円を残さない

**区分そのものが誤っていれば、何も防げない。** モデルが
`is_date_only=false` と申告して 09:00 を作れば時刻は残るし、
`cost_kind=free` と誤れば 0 円が残る。区分もモデルの出力だから。

ここは**別のこと**をする。入力に書かれているかを、こちら側で確かめる。
モデルの申告ではなく、原文の文字列を根拠にする。

## それでも限界がある

  - 照合するのは**切り詰め後の入力**。取得元ページの全文ではない
  - 表記の揺れを全部は追えない（「14時半」「午後2時」など）
  - 見つからないことは「書かれていない」の**証拠ではなく疑い**
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from ai.schemas.extraction import DeadlineKind, ExtractedOpportunity


def normalize(text: str) -> str:
    """全角・半角と空白の違いを吸収する。

    ページは「１４：００」「14:00」が混在する。表記の違いで
    「書かれていない」と誤判定しないため。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def quote_is_in_source(quote: str | None, page_content: str) -> bool:
    """根拠として示された表記が、実際に入力にあるか。

    **無ければ、その区分は入力に基づいていない。**
    """
    if not quote:
        return False
    return normalize(quote) in normalize(page_content)


def time_is_in_source(value: datetime | None, page_content: str) -> bool | None:
    """その時刻が入力に書かれているか。

    戻り値の None は「調べていない」（日時が無い）。
    False は「**見つからなかった**」であって、「書かれていない」と
    言い切るものではない。表記の揺れを全部は追えない。
    """
    if value is None:
        return None
    body = normalize(page_content)
    hour, minute = value.hour, value.minute
    forms = [
        f"{hour}:{minute:02d}",
        f"{hour:02d}:{minute:02d}",
        f"{hour}時{minute}分",
    ]
    if minute == 0:
        forms.append(f"{hour}時")
    return any(f in body for f in forms)


def check(item: ExtractedOpportunity, page_content: str) -> list[str]:
    """入力と突き合わせて、疑わしい点を挙げる。

    **値は書き換えない。** 判断の材料を返すだけ。どう扱うかは呼び出し元。
    """
    notes: list[str] = []

    if item.deadline is not None and item.deadline_kind is not DeadlineKind.UNKNOWN:
        if not quote_is_in_source(item.deadline_quote, page_content):
            notes.append("deadline_quote が入力に見つかりません")

    for field in ("start_at", "end_at", "deadline"):
        value = getattr(item, field)
        if value is None or getattr(item, f"{field}_is_date_only"):
            continue
        if time_is_in_source(value, page_content) is False:
            notes.append(f"{field} の時刻 {value:%H:%M} が入力に見つかりません")

    return notes


def ground_deadline_kind(item: ExtractedOpportunity, page_content: str) -> ExtractedOpportunity:
    """根拠が入力に無い締切区分を `unknown` へ落とす。

    **区分を信じるかどうかを、モデルの申告ではなく原文で決める。**

    `unknown` にしても候補は落とさない。受付終了の根拠に使わなくなるだけで、
    **推薦からは外れない**（`availability.is_actionable` を参照）。
    誤って閉じるより、確認できていないと示すほうがよい。
    """
    if item.deadline is None or item.deadline_kind is DeadlineKind.UNKNOWN:
        return item
    if quote_is_in_source(item.deadline_quote, page_content):
        return item
    return item.model_copy(update={"deadline_kind": DeadlineKind.UNKNOWN})
