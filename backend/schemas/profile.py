"""UserProfile スキーマ。

「その人がどんな人なのか」だけを持つ。
Agent が学習した内容（search_directions / preferences / insights）は
Agent Memory 側で別管理する。
"""

from pydantic import BaseModel


class UserProfileUpsert(BaseModel):
    """PUT /api/profile のリクエスト。

    **初回フォームの 4 項目は name / wants_now / future_goals / location。**
    残りは以前のフォームが送っていた項目で、**送らなければ既存値を保つ**
    （`upsert_profile` が `exclude_unset` で更新する）。
    """

    # 任意。未入力なら空文字。
    name: str = ""
    # **メインの自由入力。今回やってみたいこと。**
    wants_now: str | None = None
    # 任意。長期的な目標。**今回の探索の必須条件にしない。**
    future_goals: str | None = None
    # 「オンライン」も指定できる自由入力。
    location: str | None = None

    # --- 以前のフォームの項目。初回フォームには出さない ------------------
    # **省略すると既存値が残る。** 空で送ると消えるので、画面からは送らない。
    languages: list[str] | None = None
    occupation: str | None = None
    skills: list[str] | None = None
    experience: list[str] | None = None
    interests: list[str] | None = None
    goals: list[str] | None = None
    about: str | None = None


class UserProfileOut(UserProfileUpsert):
    user_id: str


class ProfileUpsertResult(BaseModel):
    user_id: str
