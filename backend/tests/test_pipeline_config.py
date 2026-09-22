"""構成の切り替えのテスト。**固定データで行う。**

比較（#65）のために A / B / C を切り替えられるようにした。ここでは
「切り替えても現行の既定が変わらない」ことと、「切り替えたときに
意図した経路を通る」ことを見る。
"""

import pytest

from ai import cost
from ai.schemas.evaluation import EvaluationOutput
from config import Settings
from tests.fixtures import candidates as fx

# --- 既定値 ------------------------------------------------------------------


def test_the_default_is_configuration_c():
    """**既定は構成 C（暫定採用）。**

    根拠は docs/experiments/65-search-comparison.md。1 run ずつの比較で、
    時間 24% 短縮・OrcaRouter 実費 47% 削減を観測した。
    """
    s = Settings(_env_file=None)
    assert s.search_provider == "serper"
    assert s.page_fetcher == "jina"
    assert s.evaluator == "jev"
    assert s.search_pipeline == "prefilter"


def test_going_back_to_a_takes_four_settings():
    """**A へ戻せる形を残す。** 4 つとも戻す。"""
    from config import FALLBACK_TO_A

    for key in (
        "SEARCH_PROVIDER=tavily",
        "PAGE_FETCHER=tavily",
        "EVALUATOR=llm",
        "SEARCH_PIPELINE=full",
    ):
        assert key in FALLBACK_TO_A


def test_missing_keys_are_named_not_silently_ignored():
    """**黙って別構成へ落とさない。**

    鍵が無いことと、候補が見つからないことは別。以前は検索が方向ごとに
    失敗し、候補 0 件で終わっていた。
    """
    from config import missing_keys

    missing = missing_keys(Settings(_env_file=None, search_provider="serper", evaluator="jev"))
    assert any("SERPER_API_KEY" in m for m in missing)
    assert any("TYPESAFE_API_KEY" in m for m in missing)


def test_jina_needs_no_key():
    """本文取得はキー無しでも動く（20 RPM）。**足りない鍵に挙げない。**"""
    from config import missing_keys

    missing = missing_keys(
        Settings(
            _env_file=None,
            search_provider="serper",
            page_fetcher="jina",
            evaluator="jev",
            serper_api_key="x",
            typesafe_api_key="y",
        )
    )
    assert missing == []


def test_read_limit_is_a_hypothesis_not_a_fixed_answer():
    """件数は仮説。比較で決める。"""
    assert 6 <= Settings(_env_file=None).prefilter_read_limit <= 8
    assert Settings(_env_file=None).prefilter_extra_reads > 0


# --- 本文取得を挟む ----------------------------------------------------------


def test_bodies_are_fetched_only_for_candidates_without_content(monkeypatch):
    """Tavily の検索は本文抜粋を返す。**取れているものを取り直さない。**"""
    from agent import loop
    from tools.base import ToolResult
    from tools.search.base import PageContent

    seen = {}

    def fake_invoke(name, **kwargs):
        seen["urls"] = kwargs["url"]
        return ToolResult(
            {
                "pages": [
                    PageContent(url=u, title="t", content="取得した本文") for u in kwargs["url"]
                ],
                "failed": [],
            },
            external=True,
        )

    monkeypatch.setattr(loop.registry, "invoke", fake_invoke)
    merged = loop._with_bodies(fx.TAVILY_RESULTS)

    # 本文が無いのは 1 件だけ
    assert seen["urls"] == fx.UNFETCHABLE_URLS
    assert len(merged) == len(fx.TAVILY_RESULTS)


def test_serper_shaped_results_all_need_a_body(monkeypatch):
    """**Serper は snippet しか返さない。**

    検索 provider を替えただけでは抽出の入力が痩せる。
    """
    from agent import loop
    from tools.base import ToolResult
    from tools.search.base import PageContent

    seen = {}

    def fake_invoke(name, **kwargs):
        seen["urls"] = kwargs["url"]
        return ToolResult(
            {
                "pages": [fx.FETCHED_PAGES[u] for u in kwargs["url"] if u in fx.FETCHED_PAGES],
                "failed": [u for u in kwargs["url"] if u not in fx.FETCHED_PAGES],
            },
            external=True,
        )

    monkeypatch.setattr(loop.registry, "invoke", fake_invoke)
    merged = loop._with_bodies(fx.SERPER_RESULTS)

    assert len(seen["urls"]) == len(fx.SERPER_RESULTS)
    # 取れた分は PageContent に、取れなかった分は SearchResult のまま残る
    assert sum(1 for m in merged if isinstance(m, PageContent)) == len(fx.FETCHED_PAGES)
    assert len(merged) == len(fx.SERPER_RESULTS)


def test_failed_fetch_does_not_drop_the_candidate(monkeypatch):
    """取得できなかった候補を捨てない。snippet だけでも抽出は試せる。"""
    from agent import loop
    from tools.search.base import SearchError

    def fake_invoke(name, **kwargs):
        raise SearchError("取得できません")

    monkeypatch.setattr(loop.registry, "invoke", fake_invoke)
    merged = loop._with_bodies(fx.SERPER_RESULTS)

    assert len(merged) == len(fx.SERPER_RESULTS)


# --- 評価器の切り替え --------------------------------------------------------


def test_evaluator_falls_back_to_llm_when_jev_is_unsure(monkeypatch):
    """**確信が持てないときは既存 LLM へ戻す。**

    戻した分の費用は LLM 側の欄に乗る。「Jev に替えた分だけ安くなる」とは
    限らないため、別々に数える。
    """
    import ai.evaluation as ev

    monkeypatch.setattr(ev, "get_settings", lambda: Settings(evaluator="jev"))
    monkeypatch.setattr(ev, "evaluate_with_jev", lambda **_: None)

    called = {"llm": 0}

    def fake_llm(**_):
        called["llm"] += 1
        return EvaluationOutput(score=70, serendipity_score=40)

    monkeypatch.setattr(ev, "_evaluate_with_llm", fake_llm)

    out = ev.evaluate(goal_summary="g", interest_connections=[], opportunity={})

    assert called["llm"] == 1
    assert out.evaluator == "llm"


def test_evaluator_failure_falls_back_instead_of_dropping(monkeypatch):
    """1 件の失敗で評価全体を止めない。"""
    import ai.evaluation as ev
    from ai.jev.client import JevError

    monkeypatch.setattr(ev, "get_settings", lambda: Settings(evaluator="jev"))

    def boom(**_):
        raise JevError("down", retryable=False)

    monkeypatch.setattr(ev, "evaluate_with_jev", boom)
    monkeypatch.setattr(
        ev, "_evaluate_with_llm", lambda **_: EvaluationOutput(score=1, serendipity_score=1)
    )

    with cost.track() as tracker:
        with cost.step("evaluation"):
            out = ev.evaluate(goal_summary="g", interest_connections=[], opportunity={})

    assert out.score == 1
    jev = tracker.by_step["evaluation"].jev
    # **低確信とは別の欄。** 「確信が持てなかった」のではなく「呼べなかった」。
    assert jev.hard_failures == 1
    assert jev.low_confidence_fallbacks == 0


def test_the_evaluator_can_be_forced_back_to_llm(monkeypatch):
    """**A へ戻せる。** EVALUATOR=llm なら Jev を呼ばない。"""
    import ai.evaluation as ev

    monkeypatch.setattr(ev, "get_settings", lambda: Settings(_env_file=None, evaluator="llm"))

    def boom(**_):  # pragma: no cover
        raise AssertionError("EVALUATOR=llm なのに Jev が呼ばれている")

    monkeypatch.setattr(ev, "evaluate_with_jev", boom)
    monkeypatch.setattr(
        ev, "_evaluate_with_llm", lambda **_: EvaluationOutput(score=5, serendipity_score=5)
    )

    assert ev.evaluate(goal_summary="g", interest_connections=[], opportunity={}).score == 5


# --- 構成の記録 --------------------------------------------------------------


def test_the_configuration_is_recorded_with_the_run():
    """**比較の記録に構成が無いと、後から読めない。**"""
    with cost.track() as tracker:
        pass

    out = tracker.to_dict()
    # **走った構成をそのまま残す。** 既定が変わっても記録は実態に従う。
    assert out["search_provider"] == Settings().search_provider
    assert out["page_fetcher"] == Settings().page_fetcher
    assert out["search_pipeline"] == Settings().search_pipeline


def test_evaluator_is_recorded():
    with cost.track() as tracker:
        cost.record_evaluator("jev", "jev-1.13.0")

    out = tracker.to_dict()
    assert out["evaluator"] == "jev"
    assert out["evaluator_model"] == "jev-1.13.0"


def test_jev_usage_survives_serialization():
    """入れ子の dataclass を JSON へ入れられること。"""
    import json

    with cost.track() as tracker:
        with cost.step("evaluation"):
            cost.record_jev_usage(model="jev-1.13.0", input_tokens=100, output_tokens=5)

    payload = json.dumps(tracker.to_dict())
    assert "jev-1.13.0" in payload


@pytest.mark.parametrize(
    "url",
    [*fx.DUPLICATE_URLS, *fx.ARTICLE_URLS, *fx.CLOSED_URLS, *fx.SERENDIPITOUS_URLS],
)
def test_fixture_covers_the_cases_we_compare_on(url):
    """固定データに、比較で見たい状態が揃っていること。"""
    assert any(r.url == url for r in fx.TAVILY_RESULTS)


# --- 構成 C を Loop まで通す --------------------------------------------------


@pytest.fixture
def db():
    from db.session import SessionLocal

    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def state(db):
    from agent.state import AgentState
    from models import AgentRun
    from schemas.agent import AgentRunStatus

    db.add(AgentRun(run_id="run_c", user_id="user_001", status=AgentRunStatus.RUNNING))
    db.commit()
    st = AgentState(run_id="run_c", user_id="user_001")
    from ai.schemas import SearchDirection

    st.search_directions = [SearchDirection(category="hackathon", query="q", reason="r")]
    return st


def _fake_registry(results):
    """search_web と read_page を tool 名で振り分ける。

    ひとつの返り値で両方をまかなうと、本文取得が呼ばれたことに気づけない。
    """
    from tools.base import ToolResult

    def invoke(name, **kwargs):
        if name == "read_page":
            wanted = kwargs["url"]
            return ToolResult(
                {
                    "pages": [fx.FETCHED_PAGES[u] for u in wanted if u in fx.FETCHED_PAGES],
                    "failed": [u for u in wanted if u not in fx.FETCHED_PAGES],
                },
                external=True,
            )
        return ToolResult(list(results), external=True)

    return invoke


def _extracted(url: str):
    from ai.schemas.extraction import ExtractedOpportunity

    return (url, ExtractedOpportunity(title=f"T {url}", type="hackathon"))


def test_prefilter_limits_what_gets_extracted(db, state, monkeypatch):
    """**全件を高コストな LLM へ投げる前に絞る。**

    絞った分だけ抽出の入力が減っていること。
    """
    from agent import loop

    monkeypatch.setattr(
        loop,
        "get_settings",
        lambda: Settings(
            agent_stub_mode=False,
            search_api_key="k",
            search_pipeline="prefilter",
            prefilter_read_limit=3,
            # 読み足しを止める。**ここで見るのは「最初に何件へ絞ったか」だけ。**
            listing_stop_after_empty_rounds=0,
        ),
    )
    monkeypatch.setattr(loop.registry, "invoke", _fake_registry(fx.TAVILY_RESULTS))
    # 見立ては固定。先頭 3 件を読む。
    monkeypatch.setattr(
        loop,
        "rank_for_reading",
        lambda results, **kw: ([0, 1, 2], list(range(3, len(results)))),
    )

    seen = {}

    def fake_extract(sources, **_):
        seen["n"] = len(sources)
        return [_extracted(s.url) for s in sources], []

    monkeypatch.setattr(loop, "extract_many", fake_extract)

    ids = loop._search_and_extract(db, state)

    assert seen["n"] == 3
    assert len(ids) == 3


def test_full_pipeline_reads_everything(db, state, monkeypatch):
    """既定（構成 A）は全件読む。**現行の挙動を変えない。**"""
    from agent import loop

    monkeypatch.setattr(
        loop,
        "get_settings",
        lambda: Settings(agent_stub_mode=False, search_api_key="k"),
    )
    monkeypatch.setattr(loop.registry, "invoke", _fake_registry(fx.TAVILY_RESULTS))

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("既定で見立てが呼ばれている")

    monkeypatch.setattr(loop, "rank_for_reading", boom)

    seen = {}

    def fake_extract(sources, **_):
        seen["n"] = len(sources)
        return [_extracted(s.url) for s in sources], []

    monkeypatch.setattr(loop, "extract_many", fake_extract)
    loop._search_and_extract(db, state)

    assert seen["n"] == len(fx.TAVILY_RESULTS)


def test_shortfall_reads_more_from_the_deferred_pile(db, state, monkeypatch):
    """読んだ結果 3 件に満たなければ、後回しにした分から追加で読む。

    **上限つき。無制限には増やさない。**
    """
    from agent import loop

    monkeypatch.setattr(
        loop,
        "get_settings",
        lambda: Settings(
            agent_stub_mode=False,
            search_api_key="k",
            search_pipeline="prefilter",
            prefilter_read_limit=2,
            prefilter_extra_reads=2,
            # 読み足しは 1 巡だけ。**回数は設定で決まる。**
            listing_stop_after_empty_rounds=1,
        ),
    )
    monkeypatch.setattr(loop.registry, "invoke", _fake_registry(fx.TAVILY_RESULTS))
    monkeypatch.setattr(
        loop,
        "rank_for_reading",
        lambda results, **kw: ([0, 1], list(range(2, len(results)))),
    )

    batches = []

    def fake_extract(sources, **_):
        batches.append(len(sources))
        # 1 回目は 1 件しか抽出できず、TOP3 に届かない
        if len(batches) == 1:
            return [_extracted(sources[0].url)], [sources[1].url]
        return [_extracted(s.url) for s in sources], []

    monkeypatch.setattr(loop, "extract_many", fake_extract)
    ids = loop._search_and_extract(db, state)

    # 1 巡ぶんだけ追加される。**巡の数は `listing_stop_after_empty_rounds`。**
    assert batches == [2, 2]
    assert len(ids) == 3
