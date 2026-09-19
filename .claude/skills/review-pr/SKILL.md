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
| メイン Agent（あなた） | 差分の取得、判定、`post_review.py` での投稿 |

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

## 4. Finding を JSON にする

`$CLAUDE_SCRATCHPAD/findings.json` へ書く。**1 件 = 1 つの独立した会話**になるので、
各 body だけを読んで対応できるように自己完結させる。

```json
[
  {
    "path": "backend/ai/llm.py",
    "line": 42,
    "side": "RIGHT",
    "severity": "Critical",
    "title": "例外に入力値が載る",
    "body": "問題: ...\n\n根拠: ...\n\n推奨修正: ..."
  }
]
```

| キー | 内容 |
| --- | --- |
| `path` | リポジトリルートからの相対パス |
| `line` | **変更後**のファイルの行番号（`side` が LEFT なら変更前） |
| `side` | `RIGHT`（既定・変更後） / `LEFT`（変更前） |
| `severity` | `Critical` / `High` / `Major` / `Medium` / `Low` / `Minor` |
| `title` | 一行の要約 |
| `body` | 問題 / 根拠 / 推奨修正 |

`body` には必ず 3 つを書く。

- **問題** — 何が起きるか（具体的な入力・状態 → 結果）
- **根拠** — なぜそう言えるか（コードのどこ、どのルールに反するか）
- **推奨修正** — どう直すか

そのまま適用できる修正なら ```suggestion ブロックを使う。
GitHub 上で Commit suggestion を押すだけで直せる。

````
```suggestion
    return LLMValidationError(_safe_reason(last_error))
```
````

`line` を特定できない指摘（設計全体の話など）は `line` を省略してよい。
自動的に Review 本文へ退避される。

## 5. 投稿する

Review 本文を `$CLAUDE_SCRATCHPAD/summary.md` に書き、スクリプトへ渡す。

**投稿前に必ず `--dry-run` で確認する。** inline と fallback の振り分けを見てから本番実行する。

```bash
.claude/skills/review-pr/post_review.py \
  --pr <PR番号> --event <APPROVE|REQUEST_CHANGES|COMMENT> \
  --body-file "$CLAUDE_SCRATCHPAD/summary.md" \
  --findings "$CLAUDE_SCRATCHPAD/findings.json" \
  --dry-run
```

問題なければ `--dry-run` を外して実行する。

スクリプトは以下をやる。

1. `gh pr diff` を解析して、inline comment を付けられる行を特定する
2. 付けられない Finding を Review 本文の末尾へ退避する
3. **複数の inline comment を 1 つの Review としてまとめて投稿する**
   （`POST /repos/{owner}/{repo}/pulls/{n}/reviews` の `comments` 配列）

1 件ずつ投稿しない。通知が分散し、Review 単位の判定も付かない。

diff の範囲外の行を指定すると API が 422 を返して Review 全体が落ちるため、
行の妥当性はスクリプトが事前に検証する。**自分で行番号を数えない。**

**このスクリプトは `ask` に入れてある。** 実行時にユーザーの承認を求める。
これは意図した設計なので、回避しようとしない。

### 自分の PR は APPROVE できない

GitHub は自分が作成した PR への Approve を拒否する
（`Can not approve your own pull request`）。

APPROVE が失敗したら `--event COMMENT` で実行し直す。本文の冒頭に
「問題は見つかりませんでした（自分の PR のため Approve ではなく Comment で投稿）」
と書き添える。

## Review 本文の形式

**個別の指摘はここに書かない。** inline comment 側に書く。
本文は全体像だけにする。

```markdown
## 判定

REQUEST_CHANGES — Critical 1 件。詳細は inline comments を参照。

## 指摘件数

| Critical | High | Medium | Low |
| --- | --- | --- | --- |
| 1 | 0 | 2 | 1 |

## CI

backend pass / frontend pass

## Summary

3〜5 行。何が変更され、どこに懸念があるかだけ。個別の指摘は書かない。

## 確認したこと

- 呼んだ reviewer（code-reviewer / security-reviewer）
- 実行したテスト
- レビューしきれなかった範囲
```

指摘が無ければ「問題は見つかりませんでした」と正直に書く。
**無理に指摘を作らない。** ハッカソン中に Minor を大量に並べない。

## やらないこと

- コードを直接修正しない。指摘するだけ。修正はユーザーの指示を待つ
- merge しない
- reviewer の報告を検証せずに転記しない
