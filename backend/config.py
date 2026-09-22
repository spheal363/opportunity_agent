"""アプリ全体の設定。値は .env から読み込む（.env.example を参照）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./opportunity_agent.db"

    # CORS 許可 Origin。カンマ区切りで複数指定できる。
    frontend_url: str = "http://localhost:5173"

    orcarouter_api_key: str | None = None
    orcarouter_base_url: str | None = None
    llm_model_cheap: str | None = None
    llm_model_standard: str | None = None
    llm_model_powerful: str | None = None

    search_api_key: str | None = None

    google_client_id: str | None = None
    google_client_secret: str | None = None
    # scripts/google_auth.py が書き出すトークン。リフレッシュトークンを含む Secret。
    # backend/ からの相対パス。.gitignore 済み。
    google_token_path: str = ".google_token.json"

    # LLM を呼ばずモックデータで Agent Loop を流すモード。
    agent_stub_mode: bool = True

    # 攻撃を仕込んだページを検索結果に 1 件混ぜる（Prompt Injection のデモ, #52）。
    # 検知と除去は本番と同じコードが行う。本番の探索では false のまま。
    demo_injection: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_url.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
