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

- OrcaRouter でモデルを振り分ける（単純な分類は cheap、重要な判断は powerful）
- 絞り込みは `Rule/Embedding → Cheap LLM → Powerful LLM` の段階式にして、
  全件を高性能モデルへ投げない
- 🚧 `agent_runs.cost_jpy` / `expensive_model_calls` にコストを記録する
  （列と DB 同期は実装済み。`AgentState` の値を加算する処理が無いため常に 0）
- LLM 失敗時は Retry → Fallback Model → Agent 再開。
  **モデル障害 ≠ Agent 全体停止**

## DB

MVP は SQLite + SQLAlchemy。PostgreSQL へ移す場合も `DATABASE_URL` の変更で済む。

| テーブル | 内容 |
| --- | --- |
| `user_profiles` | プロフィール |
| `opportunities` | 発見した機会（事実 + 評価 + status） |
| `agent_runs` | Agent 実行の状態・コスト |
| `agent_logs` | Agent が何を考え何をしたか |
| `feedbacks` | 👍 / 👎 / 参加した / 結果 |
| `agent_memories` | 🚧 Reflection で学習した内容（テーブルのみ。書き込み経路なし） |

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
- Frontend は `GET /api/agent/runs/latest` を見て知らせを出す。**画面は勝手に移らない**
