"""⑦ 検証 -> 終了候補の除外 -> 繰り上げ -> 推薦理由 -> 結果保存（#68）。

LLM も read_page も叩かない。

**受入テスト**（設計時に列挙したもの）をこのファイルで満たす。
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent import loop
from agent.state import AgentState
from ai import availability
from ai.llm import LLMValidationError
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
