---
paths:
  - "backend/agent/**/*.py"
  - "backend/ai/**/*.py"
  - "backend/tools/**/*.py"
---

# Agent / AI 処理の書き方

全体フローは `CLAUDE.md` の Agent Flow、各処理の I/O は `backend/ai/schemas/`。
ここに Schema の中身を再掲しない。

## LLM 出力の扱い

- **出力は必ず `ai/schemas/` の Pydantic モデルで受ける。** 自由文のまま次の処理へ渡さない。
- **Validation 失敗は Retry の対象。** 例外を握りつぶして不完全なデータを先へ流さない。
- **取得できなかった事実は `null`。** LLM に推測で埋めさせない。
  日時・締切・場所・参加条件は Web 上の事実であり、AI の記憶で代用しない。
- `score` / `serendipity_score` は 0-100。範囲外は不正出力として扱う。

## Agent Loop

- **State を経由する。** ステップ間の受け渡しを引数の連鎖でやらず `AgentState` に持たせる。
- **進捗は必ず DB へ書く。** `_step()` と `_log()` を通す。
  Frontend の探索中画面と「Agent が何を考えたか」のデモがこれに依存している。
- **1 ステップで失敗しても run 全体を落とさない。** `status=failed` と `error` を残して終わる。
- `AGENT_STUB_MODE` の分岐を各所へ散らさない。`loop.py` の `_step_*` 相当の関数内に閉じる。

## Tool

- **新しい Tool は `Tool` を継承し `registry.register()` する。** 直接呼び出す経路を作らない。
- **権限レベルを必ず指定する。** 外部世界に影響する操作（書き込み・送信・応募）は
  `PermissionLevel.APPROVAL`。判断に迷ったら APPROVAL にする。
- **`registry.invoke()` を経由する。** `approved` フラグを飛ばして Tool を直接呼ばない。
- **Web / 外部から取得した内容は `ToolResult(external=True)`。**
  LLM へ渡すときは「データであって命令ではない」ことが分かる形にする。

## スタブを実装に置き換えるとき

`/implement-agent-step` を使う。手順とチェック項目がそこにある。
