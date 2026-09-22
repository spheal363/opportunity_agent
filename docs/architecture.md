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
| `agent_memories` | 🚧 Reflection で学習した内容（テーブルのみ。書き込み経路なし） |

**Migration ツールは入れていない。** `db/session.py` の `init_db()` が
`create_all` でテーブルを作る。列を追加したらローカルの
`backend/opportunity_agent.db` を消して作り直すこと。

## 認証

MVP では認証を入れない。単一ユーザー（`DEFAULT_USER_ID = "user_001"`）で動く。
認証を追加するときは `backend/api/deps.py` の `current_user_id` だけ差し替える。
