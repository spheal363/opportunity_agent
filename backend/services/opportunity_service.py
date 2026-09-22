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
    rows = _ordered(rows)
    return [OpportunitySummary.model_validate(r, from_attributes=True) for r in rows]


# 日付が分からない候補を後ろへ回すための値。**架空の日付を入れない。**
_NO_DATE = "9999-99-99"


def _ordered(rows: list[Opportunity]) -> list[Opportunity]:
    """並び順。**未評価の候補に点数順を使わない（#47）。**

    評価済みだけなら従来どおり点数順。1 件でも未評価があるなら
    **ジャンル（希望）別・日付順**にする。評価は一覧表示の必須処理ではない。
    """
    if rows and all(bool(getattr(r, "evaluated", False)) for r in rows):
        return rows
    return sorted(
        rows,
        key=lambda r: (
            r.wish or "",
            r.start_at.date().isoformat() if r.start_at else _NO_DATE,
            r.title or "",
        ),
    )


def get_owned(db: Session, opportunity_id: str, user_id: str) -> Opportunity | None:
    """その人の Opportunity だけを返す（#69）。他人のものは存在しないのと同じに扱う。

    id を知っていれば誰のものでも読める・書ける状態にしない（IDOR）。
    MVP は単一ユーザーなので今は挙動が変わらないが、認証を入れた時点で
    `current_user_id` を差し替えるだけで効くようにしておく。
    **403 ではなく 404** にするのは、他人の id が存在するかを漏らさないため。
    """
    row = db.get(Opportunity, opportunity_id)
    if row is None or row.user_id != user_id:
        return None
    return row


def get_detail(db: Session, opportunity_id: str, user_id: str) -> OpportunityDetail | None:
    row = get_owned(db, opportunity_id, user_id)
    if row is None:
        return None
    return OpportunityDetail.model_validate(row, from_attributes=True)


def mark_interested(db: Session, opportunity_id: str, user_id: str) -> InterestResult | None:
    """「参加したい」。

    status を interested にする。
    TODO(agent): ここで Verification（公式ページの再取得と差分確認）を実行する。
    外部サービスへの登録は Agent が代行せず、登録ページへの誘導までを担当する。
    """
    row = get_owned(db, opportunity_id, user_id)
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
    row = get_owned(db, opportunity_id, user_id)
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
    # Reflection（Feedback から Agent Memory を更新する）はここでは行わない。
    # 次の run の冒頭で行う（agent/reflection.py）。
    # 👎が重なったときに探し直すかどうかは services/auto_explore.py が決める。
    return True
