"""Agent が自分で探索を始める（自動探索, #84 / #85）。

**自動にするのは発見だけ。** Calendar への書き込みなど外部に影響する操作は
これまでどおり人の操作に残す（Autonomous discovery, human-controlled action）。

きっかけ（schemas.agent.AgentRunTrigger）:
  feedback   最新の推薦の過半数に👎が付いた。👎を送った直後に判定する
  stale      推薦中・保存中で行動できる候補が 3 件を切り、前回の探索の後に
             締切を過ぎた・開催を終えたものが出た。定期チェック（agent/scheduler.py）で判定する
  scheduled  前回の探索から設定した時間がたった。定期チェックで判定する

止める仕組みは**すべてここでコードが強制する**。LLM の判断は使わない。
全自動 trigger に共通:
  - 機能フラグ（既定オフ。オフなら何も変えない）
  - 実行中（queued / running）の run があれば始めない。ただし進捗が止まったまま
    残った run（プロセスが落ちたなど）は妨げにしない
  - プロフィールが無ければ始めない
  - 直近 24 時間の自動 run の回数上限
  - 直近 24 時間の全 run の見積もり額（cost_jpy）の合計の上限
  - 自動 run 同士の最低間隔

**「1 日」は暦日ではなく直近 24 時間。** タイムゾーンで境目がずれず、
日付が変わった直後にまとめて走ることもない。

判定（decide_*）は run を作らない。作るのは start_* だけ。
HTTP の概念は持ち込まない。実行（BackgroundTasks / asyncio.to_thread）は呼び出し側。

**理由の文は決まった文面と数値だけ。** 候補のタイトルなど Web 由来の文を入れない。
理由は探索中画面の先頭とホームの通知にそのまま出る。攻撃ページが書いたタイトルが
「Agent がこう判断した」として画面に届いては困る（agent/loop.py の _DROPPED_MESSAGE と同じ考え）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ai.availability import Availability, as_utc, for_extracted
from config import Settings, get_settings
from logging_config import describe_exception, get_logger
from models import AgentRun, Feedback, Opportunity, UserProfile
from schemas.agent import AgentRunStatus, AgentRunTrigger
from schemas.feedback import Reaction
from schemas.opportunity import OpportunityStatus
from services import agent_service

logger = get_logger(__name__)

# 判定から run の作成までを 1 つずつ通す。feedback の route と定期チェックが
# 同時に判定すると、どちらも「実行中の run は無い」と見て 2 本走らせてしまう。
# **1 プロセス（uvicorn 1 worker）が前提。** worker を増やすなら DB 側で排他する。
_start_lock = threading.Lock()

# 回数・費用の上限を数える幅。暦日ではなく直近 24 時間。
WINDOW = timedelta(hours=24)

_ACTIVE = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)

# 推薦中・保存中。これが「行動できる候補」の母集合。参加済みなどは数えない。
_HELD = (OpportunityStatus.RECOMMENDED, OpportunityStatus.INTERESTED)

# 行動できる候補がこれを切ったら補充を考える（推薦は TOP3）。
ENOUGH_ACTIONABLE = 3

# 止まったまま残った run を failed にするときの文言。**例外の文字列は載せない。**
# run の error は GET /api/agent/runs/{id} でそのまま画面に出る。
ABANDONED_ERROR = "探索が途中で止まりました（サーバーの再起動などで中断されたとみられます）"


@dataclass(frozen=True)
class Decision:
    """自動で始めると決めたこと。reason は画面に出す文（決まった文面と数値だけ）。"""

    trigger: AgentRunTrigger
    reason: str


# --------------------------------------------------------------------------
# 理由の文面。**数値だけを差し込む。** Web 由来の文は入れない
# --------------------------------------------------------------------------


def feedback_reason(total: int, disliked: int) -> str:
    return f"今回の推薦{total}件のうち{disliked}件に👎が付いたため、反応を踏まえて探し直します"


def stale_reason(expired: int) -> str:
    return f"推薦中の機会のうち{expired}件が締切を過ぎたか開催を終えたため、新しく探します"


def scheduled_reason(elapsed: timedelta) -> str:
    """経過時間は**実際にたった時間**で書く。設定値ではない（止まっていた間も含めて正直に）。"""
    hours = int(elapsed.total_seconds() // 3600)
    if hours >= 1:
        return f"前回の探索から{hours}時間たったため、新着を探します"
    minutes = max(1, int(elapsed.total_seconds() // 60))
    return f"前回の探索から{minutes}分たったため、新着を探します"


# --------------------------------------------------------------------------
# 判定（run を作らない）
# --------------------------------------------------------------------------


def decide_after_feedback(
    db: Session, user_id: str, now: datetime, settings: Settings | None = None
) -> Decision | None:
    """👎の直後に呼ぶ。最新の推薦の過半数に👎が付いていれば探し直す。

    成り立つ条件:
      - 最新の run が完了している（**それより新しい run があれば始めない**）
      - その推薦（selected_ids）が 2 件以上
      - そのうち 2 件以上、かつ過半数に👎（reaction=dislike か status=dismissed）

    **同じ run への探し直しは 1 回まで。** 探し直した run は元の run より新しいので、
    以後は「最新の run が完了している」を満たさない。探し直した run が失敗しても、
    もう一度は走らせない（失敗した run が最新として残るため）。
    """
    settings = settings or get_settings()
    if not settings.auto_explore_on_feedback:
        return None

    base = agent_service.latest_row(db, user_id)
    if base is None or base.status != AgentRunStatus.COMPLETED:
        return None
    ids = list(base.selected_ids or [])
    if len(ids) < 2:
        return None
    disliked = _count_disliked(db, user_id, ids)
    if disliked < 2 or disliked * 2 <= len(ids):
        return None

    decision = Decision(AgentRunTrigger.FEEDBACK, feedback_reason(len(ids), disliked))
    return _unless_blocked(db, user_id, now, settings, decision)


def decide_on_tick(
    db: Session, user_id: str, now: datetime, settings: Settings | None = None
) -> Decision | None:
    """定期チェックで呼ぶ。stale を先に見て、成り立たなければ scheduled を見る。

    **一度も探索していない人には始めない。** 最初の探索は本人が始める
    （目標の保存・ボタン）。「前回」が無いので、どちらの条件も決められない。
    """
    settings = settings or get_settings()
    if not settings.auto_explore_schedule:
        return None

    last = agent_service.latest_row(db, user_id)
    if last is None:
        return None
    decision = _stale(db, user_id, as_utc(last.created_at), now) or _scheduled(
        as_utc(last.created_at), now, settings
    )
    if decision is None:
        return None
    return _unless_blocked(db, user_id, now, settings, decision)


def _stale(db: Session, user_id: str, last_run_at: datetime, now: datetime) -> Decision | None:
    """推薦中・保存中の候補が締切切れで減ったか。

    成り立つ条件:
      - 行動できる候補（受付終了でない・締切が過ぎていない）が 3 件を切った
      - **前回の探索の後に**締切を過ぎた・開催を終えたものが 1 件以上ある

    「前回の探索の後に」で絞るのは、同じ期限切れで何度も走らせないため。
    探し直しても行動できる候補が 3 件に届かないことはあり、その期限切れを
    毎回数えると、上限に達するまで同じ理由で走り続ける。

    受付終了（availability=closed）は探索中の検証でしか分からず、その run は
    もう知っている。**新しく分かるのは日時が過ぎたことだけ**なので、それを数える。
    締切の種類ごとの扱い（早割の期限は閉じる根拠にしない など）は
    ai/availability.py と同じ判定を使う。
    """
    rows = (
        db.query(Opportunity)
        .filter(
            Opportunity.user_id == user_id,
            Opportunity.status.in_([s.value for s in _HELD]),
        )
        .all()
    )
    actionable = 0
    newly_expired = 0
    for row in rows:
        known_closed = row.availability == Availability.CLOSED
        closed_now = _closed_by_date(row, now)
        if not known_closed and not closed_now:
            actionable += 1
        elif closed_now and not known_closed and not _closed_by_date(row, last_run_at):
            newly_expired += 1
    if actionable >= ENOUGH_ACTIONABLE or newly_expired == 0:
        return None
    return Decision(AgentRunTrigger.STALE, stale_reason(newly_expired))


def _scheduled(last_run_at: datetime, now: datetime, settings: Settings) -> Decision | None:
    """前回の探索（状態は問わない）から設定した時間がたったか。"""
    elapsed = now - last_run_at
    if elapsed < timedelta(minutes=settings.auto_explore_schedule_interval_minutes):
        return None
    return Decision(AgentRunTrigger.SCHEDULED, scheduled_reason(elapsed))


def _closed_by_date(row: Opportunity, at: datetime) -> bool:
    """その時点で、日時だけから受付終了と言い切れるか（ai/availability.py の判定）。"""
    status, _ = for_extracted(row, now=at)
    return status is Availability.CLOSED


def blocked_reason(db: Session, user_id: str, now: datetime, settings: Settings) -> str | None:
    """全自動 trigger に共通の止める条件。止めるならログ用の短い識別子を返す。

    **ここは緩めない。** きっかけごとに例外を作ると、どれか 1 つの経路から
    上限を超えて走らせられるようになる。
    """
    if db.get(UserProfile, user_id) is None:
        return "no_profile"
    if active_runs(db, user_id, now, settings):
        return "run_in_progress"

    recent = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.created_at >= _naive(now - WINDOW))
        .all()
    )
    automatic = [r for r in recent if r.trigger != AgentRunTrigger.MANUAL]
    if len(automatic) >= settings.auto_explore_max_runs_per_day:
        return "daily_run_limit"
    # **手動の run も数える。** 費用は誰が始めたかに関係なくかかる。
    if sum(r.cost_jpy or 0.0 for r in recent) >= settings.auto_explore_max_cost_jpy_per_day:
        return "daily_cost_limit"

    last_auto = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.trigger != AgentRunTrigger.MANUAL)
        .order_by(AgentRun.created_at.desc())
        .first()
    )
    min_interval = timedelta(minutes=settings.auto_explore_min_interval_minutes)
    if last_auto is not None and as_utc(last_auto.created_at) + min_interval > now:
        return "min_interval"
    return None


def active_runs(db: Session, user_id: str, now: datetime, settings: Settings) -> list[AgentRun]:
    """実行中とみなす run。**進捗が止まったまま残った run は数えない。**

    プロセスが落ちると run は running のまま残る。それを実行中と数えると、
    自動探索が二度と始まらない。
    """
    return [r for r in _queued_or_running(db, user_id) if not _abandoned(r, now, settings)]


def _unless_blocked(
    db: Session, user_id: str, now: datetime, settings: Settings, decision: Decision
) -> Decision | None:
    reason = blocked_reason(db, user_id, now, settings)
    if reason is None:
        return decision
    # 理由の文は出さない（決まった文面だが、ログに要るのは識別子だけ）。
    logger.info(
        "auto_explore.blocked user_id=%s trigger=%s reason=%s", user_id, decision.trigger, reason
    )
    return None


def _count_disliked(db: Session, user_id: str, ids: list[str]) -> int:
    """推薦のうち👎が付いた件数。Feedback の dislike か、status=dismissed。"""
    by_feedback = {
        oid
        for (oid,) in db.query(Feedback.opportunity_id)
        .filter(
            Feedback.user_id == user_id,
            Feedback.opportunity_id.in_(ids),
            Feedback.reaction == Reaction.DISLIKE,
        )
        .distinct()
    }
    by_status = {
        oid
        for (oid,) in db.query(Opportunity.opportunity_id).filter(
            Opportunity.user_id == user_id,
            Opportunity.opportunity_id.in_(ids),
            Opportunity.status == OpportunityStatus.DISMISSED,
        )
    }
    return len(by_feedback | by_status)


# --------------------------------------------------------------------------
# 開始（run を作る。実行は呼び出し側）
# --------------------------------------------------------------------------


def start_after_feedback(
    db: Session, user_id: str, reaction: Reaction, now: datetime | None = None
) -> str | None:
    """feedback の記録後に呼ぶ。探し直すなら run を作って run_id を返す。

    👎のときだけ判定する（👍で過半数の👎が新たに成り立つことはない）。

    **失敗しても feedback の記録は取り消さない。** feedback はもう保存されていて、
    探し直しはそれに付随する動作にすぎない。例外はログに残して None を返す。
    """
    settings = get_settings()
    if reaction != Reaction.DISLIKE or not settings.auto_explore_on_feedback:
        return None
    try:
        with _start_lock:
            now = now or datetime.now(UTC)
            expire_abandoned_runs(db, user_id, now, settings)
            decision = decide_after_feedback(db, user_id, now, settings)
            return _start(db, user_id, decision) if decision else None
    except Exception as exc:
        db.rollback()
        logger.error(
            "auto_explore.failed user_id=%s trigger=feedback %s", user_id, describe_exception(exc)
        )
        return None


def start_on_tick(db: Session, user_id: str, now: datetime | None = None) -> str | None:
    """定期チェックで呼ぶ。始めるなら run を作って run_id を返す（実行は呼び出し側）。

    例外はそのまま上げる。呼び出し側（agent/scheduler.py）がログに残して次の人へ進む。
    """
    settings = get_settings()
    if not settings.auto_explore_schedule:
        return None
    with _start_lock:
        now = now or datetime.now(UTC)
        expire_abandoned_runs(db, user_id, now, settings)
        decision = decide_on_tick(db, user_id, now, settings)
        return _start(db, user_id, decision) if decision else None


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


def _start(db: Session, user_id: str, decision: Decision) -> str:
    run_id = agent_service.create_run(db, user_id, trigger=decision.trigger, reason=decision.reason)
    logger.info("auto_explore.started run_id=%s trigger=%s", run_id, decision.trigger)
    return run_id


# --------------------------------------------------------------------------
# run の状態と日時
# --------------------------------------------------------------------------


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


def _naive(value: datetime) -> datetime:
    """SQL の比較に渡す形。**DB は tz なしの UTC で持っている。**

    tz 付きのまま渡すと、SQLite ではタイムゾーンを落とした文字列で比べられ、
    UTC 以外の時刻だとずれる。
    """
    return value.astimezone(UTC).replace(tzinfo=None)
