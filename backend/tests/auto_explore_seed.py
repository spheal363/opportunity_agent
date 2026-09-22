"""自動探索のテストで使う、DB に置く行と設定（#84 / #85）。

判定は日時で決まるので、run の作成時刻は必ず明示する（`NOW` からの差で書く）。
"""

from datetime import UTC, datetime, timedelta

from config import Settings
from models import DEFAULT_USER_ID, AgentRun, Feedback, Opportunity, UserProfile
from schemas.agent import AgentRunStatus, AgentRunTrigger
from schemas.opportunity import OpportunityStatus

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
USER = DEFAULT_USER_ID


def settings(**overrides) -> Settings:
    """.env を読まない設定。**上限は既定値のまま**にして、既定が効くことも確かめる。"""
    return Settings(_env_file=None, **overrides)


def ago(**delta) -> datetime:
    """NOW から遡った時刻。DB と同じく tz なしの UTC で返す。"""
    return (NOW - timedelta(**delta)).replace(tzinfo=None)


def add_profile(db, user_id: str = USER) -> None:
    db.add(UserProfile(user_id=user_id, name="Naoya", goals=["Build AI products"]))
    db.commit()


def add_run(
    db,
    run_id: str,
    *,
    created: datetime,
    status: AgentRunStatus = AgentRunStatus.COMPLETED,
    trigger: AgentRunTrigger = AgentRunTrigger.MANUAL,
    selected: list[str] | None = None,
    cost: float = 0.0,
    updated: datetime | None = None,
    user_id: str = USER,
) -> None:
    db.add(
        AgentRun(
            run_id=run_id,
            user_id=user_id,
            status=status,
            trigger=trigger,
            selected_ids=selected,
            cost_jpy=cost,
            created_at=created,
            updated_at=updated or created,
        )
    )
    db.commit()


def add_opp(
    db,
    oid: str,
    *,
    status: OpportunityStatus = OpportunityStatus.RECOMMENDED,
    availability: str = "unknown",
    deadline: datetime | None = None,
    end_at: datetime | None = None,
    type_: str = "event",
    user_id: str = USER,
) -> None:
    db.add(
        Opportunity(
            opportunity_id=oid,
            user_id=user_id,
            type=type_,
            title=f"{oid} のタイトル",
            status=status,
            availability=availability,
            deadline=deadline,
            end_at=end_at,
            # 時刻まで書かれていた締切として扱う（日付だけだと当日中は切れない）
            deadline_is_date_only=False,
            end_at_is_date_only=False,
            deadline_kind="application" if deadline else None,
        )
    )
    db.commit()


def add_dislike(db, oid: str, user_id: str = USER) -> None:
    db.add(Feedback(user_id=user_id, opportunity_id=oid, reaction="dislike"))
    db.commit()
