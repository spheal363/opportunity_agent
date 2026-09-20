"""Opportunity の取得・状態遷移。"""

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, Feedback, Opportunity
from schemas.feedback import FeedbackCreate
from schemas.opportunity import (
    InterestResult,
    OpportunityDetail,
    OpportunityStatus,
    OpportunitySummary,
)

# MVP では TOP3 を返す。
TOP_N = 3

# ユーザーに提示済みとみなすステータス。
_VISIBLE = (
    OpportunityStatus.RECOMMENDED,
    OpportunityStatus.INTERESTED,
    OpportunityStatus.REGISTERED,
    OpportunityStatus.ATTENDED,
)


def list_recommended(
    db: Session, user_id: str = DEFAULT_USER_ID, limit: int | None = None
) -> list[OpportunitySummary]:
    """ユーザーに提示済みの候補。**保存一覧・次の一歩の母集合。**

    **件数を絞らない。** 絞ると、保存した候補が 4 件目以降にあるときに
    保存一覧から消える。今回の選定は
    `GET /api/agent/runs/{run_id}/result` が別に返す。
    """
    query = (
        db.query(Opportunity)
        .filter(
            Opportunity.user_id == user_id,
            Opportunity.status.in_([s.value for s in _VISIBLE]),
        )
        .order_by(Opportunity.score.desc())
    )
    rows = (query.limit(limit) if limit else query).all()
    return [OpportunitySummary.model_validate(r, from_attributes=True) for r in rows]


def get_detail(db: Session, opportunity_id: str) -> OpportunityDetail | None:
    row = db.get(Opportunity, opportunity_id)
    if row is None:
        return None
    return OpportunityDetail.model_validate(row, from_attributes=True)


def mark_interested(db: Session, opportunity_id: str) -> InterestResult | None:
    """「参加したい」。

    status を interested にする。
    TODO(agent): ここで Verification（公式ページの再取得と差分確認）を実行する。
    外部サービスへの登録は Agent が代行せず、登録ページへの誘導までを担当する。
    """
    row = db.get(Opportunity, opportunity_id)
    if row is None:
        return None
    row.status = OpportunityStatus.INTERESTED
    db.commit()
    return InterestResult(
        opportunity_id=row.opportunity_id,
        status=OpportunityStatus(row.status),
        verified=row.verified,
        registration_url=row.url,
    )


def record_feedback(
    db: Session,
    opportunity_id: str,
    payload: FeedbackCreate,
    user_id: str = DEFAULT_USER_ID,
) -> bool:
    row = db.get(Opportunity, opportunity_id)
    if row is None:
        return False
    db.add(
        Feedback(
            user_id=user_id,
            opportunity_id=opportunity_id,
            reaction=payload.reaction,
            attended=payload.attended,
            outcome_score=payload.outcome_score,
        )
    )
    if payload.attended:
        row.status = OpportunityStatus.ATTENDED
    elif payload.reaction == "dislike":
        row.status = OpportunityStatus.DISMISSED
    db.commit()
    # TODO(agent): Reflection を実行して Agent Memory を更新する。
    return True
