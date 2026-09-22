"""定期チェック（#85）: 推薦が締切切れで減った（stale）・前回から時間がたった（scheduled）。

止める仕組みは feedback と共通（tests/test_auto_explore_feedback.py）。ここでは
きっかけの成立 / 不成立と、定期チェックの回し方を見る。
"""

import asyncio

import pytest

from agent import scheduler
from db.session import SessionLocal
from models import AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus, AgentRunTrigger
from schemas.opportunity import OpportunityStatus
from services import auto_explore
from tests.auto_explore_seed import NOW, USER, add_opp, add_profile, add_run, ago, settings

ON = settings(auto_explore_schedule=True)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def explored(db):
    """プロフィールと、3 時間前に完了した run。scheduled（24 時間）はまだ来ない。"""
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=3))


def _decide(db, conf=ON):
    return auto_explore.decide_on_tick(db, USER, NOW, conf)


# --- stale ---------------------------------------------------------------


def test_stale_when_a_pick_expired_after_the_last_run(db, explored):
    add_opp(db, "expired", deadline=ago(hours=1))
    add_opp(db, "open_1")
    add_opp(db, "saved", status=OpportunityStatus.INTERESTED)

    decision = _decide(db)

    assert decision is not None
    assert decision.trigger is AgentRunTrigger.STALE
    # **決まった文面と数値だけ。** 候補のタイトルは入らない
    assert (
        decision.reason == "推薦中の機会のうち1件が締切を過ぎたか開催を終えたため、新しく探します"
    )


def test_event_that_ended_counts_as_expired(db, explored):
    add_opp(db, "ended", end_at=ago(hours=1), type_="event")

    decision = _decide(db)

    assert decision is not None
    assert decision.trigger is AgentRunTrigger.STALE


def test_not_stale_while_three_picks_are_still_actionable(db, explored):
    add_opp(db, "expired", deadline=ago(hours=1))
    for i in range(3):
        add_opp(db, f"open_{i}")

    assert _decide(db) is None


def test_expiry_before_the_last_run_is_not_counted_again(db, explored):
    """**同じ期限切れで何度も走らせない。** 前回の探索はもう知っていた。"""
    add_opp(db, "expired_long_ago", deadline=ago(hours=5))

    assert _decide(db) is None


def test_known_closed_is_not_actionable_but_not_new(db, explored):
    """受付終了は探索中の検証で分かったもの。前回の run が知っている。"""
    add_opp(db, "closed", availability="closed", deadline=ago(hours=1))
    add_opp(db, "open_1")

    assert _decide(db) is None


def test_early_bird_deadline_does_not_close_the_pick(db, explored):
    """締切の種類の扱いは ai/availability.py と同じ。早割の期限では閉じない。"""
    add_opp(db, "early_bird", deadline=ago(hours=1))
    row = db.get(Opportunity, "early_bird")
    row.deadline_kind = "early_bird"
    db.commit()

    assert _decide(db) is None


def test_only_recommended_and_saved_picks_count(db, explored):
    add_opp(db, "attended", status=OpportunityStatus.ATTENDED, deadline=ago(hours=1))
    add_opp(db, "dismissed", status=OpportunityStatus.DISMISSED, deadline=ago(hours=1))

    assert _decide(db) is None


# --- scheduled -----------------------------------------------------------


def test_scheduled_after_the_interval(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=25))

    decision = _decide(db)

    assert decision is not None
    assert decision.trigger is AgentRunTrigger.SCHEDULED
    # 設定値ではなく**実際にたった時間**で書く
    assert decision.reason == "前回の探索から25時間たったため、新着を探します"


def test_not_scheduled_before_the_interval(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=23))

    assert _decide(db) is None


def test_short_interval_reads_in_minutes(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(minutes=7))
    conf = settings(
        auto_explore_schedule=True,
        auto_explore_schedule_interval_minutes=5,
        auto_explore_min_interval_minutes=0,
    )

    decision = _decide(db, conf)

    assert decision is not None
    assert decision.reason == "前回の探索から7分たったため、新着を探します"


def test_stale_comes_before_scheduled(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=25))
    add_opp(db, "expired", deadline=ago(hours=1))

    assert _decide(db).trigger is AgentRunTrigger.STALE


def test_never_starts_for_someone_who_never_explored(db):
    """最初の探索は本人が始める。「前回」が無ければ条件を決められない。"""
    add_profile(db)
    add_opp(db, "expired", deadline=ago(hours=1))

    assert _decide(db) is None


def test_flag_off_does_nothing(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=48))

    assert _decide(db, settings()) is None


# --- 共通の止める仕組みも効く -----------------------------------------------


def test_cost_limit_blocks_the_tick(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=2), cost=25.0)
    conf = settings(auto_explore_schedule=True, auto_explore_schedule_interval_minutes=60)

    assert auto_explore.blocked_reason(db, USER, NOW, conf) == "daily_cost_limit"
    assert _decide(db, conf) is None


def test_min_interval_blocks_the_tick(db):
    add_profile(db)
    add_run(db, "run_last", created=ago(minutes=30), trigger=AgentRunTrigger.SCHEDULED)
    conf = settings(auto_explore_schedule=True, auto_explore_schedule_interval_minutes=10)

    assert _decide(db, conf) is None


def test_abandoned_run_is_cleared_and_a_new_run_starts(db, monkeypatch):
    """running のまま残った run（プロセスが落ちた）は失敗にして、新しく探す。"""
    add_profile(db)
    add_run(db, "run_dead", created=ago(hours=25), status=AgentRunStatus.RUNNING)
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)

    run_id = auto_explore.start_on_tick(db, USER, NOW)

    assert run_id is not None
    db.expire_all()
    dead = db.get(AgentRun, "run_dead")
    assert dead.status == AgentRunStatus.FAILED
    assert dead.error == auto_explore.ABANDONED_ERROR
    assert db.get(AgentRun, run_id).trigger == AgentRunTrigger.SCHEDULED


# --- 定期チェックの回し方 ---------------------------------------------------


def test_scheduler_does_not_start_by_default():
    assert scheduler.start(settings()) is None


def test_tick_starts_and_runs_the_agent(db, monkeypatch):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=25))
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)

    started = asyncio.run(scheduler.tick(NOW))

    assert len(started) == 1
    db.expire_all()
    run = db.get(AgentRun, started[0])
    assert run.trigger == AgentRunTrigger.SCHEDULED
    # run_agent（stub）が最後まで走っている
    assert run.status == AgentRunStatus.COMPLETED
    first = db.query(AgentLog).filter(AgentLog.run_id == run.run_id).order_by(AgentLog.id).first()
    assert (first.step, first.message) == ("analyzing_profile", run.trigger_reason)


def test_tick_does_nothing_when_nothing_is_due(db, monkeypatch):
    add_profile(db)
    add_run(db, "run_last", created=ago(hours=1))
    monkeypatch.setattr(auto_explore, "get_settings", lambda: ON)

    assert asyncio.run(scheduler.tick(NOW)) == []
    assert db.query(AgentRun).count() == 1


def test_one_failing_user_does_not_stop_the_others(db, monkeypatch, caplog):
    add_profile(db, "user_a")
    add_profile(db, "user_b")
    seen = []

    def start_on_tick(_db, user_id, _now):
        seen.append(user_id)
        if user_id == "user_a":
            raise RuntimeError("SELECT ... secret profile text")
        return None

    monkeypatch.setattr(auto_explore, "start_on_tick", start_on_tick)

    assert asyncio.run(scheduler.tick(NOW)) == []
    assert sorted(seen) == ["user_a", "user_b"]
    # 例外の型と場所だけ。**例外の文字列は出さない**
    assert "type=RuntimeError" in caplog.text
    assert "secret profile text" not in caplog.text


def test_loop_keeps_going_after_a_failed_tick(monkeypatch, caplog):
    calls = 0

    async def main():
        done = asyncio.Event()

        async def flaky_tick():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")
            done.set()
            return []

        monkeypatch.setattr(scheduler, "tick", flaky_tick)
        task = asyncio.create_task(scheduler._run_forever(0))
        await asyncio.wait_for(done.wait(), timeout=5)
        await scheduler.stop(task)
        return task

    task = asyncio.run(main())

    assert calls >= 2
    assert task.cancelled()
    assert "auto_explore.tick_failed type=RuntimeError" in caplog.text


def test_start_and_stop_cleanly():
    async def main():
        task = scheduler.start(settings(auto_explore_schedule=True, auto_explore_tick_seconds=60))
        assert task is not None
        await asyncio.sleep(0)
        await scheduler.stop(task)
        return task

    assert asyncio.run(main()).cancelled()
