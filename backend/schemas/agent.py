"""AgentRun / AgentLog スキーマ。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from schemas.opportunity import OpportunitySummary, Timestamp


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStep(StrEnum):
    ANALYZING_PROFILE = "analyzing_profile"
    PLANNING = "planning"
    SEARCHING = "searching"
    EVALUATING = "evaluating"
    VERIFYING = "verifying"
    COMPLETED = "completed"


class AgentRunCreated(BaseModel):
    run_id: str
    status: AgentRunStatus


class AgentRunState(BaseModel):
    """GET /api/agent/runs/{run_id}。Frontend の探索中画面がポーリングする。"""

    run_id: str
    status: AgentRunStatus
    # **この run の入力原文。** 改行を保ったまま返す。
    # 古い run は None。**現在のプロフィールで補わない。**
    wishes_source: str | None = None
    region_source: str | None = None
    # AI が整理した探索方向。**原文の置き換えには使わない。別枠で見せる。**
    goal_directions: list[str] = Field(default_factory=list)
    current_step: AgentStep | None = None
    message: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    error: str | None = None

    # この探索にかかった見積もり額と、高性能モデルを使った回数。
    # **見積もりであって請求額ではない**（ai/cost.py の単価表を参照）。
    # 「全件を高性能モデルへ投げていない」ことを示すために出す。
    cost_jpy: float = Field(default=0.0, ge=0)
    expensive_model_calls: int = Field(default=0, ge=0)


class SearchCandidate(BaseModel):
    """検索で見つかった候補 1 件（#47）。

    **「読んでいない」と「日程が無い」と「終了した」を混ぜない。**
    読んでいない候補を受付中として扱わない。
    """

    title: str
    url: str
    # 本文を読んで抽出できたか。False の候補は日時も受付状況も分からない。
    read: bool = False
    # おすすめ（この run の最終選定）に入っているか。
    recommended: bool = False
    # **抽出できた開催日だけ。** 検索結果の公開日や抜粋中の日付は使わない。
    start_at: Timestamp = None
    # 出典に時刻が書かれていたか。True なら時刻を表示しない。
    start_at_is_date_only: bool | None = None
    # 期間との関係。読んでいない候補では None。
    window_status: str | None = None
    # 受付状況。**読んでいない候補では None**（unknown とも書かない）。
    availability: str | None = None
    verified: bool = False


class AgentRunResult(BaseModel):
    """GET /api/agent/runs/{run_id}/result。**この run の最終選定。**

    `GET /api/opportunities`（保存一覧の母集合）とは別物。あちらは status で
    絞った最新の一覧で、こちらは**その run で選んだものを順位順**に返す。

    `recorded` が False なら「まだ結果が無い」。未完了と、完了したが 0 件は
    `status` と `selected` の組で区別する。
    """

    run_id: str
    status: AgentRunStatus
    # **この run の入力原文。** 改行を保ったまま返す。古い run は None。
    # **現在のプロフィールで補わない。**
    wishes_source: str | None = None
    region_source: str | None = None
    # AI が整理した探索方向。**原文の置き換えには使わない。別枠で見せる。**
    goal_directions: list[str] = Field(default_factory=list)
    # この run が新しい探索経路か。**旧経路の画面を変えないため。**
    discovery_route: bool = False
    # `selected` の先頭いくつが「おすすめ」か。**評価できなければ 0。**
    # **未評価を「おすすめ」と呼ばないため、件数で区別する。**
    recommended_count: int = 0
    # **この探索のあとにプロフィールが編集されたか。**
    # True なら画面は「前回の探索結果」と分かるように出す。
    profile_changed_since: bool = False
    # 結果が記録されているか。未完了・古い run では False
    recorded: bool = False
    # 順位順。**3 件に満たないことがある**
    selected: list[OpportunitySummary] = Field(default_factory=list)
    # 3 件に満たなかった理由
    shortfall_reason: str | None = None
    # この run が対象にした期間（#47）。{'start','end','tz','days'}
    search_window: dict | None = None
    # **検索で見つかった候補すべて。** 読んだ分も読んでいない分も入る。
    # この列が付く前の run では空（水増ししない）。
    search_candidates: list[SearchCandidate] = Field(default_factory=list)
    # **推薦しなかったが、本文まで読んで抽出できた候補。**
    # 検索しただけで未読の候補は入らない（確認済みの推薦と同じ扱いにしない）。
    others: list[OpportunitySummary] = Field(default_factory=list)
    # **失敗した理由。** 「記録されていません」だけでは原因が分からない。
    # 設定不足（鍵が無いなど）と、探しても見つからなかったことは別。
    error: str | None = None


class AgentLogEntry(BaseModel):
    """GET /api/agent/runs/{run_id}/logs。"""

    step: AgentStep
    message: str
    created_at: datetime | None = None
