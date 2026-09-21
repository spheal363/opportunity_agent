"""Prompt Injection の攻撃デモ（#52）。DEMO_INJECTION=true のときだけ動く。

LLM も検索 API も叩かない。デモでも検知と「推薦しない」判断は本番のコードが行う。
"""

import pytest

from agent import demo_attack, loop
from agent.state import AgentState
from ai import guard
from ai.schemas import SearchDirection
from ai.schemas.evaluation import EvaluationOutput
from ai.schemas.extraction import ExtractedOpportunity
from ai.schemas.goal_analysis import GoalAnalysisOutput
from ai.schemas.recommendation import RecommendationOutput
from config import Settings
from db.session import SessionLocal
from models import AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus
from tools.base import ToolResult
from tools.search.base import SearchResult


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def state(db) -> AgentState:
    db.add(AgentRun(run_id="run_d", user_id="user_001", status=AgentRunStatus.RUNNING))
    db.commit()
    s = AgentState(run_id="run_d", user_id="user_001")
    s.goal_analysis = GoalAnalysisOutput(
        goal_summary="AI プロダクトで起業したい",
        goal_directions=["AI product"],
        interest_connections=["AI × Startup"],
    )
    s.search_directions = [SearchDirection(category="hackathon", query="q", reason="r")]
    return s


def _logs(db) -> list[str]:
    return [r.message for r in db.query(AgentLog).order_by(AgentLog.id).all()]


def test_demo_page_is_caught_by_the_real_guard():
    """デモ用ページは、目に見える指示と見えない指示の両方で検知される。"""
    r = guard.inspect(demo_attack.CONTENT)
    assert {"override", "hidden"} <= set(r.findings)
    assert "evil.example" not in r.text
    # 事実は残る（抽出はこの本文で行う）
    assert "2026年11月14日" in r.text


def test_real_mode_mixes_in_the_page_and_drops_it(db, state, monkeypatch):
    monkeypatch.setattr(
        loop,
        "get_settings",
        lambda: Settings(agent_stub_mode=False, search_api_key="k", demo_injection=True),
    )
    good = [
        SearchResult(title=f"G{i}", url=f"https://good.example/{i}", snippet="s", content="普通")
        for i in range(3)
    ]
    seen: list[str] = []

    def extract(sources, **_):
        seen.extend(s.url for s in sources)
        return [(s.url, ExtractedOpportunity(title=s.title, type="hackathon")) for s in sources], []

    def evaluate_many(*, opportunities, **_):
        # 防御が無ければ、攻撃どおり 100 点が付いてしまう想定
        return [
            (
                o["opportunity_id"],
                EvaluationOutput(
                    score=100 if "デモ" in o["title"] else 70,
                    serendipity_score=50,
                    match_reasons=[],
                    concerns=[],
                ),
            )
            for o in opportunities
        ], []

    monkeypatch.setattr(loop.registry, "invoke", lambda *a, **k: ToolResult(good, external=True))
    monkeypatch.setattr(loop, "extract_many", extract)
    monkeypatch.setattr(loop, "evaluate_many", evaluate_many)
    monkeypatch.setattr(loop, "recommend", lambda **k: RecommendationOutput(reason="r"))

    ids = loop._search_and_extract(db, state)
    selected = loop._evaluate_and_select(db, state, ids)

    assert demo_attack.URL in seen
    demo_row = db.query(Opportunity).filter(Opportunity.url == demo_attack.URL).one()
    assert demo_row.opportunity_id not in selected
    logs = _logs(db)
    assert demo_attack.LOG_MESSAGE in logs
    assert any("指示らしき文を見つけ、取り除いてから読みました" in m for m in logs)
    assert any("推薦から外しました" in m for m in logs)


def test_stub_mode_shows_the_same_flow(db, state, monkeypatch):
    """API が使えない場でも、検知して推薦から外す流れを見せられる。"""
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(demo_injection=True))
    monkeypatch.setattr(loop.time, "sleep", lambda _: None)

    ids = loop._search_and_extract(db, state)

    # 固定データの TOP3 候補は変わらない。デモのページは保存しない
    assert len(ids) == len(loop.stub_data.STUB_OPPORTUNITIES)
    assert db.query(Opportunity).filter(Opportunity.url == demo_attack.URL).count() == 0
    logs = _logs(db)
    assert logs[0] == demo_attack.LOG_MESSAGE
    assert any("指示らしき文を見つけ" in m for m in logs)
    assert any(
        f"「{demo_attack.TITLE}」は指示らしき文を含むページから取ったため" in m for m in logs
    )


def test_demo_is_off_by_default(db, state, monkeypatch):
    monkeypatch.setattr(loop, "get_settings", lambda: Settings())
    monkeypatch.setattr(loop.time, "sleep", lambda _: None)

    loop._search_and_extract(db, state)

    assert demo_attack.LOG_MESSAGE not in _logs(db)
