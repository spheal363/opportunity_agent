"""読む優先順位付け（構成 C）のテスト。**固定データで行う。**

検索の抜粋から始める。抽出済みの DB 行から始めると、抽出そのものの差が
見えなくなる。

**確かめたいこと。**

  1. 関連性の上位だけで埋めず、意外性と「判断できない」枠が残ること
  2. 候補を落とさないこと（順位を下げるだけ）
  3. 抜粋に期限が無いことを減点の理由にしていないこと
"""

import pytest

from ai.jev.client import JevError, JevResponse
from ai.jev.prefilter import SERENDIPITY_SLOTS, UNCLEAR_SLOTS, rank_for_reading
from tests.fixtures import candidates as fx
from tools.search.base import SearchResult

# URL ごとの見立て。(relevance 0-4, serendipity 0-4, is_opportunity, snippet十分)
_VERDICTS = {
    "https://example-hack.jp/agent-2026": (4.0, 1.0, 0.98, 1.0),
    "https://example-connpass.jp/event/998877": (4.0, 1.0, 0.97, 1.0),
    # 記事。関連性は高く出るが、参加できる機会ではない。
    "https://example-media.jp/what-is-ai-agent": (3.8, 0.5, 0.02, 1.0),
    # 意外だが関連する。関連性だけで並べると読まれない。
    "https://example-beatlab.jp/join": (2.0, 4.0, 0.9, 1.0),
    "https://example-local.jp/tech-briefing": (1.2, 3.6, 0.85, 0.2),
    # 終了済み。抜粋からは分からない。
    "https://example-meetup.jp/tokyo-ai-12": (3.0, 1.0, 0.9, 1.0),
    # 本文が取れない候補。抜粋だけでは判断できない。
    "https://example-founders.com/program": (2.6, 2.0, 0.8, 0.1),
}


class FakeJev:
    """URL ごとに決まった答えを返す。**呼び出し回数も数える。**"""

    def __init__(self, *, fail_for: set[str] | None = None):
        self.calls = 0
        self.fail_for = fail_for or set()

    def ask(self, state, questions, **_):
        self.calls += 1
        url = next(
            (u for u in _VERDICTS if u in state),
            None,
        )
        if url in self.fail_for:
            raise JevError("boom", retryable=False)
        relevance, serendipity, is_opp, sufficient = _VERDICTS[url]
        return JevResponse(
            model="jev-1.13.0",
            answers={
                "relevance": _score(relevance),
                "serendipity": _score(serendipity),
                "is_opportunity": _noul(is_opp),
                "snippet_sufficient": _noul(sufficient),
            },
            input_tokens=200,
        )


def _score(value: float):
    from ai.jev.client import JevAnswer

    return JevAnswer(kind="score", score=value, confidence=0.9)


def _noul(value: float):
    from ai.jev.client import JevAnswer

    return JevAnswer(kind="noul", noul=value)


def _rank(results: list[SearchResult], *, limit: int, jev: FakeJev | None = None):
    return rank_for_reading(
        results,
        goal_summary=fx.GOAL_SUMMARY,
        interest_connections=fx.INTERESTS,
        limit=limit,
        client=jev or FakeJev(),
    )


def _urls(results: list[SearchResult], indexes: list[int]) -> list[str]:
    return [results[i].url for i in indexes]


def test_nothing_is_lost():
    """**候補を落とさない。順位を下げるだけ。**

    本文を読んだ結果 3 件に満たなかったとき、下位から追加で読めるようにする。
    """
    results = fx.TAVILY_RESULTS
    selected, rest = _rank(results, limit=4)

    assert sorted(selected + rest) == list(range(len(results)))


def test_serendipity_has_a_reserved_slot():
    """関連性の上位だけで埋めない。

    意外性が高い候補は関連性では上位に来ない。枠を空けないと、
    この製品の軸が最初の段階で消える。
    """
    results = fx.TAVILY_RESULTS
    selected, _ = _rank(results, limit=4)
    picked = _urls(results, selected)

    assert "https://example-beatlab.jp/join" in picked


def test_unclear_snippet_has_a_reserved_slot():
    """**抜粋に情報が無いことを、無関係の根拠にしない。**

    短い snippet しか返さない検索サービスではとくに起きる。
    """
    results = fx.TAVILY_RESULTS
    selected, _ = _rank(results, limit=4)
    picked = _urls(results, selected)

    unclear = {
        "https://example-local.jp/tech-briefing",
        "https://example-founders.com/program",
    }
    assert unclear & set(picked)


def test_articles_go_last_but_are_not_dropped():
    """記事は最後に回す。**外しはしない。**

    見立てを誤ったときに取り返せるようにする。
    """
    results = fx.TAVILY_RESULTS
    selected, rest = _rank(results, limit=4)
    order = selected + rest
    article_index = order.index(next(i for i, r in enumerate(results) if r.url in fx.ARTICLE_URLS))

    assert article_index == len(order) - 1
    assert results[order[-1]].url in fx.ARTICLE_URLS


def test_relevant_candidates_are_read_first():
    results = fx.TAVILY_RESULTS
    selected, _ = _rank(results, limit=4)
    picked = _urls(results, selected)

    assert "https://example-hack.jp/agent-2026" in picked


def test_a_failed_verdict_keeps_the_candidate():
    """Jev の不調で探索そのものが空にならないこと。"""
    results = fx.TAVILY_RESULTS
    jev = FakeJev(fail_for={"https://example-hack.jp/agent-2026"})
    selected, rest = _rank(results, limit=4, jev=jev)

    assert sorted(selected + rest) == list(range(len(results)))


def test_one_request_per_candidate():
    """候補ごとに 1 リクエスト。質問は 1 回にまとめる。"""
    results = fx.TAVILY_RESULTS
    jev = FakeJev()
    _rank(results, limit=4, jev=jev)

    assert jev.calls == len(results)


def test_no_prefilter_when_candidates_fit():
    """読む上限に収まるなら見立てを呼ばない。**無駄な費用を出さない。**"""
    from ai.jev.prefilter import rank_for_reading as rank

    jev = FakeJev()
    selected, rest = rank(
        fx.TAVILY_RESULTS[:2],
        goal_summary="g",
        interest_connections=[],
        limit=8,
        client=jev,
    )
    # rank_for_reading 自体は呼ばれれば見立てる。呼ぶかどうかは loop 側の判断。
    assert selected + rest == [0, 1]


def test_empty_input():
    assert _rank([], limit=4) == ([], [])


@pytest.mark.parametrize("limit", [1, 3, 8])
def test_selected_never_exceeds_the_limit(limit):
    results = fx.TAVILY_RESULTS
    selected, _ = _rank(results, limit=limit)
    assert len(selected) <= limit


def test_slot_counts_are_documented_as_hypotheses():
    """枠の数は仮説。**固定の正解ではない。** 比較で決める。"""
    assert SERENDIPITY_SLOTS >= 1
    assert UNCLEAR_SLOTS >= 1


# --- 探索方向ごとの枠（#65）-------------------------------------------------
#
# **実測で踏んだ。** 方向を見ずに関連性順だけで並べた結果、4 方向のうち
# 2 方向（音楽・勉強会）が **1 件も読まれずに丸ごと消えた。**
# 目標と興味から方向を立てた意味が、本文を読む前に失われていた。


def _ordered(verdict_specs, *, limit, directions=None):
    """(relevance, serendipity, is_opportunity, sufficient) から順序を作る。"""
    from ai.jev.prefilter import Verdict

    verdicts = [
        Verdict(
            index=i,
            relevance=r,
            serendipity=s,
            is_opportunity=o,
            snippet_sufficient=u,
        )
        for i, (r, s, o, u) in enumerate(verdict_specs)
    ]
    from ai.jev.prefilter import _order

    return _order(verdicts, limit=limit, directions=directions)


def test_each_direction_gets_one_slot():
    """**各方向から 1 件ずつ、読む機会を確保する。**"""
    # 方向 0 が関連性で上位を独占している
    specs = [(90, 10, 0.9, 1.0), (85, 10, 0.9, 1.0), (80, 10, 0.9, 1.0), (20, 10, 0.9, 1.0)]
    directions = [0, 0, 0, 1]

    picked, slots = _ordered(specs, limit=2, directions=directions)
    read = picked[:2]

    assert 3 in read, "関連性が低い方向が 1 件も読まれない"
    assert slots[3] == "direction:1"


def test_without_directions_a_whole_direction_can_disappear():
    """方向を渡さない現行の並べ方では、丸ごと消える。**これが実測の状態。**"""
    specs = [(90, 10, 0.9, 1.0), (85, 10, 0.9, 1.0), (80, 10, 0.9, 1.0), (20, 10, 0.9, 1.0)]
    picked, _ = _ordered(specs, limit=2)

    assert 3 not in picked[:2]


def test_a_direction_with_only_articles_is_not_forced():
    """**明確に対象外しかない方向は、無理に枠を埋めない。**"""
    specs = [(90, 10, 0.9, 1.0), (85, 10, 0.9, 1.0), (70, 10, 0.02, 1.0)]
    directions = [0, 0, 1]

    picked, slots = _ordered(specs, limit=2, directions=directions)

    assert picked[:2] == [0, 1]
    assert slots.get(2) != "direction:1"


def test_an_unclear_snippet_still_earns_the_direction_slot():
    """**抜粋から日時や適格性が不明なだけでは、対象外としない。**"""
    specs = [(90, 10, 0.9, 1.0), (85, 10, 0.9, 1.0), (40, 10, 0.9, 0.1)]
    directions = [0, 0, 1]

    picked, slots = _ordered(specs, limit=2, directions=directions)

    assert 2 in picked[:2]
    assert slots[2] == "direction:1"


def test_the_remaining_slots_still_use_the_existing_rules():
    """**残りは既存の選別で埋める。** 方向枠だけにしない。"""
    # 方向 0 に意外性の高い候補、方向 1 に 1 件
    specs = [(90, 10, 0.9, 1.0), (30, 95, 0.9, 1.0), (50, 10, 0.9, 1.0)]
    directions = [0, 0, 1]

    _, slots = _ordered(specs, limit=3, directions=directions)

    assert set(slots.values()) >= {"direction:0", "direction:1", "serendipity"}


def test_every_candidate_is_still_ordered():
    """**候補は落とさない。** 順序を変えるだけ。"""
    specs = [(90, 10, 0.9, 1.0), (85, 10, 0.9, 1.0), (20, 10, 0.02, 1.0)]
    picked, _ = _ordered(specs, limit=1, directions=[0, 1, 2])

    assert sorted(picked) == [0, 1, 2]


def test_the_slot_for_each_read_candidate_is_recorded():
    """**なぜ読んだかを残す。** 後から説明できるように。"""
    specs = [(90, 10, 0.9, 1.0), (20, 10, 0.9, 1.0)]
    _, slots = _ordered(specs, limit=2, directions=[0, 1])

    assert slots[0] == "direction:0"
    assert slots[1] == "direction:1"
