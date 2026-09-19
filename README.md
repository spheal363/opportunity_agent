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
| Agent Run / Log API | 実装済み（Loop は Stub） |
| Opportunity API | 実装済み |
| Feedback API | 実装済み（Reflection 未接続） |
| Tool 権限制御 | 枠組みのみ（`backend/tools/`） |
| Verification | 未実装（`interest` で公式情報を再確認していない） |
| 再探索・終了条件 | 未実装（1 周で終わる） |
| Reflection / Agent Memory | 未実装（テーブルのみ） |
| コスト記録 | 未実装（列と同期はあるが加算処理が無く常に 0） |
| DB Migration | なし（`create_all`。列追加時は DB を作り直す） |
| Calendar API | 未実装（501 を返す） |
| OrcaRouter / LLM | 未実装 |
| Web Search / Extraction | 未実装 |
| Prompt Injection 対策 | 未実装 |
| Retry / Fallback | 未実装 |

Frontend 側は `VITE_USE_MOCK=true` にすると Backend なしで画面を作れる。

---

## Claude Code

`.claude/` に開発環境を用意してある。クローンしてそのまま使える。

| | |
| --- | --- |
| `CLAUDE.md` | 常時読まれる。製品概要・スタック・コマンド・重要原則 |
| `.claude/rules/` | 領域ごとのルール。backend / frontend などは該当ファイルを触ったときだけ読み込まれる |
| `.claude/skills/` | `/implement-agent-step`（Agent のスタブを実装に置き換える手順）、`/pre-demo-check`（デモ前チェック） |
| `.claude/agents/` | `code-reviewer` / `security-reviewer`。差分をレビューする（コードは変更しない） |
| `.claude/hooks/` | 編集時に整形、応答完了時に変更領域だけ検証 |

## 開発ルール

- Branch: `main` / `feature/*` / `fix/*`
- Commit: `feat:` `fix:` `refactor:` `docs:` `test:` `chore:`
- `main` は常にデモ可能な状態を保つ
- **Secret を commit しない**（`.env.example` だけ commit する）
- **API / Schema を勝手に変更しない**（①共有 → ②仕様更新 → ③実装）
- 30 分以上詰まったら共有する

詳細は [docs/architecture.md](docs/architecture.md) と Notion のタスクトラッカーを参照。

**Code Freeze: 9/22 10:00** — 以降は Bug Fix・デモ安定化・発表準備のみ。
