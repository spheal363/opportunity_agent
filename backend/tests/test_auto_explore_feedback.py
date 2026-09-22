"""👎が重なったら探し直す（#84）と、全自動 trigger に共通の止める仕組み。

**自動にするのは発見だけ。** 止める条件はすべてコードが強制する。
既定はオフで、オフのときは今の挙動を何も変えない。
"""

import sqlite3

import pytest
from sqlalchemy import create_engine

from db.migrate import add_missing_columns
from db.session import SessionLocal
from models import AgentLog, AgentRun, Feedback, Opportunity
from schemas.agent import AgentRunStatus, AgentRunTrigger
from schemas.opportunity import OpportunityStatus
from services import auto_explore
from tests.auto_explore_seed import (
    NOW,
    USER,
    add_dislike,
    add_opp,
    add_profile,
    add_run,
    ago,
    settings,
)

PAGE = {"X-Requested-With": "opportunity-agent"}
ON = settings(auto_explore_on_feedback=True)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def picks(db):
    """プロフィールと、完了した最新の run（推薦 3 件）。"""
    add_profile(db)
    for oid in ("a", "b", "c"):
        add_opp(db, oid)
    add_run(db, "run_base", created=ago(minutes=10), selected=["a", "b", "c"])


def _decide(db, conf=ON):
    return auto_explore.decide_after_feedback(db, USER, NOW, conf)


# --- A1 の成立 / 不成立 ---------------------------------------------------


def test_starts_when_most_picks_got_a_thumbs_down(db, picks):
    add_dislike(db, "a")
    add_dislike(db, "b")

    decision = _decide(db)

    assert decision is not None
    assert decision.trigger is AgentRunTrigger.FEEDBACK
    # **決まった文面と数値だけ。** 候補のタイトルは入らない
    assert decision.reason == "今回の推薦3件のうち2件に👎が付いたため、反応を踏まえて探し直します"
    assert "のタイトル" not in decision.reason


def test_dismissed_status_counts_as_a_thumbs_down(db, picks):
    add_dislike(db, "a")
    row = db.get(Opportunity, "b")
    row.status = OpportunityStatus.DISMISSED
    db.commit()

    assert _decide(db) is not None


def test_one_thumbs_down_is_not_enough(db, picks):
    add_dislike(db, "a")
    assert _decide(db) is None


def test_half_is_not_a_majority(db):
    add_profile(db)
    for oid in ("a", "b", "c", "d"):
        add_opp(db, oid)
    add_run(db, "run_base", created=ago(minutes=10), selected=["a", "b", "c", "d"])
    add_dislike(db, "a")
    add_dislike(db, "b")

    assert _decide(db) is None

    add_dislike(db, "c")
    assert _decide(db) is not None


def test_needs_at_least_two_picks(db):
    add_profile(db)
    add_opp(db, "a")
    add_run(db, "run_base", created=ago(minutes=10), selected=["a"])
    add_dislike(db, "a")

    assert _decide(db) is None


def test_same_dislike_twice_counts_once(db, picks):
    add_dislike(db, "a")
    add_dislike(db, "a")
    assert _decide(db) is None


@pytest.mark.parametrize(
    "status", [AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.FAILED]
)
def test_does_not_start_when_a_newer_run_exists(db, picks, status):
    """**同じ run への探し直しは 1 回まで。** 探し直した run が失敗しても繰り返さない。"""
    add_dislike(db, "a")
    add_dislike(db, "b")
    add_run(
        db, "run_newer", created=ago(minutes=5), status=status, trigger=AgentRunTrigger.FEEDBACK
    )

    assert _decide(db) is None


def test_does_not_start_when_the_latest_run_is_not_completed(db):
    add_profile(db)
    add_opp(db, "a")
    add_opp(db, "b")
    add_run(
        db,
        "run_base",
        created=ago(minutes=10),
        status=AgentRunStatus.FAILED,
        selected=["a", "b"],
    )
    add_dislike(db, "a")
    add_dislike(db, "b")

    assert _decide(db) is None


def test_flag_off_does_nothing(db, picks):
    add_dislike(db, "a")
    add_dislike(db, "b")

    assert _decide(db, settings()) is None


# --- 共通の止める仕組み ----------------------------------------------------


def _both_disliked(db):
    add_dislike(db, "a")
    add_dislike(db, "b")


def test_no_profile_blocks(db):
    for oid in ("a", "b", "c"):
        add_opp(db, oid)
    add_run(db, "run_base", created=ago(minutes=10), selected=["a", "b", "c"])
    _both_disliked(db)

    assert _decide(db) is None
    assert auto_explore.blocked_reason(db, USER, NOW, ON) == "no_profile"


def test_a_running_run_blocks(db, picks):
    """古い run がまだ進捗を書いているなら、実行中とみなす。"""
    _both_disliked(db)
    add_run(
        db,
        "run_old",
        created=ago(minutes=20),
        updated=ago(minutes=1),
        status=AgentRunStatus.RUNNING,
    )

    assert auto_explore.blocked_reason(db, USER, NOW, ON) == "run_in_progress"
    assert _decide(db) is None


def test_an_abandoned_running_run_does_not_block(db, picks):
    """プロセスが落ちて running のまま残った run に、自動探索を止めさせない。"""
    _both_disliked(db)
    add_run(db, "run_dead", created=ago(hours=3), status=AgentRunStatus.RUNNING)

    assert auto_explore.blocked_reason(db, USER, NOW, ON) is None
    assert _decide(db) is not None


def test_daily_run_limit(db, picks):
    _both_disliked(db)
    for i, hours in enumerate((20, 19, 18)):
        add_run(
            db,
            f"run_auto_{i}",
            created=ago(hours=hours),
            trigger=AgentRunTrigger.SCHEDULED,
        )

    assert auto_explore.blocked_reason(db, USER, NOW, ON) == "daily_run_limit"
    # 上限を上げれば通る（数えているのは直近 24 時間の自動 run）
    assert _decide(db, settings(auto_explore_on_feedback=True, auto_explore_max_runs_per_day=4))


def test_runs_older_than_24_hours_do_not_count(db, picks):
    _both_disliked(db)
    for i in range(3):
        add_run(
            db,
            f"run_auto_{i}",
            created=ago(hours=25 + i),
            trigger=AgentRunTrigger.SCHEDULED,
        )

    assert _decide(db) is not None


def test_manual_runs_do_not_count_toward_the_run_limit(db, picks):
    _both_disliked(db)
    for i in range(3):
        add_run(db, f"run_manual_{i}", created=ago(hours=5 + i))

    assert _decide(db) is not None


def test_daily_cost_limit_counts_manual_runs_too(db, picks):
    """**費用は誰が始めたかに関係なくかかる。** 手動の run の見積もり額も数える。"""
    _both_disliked(db)
    add_run(db, "run_expensive", created=ago(hours=3), cost=19.5)
    assert _decide(db) is not None

    add_run(db, "run_more", created=ago(hours=2), cost=0.5)
    assert auto_explore.blocked_reason(db, USER, NOW, ON) == "daily_cost_limit"
    assert _decide(db) is None


def test_min_interval_between_automatic_runs(db):
    add_profile(db)
    for oid in ("a", "b", "c"):
        add_opp(db, oid)
    add_run(db, "run_auto", created=ago(minutes=30), trigger=AgentRunTrigger.STALE)
    add_run(db, "run_base", created=ago(minutes=10), selected=["a", "b", "c"])
    _both_disliked(db)

    assert auto_explore.blocked_reason(db, USER, NOW, ON) == "min_interval"
    assert _decide(db) is None
    # 間隔を縮めれば通る
    assert _decide(
        db, settings(auto_explore_on_feedback=True, auto_explore_min_interval_minutes=20)
    )


# --- 止まったまま残った run ------------------------------------------------


def test_expire_abandoned_runs_marks_them_failed_with_a_fixed_message(db):
    add_run(db, "run_dead", created=ago(hours=3), status=AgentRunStatus.RUNNING)
    add_run(db, "run_stuck", created=ago(hours=2), status=AgentRunStatus.QUEUED)
    add_run(
        db,
        "run_alive",
        created=ago(minutes=40),
        updated=ago(minutes=2),
        status=AgentRunStatus.RUNNING,
    )

    assert auto_explore.expire_abandoned_runs(db, USER, NOW, ON) == 2

    db.expire_all()
    dead = db.get(AgentRun, "run_dead")
    assert dead.status == AgentRunStatus.FAILED
    assert dead.error == auto_explore.ABANDONED_ERROR
    assert db.get(AgentRun, "run_stuck").status == AgentRunStatus.FAILED
    assert db.get(AgentRun, "run_alive").status == AgentRunStatus.RUNNING


def test_flag_off_leaves_abandoned_runs_alone(db, picks):
    """**オフなら何も変えない。** 止まった run の片付けもしない。"""
    _both_disliked(db)
    add_run(db, "run_dead", created=ago(hours=3), status=AgentRunStatus.RUNNING)

    assert auto_explore.start_after_feedback(db, USER, "dislike", NOW) is None

    db.expire_all()
    assert db.get(AgentRun, "run_dead").status == AgentRunStatus.RUNNING


# --- run の作成 ------------------------------------------------------------


def test_start_creates_a_run_with_the_reason_as_the_first_log(db, picks, monkeypatch):
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)
    _both_disliked(db)

    run_id = auto_explore.start_after_feedback(db, USER, "dislike", NOW)

    assert run_id is not None
    run = db.get(AgentRun, run_id)
    assert run.trigger == AgentRunTrigger.FEEDBACK
    assert run.status == AgentRunStatus.QUEUED
    assert run.trigger_reason.startswith("今回の推薦3件のうち2件に👎")
    logs = db.query(AgentLog).filter(AgentLog.run_id == run_id).all()
    assert [(log.step, log.message) for log in logs] == [("analyzing_profile", run.trigger_reason)]


def test_like_never_starts_a_run(db, picks, monkeypatch):
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)
    _both_disliked(db)

    assert auto_explore.start_after_feedback(db, USER, "like", NOW) is None


def test_failure_in_the_decision_is_logged_not_raised(db, picks, monkeypatch, caplog):
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)

    def boom(*_args, **_kwargs):
        raise RuntimeError("SELECT ... secret profile text")

    monkeypatch.setattr(auto_explore, "decide_after_feedback", boom)

    assert auto_explore.start_after_feedback(db, USER, "dislike", NOW) is None
    # 例外の型と場所だけ。**例外の文字列は出さない**
    assert "type=RuntimeError" in caplog.text
    assert "secret profile text" not in caplog.text


# --- feedback の route -----------------------------------------------------


def _explore_once(client, profile_payload) -> list[str]:
    client.put("/api/profile", json=profile_payload, headers=PAGE)
    run_id = client.post("/api/agent/runs", headers=PAGE).json()["data"]["run_id"]
    result = client.get(f"/api/agent/runs/{run_id}/result").json()["data"]
    return [o["opportunity_id"] for o in result["selected"]]


def _runs():
    s = SessionLocal()
    try:
        return s.query(AgentRun).order_by(AgentRun.created_at.asc()).all()
    finally:
        s.close()


def _dislike(client, oid):
    res = client.post(
        f"/api/opportunities/{oid}/feedback", json={"reaction": "dislike"}, headers=PAGE
    )
    assert res.status_code == 200
    assert res.json()["data"] == {"opportunity_id": oid, "recorded": True}


def test_route_starts_a_run_after_the_second_thumbs_down(client, profile_payload, monkeypatch):
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)
    ids = _explore_once(client, profile_payload)
    assert len(ids) == 3

    _dislike(client, ids[0])
    assert len(_runs()) == 1

    _dislike(client, ids[1])
    runs = _runs()
    assert len(runs) == 2
    auto = runs[-1]
    assert auto.trigger == AgentRunTrigger.FEEDBACK
    # TestClient は BackgroundTask を返却後に同期実行する。探索まで走っている
    assert auto.status == AgentRunStatus.COMPLETED

    state = client.get(f"/api/agent/runs/{auto.run_id}").json()["data"]
    assert state["trigger"] == "feedback"
    assert state["trigger_reason"] == (
        "今回の推薦3件のうち2件に👎が付いたため、反応を踏まえて探し直します"
    )
    logs = client.get(f"/api/agent/runs/{auto.run_id}/logs").json()["data"]
    # **探索中画面の先頭に「なぜ始めたか」。** AgentStep は増やさない
    assert logs[0] == {
        "step": "analyzing_profile",
        "message": state["trigger_reason"],
        "created_at": logs[0]["created_at"],
    }


def test_route_does_not_retry_the_same_run_twice(client, profile_payload, monkeypatch):
    """探し直した run が失敗しても、元の run についてもう一度は探し直さない。

    間隔の上限を外して、「同じ run への探し直しは 1 回まで」だけで止まることを見る。
    """
    monkeypatch.setattr(
        auto_explore,
        "get_settings",
        lambda: settings(auto_explore_on_feedback=True, auto_explore_min_interval_minutes=0),
    )
    ids = _explore_once(client, profile_payload)

    def fail_run(run_id, _user_id):
        s = SessionLocal()
        try:
            s.get(AgentRun, run_id).status = AgentRunStatus.FAILED
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("api.routes.opportunities.run_agent", fail_run)
    _dislike(client, ids[0])
    _dislike(client, ids[1])
    assert [r.status for r in _runs()] == [AgentRunStatus.COMPLETED, AgentRunStatus.FAILED]

    # 3 件目にも👎。**元の run への探し直しはもう済んでいる**
    _dislike(client, ids[2])
    assert len(_runs()) == 2


def test_route_does_nothing_by_default(client, profile_payload):
    """既定はオフ。👎を重ねても run は増えない（今の挙動のまま）。"""
    ids = _explore_once(client, profile_payload)
    for oid in ids:
        _dislike(client, oid)

    runs = _runs()
    assert len(runs) == 1
    assert runs[0].trigger == AgentRunTrigger.MANUAL
    state = client.get(f"/api/agent/runs/{runs[0].run_id}").json()["data"]
    assert state["trigger"] == "manual"
    assert state["trigger_reason"] is None


def test_route_records_feedback_even_if_auto_explore_fails(client, profile_payload, monkeypatch):
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)

    def boom(*_args, **_kwargs):
        raise RuntimeError("db is gone")

    monkeypatch.setattr(auto_explore, "decide_after_feedback", boom)
    ids = _explore_once(client, profile_payload)

    _dislike(client, ids[0])

    s = SessionLocal()
    try:
        assert s.query(Feedback).count() == 1
    finally:
        s.close()


# --- 既存 DB への列の追加 --------------------------------------------------


def test_migrate_adds_trigger_columns_to_an_existing_runs_table(tmp_path):
    """列を足す前の run は手動だった。**既定値 manual がそのまま正しい。**"""
    import models  # noqa: F401  モデル登録のため

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE agent_runs (run_id TEXT PRIMARY KEY, user_id TEXT, status TEXT)")
    conn.execute("INSERT INTO agent_runs VALUES ('run_old', 'user_001', 'completed')")
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{path}")
    added = add_missing_columns(engine)

    assert {"agent_runs.trigger", "agent_runs.trigger_reason"} <= set(added)
    conn = sqlite3.connect(path)
    row = conn.execute('SELECT "trigger", trigger_reason FROM agent_runs').fetchone()
    conn.close()
    assert row == ("manual", None)
    # 2 回目は何も足さない（冪等）
    assert add_missing_columns(engine) == []
