"""アクセス確認・エラーページの判定（#47）。

Cloudflare の「Just a moment...」、403/404 のエラーページ、JavaScript 必須の
案内ページなどは、**取得に失敗している**。機会ではない。

実測で `Just a moment...` が Opportunity として抽出され、候補一覧に並んだ。
本文が空なので日時も締切も取れず、「日程未確認の候補」として出てしまう。

## 判定の仕方

**タイトルの一語だけで決めない。** 「Just a moment」を含む正当なイベント名が
無いとは言い切れないし、言語も様々。次の 2 つを併せて見る。

    本文が短い          機会のページなら説明文が必ずある
    既知の文面に一致    アクセス確認・エラーページの定型文

短いだけでは落とさない（取得できたが素っ気ないページはある）。
定型文に一致しただけでも落とさない（Prompt Injection の解説記事などが
文面を引用していることがある）。**両方揃ったときだけ**取得失敗として扱う。

## やらないこと

**アクセス制限を回避しない。** 判定して落とすだけで、別経路での取得は試みない。
"""

from __future__ import annotations

import re
import unicodedata

# これを下回る本文は「取得できていない」ことを疑う。
# 機会のページの本文は、抜粋でも数百文字ある（実測の中央値は 1,500 文字前後）。
SHORT_CONTENT_CHARS = 200

# アクセス確認・エラーページの定型文。**小文字で比較する。**
_MARKERS = (
    # Cloudflare / Akamai などのアクセス確認
    "just a moment",
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "enable javascript and cookies to continue",
    "ddos protection by",
    "attention required",
    "security check",
    "アクセスが制限されています",
    "アクセスできません",
    "ロボットではありません",
    # エラーページ
    "403 forbidden",
    "404 not found",
    "429 too many requests",
    "page not found",
    "access denied",
    "service unavailable",
    "ページが見つかりません",
    "お探しのページは見つかりません",
    # JavaScript 必須の案内
    "javascript is required",
    "please enable javascript",
    "javascript を有効に",
)

_SPACES = re.compile(r"\s+")


def _normalize(text: str) -> str:
    # 全角・半角と空白の揺れを均す。`Ｊｕｓｔ　ａ　ｍｏｍｅｎｔ` も拾う。
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip().lower()


def looks_like_interstitial(*, title: str | None, content: str | None) -> str | None:
    """取得失敗なら理由を、機会のページなら None を返す。

    **他の候補の処理は止めない。** 呼び出し側は理由を記録して次へ進む。
    """
    body = content or ""
    text = _normalize(f"{title or ''} {body}")
    hit = next((m for m in _MARKERS if m in text), None)
    if hit is None:
        return None
    if len(body.strip()) >= SHORT_CONTENT_CHARS:
        # 定型文には一致したが、本文がある。**解説記事などを落とさない。**
        return None
    return f"アクセス確認・エラーページの可能性（'{hit}' / 本文 {len(body.strip())} 文字）"
