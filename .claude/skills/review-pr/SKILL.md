---
name: review-pr
description: PR の差分を read-only な reviewer Subagent にレビューさせ、その結果を GitHub の PR Review として投稿する。PR をレビューしたいとき、merge 前の確認をしたいときに使う。
when_to_use: "PR をレビュー, プルリクをレビュー, review-pr, PR の差分を見て, merge していいか確認, PR にレビューを投稿"
---

# PR レビューと投稿

引数で PR 番号を受け取る（例: `/review-pr 1`）。省略された場合はこのセッションに
bound された PR、それも無ければ現在のブランチの PR を使う。

**役割分担を崩さない。**

| | |
| --- | --- |
| reviewer Subagent | 差分を読んで指摘する。**GitHub へ書き込まない**（PreToolUse hook でブロック） |
| メイン Agent（あなた） | 差分の取得、判定、`gh pr review` での投稿 |

## 1. PR を特定して差分を取る

```bash
gh pr view <PR番号> --json number,title,state,baseRefName,headRefName,isDraft,additions,deletions,changedFiles
gh pr diff <PR番号>
```

state が `OPEN` でなければ、その旨を伝えて止まる。
差分が巨大（changedFiles > 50 または additions > 3000）なら、先にユーザーへ
「全体を見るか、範囲を絞るか」を確認する。

CI の状態も見ておく。落ちているなら指摘に含める。

```bash
gh pr checks <PR番号>
```

## 2. reviewer へ委譲する

`code-reviewer` Subagent を呼ぶ。**必ず PR 番号と対象範囲を明示する。**

Subagent には以下を伝える。

- リポジトリのパスと PR 番号
- `gh pr diff <PR番号>` で差分を取ること
- base と head のブランチ名
- 必要ならテストを実行してよいこと（`cd backend && .venv/bin/pytest -q`）

**`security-reviewer` も呼ぶ条件**（どれかに当てはまれば呼ぶ。両方を並列で起動してよい）:

- `backend/agent/` `backend/ai/` `backend/tools/` に変更がある
- 外部データ（Web / 外部 API / LLM）を扱う経路の追加・変更がある
- Tool の権限、承認フロー、`.env`、`config.py`、`.claude/` に変更がある
- 依存関係（`requirements.txt` / `package.json`）が変わっている

判断に迷ったら呼ぶ。コストより見落としのほうが高くつく。

## 3. 判定する

Subagent の報告を**そのまま投稿しない。** 自分で差分を確認し、指摘が妥当か検証してから判定する。
Subagent が誤検知していることもある。

| 判定 | 条件 |
| --- | --- |
| `REQUEST_CHANGES` | Critical / High が 1 件でもある。CI が落ちている。Secret が含まれている |
| `COMMENT` | Major / Medium 止まり、または軽微な提案のみ |
| `APPROVE` | 問題が無い |

`.claude/rules/` と `docs/development.md` に反する変更は Major 以上として扱う。

## 4. 投稿する

本文は `$CLAUDE_SCRATCHPAD/pr-review.md` に書いてから `--body-file` で渡す。
日本語と改行をシェルでエスケープしないため。

```bash
gh pr review <PR番号> --request-changes --body-file <path>
gh pr review <PR番号> --comment --body-file <path>
gh pr review <PR番号> --approve --body-file <path>
```

**`gh pr review *` は `ask` に入れてある。** 実行時にユーザーの承認を求める。
これは意図した設計なので、回避しようとしない。

### 自分の PR は APPROVE できない

GitHub は自分が作成した PR への Approve を拒否する
（`Can not approve your own pull request`）。

APPROVE が失敗したら、**同じ本文を `--comment` で投稿し直す**。
冒頭に「問題は見つかりませんでした（自分の PR のため Approve ではなく Comment で投稿）」
と書き添える。

## 本文の形式

```markdown
## 判定

REQUEST_CHANGES / COMMENT / APPROVE と、その理由を 1 行。

## 指摘

[重大度] ファイル:行 — 一行の要約
  問題: 何が起きるか（具体的な入力・状態 → 結果）
  修正案: どう直すか

## 確認したこと

- CI の状態
- 実行したテスト
- 呼んだ reviewer（code-reviewer / security-reviewer）

## 補足

見落としている可能性がある範囲、レビューしきれなかった部分。
```

指摘が無ければ「問題は見つかりませんでした」と正直に書く。
**無理に指摘を作らない。** ハッカソン中に Minor を大量に並べない。

## やらないこと

- コードを直接修正しない。指摘するだけ。修正はユーザーの指示を待つ
- merge しない
- reviewer の報告を検証せずに転記しない
