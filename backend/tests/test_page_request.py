"""状態を変える API は、この画面からの要求だけを受け付ける（#80, CSRF）。

body の無い POST や text/plain の POST は、別サイトの form や fetch から
ブラウザの事前確認（preflight）なしに送れる。探索の開始は LLM の費用が
かかるので、別サイトを開いただけで走らせられないようにする。
"""

import pytest

from db.session import SessionLocal
from models import DEFAULT_USER_ID, AgentRun, Opportunity, UserProfile
from schemas.opportunity import OpportunityStatus

PAGE = {"X-Requested-With": "opportunity-agent"}


@pytest.fixture
def seeded(profile_payload):
    db = SessionLocal()
    db.add(UserProfile(user_id=DEFAULT_USER_ID, **profile_payload))
    db.add(
        Opportunity(
            opportunity_id="opp_a",
            user_id=DEFAULT_USER_ID,
            type="hackathon",
            title="AI Hackathon",
            status=OpportunityStatus.RECOMMENDED,
        )
    )
    db.commit()
    db.close()


def _runs() -> int:
    db = SessionLocal()
    try:
        return db.query(AgentRun).count()
    finally:
        db.close()


def _status() -> str:
    db = SessionLocal()
    try:
        return db.get(Opportunity, "opp_a").status
    finally:
        db.close()


WRITES = [
    ("post", "/api/agent/runs", None),
    ("post", "/api/opportunities/opp_a/interest", None),
    ("post", "/api/opportunities/opp_a/feedback", {"reaction": "dislike"}),
    ("post", "/api/opportunities/opp_a/calendar", None),
    ("put", "/api/profile", {"name": "攻撃者"}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
@pytest.mark.parametrize("headers", [{}, {"X-Requested-With": "XMLHttpRequest"}])
def test_write_without_page_header_is_refused(client, seeded, method, path, body, headers):
    res = client.request(method, path, json=body, headers=headers)

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


def test_cross_site_form_cannot_start_a_run(client, seeded):
    """別サイトの form 送信（ヘッダーを付けられない）では探索が走らない。"""
    res = client.post(
        "/api/agent/runs",
        content="x=1",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert res.status_code == 403
    assert _runs() == 0


def test_cross_site_request_does_not_change_status(client, seeded):
    client.post("/api/opportunities/opp_a/interest")
    client.post(
        "/api/opportunities/opp_a/feedback",
        content='{"reaction": "dislike"}',
        headers={"Content-Type": "text/plain"},
    )
    assert _status() == OpportunityStatus.RECOMMENDED


def test_page_request_is_accepted(client, seeded):
    """画面から送った要求は通る。"""
    assert client.post("/api/agent/runs", headers=PAGE).status_code == 200
    assert _runs() == 1
    assert client.post("/api/opportunities/opp_a/interest", headers=PAGE).status_code == 200
    assert _status() == OpportunityStatus.INTERESTED


def test_reads_do_not_need_the_header(client, seeded):
    """読み取りは状態を変えないので、ヘッダーなしでも返す。"""
    assert client.get("/api/profile").status_code == 200
    assert client.get("/api/opportunities").status_code == 200
