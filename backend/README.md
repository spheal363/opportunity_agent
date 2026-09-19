# Backend

Python + FastAPI + Pydantic + SQLAlchemy。担当: Naoya

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn main:app --reload --port 8000
```

- Health check: http://localhost:8000/api/health
- Swagger UI: http://localhost:8000/docs

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

## 構成

```
backend/
├── api/         Frontend から呼ぶ REST API
│   ├── routes/  health / profile / agent / opportunities / calendar
│   ├── errors.py  エラー封筒の統一
│   └── deps.py    current_user_id（認証を入れるときはここだけ差し替える）
├── agent/       Agent Loop / Agent State / Stub Data
├── ai/          Prompt と AI 各処理の Input/Output Schema
├── tools/       search_web / read_page / calendar（権限レベル付き）
├── models/      SQLAlchemy ORM
├── schemas/     API の Pydantic Schema
├── services/    Application Logic
├── db/          接続・初期化
└── tests/
```

`main:app` を `backend/` から起動する前提（import は `from schemas... ` のようにトップレベル）。

## AGENT_STUB_MODE

`.env` の `AGENT_STUB_MODE=true` の間は LLM / Web Search を呼ばず、
`agent/stub_data.py` の固定データで Agent Loop を流す。
Frontend がこの段階から通しで結合できるようにするためのもの。

実装する順序は `agent/loop.py` の各 `_step_*`:

1. `_analyze_goal` — ① Goal Analysis
2. `_plan_search` — ② Search Planning
3. `_search_and_extract` — Web Search Tool + ③ Extraction
4. `_evaluate_and_select` — ④ Evaluation + ⑤ TOP3 + ⑥ Recommendation
5. `_verify` — ⑦ Verification

LLM の出力は `ai/schemas/` の Pydantic モデルで Validation し、不正なら Retry する。

## 注意

- Web から取得した内容は Untrusted Data。`ToolResult.external=True` を付ける
- 取得できなかった事実は推測で補完せず `null`
- API Key / 個人情報を Log へ出さない
- `schemas/` を変更したら `frontend/src/types/` も同時に直して共有する
