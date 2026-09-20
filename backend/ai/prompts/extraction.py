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
    '  "cost": int|null        // 参加費（円）\n'
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
    "5. ページが催し・募集の情報ではない場合も、分かる範囲で title と type を埋め、"
    "残りは null にする。\n"
    "6. 出力は JSON のみ。説明文を付けない。"
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
