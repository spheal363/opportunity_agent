"""UserProfile の保存・取得。"""

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, UserProfile
from schemas.profile import UserProfileOut, UserProfileUpsert


def upsert_profile(db: Session, payload: UserProfileUpsert, user_id: str = DEFAULT_USER_ID) -> str:
    row = db.get(UserProfile, user_id)
    if row is None:
        row = UserProfile(user_id=user_id)
        db.add(row)
    # **送られた項目だけ更新する。** 初回フォームは 4 項目しか送らないので、
    # 全項目を代入すると以前の入力（興味タグ・自己紹介など）が消える。
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    # 名前は任意。**未入力でも保存できる。** 列は NOT NULL なので空文字にする。
    if row.name is None:
        row.name = ""
    db.commit()
    return user_id


def get_profile(db: Session, user_id: str = DEFAULT_USER_ID) -> UserProfileOut | None:
    row = db.get(UserProfile, user_id)
    if row is None:
        return None
    return UserProfileOut(
        user_id=row.user_id,
        name=row.name,
        # **旧データの引き継ぎ。推測で分割・書き換えはしない。**
        # `wants_now` がまだ無いプロフィールでは、以前の `goals` を
        # そのまま本文として見せる。編集画面で内容が消えないようにするため。
        wants_now=row.wants_now if row.wants_now is not None else _legacy_text(row.goals),
        future_goals=row.future_goals,
        location=row.location,
        languages=row.languages or [],
        occupation=row.occupation,
        skills=row.skills or [],
        experience=row.experience or [],
        interests=row.interests or [],
        goals=row.goals or [],
        about=row.about,
    )


def _legacy_text(goals: list | None) -> str | None:
    """以前の `goals`（配列）を、編集欄に出せる 1 つの本文にする。

    **並べ替えも要約も分割もしない。** 行を改行でつなぐだけ。
    「いま」と「将来」の切り分けは本人が編集して決める。
    """
    items = [str(g).strip() for g in (goals or []) if str(g).strip()]
    return "\n".join(items) or None
