from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import current_user_id
from api.errors import NotFound
from db.session import get_db
from schemas.calendar import CalendarAvailability, CalendarEventPreview
from schemas.common import ApiSuccess, ok
from services import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/availability", response_model=ApiSuccess[CalendarAvailability])
def check_availability(
    opportunity_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    result = calendar_service.check_availability(db, opportunity_id, user_id)
    if result is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(result)


@router.get("/preview", response_model=ApiSuccess[CalendarEventPreview])
def preview_event(
    opportunity_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    """登録する内容だけを返す。**Google へは触らない。**

    空き確認（`/availability`）は Google を呼ぶので、未連携だとそこで止まる。
    そのとき確認内容まで出せなくなると、ユーザーは「何が登録されるのか」を
    見られないまま連携を求められることになる。**確認と空き確認を分ける。**
    """
    result = calendar_service.preview(db, opportunity_id, user_id)
    if result is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(result)
