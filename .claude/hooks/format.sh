#!/bin/bash
# PostToolUse(Edit|Write): 編集された 1 ファイルだけを整形・lint する。
# 1 ファイル単位なので数百ms で終わる。重い検証は Stop hook（verify.sh）が担当する。
set -u

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

FILE=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[ -z "$FILE" ] && exit 0
[ -f "$FILE" ] || exit 0

case "$FILE" in
  "$ROOT"/backend/*.py|backend/*.py)
    RUFF="$ROOT/backend/.venv/bin/ruff"
    [ -x "$RUFF" ] || exit 0
    "$RUFF" format -q "$FILE" >/dev/null 2>&1
    # 安全に直せるものだけ自動修正する（--unsafe-fixes は使わない）
    "$RUFF" check --fix -q "$FILE" >/dev/null 2>&1
    ;;
  "$ROOT"/frontend/src/*|frontend/src/*)
    case "$FILE" in
      *.ts|*.tsx|*.css|*.json)
        [ -d "$ROOT/frontend/node_modules" ] || exit 0
        (cd "$ROOT/frontend" && npx --no-install prettier --write "$FILE" >/dev/null 2>&1)
        case "$FILE" in
          *.ts|*.tsx)
            (cd "$ROOT/frontend" && npx --no-install eslint --fix "$FILE" >/dev/null 2>&1)
            ;;
        esac
        ;;
    esac
    ;;
esac

exit 0
