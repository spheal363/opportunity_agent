from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.errors import NotFound
from db.session import get_db
from schemas.calendar import CalendarAvailability
from schemas.common import ApiSuccess, ok
from services import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/availability", response_model=ApiSuccess[CalendarAvailability])
def check_availability(opportunity_id: str, db: Session = Depends(get_db)) -> dict:
    result = calendar_service.check_availability(db, opportunity_id)
    if result is None:
        raise NotFound("指定された Opportunity が見つかりません")
    return ok(result)
