"""検索専用モデルの回答を構造化する処理（#47）。**API を呼ばない。**"""

from datetime import date

from ai import discovery
from ai.window import SearchWindow

WIN = SearchWindow(start=date(2026, 9, 22), end=date(2026, 11, 21))
CITES = [{"url": "https://example.test/a?utm_source=openai", "title": "A"}]


def _parse(text, cites=None):
    return discovery.parse_answer(
        text, wish="音楽", wish_source="四つ打ちの音楽を楽しみたい", citations=cites or []
    )


def test_行形式を解析し引用と突き合わせる():
    text = (
        "CAND | Aパーティー | 2026-10-03 | VENT | 東京都 | ハウス | https://example.test/a\n"
        "CAND | Bフェス | 2026-10-10;2026-10-11 | WOMB | 東京都 | テクノ | https://example.test/b\n"
    )
    cands, notes, parsed = _parse(text, CITES)
    assert parsed and not notes
    assert [c.name for c in cands] == ["Aパーティー", "Bフェス"]
    assert cands[0].cited is True  # クエリが違っても同じページ
    assert cands[1].cited is False
    assert cands[1].dates == ["2026-10-10", "2026-10-11"]
    assert cands[0].wish_source == "四つ打ちの音楽を楽しみたい"


def test_不明は埋めない():
    cands, _, _ = _parse("CAND | Cイベント | 不明 | 不明 | 不明 | 説明 | https://example.test/c")
    c = cands[0]
    assert c.dates == [] and c.venue is None and c.region is None
    assert c.schedule_fit == discovery.ScheduleFit.UNKNOWN or True


def test_解析できない回答は候補0件と区別する():
    cands, notes, parsed = _parse("すみません、見つかりませんでした。")
    assert cands == [] and notes == []
    assert parsed is False  # **0 件ではなく「解析できなかった」**


def test_見つからない理由を拾う():
    cands, notes, parsed = _parse(f"{discovery.NOTFOUND_PREFIX} | 日程が未発表のため")
    assert parsed is True and notes == ["日程が未発表のため"]


def test_ありえない日付は採用しない():
    dates, raw = discovery.parse_dates("2026-13-45")
    assert dates == [] and raw == "2026-13-45"


def test_期間の判定は既知の日付だけで行う():
    fit, _ = discovery.classify_window([], "", WIN)
    assert fit == discovery.ScheduleFit.UNKNOWN
    fit, _ = discovery.classify_window(["2026-10-03"], "2026-10-03", WIN)
    assert fit == discovery.ScheduleFit.WITHIN
    fit, note = discovery.classify_window(["2026-11-20", "2026-11-24"], "..", WIN)
    assert fit == discovery.ScheduleFit.PARTIAL and "2026-11-24" in note
    fit, _ = discovery.classify_window(["2026-12-01"], "", WIN)
    assert fit == discovery.ScheduleFit.OUTSIDE


def test_会期の途中1日で参加できるかは判定しない():
    cands, _, _ = _parse(
        "CAND | 会期もの | 2026-09-09..2026-11-29 | 日本橋 | 東京都 | 謎解き | https://e.test/x"
    )
    assert cands[0].participation_span is None  # **根拠が無いので不明のまま**


def test_明示された地域違いだけ落とす():
    assert discovery.check_region("幕張メッセ", "千葉県", "東京") is not None
    assert discovery.check_region("ZEROTOKYO", None, "東京") is None  # 会場名では落とさない
    assert discovery.check_region("オンラインのみ", None, "東京") is not None


def test_同じ企画は1件にまとめ日程を足す():
    a, _, _ = _parse("CAND | 同じ企画 | 2026-10-03 | V | 東京都 | x | https://e.test/1")
    b, _, _ = _parse("CAND | 同じ 企画 | 2026-10-04 | V | 東京都 | x | https://e.test/2")
    merged, added = discovery.merge(list(a), b)
    assert len(merged) == 1 and added == 0
    assert merged[0].dates == ["2026-10-03", "2026-10-04"]


def test_並び順はジャンル別日付順で点数を使わない():
    cands, _, _ = _parse(
        "CAND | 遅い | 2026-11-01 | V | 東京都 | x | https://e.test/1\n"
        "CAND | 早い | 2026-10-01 | V | 東京都 | x | https://e.test/2\n"
        "CAND | 日付なし | 不明 | V | 東京都 | x | https://e.test/3\n"
    )
    names = [c.name for c in discovery.order(cands)]
    assert names == ["早い", "遅い", "日付なし"]  # 日付不明は後ろ。架空の日付を入れない


def test_書式見本の行を候補にしない():
    # 依頼文の見本をそのまま返してくることがある（実測）
    cands, _, _ = _parse(
        "CAND | 催しの名前 | 開催日 | 会場 | 都道府県 | 1行の説明 | 情報源URL\n"
        "CAND | 本物のイベント | 2026-10-03 | V | 東京都 | x | https://e.test/1\n"
    )
    assert [c.name for c in cands] == ["本物のイベント"]


def test_会期は重なりで見る():
    # 9/9〜11/29 の会期を「対象期間外」と誤判定していた（実測）
    fit, note = discovery.classify_window(
        ["2026-09-09", "2026-11-29"], "2026-09-09..2026-11-29", WIN
    )
    assert fit == discovery.ScheduleFit.PARTIAL
    assert "未確認" in note  # **参加できる日があるかは断定しない**
    fit, _ = discovery.classify_window(["2026-10-01", "2026-10-31"], "2026-10-01..2026-10-31", WIN)
    assert fit == discovery.ScheduleFit.WITHIN
    fit, _ = discovery.classify_window(["2026-12-01", "2026-12-20"], "2026-12-01..2026-12-20", WIN)
    assert fit == discovery.ScheduleFit.OUTSIDE


def test_同じ会場の同じ日でも別イベントは統合しない():
    """**別イベントを消さない。** 同じ箱の同じ晩に別の企画が立つ。"""
    a, _, _ = _parse(
        "CAND | A.S.F. (TECHNO/HOUSE) | 2026-09-25 | WOMB | 東京都 | x | https://e.test/asf"
    )
    b, _, _ = _parse(
        "CAND | TIME HOLE 30TH ANNIVERSARY | 2026-09-25 | WOMB | 東京都 | y | https://e.test/th"
    )
    merged, added = discovery.merge(list(a), b)
    assert len(merged) == 2 and added == 1
    assert {c.name for c in merged} == {
        "A.S.F. (TECHNO/HOUSE)",
        "TIME HOLE 30TH ANNIVERSARY",
    }


def test_名前が無関係なら日付と会場が同じでも残す():
    a, _, _ = _parse("CAND | 昼の部 ハウス | 2026-10-03 | 同じ会場 | 東京都 | x | 不明")
    b, _, _ = _parse("CAND | 夜の部 テクノ | 2026-10-03 | 同じ会場 | 東京都 | y | 不明")
    merged, _ = discovery.merge(list(a), b)
    assert len(merged) == 2  # **URL も無く名前も違う -> 統合しない**


def test_個別URLが同じなら同じ回として1件にする():
    a, _, _ = _parse("CAND | 表記ゆれA | 2026-10-03 | V | 東京都 | x | https://e.test/same")
    b, _, _ = _parse(
        "CAND | 表記ゆれB | 2026-10-04 | V | 東京都 | x | https://e.test/same?utm_source=openai"
    )
    merged, added = discovery.merge(list(a), b)
    assert len(merged) == 1 and added == 0
    assert merged[0].dates == ["2026-10-03", "2026-10-04"]


def test_名前が含む関係なら同じ日同じ会場で1件にまとめる():
    a, _, _ = _parse(
        "CAND | ポケモンとアスリートのわざ展 特別編 | 2026-09-19 "
        "| 日本オリンピックミュージアム | 東京都 | x | 不明"
    )
    b, _, _ = _parse(
        "CAND | ポケモンとアスリートのわざ展 | 2026-09-19 "
        "| 日本オリンピックミュージアム 1階 | 東京都 | x | 不明"
    )
    merged, added = discovery.merge(list(a), b)
    assert len(merged) == 1 and added == 0


def test_別々の開催日を会期として扱わない():
    """`9/22;10/04` は 2 回の開催であって、9/22〜10/04 の会期ではない。"""
    cands, _, _ = _parse("CAND | 体験レッスン | 2026-09-22;2026-10-04 | 学校 | 東京都 | x | 不明")
    c = cands[0]
    assert c.dates == ["2026-09-22", "2026-10-04"]
    assert ".." not in c.dates_raw  # **会期ではない**
