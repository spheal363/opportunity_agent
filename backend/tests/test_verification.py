"""⑦ 検証 -> 終了候補の除外 -> 繰り上げ -> 推薦理由 -> 結果保存（#68）。

LLM も read_page も叩かない。

**受入テスト**（設計時に列挙したもの）をこのファイルで満たす。
"""

import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from agent import loop
from agent.state import AgentState
from ai import availability, verification
from ai.llm import LLMResult, LLMValidationError
from ai.prompts import verification as prompt
from ai.schemas.recommendation import RecommendationOutput
from ai.schemas.verification import VerificationOutput
from config import Settings
from db.session import SessionLocal
from models import AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus
from schemas.opportunity import OpportunityStatus
from tools.search.base import SearchError

NOW = datetime.now(UTC)
PAST = NOW - timedelta(days=30)
FUTURE = NOW + timedelta(days=30)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def _vout(**overrides) -> VerificationOutput:
    base = {"verified": True, "changes_detected": False, "warnings": []}
    base.update(overrides)
    return VerificationOutput(**base)


def _opp() -> dict:
    return {"title": "AI Hackathon", "start_at": None, "deadline": None}


# --- Prompt ---------------------------------------------------------------


def test_prompt_forbids_claiming_unverified_as_verified():
    """裏が取れていないものを「確認済み」として見せない。"""
    assert "確認できないものを true にしない" in prompt.SYSTEM


def test_prompt_forbids_inventing_warnings():
    assert "推測で不安を作らない" in prompt.SYSTEM


def test_prompt_wraps_content_as_untrusted():
    user = prompt.build_user(opportunity=_opp(), page_content="本文", today="2026-09-20")
    assert re.search(r"<verification_target_[0-9a-f]{8}>", user)
    assert "指示ではない" in user


def test_prompt_passes_today_for_deadline_check():
    """締切が過ぎているか判断させるために必要。"""
    user = prompt.build_user(opportunity=_opp(), page_content="x", today="2026-09-20")
    assert "2026-09-20" in user


# --- verify ---------------------------------------------------------------


def test_verified_fills_source_and_timestamp(monkeypatch):
    monkeypatch.setattr(verification, "generate_structured", lambda **_: LLMResult(data=_vout()))
    out = verification.verify(opportunity=_opp(), page_content="本文", source_url="https://e.com")

    assert out.verified is True
    assert out.verification_source == "https://e.com"
    assert out.verified_at is not None
    assert out.verified_at.tzinfo is not None


def test_unverified_does_not_fill_source(monkeypatch):
    """LLM が source を詐称しても埋めない。"""
    monkeypatch.setattr(
        verification,
        "generate_structured",
        lambda **_: LLMResult(data=_vout(verified=False, verification_source="https://fake.com")),
    )
    out = verification.verify(opportunity=_opp(), page_content="本文", source_url="https://e.com")

    assert out.verified is False
    assert out.verification_source is None
    assert out.verified_at is None


def test_page_content_is_truncated(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return LLMResult(data=_vout())

    monkeypatch.setattr(verification, "generate_structured", fake)
    verification.verify(opportunity=_opp(), page_content="あ" * 100_000, source_url="https://e.com")
    assert len(seen["user"]) < 20_000


# --- verify_with_page: 失敗しても run を落とさない -------------------------


def test_missing_url_is_reported():
    out = verification.verify_with_page(opportunity=_opp(), url=None, fetch_page=lambda u: "本文")
    assert out.verified is False
    assert "URL" in out.warnings[0]


def test_fetch_failure_is_reported():
    def boom(_url):
        raise SearchError("取得失敗")

    out = verification.verify_with_page(opportunity=_opp(), url="https://e.com", fetch_page=boom)
    assert out.verified is False
    assert "取得できません" in out.warnings[0]


def test_empty_page_is_reported():
    out = verification.verify_with_page(
        opportunity=_opp(), url="https://e.com", fetch_page=lambda u: None
    )
    assert out.verified is False
    assert "読み取れません" in out.warnings[0]


def test_llm_failure_is_reported(monkeypatch):
    monkeypatch.setattr(
        verification,
        "generate_structured",
        lambda **_: (_ for _ in ()).throw(LLMValidationError("x")),
    )
    out = verification.verify_with_page(
        opportunity=_opp(), url="https://e.com", fetch_page=lambda u: "本文"
    )
    assert out.verified is False
    assert out.warnings


def test_warnings_pass_through(monkeypatch):
    monkeypatch.setattr(
        verification,
        "generate_structured",
        lambda **_: LLMResult(
            data=_vout(changes_detected=True, warnings=["申込の締切が過ぎています"])
        ),
    )
    out = verification.verify_with_page(
        opportunity=_opp(),
        url="https://e.com",
        fetch_page=lambda u: "本文",
        today=date(2026, 9, 20),
    )
    assert out.changes_detected is True
    assert out.warnings == ["申込の締切が過ぎています"]


# --- Agent Loop への接続 ---------------------------------------------------


@pytest.fixture
def state(db) -> AgentState:
    db.add(AgentRun(run_id="run_v", user_id="user_001", status=AgentRunStatus.RUNNING))
    db.commit()
    return AgentState(run_id="run_v", user_id="user_001")


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(loop, "recommend", lambda **k: RecommendationOutput(reason="r"))


def _add(db, oid: str, **kw) -> str:
    base = {
        "opportunity_id": oid,
        "user_id": "user_001",
        "type": "hackathon",
        "title": oid,
        "url": f"https://e.com/{oid}",
        "score": 50,
        # **行動を特定できる候補が既定。** 特定できないものは
        # `recommended_action=None` を明示して作る。
        "recommended_action": "応募する",
    }
    base.update(kw)
    db.add(Opportunity(**base))
    db.commit()
    return oid


def _out(**kw) -> VerificationOutput:
    base = {"verified": True, "availability": "unknown"}
    base.update(kw)
    return VerificationOutput(**base)


def _logs(db) -> list[str]:
    return [r.message for r in db.query(AgentLog).all()]


def _result(db) -> AgentRun:
    return db.get(AgentRun, "run_v")


# --- Prompt ---------------------------------------------------------------


def test_prompt_separates_verified_from_availability():
    assert "availability は verified とは別の軸である" in prompt.SYSTEM


def test_prompt_forbids_assuming_open_from_a_future_deadline():
    """締切が未来というだけで受付中とは限らない（満員かもしれない）。"""
    assert "締切が未来というだけで open にしない" in prompt.SYSTEM


# --- 受入 1: 抽出時点で期限切れ -------------------------------------------


def test_expired_candidate_is_dropped_before_evaluation(db, state, monkeypatch):
    """**評価対象にしない。** LLM を無駄に使わない。"""
    _add(db, "expired", deadline=PAST)
    _add(db, "alive", deadline=FUTURE)
    seen = {}

    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "evaluate_many",
        lambda **k: seen.update(k)
        or ([(o["opportunity_id"], _eval()) for o in k["opportunities"]], []),
    )
    monkeypatch.setattr(loop, "select_top", lambda ev, **k: [i for i, _ in ev])

    state.goal_analysis = _goal()
    loop._evaluate_and_select(db, state, ["expired", "alive"])

    evaluated_ids = [o["opportunity_id"] for o in seen["opportunities"]]
    assert evaluated_ids == ["alive"]
    assert db.get(Opportunity, "expired").availability == availability.Availability.CLOSED
    assert any("期限切れ" in m for m in _logs(db))


def test_unknown_dates_are_not_dropped(db, state, monkeypatch):
    """**deadline が null は受付終了ではない。** 落とさない。"""
    _add(db, "unknown_date", deadline=None, start_at=None)
    seen = {}
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "evaluate_many",
        lambda **k: seen.update(k) or ([("unknown_date", _eval())], []),
    )
    monkeypatch.setattr(loop, "select_top", lambda ev, **k: [i for i, _ in ev])

    state.goal_analysis = _goal()
    loop._evaluate_and_select(db, state, ["unknown_date"])

    assert [o["opportunity_id"] for o in seen["opportunities"]] == ["unknown_date"]


def test_dismissed_is_dropped_before_evaluation(db, state, monkeypatch):
    """ユーザーが外したものを再び推薦しない。"""
    _add(db, "dismissed", status=OpportunityStatus.DISMISSED)
    _add(db, "alive")
    seen = {}
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "evaluate_many",
        lambda **k: seen.update(k)
        or ([(o["opportunity_id"], _eval()) for o in k["opportunities"]], []),
    )
    monkeypatch.setattr(loop, "select_top", lambda ev, **k: [i for i, _ in ev])

    state.goal_analysis = _goal()
    loop._evaluate_and_select(db, state, ["dismissed", "alive"])

    assert [o["opportunity_id"] for o in seen["opportunities"]] == ["alive"]


# --- 受入 4: 開始済みだが継続中 -------------------------------------------


@pytest.mark.parametrize(
    "opportunity_type,end_at,expected",
    [
        ("community", None, availability.Availability.UNKNOWN),  # 開始済みでも参加できる
        ("job", None, availability.Availability.UNKNOWN),
        ("hackathon", None, availability.Availability.UNKNOWN),  # 終了日が不明
        ("hackathon", PAST, availability.Availability.CLOSED),  # 開催終了
        ("hackathon", FUTURE, availability.Availability.UNKNOWN),  # 開催中
    ],
)
def test_started_but_ongoing_is_not_closed(opportunity_type, end_at, expected):
    """**start_at が過去でも無条件に除外しない。** 種類ごとに判断する。"""
    status, _ = availability.from_dates(
        opportunity_type=opportunity_type, deadline=None, end_at=end_at
    )
    assert status == expected


def test_naive_datetime_from_sqlite_is_treated_as_utc():
    """**SQLite は tz を保持しない。** 読み出した naive な値を UTC とみなす。"""
    naive_past = PAST.replace(tzinfo=None)
    status, _ = availability.from_dates(
        opportunity_type="hackathon", deadline=naive_past, end_at=None
    )
    assert status == availability.Availability.CLOSED


# --- 受入 2: 本文検証で初めて受付終了が判明 -------------------------------


def test_closed_found_by_verification_is_promoted_over(db, state, real_mode, monkeypatch):
    """**期限切れで 3 件を埋めない。** 次順位を繰り上げる。"""
    for oid in ("a", "b", "c", "d"):
        _add(db, oid)
    state.ranked_ids = ["a", "b", "c", "d"]

    def verify(**kw):
        closed = kw["opportunity"]["title"] == "a"
        return _out(availability="closed" if closed else "open")

    monkeypatch.setattr(loop, "verify_with_page", verify)
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["b", "c", "d"]
    assert db.get(Opportunity, "a").availability == availability.Availability.CLOSED
    assert any("受付終了" in m for m in _logs(db))


def test_promotion_is_capped(db, state, real_mode, monkeypatch):
    """繰り上げは最大 2 件。無限に掘らない。"""
    for oid in ("a", "b", "c", "d", "e", "f"):
        _add(db, oid)
    state.ranked_ids = ["a", "b", "c", "d", "e", "f"]

    checked: list[str] = []
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: checked.append(k["opportunity"]["title"]) or _out(availability="closed"),
    )

    loop._verify_and_finalize(db, state)

    assert state.selected_ids == []
    # TOP3 + 繰り上げ 2 = 5 件まで。6 件目は見に行かない
    assert len(checked) == loop.MAX_VERIFY
    assert "f" not in checked


# --- 受入 3: unknown は closed と混同しない -------------------------------


def test_unknown_stays_in_the_result(db, state, real_mode, monkeypatch):
    """**確認できていないだけで、終わったとは限らない。** 要確認として残す。"""
    _add(db, "a")
    state.ranked_ids = ["a"]
    monkeypatch.setattr(
        loop, "verify_with_page", lambda **k: _out(verified=False, availability="unknown")
    )

    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["a"]
    row = db.get(Opportunity, "a")
    assert row.verified is False
    assert row.availability == availability.Availability.UNKNOWN


def test_failed_verification_does_not_keep_an_old_open(db, state, real_mode, monkeypatch):
    """**再確認に失敗したら、古い open を今回の結果として返さない。**"""
    _add(db, "a", availability="open", availability_checked_at=PAST)
    state.ranked_ids = ["a"]
    from ai.verification import unverified

    monkeypatch.setattr(loop, "verify_with_page", lambda **k: unverified("取得できませんでした"))

    loop._verify_and_finalize(db, state)

    row = db.get(Opportunity, "a")
    assert row.availability == availability.Availability.UNKNOWN
    # SQLite は tz を保持しないため、比較前に UTC を付ける
    assert availability.as_utc(row.availability_checked_at) > PAST


# --- 受入 5: 有効候補が 3 件未満 -------------------------------------------


def test_returns_fewer_than_three_with_a_reason(db, state, real_mode, monkeypatch):
    """**3 件を無理に埋めない。** 不足理由を返す。"""
    _add(db, "a")
    _add(db, "b")
    state.ranked_ids = ["a", "b"]

    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed" if k["opportunity"]["title"] == "a" else "open"),
    )
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["b"]
    assert state.shortfall_reason is not None
    assert _result(db).shortfall_reason == state.shortfall_reason


def test_all_closed_returns_zero_with_a_reason(db, state, real_mode, monkeypatch):
    _add(db, "a")
    state.ranked_ids = ["a"]
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out(availability="closed"))

    loop._verify_and_finalize(db, state)

    assert state.selected_ids == []
    assert "受付を終了" in state.shortfall_reason


def test_fetch_failure_is_explained(db, state, real_mode, monkeypatch):
    """取得失敗も説明できる。"""
    _add(db, "a")
    state.ranked_ids = ["a"]

    def boom(**kw):
        raise SearchError("取得できません")

    from ai.verification import verify_with_page as real

    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: real(
            opportunity=k["opportunity"],
            url=k["url"],
            fetch_page=lambda u: (_ for _ in ()).throw(SearchError("x")),
        ),
    )
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["a"]  # 取得失敗は unknown。落とさない
    assert any("確認できませんでした" in m for m in _logs(db))


# --- 受入 6 / 7: 結果の記録 -----------------------------------------------


def test_selected_ids_and_order_are_saved(db, state, real_mode, monkeypatch):
    """**画面と Agent の選定を一致させる。**"""
    for oid in ("a", "b", "c"):
        _add(db, oid)
    state.ranked_ids = ["c", "a", "b"]
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out(availability="open"))

    loop._verify_and_finalize(db, state)

    assert _result(db).selected_ids == ["c", "a", "b"]


def test_reasons_are_written_only_for_the_final(db, state, real_mode, monkeypatch):
    """**最終候補にだけ**推薦理由を書く。落ちた候補には書かない。"""
    _add(db, "a")
    _add(db, "b")
    state.ranked_ids = ["a", "b"]
    called = []

    def rec(**kw):
        called.append(kw["opportunity"]["opportunity_id"])
        return RecommendationOutput(reason="r")

    monkeypatch.setattr(loop, "recommend", rec)
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed" if k["opportunity"]["title"] == "a" else "open"),
    )
    loop._verify_and_finalize(db, state)

    assert called == ["b"]
    assert db.get(Opportunity, "a").reason is None


def test_recommendation_failure_does_not_fail_the_run(db, state, real_mode, monkeypatch):
    _add(db, "a")
    state.ranked_ids = ["a"]
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out(availability="open"))
    monkeypatch.setattr(
        loop, "recommend", lambda **k: (_ for _ in ()).throw(LLMValidationError("x"))
    )

    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["a"]
    assert db.get(Opportunity, "a").status == OpportunityStatus.RECOMMENDED


def test_user_decided_status_is_kept(db, state, real_mode, monkeypatch):
    _add(db, "a", status=OpportunityStatus.INTERESTED)
    state.ranked_ids = ["a"]
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out(availability="open"))

    loop._verify_and_finalize(db, state)

    assert db.get(Opportunity, "a").status == OpportunityStatus.INTERESTED


# --- Stub 経路 -------------------------------------------------------------


def test_stub_mode_still_works(db, state):
    for oid in ("a", "b", "c"):
        _add(db, oid)
    state.ranked_ids = ["a", "b", "c"]

    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["a", "b", "c"]
    assert db.get(Opportunity, "a").verified is True
    assert _result(db).selected_ids == ["a", "b", "c"]


# --- ヘルパ ---------------------------------------------------------------


def _eval(**kw):
    from ai.schemas.evaluation import EvaluationOutput

    base = {"score": 80, "serendipity_score": 50, "match_reasons": ["AI"], "concerns": []}
    base.update(kw)
    return EvaluationOutput(**base)


def _goal():
    from ai.schemas.goal_analysis import GoalAnalysisOutput

    return GoalAnalysisOutput(goal_summary="g", goal_directions=["d"], interest_connections=["c"])


# --- 応募先を特定できない候補は最終推薦に出さない（#65）---------------------
#
# 実測で、ハッカソンの**投稿作品ページ**（他人の提出物）が TOP1 に入った。
# 検索結果一覧そのものが候補になったこともある。どちらも本人が直接
# 応募・参加できるものではない。


def test_a_candidate_without_an_action_is_not_recommended(db, state, real_mode, monkeypatch):
    """**行動の対象を特定できないものは出さない。**"""
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out())
    state.ranked_ids = [
        _add(db, "gallery", recommended_action=None),
        _add(db, "real"),
    ]
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["real"]


def test_it_is_not_decided_by_type(db, state, real_mode, monkeypatch):
    """**type で決めない。**

    解説記事（type=other）でも、本文から募集先が読み取れていれば通す。
    """
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out())
    state.ranked_ids = [
        _add(db, "article", type="other", recommended_action="応募する"),
    ]
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["article"]


def test_shortfall_says_why_when_articles_were_dropped(db, state, real_mode, monkeypatch):
    """**記事で埋めない。件数不足と理由を返す。**"""
    monkeypatch.setattr(loop, "verify_with_page", lambda **k: _out())
    state.ranked_ids = [
        _add(db, "a1", recommended_action=None),
        _add(db, "a2", recommended_action=None),
        _add(db, "real"),
    ]
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["real"]
    assert "2件" in state.shortfall_reason
    assert "行動の対象" in state.shortfall_reason


def test_a_dropped_candidate_costs_no_verification(db, state, real_mode, monkeypatch):
    """**確認に費用をかけない。** 検証より前に外す。"""
    calls = {"n": 0}

    def verify(**kwargs):
        calls["n"] += 1
        return _out()

    monkeypatch.setattr(loop, "verify_with_page", verify)
    state.ranked_ids = [_add(db, "gallery", recommended_action=None), _add(db, "real")]
    loop._verify_and_finalize(db, state)

    assert calls["n"] == 1


def test_unknown_availability_is_still_recommended(db, state, real_mode, monkeypatch):
    """**受付状況が unknown でも出す。** 不明点は理由で示す。"""
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(
            availability="unknown", availability_reason="受付状況は確認できませんでした"
        ),
    )
    state.ranked_ids = [_add(db, "u1")]
    loop._verify_and_finalize(db, state)

    assert state.selected_ids == ["u1"]
    row = db.get(loop.Opportunity, "u1")
    assert row.availability == "unknown"
    assert row.availability_reason


# --- 検証が締切の区分を見ずに閉じないこと（PR #10 の指摘）------------------
#
# 検証はページ文言だけで open / closed を決めている。渡しているのは
# `_as_dict` の中身で、`deadline_kind` は入っていない。
#
# そのため、取り消し線つきの「応募を締め切りました」（登壇者募集）を拾って
# `closed` を返しうる。**抽出段階で unknown に倒したはずの判断が、
# 最後の一歩で誤って閉じられる。**


def test_verification_cannot_close_on_a_non_participation_deadline(
    db, state, real_mode, monkeypatch
):
    """**早割の期限しか分かっていないのに、検証の closed で閉じない。**"""
    from datetime import UTC, datetime

    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="応募を締め切りました"),
    )
    state.ranked_ids = [
        _add(
            db,
            "early",
            deadline=datetime(2026, 1, 1, tzinfo=UTC),
            deadline_kind="early_bird",
        )
    ]
    loop._verify_and_finalize(db, state)

    row = db.get(loop.Opportunity, "early")
    assert row.availability == "unknown"
    assert "参加の締切かどうかを確認できませんでした" in row.availability_reason
    # **候補としては残る。**
    assert state.selected_ids == ["early"]


def test_verification_still_closes_a_confirmed_participation_deadline(
    db, state, real_mode, monkeypatch
):
    """**閉じるべきものは閉じる。** 緩めすぎない。"""
    from datetime import UTC, datetime

    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="受付を終了しました"),
    )
    state.ranked_ids = [
        _add(
            db,
            "app",
            deadline=datetime(2026, 1, 1, tzinfo=UTC),
            deadline_kind="application",
        )
    ]
    loop._verify_and_finalize(db, state)

    row = db.get(loop.Opportunity, "app")
    assert row.availability == "closed"
    assert row.availability_reason == "受付を終了しました"


def test_verification_can_still_close_when_there_is_no_deadline(db, state, real_mode, monkeypatch):
    """締切そのものが無いときは、検証の判断をそのまま採る。

    **見張るのは「参加の締切ではない締切で閉じようとする」場合だけ。**
    """
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="開催は終了しました"),
    )
    state.ranked_ids = [_add(db, "nodl")]
    loop._verify_and_finalize(db, state)

    assert db.get(loop.Opportunity, "nodl").availability == "closed"


def test_verification_opening_is_never_second_guessed(db, state, real_mode, monkeypatch):
    """**開ける向きは触らない。**

    検証はページを読んでいるので、open の根拠は抽出時より確かなことが多い。
    """
    from datetime import UTC, datetime

    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="open", availability_reason="エントリー受付中"),
    )
    state.ranked_ids = [
        _add(
            db,
            "open1",
            deadline=datetime(2026, 1, 1, tzinfo=UTC),
            deadline_kind="early_bird",
        )
    ]
    loop._verify_and_finalize(db, state)

    assert db.get(loop.Opportunity, "open1").availability == "open"


# --- 倒す範囲を表で固定する（再レビューでの自己指摘）------------------------
#
# **最初の実装は倒しすぎていた。** 締切が未来でも倒しており、
# 「満員につき受付終了」のようにページを読んで初めて分かる観察まで
# 捨てていた。**見張るのは「過ぎた締切を読み違えた」場合だけ。**

_PAST = datetime(2020, 1, 1, tzinfo=UTC)
_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _guarded(deadline, kind, *, date_only: bool | None = False) -> str:
    row = SimpleNamespace(
        type="event",
        title="t",
        description=None,
        deadline=deadline,
        end_at=None,
        deadline_kind=kind,
        deadline_is_date_only=date_only,
        end_at_is_date_only=False,
    )
    out = SimpleNamespace(availability="closed", availability_reason="募集を締め切りました")
    status, _ = loop._verified_availability(row, out)
    return str(status)


@pytest.mark.parametrize(
    ("label", "deadline", "kind", "expected"),
    [
        # 狙った不具合。過ぎた「参加の締切ではない締切」を読み違えた場合
        ("早割の期限が過去", _PAST, "early_bird", "unknown"),
        ("登壇募集の締切が過去", _PAST, "speaker", "unknown"),
        ("区分 unknown・締切が過去", _PAST, "unknown", "unknown"),
        # 閉じるべきものは閉じる
        ("申込締切が過去", _PAST, "application", "closed"),
        ("参加登録の期限が過去", _PAST, "registration", "closed"),
        # **締切が未来なら、検証の closed はその締切の話ではない**
        ("申込締切が未来（満員など）", _FUTURE, "application", "closed"),
        ("早割の期限が未来（満員など）", _FUTURE, "early_bird", "closed"),
        ("区分 unknown・締切が未来", _FUTURE, "unknown", "closed"),
        # 旧データ（区分を持たない行）の挙動を変えない
        ("旧データ・締切が過去", _PAST, None, "closed"),
        ("旧データ・締切が未来", _FUTURE, None, "closed"),
        # 締切そのものが無い
        ("締切なし", None, None, "closed"),
    ],
)
def test_the_guard_fires_only_on_a_passed_non_participation_deadline(
    label, deadline, kind, expected
):
    assert _guarded(deadline, kind) == expected, label


@pytest.mark.parametrize("date_only", [False, True, None])
def test_the_guard_does_not_depend_on_the_date_precision(date_only):
    """**日付の精度で結論を変えない。**

    `deadline_is_date_only` は「出典に時刻が書かれていたか」であって、
    「検証が読み違えうるか」とは関係がない。表の全行を 3 通りで通す。
    """
    assert _guarded(_PAST, "early_bird", date_only=date_only) == "unknown"
    assert _guarded(_PAST, "application", date_only=date_only) == "closed"
    assert _guarded(_FUTURE, "early_bird", date_only=date_only) == "closed"
    assert _guarded(None, None, date_only=date_only) == "closed"


def test_a_date_only_deadline_today_is_still_treated_as_misreadable():
    """**`availability._is_past` とはわざと違う判定を使っている。**

    あちらは「日付だけの締切は当日中は過ぎていない」とする（00:00 は
    こちらの正規化で、出典の時刻ではないため）。

    ここで見たいのは「検証が読み違えうる終了っぽい日付が近くにあるか」で、
    当日が期限の締切もページには終了告知が載りうる。**広く取る。**

    広く取ると `unknown` へ倒れる側に外れるので、誤って閉じることはない。
    """
    today_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # `_is_past` は「まだ過ぎていない」と言う
    assert availability._is_past(today_midnight, datetime.now(UTC), date_only=True) is False
    # ここでは倒す（安全側）。**精度によらず同じ。**
    for date_only in (True, None, False):
        assert _guarded(today_midnight, "early_bird", date_only=date_only) == "unknown"


def test_a_naive_deadline_from_sqlite_does_not_crash():
    """SQLite は tz を保持しない。**naive な値で落ちない。**"""
    naive = (datetime.now(UTC) - timedelta(days=5)).replace(tzinfo=None)
    assert _guarded(naive, "early_bird") == "unknown"


# --- 実測: 2023 年の申込締切が推薦に残った（#47）-----------------------------


def test_a_passed_application_deadline_found_by_verification_closes_it(
    db, state, real_mode, monkeypatch
):
    """**実測で、申込締切 2023 年 12 月の候補が推薦に残った。**

    検証は「申込の締切が過ぎています」と書いていたのに、抽出が
    `deadline_kind` を決められず `unknown` だったため、見張りが
    「参加の締切か確認できない」として `unknown` へ戻していた。

    **古い日付だから閉じるのではない。** 検証が読んだ終了の根拠が、
    推薦する行動（応募）に対応する締切を指しているから閉じる。
    """
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="申込の締切が過ぎています"),
    )
    state.ranked_ids = [
        _add(db, "old", deadline=datetime(2023, 12, 19, tzinfo=UTC), deadline_kind="unknown")
    ]
    loop._verify_and_finalize(db, state)

    assert db.get(loop.Opportunity, "old").availability == "closed"
    assert state.selected_ids == [], "受付終了の候補を推薦に残している"


def test_an_early_bird_notice_still_cannot_close_it(db, state, real_mode, monkeypatch):
    """**区分が分かっているなら、そちらを優先する。**

    早割と分類できているなら、検証が何と書いていても参加は塞がれていない。
    """
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="応募を締め切りました"),
    )
    state.ranked_ids = [
        _add(db, "eb", deadline=datetime(2026, 1, 1, tzinfo=UTC), deadline_kind="early_bird")
    ]
    loop._verify_and_finalize(db, state)

    assert db.get(loop.Opportunity, "eb").availability == "unknown"


def test_a_speaker_call_notice_does_not_close_participation(db, state, real_mode, monkeypatch):
    """登壇者募集の終了は、参加の締切ではない。"""
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: _out(availability="closed", availability_reason="登壇者の募集を終了しました"),
    )
    state.ranked_ids = [
        _add(db, "cfp", deadline=datetime(2026, 1, 1, tzinfo=UTC), deadline_kind="unknown")
    ]
    loop._verify_and_finalize(db, state)

    assert db.get(loop.Opportunity, "cfp").availability == "unknown"
