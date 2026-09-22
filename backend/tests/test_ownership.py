"""他人の Opportunity / Agent Run を id だけで読み書きできないこと（#69, IDOR）。

MVP は単一ユーザー（DEFAULT_USER_ID）なので、別の user_id の行を直接 DB に
入れて確かめる。認証を入れたら `api/deps.current_user_id` を差し替えるだけで
同じ検査が効く。
"""

import pytest

from db.session import SessionLocal
from models import DEFAULT_USER_ID, AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus, AgentStep
from schemas.opportunity import OpportunityStatus

PAGE = {"X-Requested-With": "opportunity-agent"}
OTHER = "someone_else"


@pytest.fixture
def seeded():
    db = SessionLocal()
    for owner, oid in ((OTHER, "opp_other"), (DEFAULT_USER_ID, "opp_mine")):
        db.add(
            Opportunity(
                opportunity_id=oid,
                user_id=owner,
                type="hackathon",
                title="AI Hackathon",
                status=OpportunityStatus.RECOMMENDED,
            )
        )
    db.add(AgentRun(run_id="run_other", user_id=OTHER, status=AgentRunStatus.COMPLETED))
    db.add(AgentLog(run_id="run_other", step=AgentStep.COMPLETED, message="他人の探索ログ"))
    db.commit()
    db.close()


def _status(oid: str) -> str:
    db = SessionLocal()
    try:
        return db.get(Opportunity, oid).status
    finally:
        db.close()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/opportunities/opp_other"),
        ("post", "/api/opportunities/opp_other/interest"),
        ("post", "/api/opportunities/opp_other/calendar"),
        ("get", "/api/calendar/availability?opportunity_id=opp_other"),
        ("get", "/api/agent/runs/run_other"),
        ("get", "/api/agent/runs/run_other/logs"),
        ("get", "/api/agent/runs/run_other/result"),
    ],
)
def test_other_users_resource_is_not_found(client, seeded, method, path):
    """403 ではなく 404。他人の id が存在するかどうかも漏らさない。"""
    res = getattr(client, method)(path, headers=PAGE)

    assert res.status_code == 404
    assert "他人の探索ログ" not in res.text


def test_other_users_feedback_is_rejected(client, seeded):
    res = client.post(
        "/api/opportunities/opp_other/feedback", json={"reaction": "dislike"}, headers=PAGE
    )
    assert res.status_code == 404
    # 状態も変わらない
    assert _status("opp_other") == OpportunityStatus.RECOMMENDED


def test_other_users_interest_does_not_change_status(client, seeded):
    client.post("/api/opportunities/opp_other/interest", headers=PAGE)
    assert _status("opp_other") == OpportunityStatus.RECOMMENDED


def test_own_resource_is_still_readable(client, seeded):
    """所有者チェックで自分のものまで見えなくなっていないこと。"""
    res = client.get("/api/opportunities/opp_mine")
    assert res.status_code == 200
    assert res.json()["data"]["opportunity_id"] == "opp_mine"

    res = client.post("/api/opportunities/opp_mine/interest", headers=PAGE)
    assert res.status_code == 200
    assert _status("opp_mine") == OpportunityStatus.INTERESTED
