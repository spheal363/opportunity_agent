from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import current_user_id
from api.errors import NotFound
from db.session import get_db
from schemas.common import ApiSuccess, ok
from schemas.profile import ProfileUpsertResult, UserProfileOut, UserProfileUpsert
from services import profile_service

router = APIRouter(prefix="/profile", tags=["profile"])


@router.put("", response_model=ApiSuccess[ProfileUpsertResult])
def upsert_profile(
    payload: UserProfileUpsert,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    saved_id = profile_service.upsert_profile(db, payload, user_id)
    return ok(ProfileUpsertResult(user_id=saved_id))


@router.get("", response_model=ApiSuccess[UserProfileOut])
def get_profile(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    profile = profile_service.get_profile(db, user_id)
    if profile is None:
        raise NotFound("プロフィールが登録されていません")
    return ok(profile)
