"""おすすめの選定（#47）。**LLM は呼ばない。** 並べ方と除外だけを見る。"""

from ai import matching
from ai.schemas.match import MatchJudgement


class _Row:
    def __init__(self, oid, wish, availability="unknown", searched_values=None):
        self.opportunity_id = oid
        self.wish = wish
        self.availability = availability
        self.searched_values = searched_values or {}
        self.title = f"催し{oid}"
        self.location = "東京都内"
        self.region = "東京都"
        self.description = "説明"
        self.start_at = None


def _j(oid, m, wishes=(), reason="x"):
    return MatchJudgement(opportunity_id=oid, match=m, matched_wishes=list(wishes), reason=reason)


def test_終了済みと条件外はおすすめの対象にしない():
    assert matching.recommendable(_Row("a", "音楽")) is True
    assert matching.recommendable(_Row("b", "音楽", availability="closed")) is False
    assert (
        matching.recommendable(_Row("c", "音楽", searched_values={"schedule_fit": "期間外"}))
        is False
    )
    assert (
        matching.recommendable(_Row("d", "音楽", searched_values={"excluded": "千葉県"})) is False
    )


def test_受付未確認は対象から外さない():
    """**受付の確認状況は評価と別の軸。** 未確認を理由に落とさない。"""
    assert matching.recommendable(_Row("e", "音楽", availability="unknown")) is True


def test_希望の多様性を見て上位を選ぶ():
    rows = [_Row("a", "音楽"), _Row("b", "音楽"), _Row("c", "ポケモン"), _Row("d", "DTM")]
    judged = {
        "a": _j("a", 95),
        "b": _j("b", 90),
        "c": _j("c", 85),
        "d": _j("d", 80),
    }
    top = matching.order(rows, judged, limit=3)
    # 音楽ばかりにせず、別の希望も拾う
    assert [r.opportunity_id for r in top] == ["a", "c", "d"]


def test_種類を揃えるために不適合を上位へ入れない():
    rows = [_Row("a", "音楽"), _Row("b", "音楽"), _Row("c", "ポケモン")]
    judged = {"a": _j("a", 95), "b": _j("b", 92), "c": _j("c", 20)}
    top = matching.order(rows, judged, limit=3)
    # ポケモンは適合度が離れているので、多様性のためには上げない
    assert [r.opportunity_id for r in top][:2] == ["a", "b"]


def test_評価が無ければおすすめは0件():
    """**架空の点を付けない。** 評価に失敗したら選ばない。"""
    rows = [_Row("a", "音楽"), _Row("b", "ポケモン")]
    assert matching.order(rows, {}, limit=3) == []


def test_渡していないidの判断は捨てる(monkeypatch):
    """作られた id で取り違えないこと。"""
    from ai.schemas.match import MatchOutput

    class _Res:
        data = MatchOutput(judgements=[_j("a", 80), _j("存在しない", 99)])

    monkeypatch.setattr(matching, "generate_structured", lambda **kw: _Res())
    out = matching.judge([_Row("a", "音楽")], wishes="音楽が好き", region="東京", window=None)
    assert list(out.keys()) == ["a"]


def test_候補が無ければLLMを呼ばない(monkeypatch):
    called = {"n": 0}

    def _boom(**kw):
        called["n"] += 1
        raise AssertionError("呼んではいけない")

    monkeypatch.setattr(matching, "generate_structured", _boom)
    assert matching.judge([], wishes="x", region=None, window=None) == {}
    assert called["n"] == 0


def test_配列だけの応答とid鍵を受け取れる():
    """実測: `judgements` で包まず、鍵も `id` で返してくることがある。"""
    from ai.schemas.match import MatchOutput

    out = MatchOutput.model_validate(
        [{"id": "a", "match": 80, "matched_wishes": ["音楽が好き"], "reason": "x"}]
    )
    assert out.judgements[0].opportunity_id == "a"
    assert out.judgements[0].match == 80


def test_ホームは最新の完了runだけを見る():
    """**複数 run の候補を混ぜない（#47）。**

    実測で、ホームが `GET /api/opportunities`（保存一覧の母集合）を
    そのまま並べ、過去 run の候補まで 59 件出ていた。
    """
    from datetime import UTC, datetime, timedelta

    from db.session import SessionLocal
    from models import DEFAULT_USER_ID
    from models.agent_run import AgentRun
    from services import agent_service

    now = datetime.now(UTC)
    db = SessionLocal()
    db.add(
        AgentRun(
            run_id="r_old",
            user_id=DEFAULT_USER_ID,
            status="completed",
            selected_ids=[],
            created_at=now - timedelta(hours=1),
        )
    )
    db.add(
        AgentRun(
            run_id="r_new",
            user_id=DEFAULT_USER_ID,
            status="completed",
            selected_ids=[],
            created_at=now,
        )
    )
    db.commit()
    got = agent_service.latest_result(db, DEFAULT_USER_ID)
    assert got is not None and got.run_id == "r_new"
    # 走っている途中の run は対象にしない
    db.add(
        AgentRun(
            run_id="r_running",
            user_id=DEFAULT_USER_ID,
            status="running",
            created_at=now + timedelta(minutes=5),
        )
    )
    db.commit()
    assert agent_service.latest_result(db, DEFAULT_USER_ID).run_id == "r_new"
    # 他人の run は見えない
    assert agent_service.latest_result(db, "user_other") is None
    db.close()
