"""Agent Loop の Web 探索ステップ（#19）。

LLM も検索 API も叩かない。registry の search_web と extract_many を差し替える。
Stub 経路は conftest で AGENT_STUB_MODE=true になっているため、実経路の
テストでは明示的に false へ切り替える。
"""

import pytest

from agent import loop
from agent.state import AgentState
from ai.schemas import SearchDirection
from ai.schemas.extraction import ExtractedOpportunity
from config import Settings
from db.session import SessionLocal
from models import AgentLog, AgentRun, Opportunity
from schemas.agent import AgentRunStatus
from schemas.opportunity import OpportunityStatus
from tools.base import ToolResult
from tools.search.base import SearchError, SearchResult


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def state(db) -> AgentState:
    db.add(AgentRun(run_id="run_x", user_id="user_001", status=AgentRunStatus.RUNNING))
    db.commit()
    return AgentState(run_id="run_x", user_id="user_001")


@pytest.fixture
def real_mode(monkeypatch):
    """実経路（AGENT_STUB_MODE=false）に切り替える。"""
    monkeypatch.setattr(
        loop, "get_settings", lambda: Settings(agent_stub_mode=False, search_api_key="k")
    )


def _direction(query: str) -> SearchDirection:
    return SearchDirection(category="hackathon", query=query, reason="r")


def _hit(url: str, title: str = "T") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="s", content="本文")


def _item(**overrides) -> ExtractedOpportunity:
    base = {"title": "AI Hackathon", "type": "hackathon"}
    base.update(overrides)
    return ExtractedOpportunity(**base)


def _patch(monkeypatch, *, search, extract):
    monkeypatch.setattr(loop.registry, "invoke", search)
    monkeypatch.setattr(loop, "extract_many", extract)


def _logs(db, run_id="run_x") -> list[str]:
    return [r.message for r in db.query(AgentLog).filter(AgentLog.run_id == run_id).all()]


# --- Stub 経路を壊していないこと -------------------------------------------


def test_stub_mode_still_works(db, state):
    """相方が API キー無しで動かせる経路とデモのフォールバック。消さない。"""
    ids = loop._search_and_extract(db, state)
    assert len(ids) == len(loop.stub_data.STUB_OPPORTUNITIES)


# --- 実経路 ---------------------------------------------------------------


def test_saves_extracted_opportunities(db, state, real_mode, monkeypatch):
    state.search_directions = [_direction("AI hackathon")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult([_hit("https://a.com")], external=True),
        extract=lambda src, **k: ([("https://a.com", _item(location="Tokyo"))], []),
    )

    ids = loop._search_and_extract(db, state)

    assert len(ids) == 1
    row = db.get(Opportunity, ids[0])
    assert row.title == "AI Hackathon"
    assert row.location == "Tokyo"
    assert row.run_id == "run_x"
    assert row.user_id == "user_001"
    # 評価はこの時点で付けない（④ Evaluation の責務）
    assert row.score == 0
    assert row.status == OpportunityStatus.DISCOVERED


def test_source_is_domain(db, state, real_mode, monkeypatch):
    state.search_directions = [_direction("q")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult([_hit("https://connpass.com/event/1")], external=True),
        extract=lambda src, **k: ([("https://connpass.com/event/1", _item())], []),
    )
    ids = loop._search_and_extract(db, state)
    assert db.get(Opportunity, ids[0]).source == "connpass.com"


def test_falls_back_to_source_url_when_llm_gives_none(db, state, real_mode, monkeypatch):
    """LLM が申込先を読み取れなかったときは取得元のページを使う。"""
    state.search_directions = [_direction("q")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult([_hit("https://src.com/page")], external=True),
        extract=lambda src, **k: ([("https://src.com/page", _item(url=None))], []),
    )
    ids = loop._search_and_extract(db, state)
    assert db.get(Opportunity, ids[0]).url == "https://src.com/page"


def test_each_result_keeps_its_own_source(db, state, real_mode, monkeypatch):
    """取得元がずれないこと。ずれると別の催しの URL が入る。"""
    state.search_directions = [_direction("q")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult(
            [_hit("https://a.com"), _hit("https://b.com")], external=True
        ),
        extract=lambda src, **k: (
            [
                ("https://a.com", _item(title="A", url=None)),
                ("https://b.com", _item(title="B", url=None)),
            ],
            [],
        ),
    )
    ids = loop._search_and_extract(db, state)
    saved = {db.get(Opportunity, i).title: db.get(Opportunity, i).url for i in ids}
    assert saved == {"A": "https://a.com", "B": "https://b.com"}


def test_deduplicates_across_directions(db, state, real_mode, monkeypatch):
    """同じ催しが複数の探索方向から見つかる。二重に保存しない。"""
    state.search_directions = [_direction("q1"), _direction("q2")]
    asked = []

    def search(_name, **kwargs):
        asked.append(kwargs["query"])
        return ToolResult([_hit("https://same.com")], external=True)

    _patch(
        monkeypatch,
        search=search,
        extract=lambda src, **k: ([(s.url, _item()) for s in src], []),
    )
    ids = loop._search_and_extract(db, state)

    assert asked == ["q1", "q2"]  # 検索自体は両方行う
    assert len(ids) == 1
    assert "既出" in " ".join(_logs(db))


def test_reuses_row_across_runs(db, state, real_mode, monkeypatch):
    """前の run で拾った URL は行を使い回す。run のたびに増やさない。"""
    db.add(
        Opportunity(
            opportunity_id="opp_old",
            user_id="user_001",
            url="https://same.com",
            type="hackathon",
            title="古い方",
        )
    )
    db.commit()

    state.search_directions = [_direction("q")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult([_hit("https://same.com")], external=True),
        extract=lambda src, **k: ([("https://same.com", _item(title="新しい方"))], []),
    )
    ids = loop._search_and_extract(db, state)

    assert ids == ["opp_old"]
    assert db.get(Opportunity, "opp_old").title == "新しい方"
    assert db.query(Opportunity).count() == 1


# --- 部分失敗 -------------------------------------------------------------


def test_one_failing_direction_does_not_stop_the_rest(db, state, real_mode, monkeypatch):
    state.search_directions = [_direction("ng"), _direction("ok")]

    def search(_name, **kwargs):
        if kwargs["query"] == "ng":
            raise SearchError("検索 API がエラーを返しました", retryable=True)
        return ToolResult([_hit("https://ok.com")], external=True)

    _patch(
        monkeypatch,
        search=search,
        extract=lambda src, **k: ([("https://ok.com", _item())], []),
    )
    ids = loop._search_and_extract(db, state)

    assert len(ids) == 1
    assert any("検索に失敗" in m for m in _logs(db))


def test_extraction_failures_are_reported_not_hidden(db, state, real_mode, monkeypatch):
    """取れなかった事実を隠さない。"""
    state.search_directions = [_direction("q")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult(
            [_hit("https://a.com"), _hit("https://b.com")], external=True
        ),
        extract=lambda src, **k: ([("https://a.com", _item())], ["https://b.com"]),
    )
    loop._search_and_extract(db, state)

    assert any("1件は読み取れず" in m for m in _logs(db))


def test_search_failure_log_does_not_leak_query(db, state, real_mode, monkeypatch, caplog):
    """クエリはプロフィール由来の内容を含みうる。Log へ出さない。"""
    secret = "秘密の目標を含むクエリ"
    state.search_directions = [_direction(secret)]
    _patch(
        monkeypatch,
        search=lambda *a, **k: (_ for _ in ()).throw(SearchError("boom")),
        extract=lambda src, **k: ([], []),
    )
    with caplog.at_level("WARNING"):
        loop._search_and_extract(db, state)

    assert secret not in caplog.text


# --- 進捗ログ -------------------------------------------------------------


def test_logs_are_human_readable(db, state, real_mode, monkeypatch):
    """Frontend の探索中画面に出る。ユーザーに見せられる日本語であること。"""
    state.search_directions = [_direction("AI hackathon Tokyo")]
    _patch(
        monkeypatch,
        search=lambda *a, **k: ToolResult([_hit("https://a.com")], external=True),
        extract=lambda src, **k: ([("https://a.com", _item())], []),
    )
    loop._search_and_extract(db, state)

    assert _logs(db) == ["「AI hackathon Tokyo」から1件を読み取りました"]
