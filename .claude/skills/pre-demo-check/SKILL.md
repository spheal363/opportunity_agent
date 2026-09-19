---
name: pre-demo-check
description: デモ・提出前にアプリが実際に通しで動くか確認する手順。Code Freeze 前、発表前、main へ merge する前に使う。
when_to_use: "デモ前の確認, 提出前チェック, 通しで動くか確認, main を壊していないか, code freeze"
---

# デモ前チェック

**所要 5 分。** 発表前・提出前・大きめの merge 前に必ず通す。

## 1. 静的チェック

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/pytest -q
```

```bash
cd frontend && npm run lint && npm run build
```

どれか落ちたらここで止める。デモ用の回避策を入れない。

## 2. 起動

```bash
cd backend && .venv/bin/uvicorn main:app --port 8000
```

```bash
cd frontend && npm run dev
```

```bash
curl -s localhost:8000/api/health
```

## 3. 通しで動かす

ブラウザで http://localhost:5173 を開き、**デモと同じ順番で**操作する。

- [ ] `/profile` — プロフィールを入力して送信できる
- [ ] `/explore` — 進捗バーが進み、Agent のログが順に出る
- [ ] `/opportunities` — TOP3 が出る。推薦理由が表示される
- [ ] TOP3 に **serendipity_score の高い一件**が含まれている（デモの山場）
- [ ] `/opportunities/:id` — 日時・場所・締切・参加条件が出る
- [ ] 「参加したい」→ 登録ページの URL が出る
- [ ] 👍 / 👎 が送れる

## 4. デモで見せる審査項目

実装済みのものだけ確認する。未実装は無理に見せない。

- [ ] Autonomy — ユーザーが検索キーワードを入力していないことを言える
- [ ] Serendipity — なぜその一件が普通の検索で出ないのか説明できる
- [ ] Security — Prompt Injection のブロックを見せられるか
- [ ] Cost — OrcaRouter のモデル振り分けを見せられるか
- [ ] Reliability — Fallback を見せられるか

## 5. 壊れやすいところ

- [ ] `.env` が両方に存在する（`backend/.env`, `frontend/.env`）
- [ ] `VITE_USE_MOCK` の値が意図どおり（デモで Backend を見せるなら `false`）
- [ ] `AGENT_STUB_MODE` の値が意図どおり
- [ ] Backend が落ちたときに Frontend がエラー表示で止まる（白画面にならない）
- [ ] 日時がローカル時刻で正しく出ている（UTC のまま出ていない）
- [ ] DB に古い run / opportunity が残って混乱していないか

DB をきれいにしてから本番デモをするなら:

```bash
cd backend && rm -f opportunity_agent.db
```

## 6. Git

```bash
git status --short
```

- [ ] `.env` や `*.db` が staged に入っていない
- [ ] main が最新で、ローカルと remote が一致している
