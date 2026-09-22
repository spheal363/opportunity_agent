"""今回の 10 件を、訂正を保ったまま台帳へ入れる（#47）。

**値は、こちらが実際に読んだ出典の文字列に基づく。** 推測で埋めない。
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.candidate_ledger import Candidate, Correction, Status, save, summary

OUT = Path("../docs/experiments/47-search-model/five-20260922-170649/ledger.json")

C = [
    Candidate(
        wish="音楽",
        model={
            "name": "John Talabot",
            "dates": ["2026-10-03"],
            "venue": "VENT（港区南青山）",
            "source_url": "https://ra.co/events/2515227",
        },
        verified={"dates": ["2026-10-03"], "venue": "VENT", "region": "東京都港区南青山3-18-19"},
        status=Status.CONFIRMED,
        evidence=[
            "LivePocket 概要「開催日 2026年10月3日(土) / 会場 VENT (東京都) "
            "〒107-0062 東京都港区南青山3丁目18-19」"
        ],
        registration="前売り券 販売中 ¥2,500（DOOR ¥4,000 / BEFORE 0AM ¥2,000）。完売表記なし",
        eligibility="20歳未満不可・写真付身分証必須・サンダル不可（記載あり）",
    ),
    Candidate(
        wish="音楽",
        model={
            "name": "Carlos Souffront",
            "dates": ["2026-10-10"],
            "venue": "VENT",
            "source_url": "https://nightlifetokyo.com/ja/tokyo/events/73ef3607-8b2b-4857-bcdb-a7e8627c0688",
        },
        verified={"dates": ["2026-10-10"], "venue": "Vent", "region": "東京"},
        status=Status.CONFIRMED,
        evidence=[
            "Nightlife Tokyo 個別ページ「日付 2026年10月10日土曜日 / 時間 23:00 / 会場 Vent 東京」"
        ],
        registration="入場料 Advance 2000 / Door 3500 の記載のみ。**販売中かは未確認**",
        eligibility="記載なし",
    ),
    Candidate(
        wish="音楽",
        model={
            "name": "31st Anniversary Special X-tra gaiden",
            "dates": ["2026-11-15"],
            "venue": "Z Maruyama（渋谷区真理谷町）",
            "source_url": "https://ra.co/events/2537808",
        },
        verified={
            "dates": ["2026-11-15"],
            "venue": "Z MARUYAMA",
            "region": "渋谷区円山町2-4 Doctor Jeekahn's Building 1F",
        },
        corrections=[
            Correction(
                "venue", "渋谷区真理谷町", "渋谷区円山町（Maruyamacho）", "z-maruyama.zaiko.io 公式"
            )
        ],
        status=Status.CORRECTED,
        evidence=[
            "zaiko 公式「Event date Nov 15 (Sun) 16:00–21:00 JST / "
            "Venue Z MARUYAMA, 2-4 Maruyamacho, Shibuya Ward, Tokyo」"
        ],
        registration="ADV ¥2,000、On sale until Nov 15 (Sun) 15:00 JST（販売中）",
        eligibility="記載なし",
    ),
    Candidate(
        wish="音楽",
        model={
            "name": "PICNIC PEOPLE PANIC",
            "dates": ["2026-11-13"],
            "venue": "WOMB",
            "source_url": "https://soundcheck.club/tokyo/house/2026-11/",
        },
        verified={},
        unresolved=["開催年", "開催日"],
        status=Status.CONFLICT,
        evidence=[
            "WOMB 公式 ppp-3「PICNIC PEOPLE PANIC が11月14日、第3回目を開催する」（年の記載なし）",
            "iflyer が同じ本文を「**2025年11月14日金曜日**」「終了したイベント」として掲載",
            "モデルの出典 ra.co/events/2525848 は取得できず",
        ],
        registration="未確認",
        eligibility="記載なし",
    ),
    Candidate(
        wish="音楽",
        model={
            "name": "HOUSE-TEX（DJ EMMA）",
            "dates": ["2026-11-05"],
            "venue": "DJ Bar Bridge（新宿区）",
            "source_url": "https://soundcheck.club/tokyo/house/2026-11/",
        },
        unresolved=["開催日", "会場（渋谷店か新宿店か）"],
        status=Status.UNFETCHABLE,
        evidence=[
            "挙げられた soundcheck.club に HOUSE-TEX の記載なし",
            "公式 djbar-bridge.com は**渋谷**店。当該日程の回は一覧に無い",
            "ra.co/events/2537245 は取得できず",
        ],
        registration="未確認",
        eligibility="記載なし",
    ),
    Candidate(
        wish="DTM・作曲",
        model={
            "name": "音源道場Plus「ミックスセミナー初級編」",
            "dates": ["2026-10-03"],
            "venue": "島村楽器 立川店",
            "source_url": "https://www.shimamura.co.jp/update/shops/tachikawa/dtm-recording/72789/",
        },
        verified={
            "dates": ["2026-10-03"],
            "venue": "島村楽器 立川店",
            "region": "東京都立川市",
            "apply_url": "https://form.run/@shimamura-10-0251"
            "?_field_3=【音源道場Plus】ミックスセミナー",
        },
        corrections=[
            Correction(
                "apply_url",
                "（マイク体験会の予約フォームを参照していた）",
                "ミックスセミナー【初級編】専用の予約フォーム",
                "島村楽器 立川店ページ内の該当節",
            )
        ],
        status=Status.CORRECTED,
        evidence=[
            "島村楽器 立川店「10月3日 音源道場Plus「ミックスセミナー初級編」」",
            "同節に「ミックスセミナー【初級編】のご予約はこちら！」の専用フォーム",
        ],
        registration="専用フォームで予約受付（参加費の記載なし）",
        eligibility="記載なし",
    ),
    Candidate(
        wish="ハッカソン",
        model={
            "name": "PLATEAU Hack Challenge 2026 in Tokyo",
            "dates": ["2026-09-26", "2026-09-27"],
            "venue": "TUNNEL TOKYO",
            "source_url": "https://prtimes.jp/main/html/rd/p/000000284.000017610.html",
        },
        verified={
            "dates": ["2026-09-26", "2026-09-27"],
            "venue": "TUNNEL TOKYO",
            "region": "東京都品川区西品川1-1-1 住友不動産大崎ガーデンタワー9階",
        },
        status=Status.CONFIRMED,
        evidence=[
            "prtimes 開催概要「開催日 9月26日（土）～9月27日（日）/ 会場：TUNNEL TOKYO / "
            "所在地：東京都品川区西品川1丁目1-1」"
        ],
        registration="**募集締切 9月24日(木)12:00**、募集人数40名、参加費無料（出典に明記）",
        eligibility="エンジニア・デザイナー・クリエイター・学生等を対象、個人／チーム可（記載あり）",
    ),
    Candidate(
        wish="ハッカソン",
        model={
            "name": "Tokyo Agent Hackathon",
            "dates": ["2026-10-17"],
            "venue": "東京都内・千代田区（会場名は後日発表）",
            "source_url": "https://japanhackathons.com/events/tokyo-agent-hackathon",
        },
        verified={"dates": ["2026-10-17"], "venue": "会場詳細未発表", "region": "東京都内"},
        corrections=[
            Correction(
                "venue",
                "千代田区",
                "東京都内（区の記載なし）",
                "japanhackathons「会場・アクセス：東京都内・詳細は後日発表」",
            ),
            Correction(
                "曜日",
                "10月17日（日）",
                "10月17日（土）",
                "japanhackathons「2026年10月17日（土）09:30–18:00 JST」",
            ),
        ],
        unresolved=["会場名・住所（主催が未発表）"],
        status=Status.CORRECTED,
        evidence=[
            "japanhackathons「日時 2026年10月17日（土）09:30–18:00 JST」",
            "同「会場・アクセス：東京都内・詳細は後日発表。定員70名」",
        ],
        registration="定員70名。申込受付中かは未確認",
        eligibility="記載なし",
    ),
    Candidate(
        wish="ハッカソン",
        model={
            "name": "都知事杯オープンデータ・ハッカソン 2026 Final Stage",
            "dates": ["2026-10-17"],
            "venue": "東京都庁（推測）",
            "source_url": "https://www.metro.tokyo.lg.jp/information/press/2026/09/2026091813",
        },
        verified={"dates": ["2026-10-17"], "venue": "オンライン配信（現地観覧の記載なし）"},
        status=Status.OUT_OF_SCOPE,
        evidence=[
            "都公式「当日の様子はオンラインで配信し」「視聴及び投票を行うためには、事前に申込みが必要」",
            "現地観覧についての記載は無い",
        ],
        registration="Peatix で事前申込（**視聴・投票用**）",
        eligibility="出場は一次審査通過の24チームに限定（記載あり）",
    ),
    Candidate(
        wish="ポケモン",
        model={
            "name": "伝説のポケモンと出会う レジェンドリサーチ in 日本橋＆八重洲〈10月〉",
            "dates": ["2026-10-01", "2026-10-31"],
            "venue": "日本橋・八重洲周辺",
            "source_url": "https://t.pia.jp/pia/event/event.do?eventBundleCd=b2669840",
        },
        verified={
            "dates": ["2026-09-09", "2026-11-29"],
            "venue": "日本橋・八重洲",
            "region": "東京都中央区",
        },
        corrections=[
            Correction(
                "dates",
                "2026年10月1日〜10月31日",
                "2026年9月9日〜11月29日（会期）",
                "三井ショッピングパーク公式「Event period 2026. 9.9 (Wed) 11.29 (Sun)」",
            ),
            Correction(
                "name",
                "…〈10月〉",
                "〈10月〉を外す（月ごとの開催枠ではない）",
                "公式に月別の枠の記載は無い",
            ),
        ],
        status=Status.CORRECTED,
        evidence=[
            "三井公式「Event period 2026. 9.9 (Wed) 11.29 (Sun) / Location Nihonbashi /Yaesu」",
            "同「Mitsui Shopping Park Ticket / Ticket Pia — Available now」",
        ],
        registration="謎解きキット引換券を販売中。当日まで購入可（前日までに売切れる場合あり）",
        eligibility="記載なし（立像・街の装飾は無料、謎解きは有料）",
    ),
]

if __name__ == "__main__":
    save(C, OUT)
    print(f"台帳 {len(C)} 件 -> {OUT}")
    print("内訳:", summary(C))
    print(f"掲載できる候補: {sum(c.showable() for c in C)} 件")
    sys.exit(0)
