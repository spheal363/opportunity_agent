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


def test_defaults_keep_the_current_configuration():
    """**採用が決まるまで本番の既定値を変えない。**

    Code Freeze が近く、未検証の構成をデモの既定にしない。
    """
    s = Settings()
    assert s.search_provider == "tavily"
    assert s.page_fetcher == "tavily"
    assert s.evaluator == "llm"
    assert s.search_pipeline == "full"


def test_read_limit_is_a_hypothesis_not_a_fixed_answer():
    """件数は仮説。比較で決める。"""
    assert 6 <= Settings().prefilter_read_limit <= 8
    assert Settings().prefilter_extra_reads > 0


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
    assert tracker.by_step["evaluation"].jev.low_confidence_fallbacks == 1


def test_llm_is_used_by_default(monkeypatch):
    import ai.evaluation as ev

    def boom(**_):  # pragma: no cover
        raise AssertionError("既定で Jev が呼ばれている")

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
    assert out["search_provider"] == "tavily"
    assert out["page_fetcher"] == "tavily"
    assert out["search_pipeline"] == "full"


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
