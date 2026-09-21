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
    # **既定は構成 C（暫定採用）。** 比較の根拠は
    # docs/experiments/65-search-comparison.md。
    #
    # A へ戻すには 4 つとも戻す（`.env` か環境変数）:
    #   SEARCH_PROVIDER=tavily PAGE_FETCHER=tavily
    #   EVALUATOR=llm SEARCH_PIPELINE=full
    search_provider: str = "serper"  # tavily | serper
    page_fetcher: str = "jina"  # tavily | jina

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
    # EVALUATOR=llm   自由文の match_reasons も出る（構成 A）
    # EVALUATOR=jev   **既定。** 分類・採点のみで、**自由文は作れない**
    evaluator: str = "jev"  # llm | jev
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai/v1"
    jev_model: str = "jev-latest"
    # これを下回る confidence は既存 LLM へ回す。
    # **confidence は正解率ではない**（公式が明記）。分布の尖り具合でしかない
    # ので、閾値は「迷っているものを人手/LLM に回す」ための運用値として扱う。
    jev_min_confidence: float = 0.5

    # --- 探索の構成 ------------------------------------------------------
    # SEARCH_PIPELINE=full       候補を全件抽出して評価（構成 A）
    # SEARCH_PIPELINE=prefilter  **既定。** 抽出前に読む優先順位を付ける
    search_pipeline: str = "prefilter"  # full | prefilter
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


# 構成ごとに要る鍵。**足りなければ黙って別構成へ落とさない。**
#
# 以前は鍵が無いと検索が方向ごとに失敗し、候補 0 件で終わっていた。
# 「何も見つからなかった」と「鍵が無い」は別のこと。
_REQUIRED_KEYS = {
    "search_provider": {
        "tavily": ("search_api_key", "SEARCH_API_KEY"),
        "serper": ("serper_api_key", "SERPER_API_KEY"),
    },
    "evaluator": {"jev": ("typesafe_api_key", "TYPESAFE_API_KEY")},
}

# A へ戻すときの設定。エラー文に載せる。
FALLBACK_TO_A = "SEARCH_PROVIDER=tavily PAGE_FETCHER=tavily EVALUATOR=llm SEARCH_PIPELINE=full"


def missing_keys(settings: "Settings") -> list[str]:
    """いまの構成に足りない鍵。**空なら走らせてよい。**

    `page_fetcher=jina` は鍵が無くても動く（20 RPM）ので、ここには挙げない。
    """
    missing: list[str] = []
    for field, table in _REQUIRED_KEYS.items():
        chosen = (getattr(settings, field) or "").strip().lower()
        need = table.get(chosen)
        if need and not getattr(settings, need[0]):
            missing.append(f"{need[1]}（{field}={chosen} に必要）")
    return missing


class ConfigurationError(RuntimeError):
    """構成に足りないものがある。**別構成へは落とさない。**"""


@lru_cache
def get_settings() -> Settings:
    return Settings()
