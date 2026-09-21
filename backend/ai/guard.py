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

# ゼロ幅文字。日本語のページでは改行位置の調整に正当に使われるため、
# 取り除くだけで検知には数えない（数えると普通のページを推薦から外してしまう）。
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")


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
            r"(ai|llm|assistant|agent|model|language model)s?\s*:"
        ),
        _re(r"(AI|エージェント|アシスタント|LLM)(への|に|へ)(指示|命令|メッセージ)\s*:"),
        _re(r"\b(ai|llm|assistant|agent|language model)s?\s+(reading|processing|parsing)\s+this\b"),
    ),
    "manipulation": (
        # この Agent の出力項目（score など）を名指しで操作しようとする文
        _re(r"\b(score|serendipity_score|serendipity)\s*[=:]\s*100\b"),
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

# 文の区切り。指示らしき箇所を含む文ごと取り除くために使う。
_SENTENCE_END = re.compile(r"[。！？!?\n]|\.(?=\s|$)")
# 1 箇所で取り除く最大の範囲。区切りの無い長い段落を丸ごと消さないため。
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

    何も見つからなければ本文は変えない（ゼロ幅文字の除去を除く）。
    見つけたときは、判定に使った正規化済みの本文から該当する文を
    `REMOVED_MARK` に置き換えて返す。
    """
    if not text:
        return GuardResult(text or "")

    findings: list[str] = []
    cleaned = _ZERO_WIDTH.sub("", text)
    if _HIDDEN.search(cleaned):
        findings.append("hidden")
        cleaned = _HIDDEN.sub("", cleaned)

    # 全角英字（ｉｇｎｏｒｅ）や互換文字での言い換えを同じ形にそろえてから探す。
    normalized = unicodedata.normalize("NFKC", cleaned)
    spans: list[tuple[int, int]] = []
    for kind, patterns in _PATTERNS.items():
        hits = [m for p in patterns for m in p.finditer(normalized)]
        if hits:
            findings.append(kind)
            spans.extend(_sentence_around(normalized, m.start(), m.end()) for m in hits)

    if not spans:
        return GuardResult(cleaned, tuple(findings))
    return GuardResult(_remove(normalized, spans), tuple(findings))


def _sentence_around(text: str, start: int, end: int) -> tuple[int, int]:
    """見つけた箇所を含む 1 文の範囲。"""
    lo = max(0, start - _MAX_BEFORE)
    head = text[lo:start]
    ends = list(_SENTENCE_END.finditer(head))
    begin = lo + ends[-1].end() if ends else lo

    hi = min(len(text), end + _MAX_AFTER)
    tail = _SENTENCE_END.search(text, end, hi)
    if tail is None:
        return begin, hi
    # 改行は残す。次の行と印がくっつかないように。
    return begin, tail.start() if tail.group() == "\n" else tail.end()


def _remove(text: str, spans: list[tuple[int, int]]) -> str:
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
        out.append(REMOVED_MARK)
        pos = e
    out.append(text[pos:])
    return "".join(out)
