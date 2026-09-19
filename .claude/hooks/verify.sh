#!/bin/bash
# Stop: そのターンで実際に変更された領域だけを検証する。
# backend の .py が変わったときだけ ruff + pytest、frontend/src が変わったときだけ build。
# 何も変わっていなければ即終了する。
set -u
# パイプ後段の tail で終了ステータスが隠れないようにする
set -o pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$ROOT" || exit 0

CHANGED=$(
  { git diff --name-only HEAD 2>/dev/null
    git ls-files --others --exclude-standard 2>/dev/null; } | sort -u
)
[ -z "$CHANGED" ] && exit 0

echo "$CHANGED" | grep -qE '^backend/.*\.py$' && RUN_BACKEND=1 || RUN_BACKEND=0
echo "$CHANGED" | grep -qE '^frontend/src/' && RUN_FRONTEND=1 || RUN_FRONTEND=0
[ "$RUN_BACKEND" = 0 ] && [ "$RUN_FRONTEND" = 0 ] && exit 0

FAILURES=""

if [ "$RUN_BACKEND" = 1 ] && [ -x backend/.venv/bin/python ]; then
  if ! OUT=$(cd backend && .venv/bin/ruff check . 2>&1); then
    FAILURES="${FAILURES}\n[backend ruff]\n${OUT}\n"
  fi
  if ! OUT=$(cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -30); then
    FAILURES="${FAILURES}\n[backend pytest]\n${OUT}\n"
  fi
fi

if [ "$RUN_FRONTEND" = 1 ] && [ -d frontend/node_modules ]; then
  if ! OUT=$(cd frontend && npm run build 2>&1 | tail -30); then
    FAILURES="${FAILURES}\n[frontend build]\n${OUT}\n"
  fi
fi

if [ -n "$FAILURES" ]; then
  printf '%b' "$FAILURES" | python3 -c '
import json, sys
msg = sys.stdin.read().strip()
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "Stop",
        "systemMessage": "変更した領域の検証が失敗しました。報告する前に直してください。\n" + msg,
    }
}))
'
fi

exit 0
