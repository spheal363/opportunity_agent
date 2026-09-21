"""修正後の prompt で、抽出が正しくなるかを確かめる（#65）。

**4 回は予備確認。品質保証ではない。**

    .venv/bin/python -m scripts.verify_extraction_prompt <実験ディレクトリ>
    .venv/bin/python -m scripts.verify_extraction_prompt <実験ディレクトリ> --confirm

## 保存された messages をそのまま投げない

保存されているのは**旧 prompt** の messages。今回確かめたいのは修正後の
prompt なので、保存された**ページ本文だけ**を取り出し、現在の prompt で
組み直す。検索も本文取得もやり直さない。

## 何の機会として抽出するかで期待値が変わる

  isct   ハッカソンへの**参加**。応募締切がそのまま参加の締切
  xsum   イベントへの**一般参加**。登壇者募集の締切は参加の締切ではない

**「speaker か unknown なら一律合格」とはしない。** 一般参加の機会として
抽出する以上、登壇者募集の締切で閉じないことが要件になる。

Retry・Fallback は無効。失敗も結果として記録する。
キーと認証情報は表示しない。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from ai import availability, evidence
from ai.llm import _extract_json
from ai.orcarouter import LLMRequestError, ModelTier, OrcaRouterClient
from ai.prompts import extraction as prompt
from ai.schemas.extraction import MAX_PAGE_CONTENT_CHARS as LIMIT
from ai.schemas.extraction import CostKind, DeadlineKind, ExtractedOpportunity
from config import get_settings

JST = timezone(timedelta(hours=9))
REPEATS = 2

# **早割の期限をまたいで評価する。** 日付が進んだときの誤除外を見るため。
_TIME_POINTS = {
    "9/21（早割の前）": datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    "10/3（早割の後）": datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
}
TODAY = date(2026, 9, 21)  # A の run と同じ日付を渡す


@dataclass(frozen=True)
class Expectation:
    """その機会に対して**何を期待するか**。"""

    label: str
    action: str  # 推薦する行動
    must: dict  # 満たさなければ不合格
    should: dict  # 望ましい（満たさなくても不合格にしない）
    must_not_close: bool = False


EXPECTATIONS = {
    "https://www.isct.ac.jp/ja/news/mfgtg8c86wg2": Expectation(
        label="三大学合同ハッカソン",
        action="ハッカソンへ**参加**する",
        must={
            "deadline_date": date(2026, 2, 9),  # 入力に明記。**落としてはいけない**
            "deadline_kind": {DeadlineKind.APPLICATION, DeadlineKind.REGISTRATION},
            "deadline_is_date_only": True,  # 入力に時刻は無い
            "cost": 0,
            "cost_kind": {CostKind.FREE},
            "start_at": datetime(2026, 3, 14, 14, 0, tzinfo=JST),
            "availability": availability.Availability.CLOSED,
        },
        should={"end_at": datetime(2026, 3, 16, 11, 30, tzinfo=JST)},
    ),
    "https://www.xsum.jp/gai": Expectation(
        label="GenAI/SUM",
        action="イベントへ**一般参加**する",
        must={
            # 参加の申込期限は入力に**書かれていない**
            "deadline_kind_not": {DeadlineKind.APPLICATION, DeadlineKind.REGISTRATION},
            "cost": None,  # 区分で額が違う。**0 にしてはいけない**
            "cost_kind_not": {CostKind.FREE},
            "no_invented_times": True,
        },
        should={"deadline": None, "deadline_kind": {DeadlineKind.UNKNOWN}},
        must_not_close=True,
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    directory = Path(args.directory).resolve()
    run = json.loads((directory / "run.json").read_text())
    targets = _targets(run, directory)

    _plan(targets)
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0
    if not get_settings().orcarouter_api_key:
        print("ORCAROUTER_API_KEY が未設定です。")
        return 1

    client = OrcaRouterClient()
    try:
        results = [_one(client, t, attempt) for t in targets for attempt in range(1, REPEATS + 1)]
    finally:
        client.close()

    (directory / "prompt-verification.json").write_text(
        json.dumps(
            {"at": datetime.now(UTC).isoformat(), "results": results}, ensure_ascii=False, indent=2
        )
    )
    _report(results)
    return 0


def _targets(run: dict, directory: Path) -> list[dict]:
    """対象と、**直近の実測費用**を集める。

    A の run のトークン数から出すと低く見積もる。同じ入力でも出力長は
    実行ごとに変わり、予備実験の再実行では約 2 倍になった。
    **新しい測定があればそちらを使う。**
    """
    recent = _recent_costs(directory)
    out = []
    for call in run["llm_calls"]:
        if call["step"] != "extraction":
            continue
        url, content = _split(call["messages"][1]["content"])
        if url in EXPECTATIONS:
            out.append(
                {
                    "url": url,
                    "content": content,
                    "measured_jpy": recent.get(url) or _jpy(call["usage"]),
                    "measured_from": "直近の実費" if url in recent else "A run のトークン",
                }
            )
    return out


def _recent_costs(directory: Path) -> dict[str, float]:
    """予備実験で取れた実費（USD）を円へ。**為替 150 は仮定。**"""
    path = directory / "reasoning-comparison-extraction.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    urls = list(EXPECTATIONS)
    out: dict[str, float] = {}
    for r in data["results"]:
        if r.get("effort") != "current" or r.get("cost_usd") is None:
            continue
        # index は 1 始まりで、--index 2,18 の順に isct / xsum
        url = urls[r["index"] - 1] if r["index"] - 1 < len(urls) else None
        if url:
            out[url] = r["cost_usd"] * 150.0
    return out


def _split(user_message: str) -> tuple[str, str]:
    """保存された user メッセージから、URL とページ本文を取り出す。"""
    body = user_message.split("<page_content>\n", 1)[1].split("\n</page_content>", 1)[0]
    head, _, content = body.partition("\n\n")
    return head.replace("取得元 URL:", "").strip(), content


def _jpy(usage: dict | None) -> float:
    if not usage:
        return 0.0
    return (usage["prompt_tokens"] * 45.0 + usage["completion_tokens"] * 375.0) / 1e6


def _plan(targets: list[dict]) -> None:
    n = len(targets) * REPEATS
    est = sum(t["measured_jpy"] for t in targets) * REPEATS
    print("=== 実行計画（**参考額。厳密な最大費用ではない**）===")
    print(f"  対象          {len(targets)} 件 x {REPEATS} 回 = {n} リクエスト")
    print("  Retry / Fallback  **どちらも無効**。失敗も結果として記録する")
    print("  prompt        **修正後を組み直す**（保存された旧 messages は使わない）")
    for t in targets:
        print(f"    {t['url'][:52]:54} ¥{t['measured_jpy']:.2f}/回（{t['measured_from']}）")
    print(f"  費用見積もり  約 ¥{est:.2f}（**同じ 2 件の直近実測** x {REPEATS} 回）")
    print("  **訂正**: 以前の「約 ¥2」は工程平均 ¥0.49/回 からの参考額で、")
    print("  この 2 件には低すぎた。同じ入力でも出力長は実行ごとに変わる。")
    print("  検索・本文取得はやり直さない。")
    print()


def _one(client: OrcaRouterClient, target: dict, attempt: int) -> dict:
    content = target["content"][:LIMIT]
    messages = [
        {"role": "system", "content": prompt.SYSTEM},
        {"role": "user", "content": prompt.build_user(target["url"], content, today=TODAY)},
    ]
    started = time.perf_counter()
    try:
        res = client.chat(
            messages,
            tier=ModelTier.STANDARD,
            json_mode=True,
            max_tokens=8192,
            include_cost=True,
        )
    except LLMRequestError as exc:
        return {"url": target["url"], "attempt": attempt, "error": str(exc)}

    raw = res.content
    # **応答は返っているので課金されている。** Schema を通らなかった回を
    # 費用ゼロとして落とさない。使用量が分からない失敗とも区別する。
    usage = {
        "cost_usd": res.usage.cost_usd,
        "request_id": res.usage.request_id,
        "prompt_tokens": res.usage.prompt_tokens,
        "completion_tokens": res.usage.completion_tokens,
        "reasoning_tokens": res.usage.reasoning_tokens,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    try:
        parsed = ExtractedOpportunity.model_validate(json.loads(_extract_json(raw)))
    except Exception as exc:  # noqa: BLE001
        return {
            "url": target["url"],
            "attempt": attempt,
            "raw": raw,
            **usage,
            "error": f"Schema 不通過: {type(exc).__name__}: {exc}",
        }

    grounded = evidence.ground_deadline_kind(parsed, content)
    speaker_opportunity = evidence.is_a_call_for_speakers(grounded.title, grounded.description)

    def at(now: datetime) -> dict:
        status, reason = availability.from_dates(
            opportunity_type=grounded.type,
            deadline=grounded.deadline,
            end_at=grounded.end_at,
            now=now,
            deadline_kind=grounded.deadline_kind,
            deadline_is_date_only=grounded.deadline_is_date_only,
            speaker_is_the_opportunity=speaker_opportunity,
        )
        return {"availability": str(status), "reason": reason}

    return {
        "url": target["url"],
        "attempt": attempt,
        **usage,
        "raw": raw,
        "normalized": grounded.model_dump(mode="json"),
        "downgraded": grounded.deadline_kind != parsed.deadline_kind,
        "raw_kind": parsed.deadline_kind.value,
        "evidence_notes": evidence.check(grounded, content),
        "speaker_opportunity": speaker_opportunity,
        # **日付が進んでも誤って閉じないかを見る。**
        "at": {label: at(when) for label, when in _TIME_POINTS.items()},
        "content": content,
    }


def _report(results: list[dict]) -> None:
    for r in results:
        exp = EXPECTATIONS[r["url"]]
        print(f"========== {exp.label}  {r['attempt']} 回目 ==========")
        print(f"  推薦する行動: {exp.action}")
        if "error" in r:
            print(f"  **失敗** {r['error']}")
            print()
            continue

        n = r["normalized"]
        print(f"  モデルの生出力: {r['raw'][:260].replace(chr(10), ' ')}")
        print()
        print("  正規化後:")
        for f in ("start_at", "end_at", "deadline", "cost"):
            flag = n.get(f"{f}_is_date_only")
            mark = "（日付のみ）" if flag else ""
            print(f"    {f:9} {n.get(f)!s:34}{mark}")
        print(
            f"    {'deadline_kind':9} {n['deadline_kind']}"
            f"{'  **根拠が入力に無く unknown へ**' if r['downgraded'] else ''}"
        )
        print(f"    {'cost_kind':9} {n['cost_kind']}")
        print(f"    根拠の表記  {n.get('deadline_quote')!r}")
        if r["evidence_notes"]:
            print(f"    **入力と合わない点**: {r['evidence_notes']}")
        print()
        if r["speaker_opportunity"]:
            print("  **登壇機会そのもの**と判定 -> 登壇締切が行動を閉ざす")
        for label, out in r["at"].items():
            print(f"  受付状況 {label}  {out['availability']}  {out['reason'] or ''}")
        print(
            f"  画面表示  日程 {_date_label(n, 'start_at')} / "
            f"{_deadline_label(n)} / 参加費 {_cost_label(n)}"
        )
        print()
        _judge(r, exp)
        print()


def _date_label(n: dict, field: str) -> str:
    value = n.get(field)
    if not value:
        return "日時未定"
    return value[:10] if n.get(f"{field}_is_date_only") else value


def _deadline_label(n: dict) -> str:
    kind = {
        "application": "応募締切",
        "registration": "参加申込の期限",
        "early_bird": "早割の期限",
        "speaker": "登壇者募集の締切",
        "other": "締切",
        "unknown": "締切（対象は要確認）",
    }.get(n["deadline_kind"], "締切")
    return f"{kind} {_date_label(n, 'deadline')}"


def _cost_label(n: dict) -> str:
    if n.get("cost") is not None:
        return "無料" if n["cost"] == 0 else f"{n['cost']}円"
    return {"partially_free": "一部無料・区分により異なる", "paid": "有料（金額は要確認）"}.get(
        n["cost_kind"], "参加費未確認"
    )


def _judge(r: dict, exp: Expectation) -> None:
    n = r["normalized"]
    fails: list[str] = []
    notes: list[str] = []

    if "deadline_date" in exp.must:
        got = n.get("deadline")
        want = exp.must["deadline_date"]
        if not got or datetime.fromisoformat(got).astimezone(JST).date() != want:
            fails.append(f"**入力にある締切 {want} が落ちた**（{got}）")
    if "deadline_kind" in exp.must and n["deadline_kind"] not in {
        k.value for k in exp.must["deadline_kind"]
    }:
        fails.append(f"締切の区分が {n['deadline_kind']}")
    if "deadline_kind_not" in exp.must and n["deadline_kind"] in {
        k.value for k in exp.must["deadline_kind_not"]
    }:
        fails.append(f"**参加の締切ではないものを {n['deadline_kind']} とした**")
    if (
        "deadline_is_date_only" in exp.must
        and bool(n.get("deadline_is_date_only")) != exp.must["deadline_is_date_only"]
    ):
        fails.append("締切の日付のみ/時刻ありの判定が違う")
    if "cost" in exp.must and n.get("cost") != exp.must["cost"]:
        fails.append(f"参加費が {n.get('cost')}（期待 {exp.must['cost']}）")
    if "cost_kind" in exp.must and n["cost_kind"] not in {k.value for k in exp.must["cost_kind"]}:
        fails.append(f"料金区分が {n['cost_kind']}")
    if "cost_kind_not" in exp.must and n["cost_kind"] in {
        k.value for k in exp.must["cost_kind_not"]
    }:
        fails.append(f"**有料の催しを {n['cost_kind']} とした**")
    if "start_at" in exp.must:
        got = n.get("start_at")
        want = exp.must["start_at"]
        if not got or datetime.fromisoformat(got) != want:
            fails.append(f"開始日時が {got}（期待 {want.isoformat()}）")
    closed = str(availability.Availability.CLOSED)
    if "availability" in exp.must:
        # **終了した機会を除外できたか。** 全時点で closed であること。
        bad = [k for k, v in r["at"].items() if v["availability"] != str(exp.must["availability"])]
        if bad:
            fails.append(f"受付状況が期待と違う時点: {bad}（期待 {exp.must['availability']}）")
    if exp.must_not_close:
        # **誤除外を防げたか。** どの時点でも閉じないこと。
        bad = [k for k, v in r["at"].items() if v["availability"] == closed]
        if bad:
            fails.append(f"**一般参加の機会を閉じた時点**: {bad}")
    if exp.must.get("no_invented_times") and r["evidence_notes"]:
        fails.append(f"入力に無い値: {r['evidence_notes']}")

    for key, want in exp.should.items():
        got = n.get(key)
        if isinstance(want, set):
            ok = got in {k.value for k in want}
        elif isinstance(want, datetime):
            ok = bool(got) and datetime.fromisoformat(got) == want
        else:
            ok = got == want
        if not ok:
            notes.append(f"{key} は {got}（望ましいのは {want}）")

    # **unknown は受付中ではない。** 誤除外を防げたことと、受付中と確認できた
    # ことは別。ここで言えるのは前者だけ。
    if exp.must_not_close and not fails:
        print("  （誤除外は防げた。**受付中と確認できたわけではない**）")
    print(f"  判定: {'**不合格**' if fails else '合格'}")
    for f in fails:
        print(f"    x {f}")
    for note in notes:
        print(f"    - {note}")


if __name__ == "__main__":
    sys.exit(main())
