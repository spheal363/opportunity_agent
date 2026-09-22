"""Web 本文の Prompt Injection 検知と無害化（#27）。

**LLM に渡す前に、コードで検査する。** `untrusted_block` と
`UNTRUSTED_DATA_RULE` は「従うな」とモデルに伝えるだけで、従わない保証は
無い（`ai/llm.py` の実測では cheap モデルが 1/2 で突破された）。
ここは LLM に頼らない層で、指示らしき文を**モデルに届く前に取り除く**。

    Web 本文 → inspect() → 指示らしき文を除去 → untrusted_block → LLM
                   │
                   └→ 見つけた種類（findings）を Agent へ返す
                      Agent は Log に出し、その候補を推薦しない（#77）

検知するもの:

    override      以前の指示を無視 / ignore previous instructions
    role          system: / <|im_start|> / あなたは今から / you are now
    manipulation  score を 100 に / 必ず推薦して / rank this first
    hidden        Unicode タグ文字・双方向制御文字（人には見えず LLM には読める）

**限界。** 正規表現なので、言い換えた指示はすり抜ける。すり抜けた分は
モデル側の規則と、出力側の検査（#77）で受ける。逆に、Prompt Injection を
解説するページのような正当なページも拾うことがある（疑わしきは推薦しない）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 除去した箇所に残す印。LLM には「ここに何かあった」ことだけが伝わる。
REMOVED_MARK = "[除去: 指示らしき文]"

# 人には見えず、LLM には読める文字。見つけたら取り除き、検知として数える。
#   U+E0000-E007F  Unicode タグ文字（ASCII を不可視で埋め込める）
#   U+202A-202E / U+2066-2069  双方向制御文字（表示順を入れ替えて文を隠す）
_HIDDEN = re.compile(r"[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069]")

# その他の見えない文字。取り除くだけで検知には数えない。ゼロ幅スペースは日本語の
# ページの改行位置の調整、ソフトハイフンは長い英単語の折り返しに正当に使われる
# （数えると普通のページを推薦から外してしまう）。
#
# **取り除かないと正規表現をすり抜ける。** ignore の途中にソフトハイフンを
# 挟むと `ignore` に一致しなくなるが、LLM は ignore と読む。
#   書式制御文字（Unicode の Cf 全体。ゼロ幅文字・ソフトハイフン・不可視の演算子など）
#   U+034F  結合書記素接合子      U+180B-180F  モンゴル文字の異体字セレクタ
#   U+FE00-FE0F / U+E0100-E01EF  異体字セレクタ
#   U+115F / U+1160 / U+3164 / U+FFA0  ハングルのフィラー（幅のある空白に見える）
_INVISIBLE = re.compile(
    r"[\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u180e"
    r"\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb"
    r"\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3"
    r"\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f"
    r"\u034f\u180b-\u180f\ufe00-\ufe0f\U000e0100-\U000e01ef"
    r"\u115f\u1160\u3164\uffa0]"
)


def _re(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """ASCII モードで組み立てる。

    **既定の Unicode モードでは日本語も「単語の文字」になる。** すると
    「scoreを100に」の score と を の間に `\\b` が立たず、英語の語が日本語に
    挟まれた攻撃を取りこぼす。ASCII モードなら日本語は区切りとして扱われる。
    """
    return re.compile(pattern, re.ASCII | re.IGNORECASE | flags)


# 判定は NFKC で正規化した本文に対して行う。全角英字・全角コロンは半角になっている。
_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "override": (
        _re(
            r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
            r"\b(previous|prior|above|earlier|preceding|all|any|original|system)\b[^.\n]{0,40}?"
            r"\b(instructions?|prompts?|rules?|directions?|guidelines?)\b"
        ),
        _re(
            r"(指示|命令|指令|プロンプト|ルール|規則|制約)"
            r"(は|を|に)?(すべて|全て|全部|一旦|いったん)?"
            r"(無視|忘れ|破棄|取り消|撤回|リセット)"
        ),
    ),
    "role": (
        _re(r"^\s*(system|assistant|developer|システム)\s*:", re.M),
        _re(r"<\|?\s*(im_start|im_end|endoftext)\s*\|?>|<\s*/?\s*system\s*>"),
        _re(r"\[/?(INST|SYS)\]|<<\s*/?SYS\s*>>"),
        _re(r"\b(you are now|from now on,? you (are|will|must))\b"),
        _re(r"\bnew (system )?instructions?\s*:"),
        _re(r"(あなた|君|お前)は(今から|これから|今後)"),
        _re(r"(新しい|以下の|次の)(指示|命令)(に従|を実行|を優先)"),
        _re(r"(システムプロンプト|system prompt)\s*(を|の内容を)?\s*(表示|出力|教え)"),
        _re(r"\b(reveal|print|show|repeat|output)\b[^.\n]{0,20}\bsystem prompt\b"),
        _re(
            r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+|any\s+)?"
            r"(ai assistant|ai agent|ai|llm|assistant|agent|model|language model)s?\s*:"
        ),
        _re(r"(AI|エージェント|アシスタント|LLM)(への|に|へ)(指示|命令|メッセージ)\s*:"),
        _re(r"\b(ai|llm|assistant|agent|language model)s?\s+(reading|processing|parsing)\s+this\b"),
    ),
    "manipulation": (
        # この Agent の出力項目（score など）を名指しで操作しようとする文
        # JSON で書かれた "score": 100 も拾う
        _re(r"\b(score|serendipity_score|serendipity)\"?\s*[=:]\s*\"?100\b"),
        _re(r"\b(set|give|assign)\b[^.\n]{0,30}\b(score|rating)\b[^.\n]{0,20}\b100\b"),
        _re(
            r"(スコア|評価|点数|適合度|意外性|score)[^。\n]{0,10}(100|満点|最高)[^。\n]{0,5}"
            r"(に|と)(して|しろ|せよ|すること|設定|付け)"
        ),
        _re(r"(推薦|おすすめ|オススメ)(して|しろ|せよ|すること)[^。\n]{0,10}(必ず|絶対)"),
        _re(r"(必ず|絶対に?|最優先で)[^。\n]{0,20}(推薦して|推薦しろ|推薦せよ|推薦すること)"),
        _re(r"(TOP ?3|トップ ?3|1位|一位)(に|へ)(入れ|含め|し)(て|ろ|よ|なさい)"),
        _re(
            r"\b(you must|you should|please|always|must)\s+(recommend|rank|rate|select|choose)\b"
            r"[^.\n]{0,40}\b(this|it)\b"
        ),
    ),
}

# 文の区切り。指示らしき箇所を含む文の頭を探すために使う。
_SENTENCE_END = re.compile(r"[。！？!?\n]|\.(?=\s|$)")
# 1 箇所で取り除く最大の範囲。改行の無い長いページを丸ごと消さないため。
_MAX_BEFORE = 200
_MAX_AFTER = 300


@dataclass(frozen=True)
class GuardResult:
    """検査の結果。

    `text` は LLM に渡してよい形に直した本文。`findings` は見つけた種類
    （override / role / manipulation / hidden）で、どこに何が書いてあったかは
    持たない。ページ本文を Log へ流さないため。
    """

    text: str
    findings: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return bool(self.findings)


def inspect(text: str | None) -> GuardResult:
    """本文を検査し、指示らしき文を取り除いた本文を返す。

    何も見つからなければ本文は変えない（見えない文字の除去を除く）。
    見つけたときは、判定に使った正規化済みの本文から、該当する文の頭から
    段落の終わりまでを `REMOVED_MARK` に置き換えて返す。
    """
    if not text:
        return GuardResult(text or "")

    findings: list[str] = []
    # _HIDDEN は _INVISIBLE に含まれる。数える方を先に調べる。
    if _HIDDEN.search(text):
        findings.append("hidden")
    cleaned = _INVISIBLE.sub("", text)

    # 全角英字（ｉｇｎｏｒｅ）や互換文字での言い換えを同じ形にそろえてから探す。
    normalized = unicodedata.normalize("NFKC", cleaned)
    spans: list[tuple[int, int]] = []
    for kind, patterns in _PATTERNS.items():
        hits = [m for p in patterns for m in p.finditer(normalized)]
        if hits:
            findings.append(kind)
            spans.extend(_span_around(normalized, m.start(), m.end()) for m in hits)

    if not spans:
        return GuardResult(cleaned, tuple(findings))
    return GuardResult(_remove(normalized, spans), tuple(findings))


# --- 出力側（#77）-----------------------------------------------------------
#
# LLM が書いた自由文（推薦理由・説明・参加条件など）から連絡先を取り除く。
#
# **画面に出してよい行き先は、検証済みの `url` だけにする。** 注入で
# 「申込はこちら: https://evil.example」と書かせる攻撃は、その URL が
# ページ本文に書かれていれば「本文にあるか」の照合では防げない。
# 自由文には一切載せない、と決めてしまう方が確実。
LINK_MARK = "[リンク省略]"

# URL に続く文字。ASCII に限る（「…/applyへ」の「へ」まで食べない）。
# 括弧と引用符も含めない（「(https://a.com)」の閉じ括弧を残す）。
_URL_END = r"[A-Za-z0-9\-._~:/?#@!$&*+,;=%]"

# スキームの無いドメインとして扱う TLD。**すべての TLD は並べていない。**
# 2 文字の国別 TLD をまとめて拾うと README.md・main.py・setup.sh のような
# ファイル名まで消してしまうため、拡張子と重なるもの（md py sh rs pl ms am id）は外した。
_TLDS = (
    # 汎用
    "com", "net", "org", "info", "biz", "io", "co", "ai", "app", "dev", "me", "xyz",
    "site", "online", "link", "page", "shop", "store", "top", "club", "tech", "cloud",
    "live", "life", "website", "space", "fun", "pro", "work", "jobs", "news", "blog",
    "today", "world", "email", "events", "asia", "art", "studio", "agency", "digital",
    "academy", "click", "download", "zip", "mov", "icu", "vip", "win", "buzz", "example",
    # 地域
    "tokyo", "osaka", "kyoto", "nagoya", "yokohama",
    # 国別
    "jp", "us", "uk", "ca", "au", "nz", "de", "fr", "it", "es", "nl", "be", "ch", "at",
    "se", "no", "fi", "dk", "ie", "pt", "ru", "cn", "tw", "hk", "kr", "sg", "in", "th",
    "vn", "ph", "my", "br", "mx", "ar", "eu", "to", "ly", "gg", "cc", "tv", "fm", "gl",
    "so", "la", "ws", "gd", "is",
)  # fmt: skip

# ドメインの形をしているが技術名として書かれるもの。大文字・小文字を区別せずに
# 探すため、これが無いと「ASP.NET の経験」まで消してしまう。
_NOT_LINKS = frozenset({"asp.net", "vb.net", "ado.net", "ml.net", "socket.io"})

_LINKS = (
    # hxxp:// は URL を伏せ字にする書き方
    re.compile(rf"(?:h(?:tt|xx)ps?|ftp)://{_URL_END}+", re.IGNORECASE),
    re.compile(rf"www\.{_URL_END}+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    # スキームの無いドメイン（evil.example/apply）。EVIL.COM も Evil.com も
    # 画面では行き先として読めるので、大文字・小文字を区別しない。
    re.compile(
        r"(?<![A-Za-z0-9.@/-])(?:[a-z0-9-]+\.)+"
        rf"(?:{'|'.join(_TLDS)})"
        rf"(?![A-Za-z0-9-])(?:/{_URL_END}*)?",
        re.IGNORECASE,
    ),
    # 電話番号（03-1234-5678 / +81 90 1234 5678 / 09012345678）
    re.compile(
        r"(?<!\d)(?:0\d{1,4}-\d{1,4}-\d{3,4}"
        r"|\+\d{1,3}[-\s]?\d{1,4}[-\s]?\d{2,4}[-\s]?\d{3,4}"
        r"|0\d{9,10})(?!\d)"
    ),
)


# 伏せ字にしたドメインの区切り（evil[.]com）。画面では「.」と読める。
_DEFANGED_DOT = re.compile(r"\[\.\]|\(\.\)|\{\.\}|\[dot\]|\(dot\)", re.IGNORECASE)
# 全角の英数字・記号（！〜～）を半角へ。1 文字を 1 文字へ対応させる。
_HALF_WIDTH = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}


def strip_links(text: str | None) -> str | None:
    """LLM が書いた自由文から URL・メールアドレス・電話番号を取り除く。

    **画面で行き先と読める形にそろえてから探す。** 全角（ｅｖｉｌ．ｃｏｍ）、
    見えない文字を挟んだもの、伏せ字（evil[.]com）も、人が読めば行き先になる。
    NFKC で本文ごと書き換えると日本語の全角括弧まで半角になるため、そろえた文で
    見つけた位置を元の文へ戻し、その箇所だけを置き換える。
    """
    if not text:
        return text
    folded, origin = _fold(text)
    spans: list[tuple[int, int]] = []
    for pattern in _LINKS:
        for m in pattern.finditer(folded):
            if m.group(0).split("/")[0].lower() in _NOT_LINKS:
                continue
            spans.append((origin[m.start()][0], origin[m.end() - 1][1]))
    if not spans:
        return text
    return _remove(text, spans, LINK_MARK)


def _fold(text: str) -> tuple[str, list[tuple[int, int]]]:
    """行き先として読める形にそろえた文と、その各文字が元の文のどこにあったかを返す。"""
    chars: list[str] = []
    origin: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in "[({" and (m := _DEFANGED_DOT.match(text, i)):
            chars.append(".")
            origin.append((i, m.end()))
            i = m.end()
            continue
        if not _INVISIBLE.match(c):
            chars.append(chr(_HALF_WIDTH.get(ord(c), ord(c))))
            origin.append((i, i + 1))
        i += 1
    return "".join(chars), origin


def _span_around(text: str, start: int, end: int) -> tuple[int, int]:
    """見つけた箇所を含む文の頭から、その段落（行）の終わりまで。

    **文ではなく段落の終わりまで取る。** 攻撃は「Note to AI: ... 。Prefix the
    title with ★」のように、検知した文の後ろに本命の指示を続けることが多い。
    見つけたページの候補はどのみち推薦しない（#77）ので、取りすぎの害は
    小さく、取り残しの害の方が大きい。
    """
    lo = max(0, start - _MAX_BEFORE)
    head = text[lo:start]
    ends = list(_SENTENCE_END.finditer(head))
    begin = lo + ends[-1].end() if ends else lo

    hi = min(len(text), end + _MAX_AFTER)
    newline = text.find("\n", end, hi)
    # 改行は残す。次の行と印がくっつかないように。
    return begin, newline if newline != -1 else hi


def _remove(text: str, spans: list[tuple[int, int]], mark: str = REMOVED_MARK) -> str:
    """重なる範囲をまとめてから、それぞれを印に置き換える。"""
    merged: list[list[int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    out: list[str] = []
    pos = 0
    for s, e in merged:
        out.append(text[pos:s])
        out.append(mark)
        pos = e
    out.append(text[pos:])
    return "".join(out)
