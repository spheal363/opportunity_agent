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

## Google Calendar 連携

空き確認（`GET /api/calendar/availability`）と予定追加（`POST /api/opportunities/{id}/calendar`）に使う。
Backend を動かす人ごとに、自分の Google アカウントで 1 回だけ連携する。

1. Google Cloud の OAuth クライアント（種類は**デスクトップアプリ**）の ID とシークレットを
   `.env` の `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` に入れる。
   チーム内では git ではなく DM などで受け渡す
2. 使う Google アカウントを、OAuth 同意画面の**テストユーザー**に追加してもらう
3. 連携スクリプトを実行し、ブラウザで Google にログインして「許可」を押す

```bash
.venv/bin/python -m scripts.google_auth
# ブラウザが開かないとき（WSL など）は、表示された URL を手元のブラウザで開く
.venv/bin/python -m scripts.google_auth --no-browser
```

トークンが `GOOGLE_TOKEN_PATH`（既定 `.google_token.json`）に保存される。
Backend はこれを読み、アクセストークンの期限切れ（約 1 時間）は自分で取り直す。

- **トークンは人に渡さない。** カレンダーへ書き込める権限そのもの。`.gitignore` 済み
- テスト公開中のアプリでは**リフレッシュトークンが 7 日で失効する**。
  API が `CALENDAR_NOT_CONNECTED` を返したら、スクリプトをもう一度実行する（Backend の再起動は不要）
- 使うスコープは `calendar.events` だけ（予定の読み取りと追加）。
  記事のサンプルなどで作った読み取り専用のトークンは使えないので、作り直す
- 未連携でもアプリは動く。カレンダーの確認・追加だけが「未連携」と表示される

## 注意

- Web から取得した内容は Untrusted Data。`ToolResult.external=True` を付ける
- 取得できなかった事実は推測で補完せず `null`
- API Key / 個人情報を Log へ出さない
- `schemas/` を変更したら `frontend/src/types/` も同時に直して共有する
