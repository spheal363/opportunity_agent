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
| `FORBIDDEN` | 403 | 画面以外からの操作（`X-Requested-With` が無い）。状態を変える API（POST / PUT）すべてで使う |
| `SCHEDULE_UNKNOWN` | 422 | 開催日時が分からないため、Calendar で確認・追加できない |
| `CALENDAR_NOT_CONNECTED` | 503 | Google Calendar と未連携、または連携が切れている（`backend/README.md`） |
| `CALENDAR_ERROR` | 502 | Google Calendar 側のエラー・接続失敗 |
| `NOT_IMPLEMENTED` | 501 | 未実装の機能 |
| `INTERNAL_ERROR` | 500 | 想定外のエラー |

## 状態を変える API のヘッダー

**POST / PUT はすべて `X-Requested-With: opportunity-agent` ヘッダーが必須**（無ければ `FORBIDDEN`）。
GET は不要。

body の無い POST や `text/plain` の POST は、別サイトの form や fetch からブラウザの
事前確認（preflight）なしに送れてしまう。独自ヘッダーを付けた要求はブラウザが事前確認し、
許可していない Origin は CORS で止まる。探索の開始（`POST /api/agent/runs`）は LLM の費用が
かかるため、別サイトを開いただけで走らせられないようにしている（#80）。
Frontend は `src/api/client.ts` で全リクエストに付けている。

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
POST /api/opportunities/{id}/detail-check   -> 選んだ 1 件だけ出典で確認
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
| | `GET /api/agent/runs` | 実装済み（現在のユーザーの探索履歴） |
| 3 | `GET /api/agent/runs/{run_id}` | 実装済み |
| | `GET /api/agent/runs/latest` | 実装済み（現在のユーザーの最新 run。無ければ `data: null`） |
| | `GET /api/agent/runs/{run_id}/logs` | 実装済み |
| | `GET /api/agent/runs/{run_id}/result` | 実装済み（**この run の最終選定**） |
| 4 | `GET /api/opportunities` | 実装済み |
| 5 | `GET /api/opportunities/{opportunity_id}` | 実装済み |
| 6 | `POST /api/opportunities/{opportunity_id}/interest` | 実装済み（Verification 未接続） |
| 6-b | `POST /api/opportunities/{opportunity_id}/detail-check` | 実装済み（#47）|
| 7 | `GET /api/calendar/availability` | 実装済み（Google Calendar） |
| 8 | `POST /api/opportunities/{opportunity_id}/calendar` | 実装済み（Google Calendar） |
| 9 | `POST /api/opportunities/{opportunity_id}/feedback` | 実装済み（次の run の冒頭で Reflection に反映。👎が重なると Agent が探し直すことがある。「自動探索」） |
| | `GET /api/health` | 実装済み |

### Agent 実行状態

`POST /api/agent/runs` は、同じユーザーの探索が既に実行中なら、その
`run_id` と現在の `status` を返す。新しい探索や実行タスクは追加しない。
手動・自動の開始判定は共通の排他処理を通す（1 worker 前提）。
進捗が止まった探索の扱いは自動探索と同じ。

`GET /api/agent/runs/{run_id}` は Frontend の探索中画面がポーリングする。

`status`: `queued` / `running` / `completed` / `failed`
`current_step`: `analyzing_profile` / `planning` / `searching` / `evaluating` / `verifying` / `completed`

`cost_jpy`: この探索にかかった**見積もり額**。請求額ではない（`backend/ai/cost.py` の単価表を参照）。
`expensive_model_calls`: 高性能モデルを使った回数。**全件を高性能モデルへ投げていない**ことを示す。

どちらも進捗の更新ごとに増える。途中で失敗しても、そこまでの分が残る。

`trigger`: `manual` / `feedback` / `stale` / `scheduled`（何がきっかけで始まったか。「自動探索」）
`trigger_reason`: Agent が自分で始めた理由。`manual` では `null`。
**決まった文面と数値だけ**で、候補のタイトルなど Web 由来の文は入らない。

列を足す前の run は `trigger=manual` として返る（既存 DB には `DEFAULT 'manual'` で足す）。

### 自動探索（Agent が自分で始める探索）

Agent が「いつ探すか」も自分で決める。**自動にするのは発見だけ**で、
Calendar への追加など外部への操作は人の操作のまま。**既定はすべてオフ**
（`backend/.env.example` の `AUTO_EXPLORE_*`）。判定は `backend/services/auto_explore.py`。

| `trigger` | きっかけ | 判定するとき |
| --- | --- | --- |
| `manual` | ボタン・目標の保存（`POST /api/agent/runs`） | — |
| `feedback` | 最新の完了 run の推薦（2 件以上）のうち、2 件以上かつ過半数に👎（最新の `reaction=dislike`。反応の記録が無い候補は `status=dismissed`）。その run より新しい run が無いとき | 👎を送った直後（`POST .../feedback`） |
| `stale` | 推薦中・保存中（`recommended` / `interested`）で行動できる候補（受付終了でない・締切が過ぎていない）が 3 件を切り、**前回の探索の後に**締切を過ぎた・開催を終えたものが 1 件以上あるとき | 定期チェック |
| `scheduled` | 最後の run（状態は問わない）から設定した時間（既定 24 時間）がたったとき | 定期チェック |

定期チェックは `AUTO_EXPLORE_SCHEDULE=true` のときだけ Backend の起動時に始まり、
`AUTO_EXPLORE_TICK_SECONDS`（既定 300 秒）ごとに判定する。`stale` を先に見る。
**一度も探索していない人には始めない**（最初の探索は本人が始める）。
`stale` の期限切れは「前回の探索の後に」過ぎたものだけを数える。同じ期限切れで
何度も走らせないため。締切の種類の扱いは受付状況（availability）と同じ。

始めた run は最初の Log（`step=analyzing_profile`）に `trigger_reason` と同じ文が入る。
探索中画面の先頭に「なぜ始めたか」が出る。**AgentStep は増やしていない。**

`POST .../feedback` の**レスポンスの形は変えていない。** 探し直したかどうかは返さないので、
画面は👎の後に最新の run を取って確かめる。

**止める仕組み（全自動 trigger に共通。コードが強制する）:**

- 機能フラグが既定オフ。オフなら今の挙動を何も変えない
- 直近 24 時間（暦日ではない）の自動 run の回数上限（既定 3）
- 直近 24 時間の**全 run（手動を含む）**の `cost_jpy` の合計が既定 20 円に達したら新しい自動 run を開始しない（見積もり。実行中の run を中断する上限ではない）
- 自動 run 同士の最低間隔（既定 60 分）
- `queued` / `running` の run があれば始めない。ただし進捗が一定時間（既定 30 分）無いものは
  止まった run とみなし、妨げにしない（決まった文言で `failed` にする。例外の文字列は載せない）
- プロフィールが無ければ始めない
- 同じ run への探し直しは 1 回まで（探し直した run が失敗しても繰り返さない）

#### 最新の run（`GET /api/agent/runs/latest`）

現在のユーザーのいちばん新しい run（状態は問わない）を `AgentRunState` で返す。他人の run は返さない。

**run が 1 件も無いときは 404 ではなく `{"success": true, "data": null}`。**
まだ探索していないのは正常な状態で、アプリが定期的に取りに来るため
（404 だと毎回エラーとして扱うことになる）。

画面はアプリ内（表示時・フォーカス時・30 秒ごと。最新の自動 run が実行中の間は 5 秒ごと）と
👎の後にこれを取る。`trigger` が `manual` 以外で、最後に自分で始めた run とも、
見た・閉じた run とも違えば、`trigger_reason` と「見る」リンク（実行中なら探索中画面、
完了なら結果）を出す。**画面は勝手に移らない。**

### 今回の選定結果と保存一覧は別経路

#### 探索履歴（`GET /api/agent/runs`）

現在のユーザーの手動・自動の全探索を、新しい順に返す。完了・失敗・実行中を含む。
DB の既存記録も対象で、新しい列は追加しない。

- `limit`: 1〜100、既定 20。
- `before`: 前ページの `next_cursor`（run_id）。省略すると最新から。
  他人の run や存在しない run を指定した場合は 404。
- `data`: `{items: AgentRunHistoryEntry[], next_cursor: string | null}`。
- `AgentRunHistoryEntry`: `AgentRunState` に `created_at`（UTC・tz 付き）と
  `selected_count`（記録された選定件数。記録が無い場合は null）を追加した形。
- 日時が同じ場合は run_id の降順で並べ、ページを読む途中で新しい探索が増えても
  古い履歴のページ送りがずれないようにする。

画面の「探索履歴」から、各回の結果と作業記録を開ける。
完了した古い探索に選定記録が無い場合は「結果の記録なし」と表示する。
結果 API も所有者を確認し、他人の探索は 404 にする。

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

### Calendar（7 / 8）

Backend がユーザーの Google Calendar を読み書きする。連携の手順は `backend/README.md`。

| | 動き |
| --- | --- |
| `GET /api/calendar/availability` | その機会の時間帯に重なる予定を返す。読み取りだけなので自動で呼んでよい |
| `POST /api/opportunities/{id}/calendar` | 予定を追加し、`status` を `registered`（次の一歩）にする。**ユーザーが追加内容を見てボタンを押したときだけ呼ぶ**。この操作を承認として扱う |

- `POST .../calendar` も他の POST と同じく `X-Requested-With` ヘッダーが必須（「状態を変える API のヘッダー」）。
  このヘッダーの付いた要求だけを、ユーザーの承認として扱う
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


## 検索専用モデル経路（#47）

`SEARCH_ROUTE=discovery` のときの探索。**既定は `legacy` で、切り替えで戻せる。**

### 一覧までにやること / やらないこと

| | |
| --- | --- |
| やる | 希望の分割 -> 希望ごとに並列で検索専用モデル -> 不足方向へ追加 -> 行形式の回答をコードで構造化 -> 重複統合・日付形式・既知の日付での期間判定・明示された地域違い |
| **やらない** | 検索語の組み立て、本文の取得と抽出、全件の LLM 評価、TOP3 への絞り込み |

**一覧の候補は「検索で見つかった候補」であって未確認。**
引用 URL があることは「公式で確認した」という意味ではない。
`verified=false` / `confirmed_fields=[]` がその状態を表す。

**設計上の限界:** 本文を再取得しないため、検索回答の誤りを一覧段階では防げない。

### `Opportunity` に増えた項目

| 項目 | 意味 |
| --- | --- |
| `wish` | どの希望から出た候補か（分割後の短いラベル） |
| `wish_source` | **元の入力そのまま。** 分割で原文を失わないために持つ |
| `confirmed_fields` | **詳細確認で実際に確認できた項目名。** `verified=true` だけでは何が確認できたか分からない |
| `corrections` | 訂正の履歴（`field` / `before` / `after` / `source` / `checked_at`）。**上書きせず積む** |
| `detail_checked_at` | 詳細確認を実行した時刻。**連打で二重に走らせないため** |
| `evaluated` | LLM 評価を行ったか。**false の候補の `score` を表示に使わない**（架空の点数を出さない） |
| `participation_span` | 会期の途中 1 日で参加できるか／全日必須か。**根拠が無ければ null** |

検索時の元データは `searched_values`（サーバ側に保持）に残す。訂正しても消さない。

### `POST /api/opportunities/{id}/detail-check`

ユーザーが選んだ **1 件だけ**、出典を取得して確かめる。一覧の全件には行わない。

- 直近に確認済みならそのまま返す（**同じボタンの連打で二重に走らせない**）
- 出典を取得できなかった場合は**誤りにせず未確認のまま**返す
- 参加資格は「出典に記載があるか」（`eligibility_stated`）であって、
  **本人が満たすかの照合ではない**
