# API 仕様

Base URL: `/api`
起動中は Swagger UI が使える: http://localhost:8000/docs

## レスポンス形式

成功:

```json
{ "success": true, "data": {} }
```

失敗:

```json
{ "success": false, "error": { "code": "ERROR_CODE", "message": "エラー内容" } }
```

| code | status | 意味 |
| --- | --- | --- |
| `NOT_FOUND` | 404 | 対象が存在しない |
| `VALIDATION_ERROR` | 422 | リクエスト形式が不正 |
| `SCHEDULE_UNKNOWN` | 422 | 開催日時が分からないため、Calendar で確認・追加できない |
| `CALENDAR_NOT_CONNECTED` | 503 | Google Calendar と未連携、または連携が切れている（`backend/README.md`） |
| `CALENDAR_ERROR` | 502 | Google Calendar 側のエラー・接続失敗 |
| `NOT_IMPLEMENTED` | 501 | 未実装の機能 |
| `INTERNAL_ERROR` | 500 | 想定外のエラー |

## MVP の基本フロー

```
PUT  /api/profile
      ↓
POST /api/agent/runs                          -> run_id
      ↓
GET  /api/agent/runs/{run_id}                 （completed まで polling）
      ↓
GET  /api/opportunities                       -> TOP3
      ↓
GET  /api/opportunities/{id}
      ↓
POST /api/opportunities/{id}/interest
      ↓
GET  /api/calendar/availability?opportunity_id={id}
      ↓
【ユーザーが外部サイトで登録】
      ↓
POST /api/opportunities/{id}/calendar
      ↓
POST /api/opportunities/{id}/feedback
```

## エンドポイント

| | Endpoint | 状態 |
| --- | --- | --- |
| 1 | `PUT /api/profile` | 実装済み |
| | `GET /api/profile` | 実装済み |
| 2 | `POST /api/agent/runs` | 実装済み |
| 3 | `GET /api/agent/runs/{run_id}` | 実装済み |
| | `GET /api/agent/runs/{run_id}/logs` | 実装済み |
| 4 | `GET /api/opportunities` | 実装済み |
| 5 | `GET /api/opportunities/{opportunity_id}` | 実装済み |
| 6 | `POST /api/opportunities/{opportunity_id}/interest` | 実装済み（Verification 未接続） |
| 7 | `GET /api/calendar/availability` | 実装済み（Google Calendar） |
| 8 | `POST /api/opportunities/{opportunity_id}/calendar` | 実装済み（Google Calendar） |
| 9 | `POST /api/opportunities/{opportunity_id}/feedback` | 実装済み（Reflection 未接続） |
| | `GET /api/health` | 実装済み |

### Agent 実行状態

`GET /api/agent/runs/{run_id}` は Frontend の探索中画面がポーリングする。

`status`: `queued` / `running` / `completed` / `failed`
`current_step`: `analyzing_profile` / `planning` / `searching` / `evaluating` / `verifying` / `completed`

`cost_jpy`: この探索にかかった**見積もり額**。請求額ではない（`backend/ai/cost.py` の単価表を参照）。
`expensive_model_calls`: 高性能モデルを使った回数。**全件を高性能モデルへ投げていない**ことを示す。

どちらも進捗の更新ごとに増える。途中で失敗しても、そこまでの分が残る。

### 日時

すべて ISO 8601 の **UTC**（`2026-10-10T10:00:00Z`）で返す。
表示側のタイムゾーン変換は Frontend が行う（`frontend/src/utils/date.ts`）。
Web から取得できなかった日時は推測せず `null`。

### Calendar（7 / 8）

Backend がユーザーの Google Calendar を読み書きする。連携の手順は `backend/README.md`。

| | 動き |
| --- | --- |
| `GET /api/calendar/availability` | その機会の時間帯に重なる予定を返す。読み取りだけなので自動で呼んでよい |
| `POST /api/opportunities/{id}/calendar` | 予定を追加し、`status` を `registered`（次の一歩）にする。**ユーザーが追加内容を見てボタンを押したときだけ呼ぶ**。この操作を承認として扱う |

- 時間帯は `start_at`〜`end_at`。**`end_at` が無いときは仮に 1 時間**で、予定の説明にも「仮」と書く
- `start_at` が `null` の機会は確認も追加もしない（`SCHEDULE_UNKNOWN`）。推測で埋めない
- 予定に入れるのはタイトル・日時・場所・公式ページの URL だけ。AI の評価（`score` / `reason`）は入れない
- 同じ機会は何度押しても 1 件。2 回目以降の `status` は `already_exists`（`created` / `already_exists`）
- `conflicts` に含めないもの: 「予定なし」にした予定、辞退した招待、この機会についてすでに入れた予定
- 追加に失敗したときは `status` を変えない。`attended` の機会は `registered` に戻さない

## Schema の対応

| 定義 | Backend | Frontend |
| --- | --- | --- |
| UserProfile | `backend/schemas/profile.py` | `frontend/src/types/profile.ts` |
| Opportunity | `backend/schemas/opportunity.py` | `frontend/src/types/opportunity.ts` |
| AgentRun | `backend/schemas/agent.py` | `frontend/src/types/agent.ts` |
| Calendar | `backend/schemas/calendar.py` | `frontend/src/types/calendar.ts` |
| AI 各処理 I/O | `backend/ai/schemas/` | — |

**フィールド名・型がズレないよう、変更するときは必ず両方を同時に直して共有する。**
