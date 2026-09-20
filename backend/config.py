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

    # --- 検索と本文取得 ------------------------------------------------
    # **別々に選ぶ。** Serper は検索だけで本文を返さないため、検索 provider を
    # 変えただけでは抽出の入力が痩せる（#65）。
    #
    # 既定値は比較で採用が決まるまで**現行構成のまま**にする。
    search_provider: str = "tavily"  # tavily | serper
    page_fetcher: str = "tavily"  # tavily | jina

    # 応答に実費（usage.cost_usd）を載せてもらうヘッダを送るか。
    # **モデルの挙動は変わらない。** 既定は無効にしてあり、比較のときだけ
    # 有効にする。見積もりと実費は別々に記録する（#65）。
    orcarouter_include_cost: bool = False

    search_api_key: str | None = None  # Tavily
    serper_api_key: str | None = None
    # 日本語のイベントを探す用途に合わせる。英語圏の既定のままだと比較が用途とずれる。
    serper_gl: str = "jp"
    serper_hl: str = "ja"
    # Jina Reader は**キー無しでも動く**（20 RPM）。キーがあると 500 RPM。
    jina_api_key: str | None = None

    # --- 評価器 ----------------------------------------------------------
    # EVALUATOR=llm   既定・現行。自由文の match_reasons も出る
    # EVALUATOR=jev   分類・採点のみ。**自由文は作れない**（#65 の A/B 比較）
    evaluator: str = "llm"
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai/v1"
    jev_model: str = "jev-latest"
    # これを下回る confidence は既存 LLM へ回す。
    # **confidence は正解率ではない**（公式が明記）。分布の尖り具合でしかない
    # ので、閾値は「迷っているものを人手/LLM に回す」ための運用値として扱う。
    jev_min_confidence: float = 0.5

    # --- 探索の構成 ------------------------------------------------------
    # SEARCH_PIPELINE=full       既定・現行。見つけた候補を全件抽出して評価
    # SEARCH_PIPELINE=prefilter  抽出前に読む優先順位を付ける（構成 C）
    search_pipeline: str = "full"
    # 本文を読む候補の数。**仮説であって正解ではない。** 比較で決める。
    prefilter_read_limit: int = 8
    # 不足したときに追加で読む上限。無制限には増やさない。
    prefilter_extra_reads: int = 4

    google_client_id: str | None = None
    google_client_secret: str | None = None

    # LLM を呼ばずモックデータで Agent Loop を流すモード。
    agent_stub_mode: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_url.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
