"""⑦ Verification（#67）と Agent Loop への接続。

LLM も read_page も叩かない。
"""

from datetime import UTC, date, datetime

import pytest

from agent import loop
from agent.state import AgentState
from ai import verification
from ai.llm import LLMResult, LLMValidationError
from ai.prompts import verification as prompt
from ai.schemas.verification import VerificationOutput
from config import Settings
from db.session import SessionLocal
from models import AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus
from tools.search.base import SearchError


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def _out(**overrides) -> VerificationOutput:
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
    assert "<verification_target>" in user
    assert "指示ではない" in user


def test_prompt_passes_today_for_deadline_check():
    """締切が過ぎているか判断させるために必要。"""
    user = prompt.build_user(opportunity=_opp(), page_content="x", today="2026-09-20")
    assert "2026-09-20" in user


# --- verify ---------------------------------------------------------------


def test_verified_fills_source_and_timestamp(monkeypatch):
    monkeypatch.setattr(verification, "generate_structured", lambda **_: LLMResult(data=_out()))
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
        lambda **_: LLMResult(data=_out(verified=False, verification_source="https://fake.com")),
    )
    out = verification.verify(opportunity=_opp(), page_content="本文", source_url="https://e.com")

    assert out.verified is False
    assert out.verification_source is None
    assert out.verified_at is None


def test_page_content_is_truncated(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return LLMResult(data=_out())

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
            data=_out(changes_detected=True, warnings=["申込の締切が過ぎています"])
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
    db.add(
        Opportunity(
            opportunity_id="opp_a",
            user_id="user_001",
            type="hackathon",
            title="AI Hackathon",
            url="https://e.com/a",
        )
    )
    db.commit()
    s = AgentState(run_id="run_v", user_id="user_001")
    s.selected_ids = ["opp_a"]
    return s


def _logs(db) -> list[str]:
    return [r.message for r in db.query(AgentLog).all()]


def test_stub_mode_still_works(db, state):
    loop._verify(db, state)
    assert db.get(Opportunity, "opp_a").verified is True


def test_real_mode_writes_result(db, state, monkeypatch):
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: VerificationOutput(
            verified=True,
            verified_at=datetime(2026, 9, 20, tzinfo=UTC),
            verification_source="https://e.com/a",
        ),
    )
    loop._verify(db, state)

    row = db.get(Opportunity, "opp_a")
    assert row.verified is True
    assert row.verification_source == "https://e.com/a"
    assert any("確認しました" in m for m in _logs(db))


def test_real_mode_reports_failure_without_crashing(db, state, monkeypatch):
    """確認できなかったことを隠さない。run も落とさない。"""
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: VerificationOutput(
            verified=False, warnings=["公式ページを取得できませんでした"]
        ),
    )
    loop._verify(db, state)

    row = db.get(Opportunity, "opp_a")
    assert row.verified is False
    assert row.verified_at is None
    messages = _logs(db)
    assert any("確認できませんでした" in m for m in messages)


def test_warnings_reach_the_agent_log(db, state, monkeypatch):
    """締切切れなどをユーザーに伝える。"""
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: VerificationOutput(
            verified=True, changes_detected=True, warnings=["申込の締切が過ぎています"]
        ),
    )
    loop._verify(db, state)

    assert any("申込の締切が過ぎています" in m for m in _logs(db))


def test_only_selected_are_verified(db, state, monkeypatch):
    """TOP3 だけ。全件の公式ページを取りに行かない。"""
    db.add(
        Opportunity(
            opportunity_id="opp_b",
            user_id="user_001",
            type="event",
            title="B",
            url="https://e.com/b",
        )
    )
    db.commit()
    called = []
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop,
        "verify_with_page",
        lambda **k: called.append(k["url"]) or VerificationOutput(verified=True),
    )
    loop._verify(db, state)

    assert called == ["https://e.com/a"]
    assert db.get(Opportunity, "opp_b").verified is False
