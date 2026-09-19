#!/bin/bash
# レビュー用 Subagent から GitHub / git への書き込みを禁止する。
#
# .claude/agents/{code,security}-reviewer.md の PreToolUse から呼ばれ、
# その Subagent の実行中だけ適用される。メイン Agent には影響しない。
#
# レビュアーは「読んで指摘する」だけの役割であり、PR への投稿は
# メイン Agent が行う（/review-pr スキル）。この境界を仕組みで担保する。
#
# 方針は default-deny。gh は読み取り専用サブコマンドだけを通す。
set -u

COMMAND=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)
[ -z "$COMMAND" ] && exit 0

deny() {
  echo "$1" >&2
  exit 2
}

# --- PR への投稿スクリプト ---
# レビュアーが直接叩けば gh の制限を迂回できてしまうため塞ぐ。
if printf '%s' "$COMMAND" | grep -qE 'post_review\.py'; then
  deny "レビュアーは PR へ投稿できません。指摘は報告として返してください。投稿はメイン Agent が行います。"
fi

# --- git の書き込み系 ---
if printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+(push|commit|merge|rebase|reset|revert|tag|checkout|switch|cherry-pick|clean|am|apply)([[:space:]]|$)'; then
  deny "レビュアーは git への書き込みを実行できません。指摘と修正案の報告のみ行ってください。"
fi

# --- gh は読み取り専用サブコマンドのみ許可（default-deny） ---
if printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])gh([[:space:]]|$)'; then
  # 例: gh pr diff 12 / gh pr view --json ... / gh run list
  if printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])gh[[:space:]]+(pr|issue|run|repo|release|workflow|cache|search)[[:space:]]+(view|diff|checks|list|status|download)([[:space:]]|$)'; then
    :
  # 例: gh api repos/... （GET のみ。-X/--method が付くものは拒否）
  elif printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])gh[[:space:]]+api[[:space:]]' \
       && ! printf '%s' "$COMMAND" | grep -qE '(-X|--method)[[:space:]]*(POST|PATCH|PUT|DELETE|post|patch|put|delete)'; then
    :
  else
    deny "レビュアーは gh の書き込み操作を実行できません（読み取り専用サブコマンドのみ許可）。PR への投稿はメイン Agent が行います。"
  fi
fi

exit 0
