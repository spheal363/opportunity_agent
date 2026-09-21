"""保存済みの run を、現在の判定ロジックで評価し直す。**API は呼ばない。**

    .venv/bin/python -m scripts.rejudge_run <実験ディレクトリ>

**実行時の結果と、再判定の結果は別に保存する。** 混ぜると「そのとき何が
起きたか」が読めなくなる。

分かるのは受付状況と、その結果として選定対象がどう変わるかまで。
**順位は評価点に依存し、評価はやり直していない**ので、選定対象から外れた
ぶんの繰り上げは未確認。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from ai import availability, evidence
from ai.evaluation import _SERENDIPITY_WEIGHT, TOP_N
from ai.schemas.extraction import ExtractedOpportunity


def main() -> int:
    directory = Path(sys.argv[1]).resolve()
    run = json.loads((directory / "run.json").read_text())
    extracted = _extracted_by_url(run)

    rows = []
    for o in run["opportunities"]:
        item = extracted.get(o["url"])
        before = o["availability"]
        after, reason, kind_before, kind_after = _rejudge(o, item)
        rows.append(
            {
                **{
                    k: o[k]
                    for k in (
                        "opportunity_id",
                        "title",
                        "type",
                        "url",
                        "score",
                        "serendipity_score",
                        "deadline",
                    )
                },
                "availability_at_run": before,
                "availability_now": after,
                "reason_now": reason,
                "deadline_kind_at_run": kind_before,
                "deadline_kind_now": kind_after,
                "changed": before != after,
            }
        )

    selected_before = run["selected_ids"] or []
    actionable = [r for r in rows if availability.is_actionable(r["availability_now"])]
    ranked = sorted(
        actionable,
        key=lambda r: r["score"] + _SERENDIPITY_WEIGHT * r["serendipity_score"],
        reverse=True,
    )
    selected_after = [r["opportunity_id"] for r in ranked[:TOP_N]]

    payload = {
        "at": datetime.now(UTC).isoformat(),
        "source_run": run["run_id"],
        "note": "**再判定。実行時の結果ではない。** 評価はやり直していない",
        "selected_at_run": selected_before,
        "selected_now": selected_after,
        "rows": rows,
    }
    (directory / "rejudged.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _report(payload, rows)
    return 0


def _extracted_by_url(run: dict) -> dict[str, ExtractedOpportunity]:
    """抽出の生出力を URL ごとに読み直し、**原文と突き合わせる。**

    生の出力をそのまま使うと、根拠の検査を通していないことになる。
    実行時は `extract_opportunity` の中で通っている。
    """
    out: dict[str, ExtractedOpportunity] = {}
    for call in run["llm_calls"]:
        if call["step"] != "extraction" or not call.get("response"):
            continue
        url = _source_url(call)
        try:
            item = ExtractedOpportunity.model_validate(json.loads(call["response"]))
        except Exception:  # noqa: BLE001 - 通らなかったものは対象外
            continue
        out[url] = evidence.ground_deadline_kind(item, _page_content(call))
    return out


def _page_content(call: dict) -> str:
    """モデルへ実際に渡したページ本文を取り出す。"""
    body = call["messages"][1]["content"]
    if "<page_content>\n" not in body:
        return ""
    inner = body.split("<page_content>\n", 1)[1].split("\n</page_content>", 1)[0]
    return inner.partition("\n\n")[2]


def _source_url(call: dict) -> str:
    for line in call["messages"][1]["content"].splitlines():
        if line.startswith("取得元 URL:"):
            return line.replace("取得元 URL:", "").strip()
    return ""


def _rejudge(row: dict, item: ExtractedOpportunity | None):
    """**検証で上書きされた open は、そのまま残す。**

    再判定できるのは日付からの判断だけ。ページを読み直していないので、
    検証の結果までは作り直せない。
    """
    kind_before = row.get("deadline_kind")
    kind_after = kind_before
    if item is not None:
        kind_after = item.deadline_kind.value

    status, reason = availability.for_extracted(
        item
        if item is not None
        else SimpleNamespace(
            type=row["type"],
            title=row["title"],
            description=None,
            deadline=_dt(row["deadline"]),
            end_at=_dt(row.get("end_at")),
            deadline_kind=kind_after,
            deadline_is_date_only=bool(row.get("deadline_is_date_only")),
            end_at_is_date_only=bool(row.get("end_at_is_date_only")),
        )
    )
    if status is availability.Availability.CLOSED:
        return status.value, reason, kind_before, kind_after
    # 日付からは閉じられない。実行時の結果を残す（検証の結果を捨てない）。
    return (
        row["availability_at_run"] if "availability_at_run" in row else row["availability"],
        reason,
        kind_before,
        kind_after,
    )


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _report(payload: dict, rows: list[dict]) -> None:
    changed = [r for r in rows if r["changed"]]
    print("=== 再判定（**実行時の結果とは別に保存**）===")
    print(f"  候補 {len(rows)} 件中 {len(changed)} 件で受付状況が変わった\n")
    for r in changed:
        print(f"  {r['title'][:46]}")
        print(f"    {r['availability_at_run']} -> **{r['availability_now']}**  {r['reason_now']}")
        kinds = f"{r['deadline_kind_at_run']} -> {r['deadline_kind_now']}"
        print(f"    締切 {r['deadline']}  区分 {kinds}")
    print()
    print("=== 選定対象 ===")
    print(f"  実行時 {payload['selected_at_run']}")
    if not changed:
        print("  **受付状況が変わっていないので、選定対象も変わらない。**")
        print("  （再判定側の並べ替えは検証・繰り上げを再現していないため、")
        print("   一致しない場合があるが、それは判定の変化ではない）")
        return
    print(f"  再判定 {payload['selected_now']}")
    print("  **変わった。** ただし評価も検証もやり直していないので、")
    print("  繰り上げた候補の評価点は実行時のまま。**順位の妥当性は未確認。**")


if __name__ == "__main__":
    sys.exit(main())
