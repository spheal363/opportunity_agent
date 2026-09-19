---
paths:
  - "backend/**/*.py"
---

# Backend の書き方

構成と各ディレクトリの役割は `backend/README.md`。API 一覧は `docs/api.md`。

## 必ず守る

- **レスポンスは封筒形式**。`schemas/common.py` の `ok()` を使い、
  route には `response_model=ApiSuccess[T]` を付ける。手書きで dict を組まない。
- **エラーは `api/errors.py` の `ApiError` / `NotFound` を raise する。**
  `HTTPException` を直接使わない。未実装は `NotImplementedError`（501 に変換される）。
- **DB アクセスは `Depends(get_db)`。** route や service 内で `SessionLocal()` を直接作らない。
  例外は Agent Loop（リクエストの寿命に縛られないため自前でセッションを持つ）。
- **日時は UTC + tz 付きで返す。** `schemas/opportunity.py` の `Timestamp` を使う。
  naive な datetime を API レスポンスに載せない（Frontend が 9 時間ズレて解釈する）。
- **Secret を Log に出さない。** API Key、`.env` の値、プロフィール本文を `logger` へ渡さない。

## import

`backend/` を起点にする。`from schemas.opportunity import ...`、`from services import ...`。
相対 import（`from ..schemas import`）を使わない。

## テスト

`tests/conftest.py` の `client` fixture を使う。`clean_db` が毎テスト DB を作り直すので、
テスト間で状態を共有しない。API を足したら最低 1 本、正常系とエラー系を書く。

## 変更後

```bash
.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/pytest -q
```
