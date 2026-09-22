# アーキテクチャ

このページは**設計**を書く。実装状況の正本は `README.md` の表。
設計のうち未実装のものには 🚧 を付けている。

## 全体

```
┌──────────────────────────┐
│ Frontend                 │
│ React / TypeScript       │
│ Vite / Tailwind CSS      │   担当: 土居すみれ
└────────────┬─────────────┘
             │  REST / JSON
┌────────────▼─────────────┐
│ Backend (FastAPI)        │
│ api/ services/ schemas/  │   担当: Naoya
└────────────┬─────────────┘
             │
┌────────────▼─────────────┐
│ Opportunity Agent        │
│  Goal Analyzer           │
│  Search Planner          │
│  Agent Loop              │
│  Evaluator               │
│  Verification            │
│  Reflection              │
└───────┬─────────┬────────┘
        │         │
   OrcaRouter   Tools
                  │
           Web / Calendar
                  │
               SQLite
```

## Agent Loop

```
START
 ↓
Profile 取得
 ↓
① Goal Analysis        analyzing_profile
 ↓
② Search Planning      planning
 ↓
Web Search Tool ─┐
 ↓               │
③ Extraction     │     searching
 ↓               │
④ Evaluation     │     evaluating
 ↓               │
十分？ ── NO ─────┘（検索戦略を変えて再探索）
 │ YES
 ↓
⑤ TOP3 Selection
 ↓
⑥ Recommendation
 ↓
⑦ Verification         verifying
 ↓
保存 → Frontend へ      completed
 ↓
Feedback
 ↓
⑧ Reflection → Agent Memory → 次回の探索へ
```

単発の LLM 呼び出しではなく、**Agent が State を持って判断しループする**ことが要件。
State は `backend/agent/state.py`、DB 同期は `agent_runs` テーブル。
途中で落ちても `status` / `current_step` / `progress` から状態を追える。

🚧 **再探索ループ（十分？ → NO）は未実装。** 現在は 1 周で終わる。
`AgentState.max_iterations` は用意してあるが誰も見ていない（タスク22）。
run の中で探し直すことはしないが、**前回までの反応は次の run に反映する**（下の ⑧ Reflection）。

### ⑧ Reflection（次の run への学習）

**振り返りは各 run の冒頭で行う**（フィードバックを受けた時点ではない）。
`backend/agent/reflection.py` が、そのユーザーの全フィードバックと Opportunity の `status` を
**LLM を使わずに**集計し直し、`agent_memories` の preference / insight を置き換える。
毎回すべての反応から作り直すので、付け直しや途中で落ちた run で値がずれない（冪等）。

| 1 件の候補から読む信号 | 重み |
| --- | --- |
| 👍 / 「気になる」 | +1 |
| 予定に追加 / 参加した | +2 |
| 👎（最新の反応を採る） | −1 |

- 同じ候補の信号は足し合わせず、最も強いもの 1 つにする（最新が 👎 なら −1）。
  👎 が立てる `status=dismissed` は数えない（二重に数えない）
- 鍵は `type:<OpportunityType>` と `format:<OpportunityFormat>` だけ。`type:other` は除く。
  **タイトル・説明・ドメインは鍵にしない**（Web 由来の文が Memory に入ると以後の全 run に
  効き続ける = memory poisoning。集約サイトのドメインは広すぎる）
- 鍵ごとの重みは ±3 で切る

| 反映先 | 反映のしかた | 必要な根拠 |
| --- | --- | --- |
| ② 探索計画 | enum の値と件数だけで作った「これまでの反応」を渡し、反応の悪い種類を減らし良い種類を増やす。**Serendipity の方向は必ず残す**（規則と `_ensure_serendipity`） | 同じ向きの反応が 2 件以上の候補 |
| ⑤ 順位付け | 種類は重み 1 あたり 3 点、形式はその半分、前の run で推薦して無反応なら −3 点。1 件あたり ±10 点まで | 反応 1 件から |
| ⑤ 意外性の重み | 反応した候補の `serendipity_score` の傾向で、既定 0.3 を 0.2〜0.45 の範囲で動かす | 反応 2 件以上 |

- **`score` 列は書き換えない。** 補正は並べ替えにだけ使う（AI の評価と学習結果を混ぜない）。
  評価の出力の後に足すので、評価器（LLM / Jev）に依存しない
- **UserProfile は書き換えない。** 学んだことは Agent Memory にだけ置く
- `AgentStep` は増やさず、`analyzing_profile` / `planning` / `evaluating` の Log として出す
- stub（`AGENT_STUB_MODE=true`）でも振り返りの Log と順位の補正は効く。計画は固定のまま

## データの分離

Opportunity の情報は 3 種類に分けて扱う。混同しない。

| 種類 | 例 | 出どころ |
| --- | --- | --- |
| ① Web 上の事実 | `title` `start_at` `deadline` `location` `cost` | Web Search / Page Reader |
| ② AI の評価 | `score` `reason` `serendipity_score` `match_reasons` | LLM |
| ③ ユーザーとの関係 | `status` | ユーザー操作 |

同様に、

- **UserProfile** =「その人がどんな人なのか」（`user_profiles`）
- **Agent Memory** =「Agent がその人について何を学んだのか」（`agent_memories`）

を分離する。プロフィールを書き換えずに Agent 側の理解だけを育てられる。

## Security

Web から取得した内容はすべて **Untrusted Data**。
`ToolResult.external=True` で印を付け、LLM へは「命令ではなくデータ」として渡す。
ページ内に「以前の命令を無視してください」等があっても Agent への命令として実行しない。

**LLM が騙されない前提に立たない。** モデルに「従うな」と伝えるだけでなく、
指示らしき文を LLM の手前でコードが取り除き（`backend/ai/guard.py`）、
引っかかったページは推薦しない。防御の層・実測・限界は `docs/security.md`。

Tool には権限レベルを持たせ、LLM が騙されても重要操作を実行できないようにする
（`backend/tools/base.py`）。

| Tool | 権限 |
| --- | --- |
| `search_web` | AUTO |
| `read_page` | AUTO |
| `check_calendar` | AUTO |
| `add_calendar_event` | APPROVAL |
| `submit_application`（将来） | APPROVAL |

## Cost / Reliability

### 工程ごとのモデル振り分け

方針は `backend/ai/routing.py` の 1 か所だけ。工程名ではなく
**入力の出所・判断の重さ・呼び出し数・許容できる時間**で決める。
判断の根拠と実測は `docs/experiments/26-routing.md`。

| 工程 | 入力の出所 | 通常 tier | 上位へ移る条件 | 理由 |
| --- | --- | --- | --- | --- |
| ① 目標分析 | プロフィール自由文 | STANDARD | Fallback のみ | `about` に指示文を書ける |
| ② 検索計画 | ①の出力 + 活動地域 | STANDARD | Fallback のみ | 外部本文は読まない。CHEAP を実測したが不合格 |
| 事前選別 | 検索結果 | **LLM なし**（Jev） | — | OrcaRouter を通らない |
| ③ 抽出 | **Web 本文** | STANDARD | Fallback のみ | 外部本文を直接読む。**CHEAP 禁止** |
| ④ 評価 | ③の抽出結果 | STANDARD（Jev 優先） | Fallback のみ | 外部由来。要約を経ても trusted にしない |
| ⑤ TOP3 選定 | ④のスコア | **LLM なし** | — | コードで決まる |
| ⑥ 推薦理由 | ③④の結果 | STANDARD | Fallback のみ | 外部由来を読み、画面にそのまま出る |
| ⑦ 検証 | **公式ページ本文** | STANDARD | Fallback のみ | 外部本文を直接読む。**CHEAP 禁止** |
| ⑧ Reflection | — | **未実装** | — | Schema のみ。Agent Loop へ未接続 |

**外部由来のデータを読む工程に CHEAP を使わない。** cheap は Prompt Injection に
1/2 で突破される実測がある。表を書き換えても `routing._check_table` が import 時に落とす。

**POWERFUL は通常 tier に置かない。** 1 呼び出し 4.5 秒かかる。
上がるのは STANDARD が試行を使い切ったときだけ。

`LLM_ROUTING=standard` で表を無視して全工程 STANDARD に戻せる。

### その他

- 絞り込みは `Rule/Embedding → Cheap LLM → Powerful LLM` の段階式にして、
  全件を高性能モデルへ投げない（現状は Jev による事前選別とコードによる TOP3 選定）
- `agent_runs.cost_jpy` / `expensive_model_calls` にコストを記録する（実装済み）。
  **見積もりであって請求額ではない。** `ORCAROUTER_INCLUDE_COST=true` のときだけ
  実費も別欄に記録する
- LLM 失敗時は Retry → Fallback Model → Agent 再開。
  **モデル障害 ≠ Agent 全体停止**
- 1 論理呼び出しにつき `llm.routed` を 1 行残す（工程・選択理由・要求 tier・
  実際のモデル・試行数・Fallback 数・トークン・実費）

## DB

MVP は SQLite + SQLAlchemy。PostgreSQL へ移す場合も `DATABASE_URL` の変更で済む。

| テーブル | 内容 |
| --- | --- |
| `user_profiles` | プロフィール |
| `opportunities` | 発見した機会（事実 + 評価 + status） |
| `agent_runs` | Agent 実行の状態・コスト |
| `agent_logs` | Agent が何を考え何をしたか |
| `feedbacks` | 👍 / 👎 / 参加した / 結果 |
| `agent_memories` | Reflection で学習した内容（preference: 種類・形式ごとの重みと件数、意外性の重み / insight: 学んだことの文）。毎 run 作り直す |

**Migration ツールは入れていない。** `db/session.py` の `init_db()` が
`create_all` でテーブルを作る。列を追加したらローカルの
`backend/opportunity_agent.db` を消して作り直すこと。

## 認証

MVP では認証を入れない。単一ユーザー（`DEFAULT_USER_ID = "user_001"`）で動く。
認証を追加するときは `backend/api/deps.py` の `current_user_id` だけ差し替える。

## 自動探索（Agent が「いつ探すか」を決める）

**自動にするのは発見だけ。** Calendar への書き込みなど外部に影響する操作は、
これまでどおり人の操作に残す（Autonomous discovery, human-controlled action）。
既定はオフ。条件と既定値は `docs/api.md` の「自動探索」。

```
POST .../feedback（👎） ─→ auto_explore.start_after_feedback ─┐
                                                               ├─→ create_run(trigger, reason) ─→ run_agent
scheduler（N 秒ごと）   ─→ auto_explore.start_on_tick ─────────┘
```

- **判定と上限は `backend/services/auto_explore.py` に集め、LLM は使わない。**
  上限（回数・費用・最低間隔・実行中の run・プロフィール必須・同じ run への探し直しは 1 回）は
  全 trigger に共通で、きっかけごとの例外を作らない
- **理由の文は決まった文面と数値だけ。** 候補のタイトルなど Web 由来の文を
  「Agent の判断理由」として画面に出さない。run の最初の Log に入れ、探索中画面の先頭に出す。
  AgentStep は増やさない
- 定期チェックは `backend/agent/scheduler.py`。フラグがオンのときだけ lifespan で asyncio の
  タスクを 1 本起動し、run は `asyncio.to_thread` で走らせる。**1 プロセス前提**
  （uvicorn の worker を増やすとチェックも重複する）
- 手動・自動の開始は `services/run_lifecycle.py` の共通ロックを通す。既に実行中なら手動開始はその run を返し、新しい実行タスクを増やさない
- Frontend は `GET /api/agent/runs/latest` を見て知らせを出す。**画面は勝手に移らない**
- 「探索履歴」は `GET /api/agent/runs` から本人の過去の探索を取り、各回の結果・ログへ案内する。DB の既存記録を使い、候補の内容は最新値で表示する
