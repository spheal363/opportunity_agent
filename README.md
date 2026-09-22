# Opportunity Agent

> あなたの目標・興味・スキルを理解し、AI が自律的に Web を探索して
> 「まだ自分では探していなかった機会」を発見し、行動まで支援する Personal Opportunity Agent。

ユーザーは検索キーワードを指定しない。Agent 自身が「何を探すべきか」を決め、
Web を探索し、評価し、TOP3 と「なぜあなたにおすすめなのか」を返す。

設計方針は **Autonomous discovery, human-controlled action.**
発見は Agent が自律的に行い、外部世界に影響する操作は人間に戻す。

---

## 構成

```
opportunity-agent/
├── frontend/   React + TypeScript + Vite + Tailwind   担当: 土居すみれ
├── backend/    Python + FastAPI + SQLAlchemy          担当: Naoya
├── docs/       アーキテクチャ / API / デモ資料
└── .github/
```

Frontend と Backend は **API 仕様を境界に並行開発する**。
片方が未完成でも、Frontend は Mock Data、Backend は API 単体で開発を進められる。

---

## セットアップ

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn main:app --reload --port 8000
```

必要な環境変数は [`backend/.env.example`](backend/.env.example) を参照（`backend/config.py` と対応）。

- Health check: http://localhost:8000/api/health
- OpenAPI (Swagger): http://localhost:8000/docs

```bash
cd backend && .venv/bin/pytest -q      # テスト
cd backend && .venv/bin/ruff check .   # Lint
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

必要な環境変数は [`frontend/.env.example`](frontend/.env.example) を参照（`frontend/src/vite-env.d.ts` と対応）。

http://localhost:5173 で起動する。

```bash
cd frontend && npm run lint && npm run build
```

### Docker

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
docker compose up
```

---

## 今の状態

**Profile 登録 → Agent 探索 → TOP3 → 詳細 → 参加したい → Feedback** まで通しで動く。

ただし Agent の中身は `AGENT_STUB_MODE=true` の固定データで動いている。
LLM / Web Search はまだ繋いでいない（`backend/agent/loop.py` の `_step_*` を差し替える）。

| | 状態 |
| --- | --- |
| Profile API | 実装済み |
| Agent Run / Log API | 実装済み |
| Opportunity API | 実装済み |
| Feedback API | 実装済み（Reflection 未接続） |
| Tool 権限制御 | 枠組みのみ（`backend/tools/`） |
| Agent Loop: Web 探索 | 実装済み（検索 → 抽出 → 保存。重複は URL で除去） |
| Agent Loop: Goal 分析 | 実装済み（プロフィール → 目標・興味の交差点） |
| Agent Loop: 探索計画 | 実装済み（Serendipity 方向を最低 1 つ確保） |
| Agent Loop: 評価 / 順位付け | 実装済み（選定は LLM 不使用。意外性を重みづけ） |
| Search / Page Fetch / 評価器の差し替え | 実装済み（既定は現行のまま。比較は [#65](docs/experiments/65-search-comparison.md)） |
| 受付状況の判定 | 実装済み（`verified` とは別軸。期限切れを推薦から外す） |
| Agent Loop: Verification | 実装済み（TOP3 の公式ページを再確認。警告を Log に出す） |
| `interest` 時の再確認 | 未実装（探索時には検証済み。押した時点では再確認しない） |
| 再探索・終了条件 | 未実装（1 周で終わる） |
| Reflection / Agent Memory | 未実装（テーブルのみ） |
| コスト記録 | 実装済み（見積もり。1 探索あたり約 1 円。実単価が出たら差し替える） |
| DB Migration | ツールは無いが、`init_db` が不足列を足す（冪等・既存データを消さない） |
| Calendar API | 実装済み（空き確認と予定追加。連携手順は `backend/README.md`） |
| OrcaRouter / LLM | 実装済み（接続・Schema Validation・Retry・Fallback・コスト記録） |
| Web Search | 実装済み（Tavily。provider 差し替え可能） |
| ページ取得 | 実装済み（Tavily extract。一部失敗しても残りを返す） |
| Opportunity 構造化 | 実装済み（LLM 抽出。日時は tz 必須、不明な項目は null） |
| Prompt Injection 対策 | 実装済み（LLM の手前で指示らしき文を除去し、疑わしいページは推薦しない。実測と限界は `docs/security.md`） |
| Retry / Fallback | 実装済み（tier ごとに Retry し、駄目なら上の tier へ Fallback） |

Frontend 側は `VITE_USE_MOCK=true` にすると Backend なしで画面を作れる。

---

## Claude Code

`.claude/` に開発環境を用意してある。クローンしてそのまま使える。

| | |
| --- | --- |
| `CLAUDE.md` | 常時読まれる。製品概要・スタック・コマンド・重要原則 |
| `.claude/rules/` | 領域ごとのルール。backend / frontend などは該当ファイルを触ったときだけ読み込まれる |
| `.claude/skills/` | `/implement-agent-step`（Agent のスタブを実装に置き換える手順）、`/pre-demo-check`（デモ前チェック）、`/review-pr`（PR をレビューして投稿） |
| `.claude/agents/` | `code-reviewer` / `security-reviewer`。差分をレビューする。コード変更は不可、GitHub への書き込みは hook でブロック（完全な保証ではない） |
| `.claude/hooks/` | 編集時に整形、応答完了時に変更領域だけ検証 |

## 開発ルール

Branch / Commit / Merge ルールの正本は **[docs/development.md](docs/development.md)**。

要点だけ挙げると:

- **1 つのまとまった機能 = 1 ブランチ / 1 チケット = 1 commit**
- `main` は常にデモ可能な状態を保つ。`main` 上で直接機能開発しない
- **Secret を commit しない**（`.env.example` だけ commit する）
- **API / Schema を勝手に変更しない**（①共有 → ②仕様更新 → ③実装）
- 30 分以上詰まったら共有する

**Code Freeze: 9/22 10:00** — 以降は Bug Fix・デモ安定化・発表準備のみ。

アーキテクチャは [docs/architecture.md](docs/architecture.md)、タスクは Notion のタスクトラッカーを参照。
