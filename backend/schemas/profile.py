"""UserProfile スキーマ。

「その人がどんな人なのか」だけを持つ。
Agent が学習した内容（search_directions / preferences / insights）は
Agent Memory 側で別管理する。
"""

from pydantic import BaseModel, Field


class UserProfileUpsert(BaseModel):
    """PUT /api/profile のリクエスト。MVP の初回登録画面で入力する項目。"""

    name: str
    location: str | None = None
    languages: list[str] = Field(default_factory=list)
    occupation: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    about: str | None = None


class UserProfileOut(UserProfileUpsert):
    user_id: str


class ProfileUpsertResult(BaseModel):
    user_id: str
