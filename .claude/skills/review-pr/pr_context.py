#!/usr/bin/env python3
"""レビューに必要な文脈を読み取る。**書き込みは一切しない。**

投稿は post_review.py が担当する。読み取りと書き込みを別スクリプトに分けて
あるのは、読み取りを permissions の allow に、書き込みを ask に置けるようにするため。

## scope — どこをレビューすべきか

初回は PR の全差分。**再レビューでは前回レビュー以降の差分だけ**を対象にする。
全文を読み直すとトークンを無駄に使い、既に指摘した箇所を再指摘してしまう。

    pr_context.py scope --pr 2

前回レビューの commit_id（GitHub が review ごとに保持している）から HEAD までを
範囲として出す。レビューが無ければ base...HEAD。

## threads — 既存の指摘スレッド

    pr_context.py threads --pr 2

各 inline comment の id / path / line / 解決済みかどうかを出す。
返信は「スレッドごと」に行うため、この id が必要になる。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _gh(args: list[str], stdin: str | None = None) -> str:
    res = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        sys.exit(f"gh {' '.join(args)} が失敗しました:\n{res.stderr.strip()}")
    return res.stdout


def repo_slug() -> str:
    return json.loads(_gh(["repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]


def cmd_scope(args: argparse.Namespace) -> None:
    pr = json.loads(
        _gh(
            [
                "pr",
                "view",
                str(args.pr),
                "--json",
                "number,state,baseRefName,headRefName,headRefOid,changedFiles,additions,deletions",
            ]
        )
    )
    slug = repo_slug()
    reviews = json.loads(_gh(["api", f"repos/{slug}/pulls/{args.pr}/reviews"]))

    # 自分が以前に投稿したレビューのうち、最後のものの commit_id を起点にする。
    mine = [r for r in reviews if r.get("commit_id")]
    last = mine[-1] if mine else None
    head = pr["headRefOid"]

    print(f"PR #{pr['number']}  {pr['state']}  {pr['headRefName']} -> {pr['baseRefName']}")
    print(f"  head            : {head[:12]}")
    print(f"  全体の差分      : {pr['changedFiles']} files  +{pr['additions']} / -{pr['deletions']}")
    print(f"  過去のレビュー  : {len(reviews)} 件")

    if last is None:
        print()
        print("  → 初回レビュー。PR の全差分を対象にする。")
        print(f"     gh pr diff {args.pr}")
        return

    base = last["commit_id"]
    print(f"  前回レビュー    : {last['state']} @ {base[:12]}  ({last.get('submitted_at')})")

    if base == head:
        print()
        print("  → 前回レビュー以降、新しい commit はない。再レビュー不要。")
        return

    rng = f"{base}...{head}"
    changed = _gh(["api", f"repos/{slug}/compare/{base}...{head}", "--jq", ".files[].filename"])
    files = [f for f in changed.splitlines() if f]
    print()
    print("  → 再レビュー。**前回以降の差分だけ**を対象にする。")
    print(f"     git diff {rng}")
    print(f"     変更されたファイル: {len(files)} 件")
    for f in files:
        print(f"       {f}")
    print()
    print("  注: inline comment を付けられる行は PR 全体の差分で決まる。")
    print("      レビュー範囲は上の range、行の妥当性は post_review.py が判定する。")


_THREADS_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100) {
        nodes {
          isResolved
          isOutdated
          path
          line
          originalLine
          comments(first:1) {
            nodes { databaseId author { login } body }
          }
        }
      }
    }
  }
}
"""


def cmd_threads(args: argparse.Namespace) -> None:
    owner, name = repo_slug().split("/")
    out = _gh(
        [
            "api", "graphql",
            "-f", f"query={_THREADS_QUERY}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
            "-F", f"number={args.pr}",
        ]
    )
    nodes = json.loads(out)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    if not nodes:
        print("inline comment スレッドはありません。")
        return

    open_threads = [n for n in nodes if not n["isResolved"]]
    print(f"スレッド {len(nodes)} 件（未解決 {len(open_threads)} 件）")
    print()
    for n in nodes:
        c = (n["comments"]["nodes"] or [{}])[0]
        state = "resolved" if n["isResolved"] else "OPEN    "
        outdated = " [outdated]" if n["isOutdated"] else ""
        line = n["line"] or n["originalLine"]
        head = (c.get("body") or "").splitlines()[0][:70]
        print(f"  {state} id={c.get('databaseId')}  {n['path']}:{line}{outdated}")
        print(f"           {head}")
    print()
    print("返信は post_review.py reply --pr N --replies replies.json（スレッドごと）。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scope", help="レビュー対象の範囲を出す")
    s.add_argument("--pr", required=True, type=int)
    s.set_defaults(func=cmd_scope)

    t = sub.add_parser("threads", help="既存の指摘スレッドを一覧する")
    t.add_argument("--pr", required=True, type=int)
    t.set_defaults(func=cmd_threads)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
