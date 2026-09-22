"""Agent Run の作成・状態取得。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, AgentLog, AgentRun, Opportunity
from schemas.agent import (
    AgentLogEntry,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    AgentRunTrigger,
    AgentStep,
)
from schemas.opportunity import OpportunitySummary


def create_run(
    db: Session,
    user_id: str = DEFAULT_USER_ID,
    *,
    trigger: AgentRunTrigger = AgentRunTrigger.MANUAL,
    reason: str | None = None,
) -> str:
    """run を作る。実行（run_agent）は呼び出し側。

    `reason` は Agent が自分で始めたときの「なぜ始めたか」（services/auto_explore.py）。
    **決まった文面と数値だけを渡すこと。** 画面にそのまま出る。
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db.add(
        AgentRun(
            run_id=run_id,
            user_id=user_id,
            status=AgentRunStatus.QUEUED,
            trigger=trigger,
            trigger_reason=reason,
            # **マイクロ秒まで持たせる。** server_default（CURRENT_TIMESTAMP）は秒までで、
            # 同じ秒に作った run のどちらが新しいか分からなくなる。自動探索は
            # 「最新の run」「最後の自動 run」で判定するので、前後を取り違えると困る。
            # 保存は他の列と同じく tz なしの UTC。
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    if reason:
        # 探索中画面の先頭に「なぜ始めたか」を出す。**AgentStep は増やさない。**
        # 最初のステップ（プロフィール分析）の記録として置く。Agent Loop の
        # 最初の Log はこれより後に書かれる。
        db.add(AgentLog(run_id=run_id, step=AgentStep.ANALYZING_PROFILE, message=reason))
    db.commit()
    return run_id


def latest_row(db: Session, user_id: str) -> AgentRun | None:
    """その人の最新の run（状態は問わない）。無ければ None。"""
    return (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc())
        .first()
    )


def get_latest_run(db: Session, user_id: str) -> AgentRunState | None:
    """その人の最新の run。無ければ None。

    Agent が自分で始めた探索（trigger が manual 以外）を画面が見つけるのに使う。
    他人の run は返さない（#69）。
    """
    row = latest_row(db, user_id)
    if row is None:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def get_run(db: Session, run_id: str, user_id: str) -> AgentRunState | None:
    """その人の run だけを返す（#69）。他人の run は存在しないのと同じに扱う。"""
    row = db.get(AgentRun, run_id)
    if row is None or row.user_id != user_id:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def list_logs(db: Session, run_id: str) -> list[AgentLogEntry]:
    """run の Log。**呼ぶ前に `get_run` で所有者を確かめること。**"""
    rows = db.query(AgentLog).filter(AgentLog.run_id == run_id).order_by(AgentLog.id.asc()).all()
    return [AgentLogEntry.model_validate(r, from_attributes=True) for r in rows]


def get_result(db: Session, run_id: str) -> AgentRunResult | None:
    """この run の最終選定を順位順で返す。

    **`GET /api/opportunities` とは別経路。** あちらは status で絞った最新の
    一覧（保存一覧の母集合）で、こちらは**その run が選んだものだけ**。

    区別するもの:
      run が無い        -> None（呼び出し側が 404）
      未完了            -> recorded=False, status=running
      結果の記録が無い   -> recorded=False（列を足す前の古い run）
      完了したが 0 件    -> recorded=True, selected=[]
    """
    run = db.get(AgentRun, run_id)
    if run is None:
        return None

    ids = run.selected_ids
    if ids is None:
        # **失敗したときこそ理由が要る。** 「記録されていません」だけでは、
        # 設定が足りないのか、探しても見つからなかったのかが分からない。
        return AgentRunResult(run_id=run_id, status=run.status, recorded=False, error=run.error)

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity).filter(Opportunity.opportunity_id.in_(ids)).all()
    }
    # **順位を保つ。** DB の返す順ではなく selected_ids の順。
    selected = [
        OpportunitySummary.model_validate(rows[i], from_attributes=True) for i in ids if i in rows
    ]
    return AgentRunResult(
        run_id=run_id,
        status=run.status,
        recorded=True,
        selected=selected,
        shortfall_reason=run.shortfall_reason,
        # **失敗の理由を隠さない。** 設定不足なら直せる。
        error=run.error,
    )
