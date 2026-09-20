"""⑦ Verification の Prompt。

抽出済みの情報と、公式ページの現在の内容を突き合わせる。
**日時などの重要情報を LLM の記憶だけで判断させない。**

担当メモ: AI Prompt は土居さんの領域。#67 を通すために naoya が先行実装した。
"""

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

SYSTEM = (
    "あなたは、すでに抽出済みの催し情報が公式ページの現在の内容と"
    "合っているかを確認する担当である。以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "verified": bool,           // 公式ページで裏が取れたか\n'
    '  "changes_detected": bool,   // 抽出済みの内容と食い違いがあるか\n'
    '  "warnings": [str]           // ユーザーに伝えるべき注意。無ければ空\n'
    "}\n"
    "\n"
    "verified の判断:\n"
    "  true  ページが同じ催しのもので、主要な情報（名称・日時・場所のいずれか）"
    "を確認できた\n"
    "  false ページが別の催しのもの、内容が取得できない、"
    "または判断材料が無い\n"
    "\n"
    "**確認できないものを true にしない。** "
    "裏が取れていない情報を「確認済み」として見せるほうが、"
    "「確認できませんでした」と伝えるより有害である。\n"
    "\n"
    "warnings に書くこと（事実として読み取れる場合のみ）:\n"
    "  - 申込の締切が過ぎている\n"
    "  - 日時や場所が抽出済みの内容と違う\n"
    "  - 定員に達している、受付を終了している\n"
    "  - 参加に費用や資格が必要だが抽出済みの内容に無い\n"
    "\n"
    "規則:\n"
    "1. warnings は**ユーザーに見せる日本語**で、1 件 1 文にする。\n"
    "2. ページから読み取れないことを warnings に書かない。推測で不安を作らない。\n"
    "3. 食い違いが無ければ changes_detected は false、warnings は空にする。\n"
    "4. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(*, opportunity: dict, page_content: str, today: str) -> str:
    """抽出済みの内容と公式ページを並べて渡す。

    どちらも Web 由来の Untrusted Data。まとめて囲む。
    締切が過ぎているかを判断させるため今日の日付を渡す。
    """
    lines = [
        "# すでに抽出済みの内容",
        f"title: {opportunity.get('title')}",
        f"start_at: {opportunity.get('start_at') or '不明'}",
        f"deadline: {opportunity.get('deadline') or '不明'}",
        f"location: {opportunity.get('location') or '不明'}",
        f"cost: {opportunity.get('cost') if opportunity.get('cost') is not None else '不明'}",
        "",
        "# 公式ページの現在の内容",
        page_content,
    ]
    return f"今日の日付: {today}\n\n{untrusted_block('verification_target', chr(10).join(lines))}"
