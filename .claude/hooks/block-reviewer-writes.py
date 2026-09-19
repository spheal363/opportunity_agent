#!/usr/bin/env python3
r"""レビュー用 Subagent から外部への書き込みを禁止する PreToolUse hook。

`.claude/agents/{code,security}-reviewer.md` の frontmatter から呼ばれ、
その Subagent の実行中だけ適用される。メイン Agent には影響しない。

レビュアーは「読んで指摘する」だけの役割で、PR への投稿はメイン Agent が行う
（`/review-pr`）。この境界を仕組み側で担保する。

## 方針

**fail-closed。** 入力を解釈できなければ拒否する。hook が壊れている間は
レビュアーが Bash を使えなくなるが、境界が黙って無効化されるより良い。

**argv で判定する。** コマンド文字列への正規表現は、絶対パス・`\gh`・
`git -C dir push` のようなごく普通の書き方で外れる。シェル演算子で分割し、
`shlex` で argv へ分解して、`argv[0]` の basename で判定する。

## 限界

これは多層防御の 1 枚目であり、完全な保証ではない。Bash がある以上、
文字列照合で到達手段をすべて列挙することはできない。
インタプリタの起動（ワンライナー・スクリプトファイルとも）、透過ラッパーの前置、
`api.github.com` への直接アクセスも塞いでいるが、「塞ぎ得ないものがある」前提で運用する。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

# gh で通す読み取り専用サブコマンド。ここに無いものは全て拒否する。
GH_READONLY = {
    ("pr", "view"), ("pr", "diff"), ("pr", "checks"), ("pr", "list"), ("pr", "status"),
    ("issue", "view"), ("issue", "list"),
    ("run", "view"), ("run", "list"),
    ("repo", "view"),
    ("release", "view"), ("release", "list"),
    ("search", "prs"), ("search", "issues"), ("search", "code"), ("search", "repos"),
    ("cache", "list"),
}

# git の書き込み系サブコマンド。
GIT_WRITE = {
    "push", "commit", "merge", "rebase", "reset", "revert", "tag", "checkout",
    "switch", "cherry-pick", "clean", "am", "apply", "restore", "stash",
    "fetch", "pull", "clone", "remote", "config", "gc", "prune", "worktree",
    "update-ref", "symbolic-ref", "filter-branch", "notes", "submodule",
}

# 任意コードを実行でき、文字列照合を無意味にするもの。
INTERPRETERS = {
    "python", "python3", "python2", "node", "nodejs", "deno", "bun",
    "ruby", "perl", "php", "osascript", "sh", "bash", "zsh", "fish", "ksh",
}
INTERPRETER_EVAL_FLAGS = {"-c", "-e", "--eval", "--exec", "-E"}

# gh を介さず GitHub API へ到達する経路。
HTTP_CLIENTS = {"curl", "wget", "http", "httpie", "xh"}

# 引数を別コマンドとして実行する透過ラッパー。1 語前置しただけで判定を外れるため、
# 実際のコマンドに辿り着くまで再帰的に読み飛ばす。
WRAPPERS = {
    "env", "command", "builtin", "exec", "nice", "nohup", "time", "timeout",
    "xargs", "stdbuf", "sudo", "doas", "setsid", "ionice", "watch", "nocorrect",
    "noglob", "script",
}

# python -m <module> の形でだけ許す module。レビュアーはテストと lint を回す。
SAFE_PYTHON_MODULES = {"pytest", "ruff"}

SHELL_OPERATORS = ("&&", "||", ";", "|", "&", "\n")


def deny(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def segments(command: str) -> list[str]:
    """シェル演算子とコマンド置換で分割する。

    `)` を一律で区切りにすると `grep -n "def main()"` のような通常の読み取りが
    引用符ごと分断され、shlex が失敗して fail-closed で拒否されてしまう。
    コマンド置換は `$(...)` と `` `...` `` の対応した組だけを狙い、中身は
    独立したセグメントとして残して検査対象にする。
    """
    text = re.sub(r"\$\(([^()]*)\)", r" ; \1 ; ", command)
    text = re.sub(r"`([^`]*)`", r" ; \1 ; ", text)
    for op in SHELL_OPERATORS:
        text = text.replace(op, "\n")
    return [s for s in (line.strip() for line in text.split("\n")) if s]


def unwrap(args: list[str]) -> list[str]:
    """環境変数代入と透過ラッパーを読み飛ばし、実際に動くコマンドを返す。

    `env gh pr merge` `timeout 10 gh pr review` `FOO=bar gh ...` のように、
    1 語足すだけで判定を外れるのを防ぐ。
    """
    rest = list(args)
    changed = True
    while changed and rest:
        changed = False

        # VAR=VAL の連なり（env なしの前置代入）
        while rest and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", rest[0]):
            rest.pop(0)
            changed = True

        if rest and program_name(rest[0]) in WRAPPERS:
            rest.pop(0)
            changed = True
            # ラッパー自身のオプション・秒数・代入を飛ばす
            while rest and (
                rest[0].startswith("-")
                or re.fullmatch(r"\d+(\.\d+)?[smhd]?", rest[0])
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", rest[0])
            ):
                rest.pop(0)
    return rest


def program_name(token: str) -> str:
    """`/usr/bin/gh` `\\gh` `'gh'` などから実行ファイル名を取り出す。"""
    return os.path.basename(token.lstrip("\\").strip("'\"")).lower()


def skip_global_options(args: list[str], takes_value: set[str]) -> list[str]:
    """サブコマンドの前に置かれるグローバルオプションを読み飛ばす。"""
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            return args[i:]
        if arg in takes_value:
            i += 2
        else:
            i += 1
    return []


def check_gh(args: list[str], raw: str) -> None:
    rest = skip_global_options(args, {"-R", "--repo", "--hostname"})
    if not rest:
        deny("レビュアーは gh の書き込み操作を実行できません（読み取り専用のみ許可）。")

    # gh api はボディを付けると -X なしで POST になる。読み取りは gh pr で足りるため丸ごと拒否する。
    if rest[0] == "api":
        deny(
            "レビュアーは gh api を実行できません。"
            "-f/--input を付けるとメソッド指定なしで POST になるため全面的に拒否しています。"
            "差分は gh pr diff を使ってください。"
        )

    sub = tuple(a for a in rest if not a.startswith("-"))[:2]
    if sub not in GH_READONLY:
        deny(
            f"レビュアーは `gh {' '.join(sub)}` を実行できません（読み取り専用のみ許可）。"
            "PR への投稿はメイン Agent が行います。"
        )


def check_git(args: list[str]) -> None:
    rest = skip_global_options(args, {"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
    if not rest:
        return
    if rest[0].lower() in GIT_WRITE:
        deny(
            f"レビュアーは `git {rest[0]}` を実行できません。"
            "指摘と修正案の報告のみ行ってください。"
        )


def check_interpreter(program: str, args: list[str]) -> None:
    """インタプリタの起動を拒否する。

    ワンライナーだけでなく**スクリプトファイルの実行も**塞ぐ。レビュアーは
    Bash でヒアドキュメントからファイルを作れるため、ファイル実行を許すと
    文字列照合による制限がすべて無意味になる。

    例外は `python -m pytest` / `python -m ruff` のみ。レビュアーが
    テストと lint を回せる必要があるため。
    """
    positional = [a for a in args if not a.startswith("-")]
    if "-m" in args and positional and positional[0] in SAFE_PYTHON_MODULES:
        return
    if any(a in INTERPRETER_EVAL_FLAGS for a in args):
        deny(
            f"レビュアーは {program} のワンライナー実行を使えません。"
            "任意コードを実行できるため、書き込みの制限を回避できてしまいます。"
        )
    deny(
        f"レビュアーは {program} を起動できません。"
        "任意コードを実行できるため、書き込みの制限を回避できてしまいます。"
        "テストと lint は .venv/bin/pytest / .venv/bin/ruff を直接使ってください。"
    )


def check_http(raw: str) -> None:
    if "api.github.com" in raw or "uploads.github.com" in raw:
        deny("レビュアーは GitHub API へ直接アクセスできません。")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
    except Exception:
        deny("hook が入力を解釈できませんでした（安全側に倒して拒否します）。")

    if not isinstance(command, str) or not command.strip():
        deny("hook がコマンドを解釈できませんでした（安全側に倒して拒否します）。")

    # 投稿スクリプトは gh を介さないため、パスの書き方によらず文字列で弾く。
    if "post_review.py" in command:
        deny(
            "レビュアーは PR へ投稿できません。"
            "指摘は報告として返してください。投稿はメイン Agent が行います。"
        )

    for segment in segments(command):
        try:
            args = shlex.split(segment)
        except ValueError:
            deny("hook がコマンドを解釈できませんでした（安全側に倒して拒否します）。")
        if not args:
            continue

        args = unwrap(args)
        if not args:
            continue

        program = program_name(args[0])
        rest = args[1:]

        if program == "gh":
            check_gh(rest, segment)
        elif program == "git":
            check_git(rest)
        elif program in INTERPRETERS:
            check_interpreter(program, rest)
        elif program in HTTP_CLIENTS:
            check_http(segment)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # 予期しない例外でも素通りさせない
        # exit 1 は「非ブロックのエラー」として扱われ、コマンドが実行されてしまう。
        # 境界が黙って無効化されるのを防ぐため、必ず exit 2 で拒否する。
        deny(f"hook が予期しないエラーで停止しました（安全側に倒して拒否します）: {type(exc).__name__}")
