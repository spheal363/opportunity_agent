from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import current_user_id
from api.errors import NotFound
from db.session import get_db
from schemas.calendar import CalendarEventCreated
from schemas.common import ApiSuccess, ok
from schemas.feedback import FeedbackCreate, FeedbackResult
from schemas.opportunity import InterestResult, OpportunityDetail, OpportunitySummary
from services import calendar_service, opportunity_service

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=ApiSuccess[list[OpportunitySummary]])
def list_opportunities(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    """Agent が推薦した Opportunity。MVP では TOP3 を返す。"""
    return ok(opportunity_service.list_recommended(db, user_id))


@router.get("/{opportunity_id}", response_model=ApiSuccess[OpportunityDetail])
def get_opportunity(opportunity_id: str, db: Session = Depends(get_db)) -> dict:
    detail = opportunity_service.get_detail(db, opportunity_id)
    if detail is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(detail)


@router.post("/{opportunity_id}/interest", response_model=ApiSuccess[InterestResult])
def mark_interested(opportunity_id: str, db: Session = Depends(get_db)) -> dict:
    result = opportunity_service.mark_interested(db, opportunity_id)
    if result is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(result)


@router.post("/{opportunity_id}/calendar", response_model=ApiSuccess[CalendarEventCreated])
def add_to_calendar(opportunity_id: str, db: Session = Depends(get_db)) -> dict:
    """ユーザーの確認後に Calendar へ予定を追加する。"""
    result = calendar_service.add_event(db, opportunity_id)
    if result is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(result)


@router.post("/{opportunity_id}/feedback", response_model=ApiSuccess[FeedbackResult])
def post_feedback(
    opportunity_id: str,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    if not opportunity_service.record_feedback(db, opportunity_id, payload, user_id):
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(FeedbackResult(opportunity_id=opportunity_id))
