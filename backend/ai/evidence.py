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

from ai.schemas.extraction import GATING_DEADLINES, DeadlineKind, ExtractedOpportunity


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


# 区分ごとの手がかりになる語。**サイト名や特定の日付には依存しない。**
#
# ここに挙げるのは「その語があればその区分らしい」という手がかりであって、
# 区分の定義ではない。語が見つからないことは、区分が誤っている証拠では
# なく、**根拠が示されていない**ということ。
_KIND_MARKERS: dict[DeadlineKind, tuple[str, ...]] = {
    DeadlineKind.APPLICATION: ("応募", "申込", "申し込み", "エントリー", "募集締切", "受付"),
    DeadlineKind.REGISTRATION: ("参加登録", "申込", "申し込み", "登録", "受付", "チケット"),
    DeadlineKind.EARLY_BIRD: ("早割", "早期割引", "早期申込", "先行販売", "先行予約"),
    DeadlineKind.SPEAKER: ("登壇", "発表者", "スピーカー", "出展", "ピッチ", "講演"),
}

# **他の区分にしか出ない語。** claimed kind と食い違えば、分類を疑う。
_EXCLUSIVE_MARKERS: dict[DeadlineKind, tuple[str, ...]] = {
    DeadlineKind.EARLY_BIRD: ("早割", "早期割引", "先行販売", "先行予約"),
    DeadlineKind.SPEAKER: ("登壇", "発表者", "スピーカー", "出展", "ピッチ"),
}


def context_is_in_source(context: str | None, page_content: str) -> bool:
    """周辺文が原文にそのままあるか。

    **モデルが周辺文を補っていないかを見る。** 要約や言い換えが入れば一致しない。
    """
    if not context:
        return False
    return normalize(context) in normalize(page_content)


# 周辺文の前後をどれだけ見るか（正規化後の文字数）。
#
# **意味は一行上の見出しにあることが多い。** 実測では、モデルが
# 「2026年2月9日（月）、各大学20名程度」を周辺文として写したが、
# それが応募締切だと分かるのは直前の見出し「応募締切・募集人数」だった。
#
# 広げるほど無関係な語を拾いやすくなるが、**拾った側の誤りは
# `unknown` に落ちる**（閉じない）ので、安全な方向に外れる。
_WINDOW_BEFORE = 120
_WINDOW_AFTER = 60


def source_window(context: str, page_content: str) -> str | None:
    """周辺文が原文のどこにあるかを見つけ、その前後を切り出す。

    **切り出すのは原文。** モデルが書いた文字列ではない。
    """
    body = normalize(page_content)
    needle = normalize(context)
    at = body.find(needle)
    if at < 0:
        return None
    return body[max(0, at - _WINDOW_BEFORE) : at + len(needle) + _WINDOW_AFTER]


def context_supports_kind(
    context: str | None, kind: DeadlineKind, page_content: str
) -> tuple[bool, str | None]:
    """周辺文が、その区分を支えているか。

    **引用が原文にあることと、意味が検証できたことは別。**
    「9月30日まで」は原文にあっても、それが参加申込の期限か早割の期限かを
    示さない。ここで見るのは後者。

    判断は 2 段。**原文の前後も含めて**見る。

      1. 他の区分にしか出ない語があれば、**食い違い**として退ける
      2. その区分の手がかりが 1 つも無ければ、**根拠が示されていない**

    見るのは原文の窓であって、モデルが書いた文字列ではない。
    周辺文は「原文のどこを指しているか」を決めるために使う。

    戻り値は (支えているか, 退けた理由)。
    """
    if not context:
        return False, "周辺文がありません"
    window = source_window(context, page_content)
    if window is None:
        return False, "周辺文が原文に見つかりません"

    for other, words in _EXCLUSIVE_MARKERS.items():
        if other is kind:
            continue
        hit = next((w for w in words if normalize(w) in window), None)
        if hit:
            return False, f"原文の前後に「{hit}」があり、{kind.value} と食い違います"

    words = _KIND_MARKERS.get(kind, ())
    if words and not any(normalize(w) in window for w in words):
        return False, f"原文の前後に {kind.value} を示す語がありません"
    return True, None


def check(item: ExtractedOpportunity, page_content: str) -> list[str]:
    """入力と突き合わせて、疑わしい点を挙げる。

    **値は書き換えない。** 判断の材料を返すだけ。どう扱うかは呼び出し元。
    """
    notes: list[str] = []

    if item.deadline is not None and item.deadline_kind is not DeadlineKind.UNKNOWN:
        # ① 日付そのものが原文にあるか
        if not quote_is_in_source(item.deadline_quote, page_content):
            notes.append("deadline_quote が入力に見つかりません")
        # ② その日付が何の期限かを、原文が支えているか。**① とは別のこと。**
        supported, why = context_supports_kind(
            item.deadline_context, item.deadline_kind, page_content
        )
        if not supported:
            notes.append(why or "締切の区分を支える根拠がありません")

    for field in ("start_at", "end_at", "deadline"):
        value = getattr(item, field)
        if value is None or getattr(item, f"{field}_is_date_only"):
            continue
        if time_is_in_source(value, page_content) is False:
            notes.append(f"{field} の時刻 {value:%H:%M} が入力に見つかりません")

    return notes


def ground_deadline_kind(item: ExtractedOpportunity, page_content: str) -> ExtractedOpportunity:
    """根拠の示されていない締切区分を `unknown` へ落とす。

    **区分を信じるかどうかを、モデルの申告ではなく原文で決める。**

    証明を求めるのは、**受付終了の根拠になる区分だけ**。早割や登壇者募集は
    何も閉じないので、誤っていても行動を妨げない。参加・応募の締切だと
    主張するなら、原文がそれを支えている必要がある。

    `unknown` にしても候補は落とさない。受付終了の根拠に使わなくなるだけで、
    **推薦からは外れない**（`availability.is_actionable` を参照）。
    誤って閉じるより、確認できていないと示すほうがよい。
    """
    if item.deadline is None or item.deadline_kind not in GATING_DEADLINES:
        return item
    if not quote_is_in_source(item.deadline_quote, page_content):
        return item.model_copy(update={"deadline_kind": DeadlineKind.UNKNOWN})
    supported, _ = context_supports_kind(item.deadline_context, item.deadline_kind, page_content)
    if not supported:
        return item.model_copy(update={"deadline_kind": DeadlineKind.UNKNOWN})
    return item


# その機会**そのもの**が登壇・発表者の募集であることを示す語。
#
# 「登壇締切は何も閉じない」は一般化できない。**登壇機会そのものを
# 推薦するなら、その締切は行動を閉ざす。**
_SPEAKER_OPPORTUNITY_MARKERS = (
    "登壇者募集",
    "登壇募集",
    "発表者募集",
    "スピーカー募集",
    "講演者募集",
    "出展者募集",
    "登壇者を募集",
    "発表者を募集",
    "call for speakers",
    "call for papers",
    "cfp",
)


def is_a_call_for_speakers(title: str | None, description: str | None = None) -> bool:
    """その機会そのものが、登壇・発表者の募集か。

    **語で見る粗い判定。** 「登壇者募集」と名のつくページだけを拾う。
    イベント紹介の中で登壇者募集にも触れているページは拾わない
    （そこは一般参加の機会として扱うほうが実態に近い）。

    限界:
      - 一般参加と登壇募集を**両方**扱うページは、片方しか表せない
      - `deadline` が 1 つしか無いので、2 つの締切は持てない
      - 英語以外の言い回しは拾えない
    """
    body = normalize(f"{title or ''} {description or ''}").lower()
    return any(normalize(m).lower() in body for m in _SPEAKER_OPPORTUNITY_MARKERS)
