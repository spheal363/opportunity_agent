"""UserProfile の保存・取得。"""

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, UserProfile
from schemas.profile import UserProfileOut, UserProfileUpsert


def upsert_profile(
    db: Session, payload: UserProfileUpsert, user_id: str = DEFAULT_USER_ID
) -> str:
    row = db.get(UserProfile, user_id)
    if row is None:
        row = UserProfile(user_id=user_id)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return user_id


def get_profile(db: Session, user_id: str = DEFAULT_USER_ID) -> UserProfileOut | None:
    row = db.get(UserProfile, user_id)
    if row is None:
        return None
    return UserProfileOut(
        user_id=row.user_id,
        name=row.name,
        location=row.location,
        languages=row.languages or [],
        occupation=row.occupation,
        skills=row.skills or [],
        experience=row.experience or [],
        interests=row.interests or [],
        goals=row.goals or [],
        about=row.about,
    )
