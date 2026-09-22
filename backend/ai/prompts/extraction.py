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
    '  "region": str|null,     // 開催地の都道府県（例: 東京都）。分かるときだけ\n'
    '  "online_participation": bool|null, // オンラインでも参加できるか\n'
    '  "eligibility": str|null,// 参加条件\n'
    '  "cost": int|null,       // 参加費（円）\n'
    '  "cost_kind": str,       // free / paid / partially_free / unknown\n'
    '  "recommended_action": str|null, // 本人が取れる行動（例: 応募する）\n'
    '  "deadline_kind": str,   // application / registration / submission /\n'
    "                          // early_bird / speaker / other / unknown\n"
    '  "deadline_quote": str|null,     // deadline の日付そのものの表記\n'
    '  "deadline_context": str|null,   // 何の期限か分かる周辺の一文（原文のまま）\n'
    '  "start_at_is_date_only": bool|null, // 時刻が無く日付だけなら true\n'
    '  "end_at_is_date_only": bool|null,\n'
    '  "deadline_is_date_only": bool|null\n'
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
    "対応する *_is_date_only を true にする。時刻まで書かれていれば false。"
    "**対応する日時が null のときは *_is_date_only も null にする。**\n"
    "7. **締切は「何に対するものか」を deadline_kind で区別する。** "
    "同じページに複数の締切が並ぶ。\n"
    "   application  応募締切・参加申込の締切（**推薦する行動に対応する**）\n"
    "   registration 参加登録・チケット申込の期限（同上）\n"
    "   submission   **作品・提出物の締切。申込の締切とは別。**\n"
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
    "10. **本人が取れる行動を特定できるときだけ recommended_action を入れる。**\n"
    "   入れてよい例: 応募する / 参加登録する / 申し込む / 入会する / 問い合わせる\n"
    "   **応募が要らない催しにも行動はある。** クラブイベント・ライブ・展示など、"
    "チケットを買うか当日行けば参加できるものは"
    "「チケットを購入する」「当日会場へ行く」を入れる。"
    "**応募先が無いことを理由に null にしない**"
    "（実測で、入場料と会場が分かっている音楽イベントが null になり、"
    "推薦の手前で落ちた）。\n"
    "   **対象は url に書く。** 別の欄は設けない。\n"
    "   **null にする例**（本人が直接応募・参加できないページ）:\n"
    "     他人の投稿作品・提出物のページ\n"
    "     終了した催しの開催レポート\n"
    "     仕組みや事例の解説記事\n"
    "     検索結果・イベント一覧のページそのもの\n"
    "   **type だけで決めない。** 解説記事でも、本文に具体的な募集先が"
    "書かれていれば行動を特定できる。その場合は recommended_action を入れる。"
    "   一覧ページから 1 件を取り出した場合は、その 1 件の url を書く。"
    "**一覧そのものを対象にしない。**\n"
    "11. **region は開催地の都道府県を入れる。**"
    "会場名だけでは地域が分からないため、本文から都道府県を読み取る。\n"
    "   例: 会場が「ZEROTOKYO」「ヨドバシ池袋ビル屋上」「天王洲アイル」なら"
    "region は「東京都」\n"
    "   **本文に手がかりが無ければ null。** 会場名からの推測で埋めない。\n"
    "   オンラインのみなら null にし、online_participation を true にする。\n"
    "12. **online_participation は「本人がオンラインで参加できるか」。**\n"
    "   配信を見るだけ・アーカイブ公開のみは false。参加枠があるときだけ true。\n"
    "   書かれていなければ null。\n"
    "13. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    source_url: str,
    page_content: str,
    *,
    today: date | None = None,
    source_title: str | None = None,
) -> str:
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
    # **取得元が持っているタイトルを捨てない。**
    #
    # 本文の抜粋は、ページの見出しを含まないことがある。実測で、催しの
    # 名称が「GenAI/SUM事務局」という組織名の一部としてしか現れない入力が
    # あり、title が null になって Schema を通らなかった。
    # 検索結果・取得結果は title を持っているので、それも渡す。
    #
    # これも外部から取得したデータで、`untrusted_block` の中に入れる。
    header = f"取得元 URL: {source_url}"
    if source_title:
        header += f"\n取得元のページタイトル: {source_title}"
    source = f"{header}\n\n{page_content}"
    return f"今日の日付: {today.isoformat()}\n\n{untrusted_block('page_content', source)}"
