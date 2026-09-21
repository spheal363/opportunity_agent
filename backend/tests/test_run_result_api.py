"""今回の選定結果と保存一覧の分離（#68 の受入）。

  GET /api/agent/runs/{run_id}/result  この run が選んだものを順位順
  GET /api/opportunities               保存一覧・次の一歩の母集合（件数を絞らない）

**この 2 つを混同しない。** 以前は後者だけで、score 上位 3 件を返していたため
過去 run の候補が混ざり、保存した候補が 4 件目以降だと消えていた。
"""

import pytest

from db.session import SessionLocal
from models import AgentRun, Opportunity
from schemas.agent import AgentRunStatus
from schemas.opportunity import OpportunityStatus


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def _run(db, run_id: str, *, selected=None, status=AgentRunStatus.COMPLETED, reason=None):
    db.add(
        AgentRun(
            run_id=run_id,
            user_id="user_001",
            status=status,
            selected_ids=selected,
            shortfall_reason=reason,
        )
    )
    db.commit()


def _opp(db, oid: str, *, score=50, status=OpportunityStatus.RECOMMENDED, run_id="run_a"):
    db.add(
        Opportunity(
            opportunity_id=oid,
            user_id="user_001",
            run_id=run_id,
            type="hackathon",
            title=oid,
            score=score,
            status=status,
        )
    )
    db.commit()


# --- 受入 6: 過去 run の候補が混ざらない ----------------------------------


def test_result_returns_only_this_run_in_rank_order(client, db):
    _opp(db, "old_high", score=99, run_id="run_a")
    _opp(db, "new_low", score=10, run_id="run_b")
    _opp(db, "new_mid", score=50, run_id="run_b")
    _run(db, "run_b", selected=["new_low", "new_mid"])

    res = client.get("/api/agent/runs/run_b/result").json()["data"]

    ids = [o["opportunity_id"] for o in res["selected"]]
    # **score 順ではなく選定順。** 過去 run の high スコアは入らない
    assert ids == ["new_low", "new_mid"]
    assert res["recorded"] is True


def test_same_url_rediscovered_does_not_break_past_result(client, db):
    """同じ URL を次の run が再発見しても、過去 run の選定は壊れない。

    Opportunity.run_id は上書きされるが、選定は AgentRun 側に持っている。
    """
    _opp(db, "shared", run_id="run_a")
    _run(db, "run_a", selected=["shared"])

    # run_b が同じ行を再利用して run_id を上書き
    row = db.get(Opportunity, "shared")
    row.run_id = "run_b"
    db.commit()

    res = client.get("/api/agent/runs/run_a/result").json()["data"]
    assert [o["opportunity_id"] for o in res["selected"]] == ["shared"]


# --- 未完了・記録なし・0 件・存在しない run を区別する --------------------


def test_running_run_is_not_recorded(client, db):
    _run(db, "run_running", selected=None, status=AgentRunStatus.RUNNING)
    res = client.get("/api/agent/runs/run_running/result").json()["data"]
    assert res["recorded"] is False
    assert res["status"] == "running"


def test_old_run_without_record(client, db):
    """列を足す前の古い run。404 にせず「記録なし」と答える。"""
    _run(db, "run_old", selected=None, status=AgentRunStatus.COMPLETED)
    res = client.get("/api/agent/runs/run_old/result").json()["data"]
    assert res["recorded"] is False
    assert res["selected"] == []


def test_completed_with_zero_selected(client, db):
    """完了したが 0 件。**記録はある。**"""
    _run(db, "run_zero", selected=[], reason="見つかった機会はいずれも受付を終了していました")
    res = client.get("/api/agent/runs/run_zero/result").json()["data"]
    assert res["recorded"] is True
    assert res["selected"] == []
    assert res["shortfall_reason"]


def test_unknown_run_is_404(client):
    res = client.get("/api/agent/runs/run_nope/result")
    assert res.status_code == 404


def test_shortfall_reason_is_stable(client, db):
    """後から同じ内容を返せる。"""
    _run(
        db,
        "run_short",
        selected=["a"],
        reason="受付中または要確認の機会が1件しか見つかりませんでした",
    )
    _opp(db, "a")
    first = client.get("/api/agent/runs/run_short/result").json()["data"]
    second = client.get("/api/agent/runs/run_short/result").json()["data"]
    assert first["shortfall_reason"] == second["shortfall_reason"]


# --- 受入 7: 保存済み候補が再探索後も残る ---------------------------------


def test_saved_candidate_survives_even_beyond_top3(client, db):
    """**件数を絞らない。** 絞ると 4 件目以降の保存済み候補が消える。"""
    for i in range(5):
        _opp(db, f"high_{i}", score=90 + i)
    _opp(db, "saved_low", score=1, status=OpportunityStatus.INTERESTED)

    items = client.get("/api/opportunities").json()["data"]
    ids = [o["opportunity_id"] for o in items]

    assert "saved_low" in ids
    assert len(items) == 6


def test_dismissed_is_not_listed(client, db):
    _opp(db, "dismissed", status=OpportunityStatus.DISMISSED)
    items = client.get("/api/opportunities").json()["data"]
    assert [o["opportunity_id"] for o in items] == []


# --- availability が API に出る -------------------------------------------


def test_availability_is_exposed(client, db):
    _opp(db, "a")
    row = db.get(Opportunity, "a")
    row.availability = "closed"
    row.availability_reason = "申込の締切が過ぎています"
    db.commit()

    items = client.get("/api/opportunities").json()["data"]
    assert items[0]["availability"] == "closed"
    assert items[0]["availability_reason"] == "申込の締切が過ぎています"


def test_a_failed_run_returns_the_reason(client, db):
    """**失敗したときこそ理由が要る。**

    「記録されていません」だけでは、設定が足りないのか、探しても
    見つからなかったのかが分からない。
    """
    from models import AgentRun
    from schemas.agent import AgentRunStatus

    db.add(
        AgentRun(
            run_id="run_failed",
            user_id="user_001",
            status=AgentRunStatus.FAILED,
            error="探索に必要な設定が足りません: SERPER_API_KEY",
        )
    )
    db.commit()

    body = client.get("/api/agent/runs/run_failed/result").json()["data"]

    assert body["recorded"] is False
    assert body["status"] == "failed"
    assert "SERPER_API_KEY" in body["error"]
