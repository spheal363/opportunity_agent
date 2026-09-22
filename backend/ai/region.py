"""希望した地域と、候補の開催地の照合（#47）。

実測で、活動したい地域が「東京 / オンライン」なのに**沖縄の現地開催**が
おすすめに入った。開催地を見る処理が無かった。

## 何で判断するか

**保存済みの `location` と `format` だけ。** どちらも本文から抽出した値で、
新しい取得もサービスも要らない。

    format = online / hybrid   オンライン参加が明示されている
    format = offline           現地開催。`location` と照合する
    format = なし              参加形式が分からない

**URL やドメインで開催地を決めない。** `dtm.okinawa` だから沖縄、のような
判断はしない（ドメインは開催地ではない）。
**「配信」という語だけでオンライン参加可能と判断しない。**
判断に使うのは抽出済みの `format` で、語の拾い読みはしない。

## 3 つに分ける

    MATCH     希望地での現地開催が確認できる、またはオンライン参加が明示
    MISMATCH  希望地以外の現地開催で、オンライン参加の根拠が無い
    UNKNOWN   開催地も参加形式も判断できない

**UNKNOWN を MATCH として扱わない。** 分からないものは分からないまま、
別枠で見せる。

## ここで見ないこと

**参加資格は別。** 「20歳以上」「学生限定」などは `eligibility` の話で、
地域の一致とは混ぜない。
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum

# 希望の文字列に出てきたら「オンライン参加でもよい」と読む語。
# **候補側の判定には使わない**（候補側は `format` を見る）。
_ONLINE_WORDS = ("オンライン", "online", "リモート", "remote", "どこでも", "全国")

# 希望を場所ごとに切る区切り。「東京 / オンライン」「東京、大阪」など。
_SEPARATORS = ("/", "／", "、", ",", "・", "|", "｜", " ", "　")


class RegionMatch(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().lower()


def wanted_places(wanted: str | None) -> tuple[list[str], bool]:
    """希望の文字列を、場所の一覧と「オンラインでもよいか」に分ける。

    「東京 / オンライン」-> (["東京"], True)
    """
    if not wanted:
        return [], False
    text = wanted
    for sep in _SEPARATORS:
        text = text.replace(sep, "\n")
    parts = [p.strip() for p in text.split("\n") if p.strip()]

    online_ok = any(any(w in _normalize(p) for w in _ONLINE_WORDS) for p in parts)
    places = [p for p in parts if not any(w in _normalize(p) for w in _ONLINE_WORDS)]
    return places, online_ok


def classify(
    *,
    wanted: str | None,
    location: str | None,
    opportunity_format: str | None,
) -> RegionMatch:
    """候補が希望の地域に合うか。

    **希望が未記入なら判定しない**（UNKNOWN。全件を不一致にしない）。
    """
    places, online_ok = wanted_places(wanted)
    if not places and not online_ok:
        return RegionMatch.UNKNOWN

    fmt = (opportunity_format or "").strip().lower()

    # オンライン参加が明示されている。**語の拾い読みではなく抽出済みの形式。**
    if fmt in ("online", "hybrid"):
        return RegionMatch.MATCH if online_ok else RegionMatch.MISMATCH

    place_text = _normalize(location or "")
    hit = any(_normalize(p) and _normalize(p) in place_text for p in places)
    if hit:
        # 希望した地名が開催地に出てくる。現地開催として一致。
        return RegionMatch.MATCH

    if fmt == "offline":
        if not place_text:
            # 現地開催だが場所が取れていない。**東京と決めつけない。**
            return RegionMatch.UNKNOWN
        # 現地開催で、希望した地名がどこにも出てこない。
        # **「沖縄だ」と断定はしない。** 言えるのは「希望地を確認できない」こと。
        return RegionMatch.MISMATCH

    # 参加形式が分からない。場所も一致しない。
    return RegionMatch.UNKNOWN


def note(match: RegionMatch, *, wanted: str | None, location: str | None) -> str:
    """画面に出す一行。**断定しない書き方にする。**"""
    if match is RegionMatch.MATCH:
        return f"希望した地域（{wanted}）に合致"
    if match is RegionMatch.MISMATCH:
        where = location or "場所不明"
        return f"希望した地域（{wanted}）での開催を確認できません（開催地: {where}）"
    return "開催地・参加形式を確認できません（希望地域との一致は未確認）"
