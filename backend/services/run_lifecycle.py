"""探索の開始を直列化し、中断した run を回復する。uvicorn 1 worker 前提。"""

import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ai.availability import as_utc
from config import Settings
from logging_config import get_logger
from models import AgentRun
from schemas.agent import AgentRunStatus

logger = get_logger(__name__)

# 手動・フィードバック・定期実行で同じロックを使う。
start_lock = threading.Lock()
_ACTIVE = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)
ABANDONED_ERROR = "探索が途中で止まりました（サーバーの再起動などで中断されたとみられます）"


def active_runs(db: Session, user_id: str, now: datetime, settings: Settings) -> list[AgentRun]:
    """実行中とみなす run。**進捗が止まったまま残った run は数えない。**

    プロセスが落ちると run は running のまま残る。それを実行中と数えると、
    自動探索が二度と始まらない。
    """
    return [r for r in _queued_or_running(db, user_id) if not _abandoned(r, now, settings)]


def expire_abandoned_runs(db: Session, user_id: str, now: datetime, settings: Settings) -> int:
    """進捗が止まったまま残った run を failed にする。直した件数を返す。

    **決まった文言だけを残す。** 例外の文字列は載せない（ABANDONED_ERROR）。
    万一まだ動いていた run なら、次に進捗を書いたときに Agent Loop が状態を
    上書きするので、取り返しのつかない変更にはならない。
    """
    stale = [r for r in _queued_or_running(db, user_id) if _abandoned(r, now, settings)]
    for run in stale:
        run.status = AgentRunStatus.FAILED
        run.message = "探索に失敗しました"
        run.error = ABANDONED_ERROR
        logger.warning("auto_explore.abandoned run_id=%s", run.run_id)
    if stale:
        db.commit()
    return len(stale)


def _queued_or_running(db: Session, user_id: str) -> list[AgentRun]:
    return (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.status.in_([s.value for s in _ACTIVE]))
        .all()
    )


def _abandoned(run: AgentRun, now: datetime, settings: Settings) -> bool:
    """最後に進捗を書いてから一定時間たった queued / running の run か。

    updated_at は Agent Loop が進捗を書くたびに進む。作成直後は created_at を見る。
    """
    seen = [as_utc(t) for t in (run.created_at, run.updated_at) if t is not None]
    if not seen:
        return False
    return max(seen) + timedelta(minutes=settings.auto_explore_abandoned_after_minutes) < now
