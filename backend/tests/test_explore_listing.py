"""一覧から個別イベントへ進む経路（#47）。ネットワークへは出ない。"""

import pytest

from agent import loop
from agent.state import AgentState
from ai import explore, listing
from ai.schemas.goal_analysis import GoalAnalysisOutput
from ai.schemas.link_pick import LinkPickOutput, PickedLink
from config import Settings
from db.session import SessionLocal
from models import AgentRun
from schemas.agent import AgentRunStatus
from tools.search.base import PageContent

LISTING_URL = "https://ja.ra.co/events/jp/tokyo/house"
LISTING_BODY = "\n".join(
    [f"[Event {i}](https://ja.ra.co/events/20010{i:02d})" for i in range(1, 9)]
)


def _page(url, content, title="t"):
    return PageContent(url=url, title=title, content=content)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def state(db) -> AgentState:
    db.add(AgentRun(run_id="run_l", user_id="user_001", status=AgentRunStatus.RUNNING))
    db.commit()
    st = AgentState(run_id="run_l", user_id="user_001")
    st.goal_analysis = GoalAnalysisOutput(
        goal_summary="g", wanted_now=["ハウス/テクノの音楽イベント"]
    )
    st.wanted_region = "東京 / オンライン"
    st.search_window = {"start": "2026-09-22", "end": "2026-11-21", "tz": "Asia/Tokyo"}
    return st


# --- リンクを選ぶ -----------------------------------------------------------


def test_only_the_offered_indexes_are_used(monkeypatch):
    """**渡していない番号は捨てる。** 作られた index で落ちない。"""
    links = [listing.Link(title=f"e{i}", url=f"https://x/{i}") for i in range(3)]
    monkeypatch.setattr(
        explore,
        "generate_structured",
        lambda **k: type(
            "R",
            (),
            {
                "data": LinkPickOutput(
                    is_listing=True, picked=[PickedLink(index=0), PickedLink(index=99)]
                )
            },
        )(),
    )

    is_listing, picked = explore.pick_links(
        links, wishes=["音楽"], location=None, window=None, limit=5
    )
    assert is_listing is True
    assert [p.url for p in picked] == ["https://x/0"]


def test_the_limit_is_respected(monkeypatch):
    links = [listing.Link(title=f"e{i}", url=f"https://x/{i}") for i in range(5)]
    monkeypatch.setattr(
        explore,
        "generate_structured",
        lambda **k: type(
            "R",
            (),
            {
                "data": LinkPickOutput(
                    is_listing=True, picked=[PickedLink(index=i) for i in range(5)]
                )
            },
        )(),
    )
    _, picked = explore.pick_links(links, wishes=[], location=None, window=None, limit=2)
    assert len(picked) == 2


def test_a_failed_pick_returns_nothing_instead_of_guessing(monkeypatch):
    """**上位から機械的に取る代替はしない。** 一覧の並びは開催日順とは限らない。"""
    from ai.llm import LLMValidationError

    links = [listing.Link(title="e", url="https://x/1")]
    monkeypatch.setattr(
        explore,
        "generate_structured",
        lambda **k: (_ for _ in ()).throw(LLMValidationError("nope")),
    )
    assert explore.pick_links(links, wishes=[], location=None, window=None, limit=2) == (False, [])


# --- 一覧を辿る -------------------------------------------------------------


def test_a_listing_is_followed_to_the_individual_pages(monkeypatch):
    monkeypatch.setattr(explore, "pick_links", lambda links, **k: (True, list(links[:2])))
    fetched = [
        _page("https://ja.ra.co/events/2001001", "10月10日 Contact Tokyo で開催。" * 20),
        _page("https://ja.ra.co/events/2001002", "10月17日 WOMB で開催。" * 20),
    ]
    result = explore.follow(
        _page(LISTING_URL, LISTING_BODY),
        wishes=["音楽"],
        location="東京",
        window=None,
        limit=2,
        fetch=lambda urls: fetched,
    )

    assert len(result.pages) == 2
    assert result.links_found == 8


def test_an_interstitial_is_recorded_not_recommended(monkeypatch):
    """**アクセス制限は回避しない。** 理由を残して次へ進む。"""
    monkeypatch.setattr(explore, "pick_links", lambda links, **k: (True, links[:1]))
    blocked = _page("https://ja.ra.co/events/2001001", "", title="Just a moment...")
    result = explore.follow(
        _page(LISTING_URL, LISTING_BODY),
        wishes=[],
        location=None,
        window=None,
        limit=1,
        fetch=lambda urls: [blocked],
    )

    assert result.pages == []
    assert result.failures and "取得できませんでした" in result.failures[0][1]


def test_a_page_that_cannot_be_fetched_is_recorded(monkeypatch):
    monkeypatch.setattr(explore, "pick_links", lambda links, **k: (True, list(links[:1])))
    result = explore.follow(
        _page(LISTING_URL, LISTING_BODY),
        wishes=[],
        location=None,
        window=None,
        limit=1,
        fetch=lambda urls: [],
    )
    assert result.failures


# --- Agent Loop への接続 ----------------------------------------------------


def test_the_loop_adds_the_individual_pages_and_keeps_the_listing(db, state, monkeypatch):
    """**一覧も残す。** 一覧しか手がかりが無いときに取得元として出せるように。"""
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    monkeypatch.setattr(
        loop.explore,
        "follow",
        lambda page, **k: explore.ExploreResult(
            pages=[_page("https://ja.ra.co/events/2001001", "本文" * 200)],
            links_found=8,
            picked=1,
        ),
    )

    out = loop._follow_listings(db, state, [_page(LISTING_URL, LISTING_BODY)])

    assert len(out) == 2
    assert {p.url for p in out} == {LISTING_URL, "https://ja.ra.co/events/2001001"}


def test_the_budget_stops_the_expansion(db, state, monkeypatch):
    """**無制限に取りに行かない。** 上限は設定で変えられる。"""
    monkeypatch.setattr(
        loop, "get_settings", lambda: Settings(agent_stub_mode=False, listing_max_fetches=0)
    )
    called = []
    monkeypatch.setattr(loop.explore, "follow", lambda page, **k: called.append(1))

    out = loop._follow_listings(db, state, [_page(LISTING_URL, LISTING_BODY)])

    assert called == [], "上限 0 でも一覧を辿っている"
    assert len(out) == 1


def test_a_non_listing_page_is_left_alone(db, state, monkeypatch):
    monkeypatch.setattr(loop, "get_settings", lambda: Settings(agent_stub_mode=False))
    called = []
    monkeypatch.setattr(loop.explore, "follow", lambda page, **k: called.append(1))

    individual = _page("https://ja.ra.co/events/2001001", "10月10日 Contact Tokyo。")
    out = loop._follow_listings(db, state, [individual])

    assert called == []
    assert out == [individual]


def test_an_article_is_rejected_by_the_model_not_by_the_url(monkeypatch):
    """**構造では分けられない。** 一覧でないと LLM が言えば、そこで止まる。

    実測で、`okinawatimes` の記事は同形リンク 24 本で門を通る。
    止めるのは本文を読んだ判断。
    """
    monkeypatch.setattr(
        explore,
        "generate_structured",
        lambda **k: type(
            "R", (), {"data": LinkPickOutput(is_listing=False, listing_reason="記事の関連記事欄")}
        )(),
    )
    result = explore.follow(
        _page("https://ja.ra.co/articles/1", LISTING_BODY),
        wishes=["音楽"],
        location=None,
        window=None,
        limit=2,
        fetch=lambda urls: pytest.fail("一覧でないのに取得している"),
    )

    assert result.is_listing is False
    assert result.pages == []
    assert "イベント一覧ではありませんでした" in result.failures[0][1]
