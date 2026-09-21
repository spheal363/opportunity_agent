"""③ Opportunity Extraction の Prompt。

**ここでは評価をしない。** score / reason は ④ Evaluation の責務。
このステップは Web 上の事実を構造化するだけに徹する。

取得できなかった項目は推測で埋めず null にする。`0` と `null` は意味が違う
（参加費 0 円と「参加費が不明」を混同しない）。
"""

from datetime import date

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

SYSTEM = (
    "あなたは Web ページから催し・募集の事実を抽出する担当である。"
    "与えられたページ内容から、以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "title": str,           // 名称\n'
    '  "type": str,            // event / hackathon / job / freelance / community /\n'
    "                          // accelerator / competition / scholarship / other\n"
    '  "description": str|null,// 3 行以内の概要\n'
    '  "url": str|null,        // 申込・詳細ページ\n'
    '  "start_at": str|null,   // 開始日時\n'
    '  "end_at": str|null,     // 終了日時\n'
    '  "deadline": str|null,   // 申込締切\n'
    '  "location": str|null,   // 開催場所\n'
    '  "format": str|null,     // offline / online / hybrid\n'
    '  "eligibility": str|null,// 参加条件\n'
    '  "cost": int|null,       // 参加費（円）\n'
    '  "cost_kind": str,       // free / paid / partially_free / unknown\n'
    '  "deadline_kind": str,   // application / registration / early_bird /\n'
    "                          // speaker / other / unknown\n"
    '  "deadline_quote": str|null,     // deadline の日付そのものの表記\n'
    '  "deadline_context": str|null,   // 何の期限か分かる周辺の一文（原文のまま）\n'
    '  "start_at_is_date_only": bool,  // 出典に時刻が無く日付だけなら true\n'
    '  "end_at_is_date_only": bool,\n'
    '  "deadline_is_date_only": bool\n'
    "}\n"
    "\n"
    "規則:\n"
    "1. ページに書かれていない事実は推測せず null にする。"
    "「たぶん無料」「おそらく東京」のような補完をしない。\n"
    "2. 参加費が無料と明記されている場合のみ cost を 0 にする。"
    "記載が無ければ null。0 と null は意味が違う。\n"
    "3. 日時は ISO 8601 で、**必ずタイムゾーンオフセットを付ける**。"
    "オフセットの無い日時は不正として拒否される。"
    "ページにオフセットの記載が無い場合は開催地の現地時間とみなして付ける"
    "（日本の催しなら +09:00）。"
    "オフセットを判断できないなら、その項目は null にする。\n"
    '   正: "2026-09-21T19:00:00+09:00"\n'
    '   誤: "2026-09-21T19:00:00" / "2026-09-21 19:00" / "9月21日 19時"\n'
    "4. 年が書かれていない日付は、今日以降で最も近い年として解釈する。\n"
    "5. **ページが催しや募集の告知ではなく、記事・ブログ・解説の場合は "
    'type を "other" にする。** 記事の題名を催しの名称のように扱わない。\n'
    "6. **時刻が書かれていない日付に、時刻を作らない。** "
    "「10月7日」としか書かれていないのに 09:00 や 17:00 を入れてはならない。"
    "日付だけのときは、その日の 00:00 に開催地のオフセットを付けたうえで、"
    "対応する *_is_date_only を true にする。時刻まで書かれていれば false。\n"
    "7. **締切は「何に対するものか」を deadline_kind で区別する。** "
    "同じページに複数の締切が並ぶ。\n"
    "   application  応募締切・参加申込の締切（**推薦する行動に対応する**）\n"
    "   registration 参加登録・チケット申込の期限（同上）\n"
    "   early_bird   早割・先行販売の期限（**過ぎても参加できる**）\n"
    "   speaker      登壇者・発表者・出展者の募集締切（**参加とは別の行動**）\n"
    "   other        上のどれでもない締切\n"
    "   unknown      何に対する締切か特定できない\n"
    "   deadline には **deadline_kind に対応する日付だけ**を入れる。"
    "早割の期限を申込締切として入れてはならない。"
    "参加・応募の締切が読み取れないなら deadline は null、"
    'deadline_kind は "unknown" にする。\n'
    "   deadline_quote には、その日付の表記をそのまま写す（例:「2026年8月21日」）。\n"
    "   deadline_context には、**何の期限か分かる周辺の一文**を"
    "**原文のまま**写す。日付だけを写してはならない。\n"
    "     正:「応募締め切り：2026年8月21日(金)17時（日本時間）」\n"
    "     正:「定価2万円のチケットの早割価格での提供となります。（9月30日まで）」\n"
    "     誤:「9月30日まで」（何の期限か分からない）\n"
    "   **原文に無い文を書いてはならない。** 要約も言い換えもしない。"
    "該当する一文が見つからないなら、deadline は null、"
    'deadline_kind は "unknown" にする。\n'
    "8. **取り消し線や「募集を締め切りました」「延長しました」は、"
    "どの募集に付いているかを見る。** 登壇者募集が終了していても、"
    "一般参加が受付中のことがある。ページ全体を一括で終了と判断しない。\n"
    "9. **一部の区分が無料でも、機会全体を無料としない。**\n"
    "   free           全体が無料と明記されている\n"
    "   paid           有料の記載がある\n"
    "   partially_free 一部の区分・条件だけ無料（学生無料、関係者無料など）\n"
    "   unknown        参加費の記載が無い（**無料ではない**）\n"
    "   cost に金額を入れてよいのは、その金額が"
    "「この機会に参加するために誰もが払う額」である場合のみ。"
    "区分によって額が違うなら cost は null にする。\n"
    "10. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(source_url: str, page_content: str, *, today: date | None = None) -> str:
    """抽出対象のページを user メッセージに組み立てる。

    ページ内容は `untrusted_block` で囲む。**これは防御ではなく境界の明示。**
    system 側の `UNTRUSTED_DATA_RULE` と併せて使う（`ai/llm.py` の実測を参照）。

    今日の日付を渡すのは、「9/21(土)」のように年が書かれていない日付を
    解釈させるため。

    **URL も囲みの内側に入れる。** 検索結果の URL は攻撃者がドメインもパスも
    自由に決められるため、本文と同じく信頼できないデータである。囲みの外に
    置くと、URL 文字列に仕込んだ指示が system 直後の位置に並ぶ。
    """
    today = today or date.today()
    source = f"取得元 URL: {source_url}\n\n{page_content}"
    return f"今日の日付: {today.isoformat()}\n\n{untrusted_block('page_content', source)}"
