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
| `NOT_IMPLEMENTED` | 501 | 未実装の機能（Calendar など） |
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
| | `GET /api/agent/runs/{run_id}/result` | 実装済み（**この run の最終選定**） |
| 4 | `GET /api/opportunities` | 実装済み |
| 5 | `GET /api/opportunities/{opportunity_id}` | 実装済み |
| 6 | `POST /api/opportunities/{opportunity_id}/interest` | 実装済み（Verification 未接続） |
| 7 | `GET /api/calendar/availability` | 未実装（501） |
| 8 | `POST /api/opportunities/{opportunity_id}/calendar` | 未実装（501） |
| 9 | `POST /api/opportunities/{opportunity_id}/feedback` | 実装済み（Reflection 未接続） |
| | `GET /api/health` | 実装済み |

### Agent 実行状態

`GET /api/agent/runs/{run_id}` は Frontend の探索中画面がポーリングする。

`status`: `queued` / `running` / `completed` / `failed`
`current_step`: `analyzing_profile` / `planning` / `searching` / `evaluating` / `verifying` / `completed`

`cost_jpy`: この探索にかかった**見積もり額**。請求額ではない（`backend/ai/cost.py` の単価表を参照）。
`expensive_model_calls`: 高性能モデルを使った回数。**全件を高性能モデルへ投げていない**ことを示す。

どちらも進捗の更新ごとに増える。途中で失敗しても、そこまでの分が残る。

### 今回の選定結果と保存一覧は別経路

**混同しない。**

| | 返すもの |
| --- | --- |
| `GET /api/agent/runs/{run_id}/result` | **その run が選んだものを順位順**。3 件に満たないことがある |
| `GET /api/opportunities` | ユーザーに提示済みの候補すべて。**保存一覧・次の一歩の母集合**。件数を絞らない |

`Opportunity.run_id` は同じ URL を再発見すると上書きされるため、過去 run の
選定結果は保てない。選定は `AgentRun.selected_ids` に順位順で持つ。

**保証するのは「どれをどの順で選んだか」だけ。** 候補の内容は最新値で、
選定時点の本文を保存するものではない。

`result` の状態:

```
recorded=false, status=running   まだ探索中
recorded=false, status=completed 結果の記録が無い（列を足す前の古い run）
recorded=true,  selected=[]      完了したが 0 件。shortfall_reason に理由
404                              その run が存在しない
```

### 受付状況（availability）

**`verified` とは別の軸。**

| | 意味 |
| --- | --- |
| `verified` | その情報を公式ページで**確認できたか** |
| `availability` | いま**応募・参加できるか** |

確認できたうえで受付終了、ということがある。

```
open     受付中を**確認できた**。参加資格や空き枠までは保証しない
closed   受付終了・開催終了を**確認できた**
unknown  どちらとも確認できていない
```

**締切が未来というだけで `open` にしない**（満員かもしれない）。
`deadline` が `null` は「受付終了でも受付中でもない」ので `unknown`。

`availability_checked_at` と必ず対で読む。**再確認に失敗したときに古い
`open` を今の状態として扱わない**ため。

### 日時

すべて ISO 8601 の **UTC**（`2026-10-10T10:00:00Z`）で返す。
表示側のタイムゾーン変換は Frontend が行う（`frontend/src/utils/date.ts`）。
Web から取得できなかった日時は推測せず `null`。

## Schema の対応

| 定義 | Backend | Frontend |
| --- | --- | --- |
| UserProfile | `backend/schemas/profile.py` | `frontend/src/types/profile.ts` |
| Opportunity | `backend/schemas/opportunity.py` | `frontend/src/types/opportunity.ts` |
| AgentRun | `backend/schemas/agent.py` | `frontend/src/types/agent.ts` |
| Calendar | `backend/schemas/calendar.py` | `frontend/src/types/calendar.ts` |
| AI 各処理 I/O | `backend/ai/schemas/` | — |

**フィールド名・型がズレないよう、変更するときは必ず両方を同時に直して共有する。**
