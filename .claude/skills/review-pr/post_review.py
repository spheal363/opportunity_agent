#!/usr/bin/env python3
"""レビュー結果を GitHub の PR Review として投稿する。

複数の inline comment を **1 つの Review** としてまとめて投稿する
（POST /repos/{owner}/{repo}/pulls/{n}/reviews の comments 配列）。
1 件ずつ投稿すると通知が分散し、Review 単位の判定も付かないため。

inline comment を付けられるのは diff に含まれる行だけ。範囲外の行を指定すると
API が 422 を返して Review 全体が失敗する。そのため投稿前に diff を解析し、
付けられない Finding は Review 本文へ退避する。

指摘への返信は **スレッドごと**に投稿する（`reply`）。1 つのコメントに全件を
まとめると読みづらく、`Resolve conversation` も指摘単位で押せない。

使い方:

    # レビューを投稿する
    post_review.py review --pr 3 --event COMMENT \\
        --body-file summary.md --findings findings.json [--dry-run]

    # 指摘ごとに返信する（スレッド id は pr_context.py threads で取る）
    post_review.py reply --pr 3 --replies replies.json [--dry-run]

replies.json は以下の配列:

    [{"comment_id": 4052670690, "body": "対応しました。..."}]

findings.json は以下の配列:

    [
      {
        "path": "backend/ai/llm.py",
        "line": 42,
        "side": "RIGHT",
        "severity": "Critical",
        "title": "例外に入力値が載る",
        "body": "問題: ...\\n根拠: ...\\n推奨修正: ..."
      }
    ]

side を省略すると RIGHT（変更後）。line を省略した Finding は必ず Fallback。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field

SEVERITY_ORDER = ["Critical", "High", "Major", "Medium", "Low", "Minor"]
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffIndex:
    """path -> side -> コメントを付けられる行番号の集合。"""

    right: dict[str, set[int]] = field(default_factory=dict)
    left: dict[str, set[int]] = field(default_factory=dict)

    def allows(self, path: str, line: int, side: str) -> bool:
        table = self.right if side == "RIGHT" else self.left
        return line in table.get(path, set())

    def paths(self) -> set[str]:
        return set(self.right) | set(self.left)


def parse_diff(diff: str) -> DiffIndex:
    """unified diff から、コメント可能な行を拾う。

    RIGHT: 追加行（+）と文脈行（空白）
    LEFT : 削除行（-）と文脈行（空白）
    """
    index = DiffIndex()
    path: str | None = None
    old_path: str | None = None
    deleted = False
    old_no = new_no = 0
    in_hunk = False

    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, old_path, deleted, in_hunk = None, None, False, False
            continue
        if raw.startswith("--- "):
            source = raw[4:].strip()
            old_path = None if source == "/dev/null" else source.removeprefix("a/")
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            # 全体削除されたファイルは +++ が /dev/null。--- 側のパスで LEFT だけ登録する。
            deleted = target == "/dev/null"
            path = old_path if deleted else target.removeprefix("b/")
            continue

        m = _HUNK.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            in_hunk = True
            continue

        if not in_hunk or path is None:
            continue
        if raw.startswith("\\"):  # \ No newline at end of file
            continue

        marker = raw[:1]
        if marker == "+":
            index.right.setdefault(path, set()).add(new_no)
            new_no += 1
        elif marker == "-":
            index.left.setdefault(path, set()).add(old_no)
            old_no += 1
        elif marker == " " or raw == "":
            if not deleted:
                index.right.setdefault(path, set()).add(new_no)
            index.left.setdefault(path, set()).add(old_no)
            old_no += 1
            new_no += 1
        else:
            in_hunk = False

    return index


def _gh(args: list[str], stdin: str | None = None) -> str:
    res = subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        sys.exit(f"gh {' '.join(args)} が失敗しました:\n{res.stderr.strip()}")
    return res.stdout


def comment_body(f: dict) -> str:
    """inline comment の本文。1 件で完結させ、独立した conversation として扱えるようにする。"""
    parts = [f"**[{f.get('severity', '?')}] {f.get('title', '').strip()}**".rstrip(), ""]
    parts.append(f.get("body", "").strip())
    return "\n".join(parts).strip()


def split(findings: list[dict], index: DiffIndex) -> tuple[list[dict], list[tuple[dict, str]]]:
    inline: list[dict] = []
    fallback: list[tuple[dict, str]] = []

    for f in findings:
        path, line = f.get("path"), f.get("line")
        side = (f.get("side") or "RIGHT").upper()

        if not path:
            fallback.append((f, "ファイルを特定できない指摘"))
        elif line is None:
            fallback.append((f, "行を特定できない指摘"))
        elif path not in index.paths():
            fallback.append((f, "この PR の差分に含まれないファイル"))
        elif not index.allows(path, int(line), side):
            fallback.append((f, f"{path}:{line} は diff の範囲外"))
        else:
            inline.append(
                {"path": path, "line": int(line), "side": side, "body": comment_body(f)}
            )
    return inline, fallback


def counts(findings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.get("severity", "Unknown")] = out.get(f.get("severity", "Unknown"), 0) + 1
    return out


def fallback_section(fallback: list[tuple[dict, str]]) -> str:
    if not fallback:
        return ""
    lines = [
        "",
        "---",
        "",
        "### inline comment を付けられなかった指摘",
        "",
        "diff の範囲外などの理由で該当行へ紐づけられなかったものです。",
        "",
    ]
    for f, reason in fallback:
        loc = f.get("path") or "（ファイル不明）"
        if f.get("line"):
            loc += f":{f['line']}"
        lines.append(f"**[{f.get('severity', '?')}] {loc}** — {f.get('title', '').strip()}")
        lines.append(f"（{reason}）")
        lines.append("")
        lines.append(f.get("body", "").strip())
        lines.append("")
    return "\n".join(lines)


def load_findings(path: str | None) -> list[dict]:
    """findings JSON を読む。壊れていたら理由が分かる形で落とす。

    書くのは LLM なので、キー欠落や JSON 崩れは現実に起こる。
    スタックトレースではなく直せるメッセージにする。
    """
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        sys.exit(f"findings が見つかりません: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"findings が JSON として不正です: {path}\n  {exc}")
    if not isinstance(data, list):
        sys.exit(f"findings は配列である必要があります: {path}")
    for i, f in enumerate(data):
        if not isinstance(f, dict):
            sys.exit(f"findings[{i}] がオブジェクトではありません")
        if not str(f.get("body", "")).strip():
            sys.exit(f"findings[{i}] に body がありません（path={f.get('path')}）")
    return data


def load_replies(path: str) -> list[dict]:
    """replies JSON を読む。壊れていたら理由が分かる形で落とす。"""
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        sys.exit(f"replies が見つかりません: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"replies が JSON として不正です: {path}\n  {exc}")
    if not isinstance(data, list):
        sys.exit(f"replies は配列である必要があります: {path}")
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            sys.exit(f"replies[{i}] がオブジェクトではありません")
        if not isinstance(r.get("comment_id"), int):
            sys.exit(f"replies[{i}] の comment_id が整数ではありません")
        if not str(r.get("body", "")).strip():
            sys.exit(f"replies[{i}] に body がありません（comment_id={r.get('comment_id')}）")
    return data


def cmd_review(args: argparse.Namespace) -> None:
    findings = load_findings(args.findings)
    findings.sort(
        key=lambda f: SEVERITY_ORDER.index(f["severity"])
        if f.get("severity") in SEVERITY_ORDER
        else len(SEVERITY_ORDER)
    )

    # 行の妥当性は **PR 全体の差分** で決まる（再レビューで範囲を絞っても同じ）。
    index = parse_diff(_gh(["pr", "diff", str(args.pr)]))
    inline, fallback = split(findings, index)

    with open(args.body_file, encoding="utf-8") as fp:
        body = fp.read().rstrip() + fallback_section(fallback)
    repo = json.loads(_gh(["repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]
    payload = {"event": args.event, "body": body, "comments": inline}

    if args.dry_run:
        print(f"POST /repos/{repo}/pulls/{args.pr}/reviews")
        print(f"  event    : {args.event}")
        print(f"  severity : {counts(findings) or '指摘なし'}")
        print(f"  inline   : {len(inline)} 件")
        for c in inline:
            print(f"      {c['path']}:{c['line']} ({c['side']}) {c['body'].splitlines()[0]}")
        print(f"  fallback : {len(fallback)} 件")
        for f, reason in fallback:
            print(f"      {f.get('path')}:{f.get('line')} — {reason}")
        print(f"  body     : {len(body)} 文字")
        return

    res = json.loads(
        _gh(
            ["api", "--method", "POST", f"repos/{repo}/pulls/{args.pr}/reviews", "--input", "-"],
            stdin=json.dumps(payload),
        )
    )
    print(f"投稿しました: {res.get('html_url')}")
    print(f"  event={args.event}  inline={len(inline)}  fallback={len(fallback)}")


def cmd_reply(args: argparse.Namespace) -> None:
    """各指摘スレッドへ個別に返信する。

    1 つのコメントに全件まとめると読みづらく、指摘単位で
    Resolve conversation も押せなくなる。
    """
    replies = load_replies(args.replies)
    repo = json.loads(_gh(["repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]

    if args.dry_run:
        print(f"POST /repos/{repo}/pulls/{args.pr}/comments/<id>/replies  × {len(replies)}")
        for r in replies:
            head = r["body"].strip().splitlines()[0][:60]
            print(f"      id={r['comment_id']}  {len(r['body'])} 文字  {head}")
        return

    for r in replies:
        out = _gh(
            [
                "api", "--method", "POST",
                f"repos/{repo}/pulls/{args.pr}/comments/{r['comment_id']}/replies",
                "--input", "-",
            ],
            stdin=json.dumps({"body": r["body"]}),
        )
        url = json.loads(out).get("html_url", "")
        print(f"  返信しました id={r['comment_id']}  {url}")
    print(f"{len(replies)} 件のスレッドへ返信しました。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("review", help="レビューを inline comments つきで投稿する")
    r.add_argument("--pr", required=True, type=int)
    r.add_argument("--event", required=True, choices=["APPROVE", "REQUEST_CHANGES", "COMMENT"])
    r.add_argument("--body-file", required=True)
    r.add_argument("--findings", help="findings JSON。省略時は指摘なし")
    r.add_argument("--dry-run", action="store_true", help="投稿せず内容を表示する")
    r.set_defaults(func=cmd_review)

    p = sub.add_parser("reply", help="指摘スレッドごとに返信する")
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--replies", required=True, help="replies JSON")
    p.add_argument("--dry-run", action="store_true", help="投稿せず内容を表示する")
    p.set_defaults(func=cmd_reply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
