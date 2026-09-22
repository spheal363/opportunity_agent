"""新経路と、main 側の仕組み（反応の反映・自動探索）のつながり（#47）。

**保存データとテストだけで確かめる。** 有料の探索は呼ばない。
"""

from datetime import UTC, datetime

import pytest

from agent import discovery_run, loop
from ai import discovery, search_plan
from ai.schemas.search_plan import SearchDirection
from db.session import SessionLocal
from models import DEFAULT_USER_ID
from models.agent_run import AgentRun
from models.user_profile import UserProfile
from schemas.agent import AgentRunTrigger
from services import agent_service

WISHES = (
    "ハウスやテクノなど四つ打ちの音楽を楽しめるイベントに行きたい\n"
    "初めての曲作りにつながるDTM・作曲のワークショップに出たい\n"
    "エンジニアとしてプロダクトを作れるハッカソンに参加したい\n"
    "ポケモンのイベントにも参加したい"
)


def _profile(db):
    p = UserProfile(user_id=DEFAULT_USER_ID, name="検証", wants_now=WISHES, location="東京")
    db.merge(p)
    db.commit()
    return p


# --- ② serendipity の保証が何をするか ------------------------------------


def _dir(q, serendipity=False):
    return SearchDirection(category="event", query=q, reason="r", serendipity=serendipity)


def test_serendipityの確保は既存の方向を書き換えない():
    """**ラベルの付け替えでもクエリの書き換えでも削除でもない。** 追加だけ。"""
    before = [_dir("ポケモン イベント 東京"), _dir("ハウス テクノ 東京")]
    after = search_plan._ensure_serendipity(list(before), ["AI × Music"])

    # 元の方向はそのまま残る（順序・クエリ・ラベル）
    assert [d.query for d in after[:2]] == [d.query for d in before]
    assert [d.serendipity for d in after[:2]] == [False, False]
    # 足されたのは 1 本だけ
    assert len(after) == len(before) + 1
    assert after[-1].serendipity is True


def test_希望が枠を埋めても交差点で置き換えない():
    """**4 希望で枠が埋まっても、希望は消えない。**

    `_ensure_serendipity` は `[:MAX_DIRECTIONS]` の**あと**に足すので、
    交差点は枠を奪わず末尾に付く。
    """
    from ai.prompts.search_plan import MAX_DIRECTIONS

    wishes = [
        "ハウス テクノ 東京",
        "DTM 作曲 体験 東京",
        "ハッカソン 東京",
        "ポケモン イベント 東京",
    ]
    assert len(wishes) == MAX_DIRECTIONS  # 枠がちょうど埋まっている

    after = search_plan._ensure_serendipity([_dir(q) for q in wishes], ["AI × Music"])
    kept = [d.query for d in after if not d.serendipity]
    assert kept == wishes  # **ポケモンを含め、1 つも落ちていない**
    # 交差点は「置き換え」ではなく「追加」
    assert len(after) == MAX_DIRECTIONS + 1
    assert "ポケモン" not in after[-1].query  # 希望を交差点に混ぜていない


def test_交差点が無ければ足さない():
    before = [_dir("ポケモン イベント 東京")]
    assert search_plan._ensure_serendipity(list(before), []) == before


def test_serendipityの確保は新経路では使われない():
    """**旧経路だけの仕組み。** 新経路は希望ごとに独立して問い合わせる。"""
    import inspect

    assert "_ensure_serendipity" in inspect.getsource(search_plan.plan_search)
    assert "_ensure_serendipity" not in inspect.getsource(discovery_run.run)
    assert "_ensure_serendipity" not in inspect.getsource(discovery.discover)


def test_新経路は希望ごとに独立して聞く():
    """**希望どうしを掛け合わせない。** 1 つの依頼に 1 つの希望しか入れない。"""
    wishes = [w for w in WISHES.splitlines() if w]
    prompts = [
        discovery.build_prompt(wish=w, region="東京", window_text="期間", want=5, known=[])
        for w in wishes
    ]
    for wish, text in zip(wishes, prompts, strict=True):
        assert wish in text
        for other in wishes:
            if other != wish:
                assert other not in text  # ほかの希望が混ざらない
    # ポケモンの依頼に技術の語を足していない
    poke = prompts[-1]
    assert "ハッカソン" not in poke and "エンジニア" not in poke
    assert "他の希望や条件を混ぜないでください" in poke


# --- ① 反応の反映がどこまで届くか ----------------------------------------


def test_反応の反映は旧経路だけに渡っている(monkeypatch):
    """**未対応をテストで固定する。**

    `learned`（#50）は旧経路の検索計画と評価にしか渡っていない。
    新経路の検索・評価には届いていない。
    """
    import inspect

    src = inspect.getsource(loop._run)
    # 旧経路には渡っている
    assert "_plan_search(state, profile, learned, db=db)" in src
    assert "_evaluate_and_select(db, state, found, learned)" in src
    # 新経路には渡していない
    assert "discovery_run.run(db, state, profile, win, log=_log, step=_step)" in src
    assert "learned" not in inspect.signature(discovery_run.run).parameters


def test_新経路の評価は今回の希望だけを入力にする():
    """**過去の反応が、今回の希望を置き換えないこと。**"""
    import inspect

    from ai import matching

    src = inspect.getsource(matching.judge)
    assert "wishes" in inspect.signature(matching.judge).parameters
    assert "learned" not in inspect.signature(matching.judge).parameters
    assert "feedback" not in src


# --- ③ 自動探索とのつながり ----------------------------------------------


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def test_自動探索のrunも新経路を通り入力原文を残す(monkeypatch, db):
    """自動で始まった run でも、経路の切り替えと原文の保存が効く。"""
    from config import get_settings

    _profile(db)
    # **設定は lru_cache されている。** 環境変数を変えたらキャッシュを捨てる。
    monkeypatch.setenv("SEARCH_ROUTE", "discovery")
    get_settings.cache_clear()

    seen = {}

    def _fake(db_, state, profile, win, **kw):
        seen["user_id"] = state.user_id
        seen["run_id"] = state.run_id
        return []

    monkeypatch.setattr(discovery_run, "run", _fake)

    run_id = agent_service.create_run(
        db, DEFAULT_USER_ID, trigger=AgentRunTrigger.SCHEDULED, reason="定期チェック"
    )
    loop.run_agent(run_id, DEFAULT_USER_ID)

    get_settings.cache_clear()
    row = db.get(AgentRun, run_id)
    db.refresh(row)
    assert seen["run_id"] == run_id  # **新経路を通った**
    assert row.trigger == AgentRunTrigger.SCHEDULED.value
    # run 開始時の入力原文が残る（自動 run でも）
    assert row.wishes_source == WISHES
    assert row.region_source == "東京"


def test_ホームは他人のrunを返さない(db):
    """`latest_result` は user_id で絞る（#86 の安全なアクセス）。"""
    _profile(db)
    db.add(
        AgentRun(
            run_id="r_mine",
            user_id=DEFAULT_USER_ID,
            status="completed",
            selected_ids=[],
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    assert agent_service.latest_result(db, DEFAULT_USER_ID).run_id == "r_mine"
    assert agent_service.latest_result(db, "user_other") is None


# --- 既定の経路（#47）-----------------------------------------------------


def _route_taken(monkeypatch, db, route: str | None) -> str:
    """その設定で実際に通った経路を返す。**外部は呼ばない。**"""
    from config import get_settings

    _profile(db)
    if route is None:
        monkeypatch.delenv("SEARCH_ROUTE", raising=False)
    else:
        monkeypatch.setenv("SEARCH_ROUTE", route)
    get_settings.cache_clear()

    taken = {}
    monkeypatch.setattr(
        discovery_run, "run", lambda *a, **k: taken.setdefault("route", "discovery") or []
    )
    monkeypatch.setattr(
        loop, "_plan_search", lambda *a, **k: taken.setdefault("route", "legacy") or []
    )
    monkeypatch.setattr(loop, "_search_and_extract", lambda *a, **k: [])
    monkeypatch.setattr(loop, "_evaluate_and_select", lambda *a, **k: [])
    monkeypatch.setattr(loop, "_verify_and_finalize", lambda *a, **k: None)

    run_id = agent_service.create_run(db, DEFAULT_USER_ID)
    loop.run_agent(run_id, DEFAULT_USER_ID)
    get_settings.cache_clear()
    return taken.get("route", "（どちらも通っていない）")


def test_設定未指定なら新しい経路を通る(monkeypatch, db):
    assert _route_taken(monkeypatch, db, None) == "discovery"


def test_legacyを明示すれば旧経路を通る(monkeypatch, db):
    assert _route_taken(monkeypatch, db, "legacy") == "legacy"


def test_自動探索でも同じ経路選択になる(monkeypatch, db):
    """**自動探索は経路を選ばない。** 設定に従うだけ（有効・無効は変えない）。"""
    from config import get_settings

    _profile(db)
    monkeypatch.delenv("SEARCH_ROUTE", raising=False)
    get_settings.cache_clear()
    taken = {}
    monkeypatch.setattr(
        discovery_run, "run", lambda *a, **k: taken.setdefault("route", "discovery") or []
    )
    run_id = agent_service.create_run(
        db, DEFAULT_USER_ID, trigger=AgentRunTrigger.SCHEDULED, reason="定期"
    )
    loop.run_agent(run_id, DEFAULT_USER_ID)
    get_settings.cache_clear()
    assert taken.get("route") == "discovery"


def test_OrcaRouterの鍵が無ければ理由を出して止まる(monkeypatch, db):
    """**黙って別経路へ切り替えない。** 名前と経路を出して失敗させる。"""
    from config import get_settings

    _profile(db)
    monkeypatch.setenv("AGENT_STUB_MODE", "false")
    monkeypatch.setenv("ORCAROUTER_API_KEY", "")
    get_settings.cache_clear()

    run_id = agent_service.create_run(db, DEFAULT_USER_ID)
    loop.run_agent(run_id, DEFAULT_USER_ID)
    get_settings.cache_clear()

    row = db.get(AgentRun, run_id)
    db.refresh(row)
    assert row.status == "failed"
    assert "ORCAROUTER_API_KEY" in (row.error or "")
    assert "SEARCH_ROUTE=discovery" in (row.error or "")


def test_ホームと結果画面が同じrunのおすすめを返す(db):
    """**同じ `get_result` を通る。** 候補 ID も件数も一致する。"""
    _profile(db)
    run_id = agent_service.create_run(db, DEFAULT_USER_ID)
    loop.run_agent(run_id, DEFAULT_USER_ID)

    home = agent_service.latest_result(db, DEFAULT_USER_ID)
    page = agent_service.get_result(db, run_id, DEFAULT_USER_ID)
    assert home is not None and page is not None
    assert home.run_id == page.run_id == run_id
    assert home.recommended_count == page.recommended_count
    top = lambda r: [o.opportunity_id for o in r.selected[: r.recommended_count]]  # noqa: E731
    assert top(home) == top(page)
    assert len(top(home)) == home.recommended_count
