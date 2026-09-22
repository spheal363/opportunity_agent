"""保存した A の評価入力 14 件を、そのまま Jev へ渡す（#65 の A/B 比較）。

**検索・本文取得・抽出はやり直さない。** A の run で保存した入力を再利用する。

    cd backend && .venv/bin/python -m scripts.compare_jev <実験ディレクトリ>

## これは「本番 B の実測」ではない

A の評価結果を参照して比較の準備をするだけで、**本番 B を走らせたわけでは
ない。** 本番 B なら低確信時に実 LLM へ落ちるので、時間も費用も変わる。
ここで出る数字を B の実測時間・実測費用とは呼ばない。

## フォールバックしない

低確信でも実 LLM を呼ばない。**「本番ならフォールバック対象」と記録する
だけ**にして、追加の LLM 費用を使わずにフォールバック率を測る。

## 入力が同じであることを証明する

保存された評価プロンプトと、DB 行から組み直したプロンプトを**文字列として
突き合わせる。** 一致しなければ「同じ入力」とは言えないので止める。

キーと認証情報は保存も表示もしない。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if len(sys.argv) < 2:
    print("使い方: python -m scripts.compare_jev <実験ディレクトリ>")
    raise SystemExit(2)

_DIR = Path(sys.argv[1]).resolve()
_RUN = json.loads((_DIR / "run.json").read_text())

# --- A と同じ DB を読む。**db.session の import より先に。** ---------------
os.environ["DATABASE_URL"] = f"sqlite:///{_DIR / 'experiment.db'}"

from agent.loop import _as_dict  # noqa: E402
from ai import cost  # noqa: E402
from ai.concurrency import DEFAULT_WORKERS, map_parallel  # noqa: E402
from ai.evaluation import _SERENDIPITY_WEIGHT  # noqa: E402
from ai.jev import questions as q  # noqa: E402
from ai.jev.client import JevClient, JevError  # noqa: E402
from ai.jev.evaluation import _build_state  # noqa: E402
from ai.prompts import evaluation as eval_prompt  # noqa: E402
from config import get_settings  # noqa: E402
from db.session import SessionLocal  # noqa: E402
from models import Opportunity  # noqa: E402


def _goal_and_interests() -> tuple[str, list[str]]:
    """A の評価入力から目標と興味を取り出す。**全件で同じ値。**

    Jev へも同じものを渡す。**片方だけ欠けると「同じ入力」でなくなる。**
    とくに意外性は「本人が自分で探すか」を尋ねる質問なので、興味を渡さないと
    判断の材料そのものが違う。
    """
    head = [c for c in _RUN["llm_calls"] if c["step"] == "evaluation"][0]["messages"][1]["content"]
    goal = _between(head, "目標: ", "\n")
    line = _between(head, "興味の交差点: ", "\n")
    return goal, [x.strip() for x in line.split(",") if x.strip()]


def main() -> int:
    settings = get_settings()
    print("=== 設定（値は表示しない）===")
    print(f"  TYPESAFE_API_KEY   {'設定あり' if settings.typesafe_api_key else '**未設定**'}")
    print(f"  JEV_MODEL          {settings.jev_model}")
    print(f"  閾値               {settings.jev_min_confidence}（**維持する**）")
    print(f"  並列数             {DEFAULT_WORKERS}（**A の評価工程と同じ**）")
    print(f"  EVALUATOR（既定）  {settings.evaluator}（**変えない**）")
    print()
    if not settings.typesafe_api_key:
        print("TYPESAFE_API_KEY が未設定です。")
        return 1

    targets = _match_saved_inputs()
    if targets is None:
        return 1

    print(f"=== Jev へ {len(targets)} 件を投げる（**検索・抽出はやり直さない**）===")
    client = JevClient()
    try:
        results, total_ms = _ask_all(client, targets)
    finally:
        client.close()

    _save(results, total_ms)
    _report(results, total_ms, targets)
    return 0


def _match_saved_inputs() -> list[dict] | None:
    """保存された評価プロンプトと、DB 行から組み直したものを突き合わせる。

    **一致しなければ「同じ入力」とは言えない。** 止める。
    """
    saved = [c for c in _RUN["llm_calls"] if c["step"] == "evaluation"]
    prompts = {c["messages"][1]["content"]: c for c in saved}
    goal, interests = _goal_and_interests()

    db = SessionLocal()
    rows = db.query(Opportunity).all()
    matched: list[dict] = []
    for row in rows:
        payload = _as_dict(row)
        built = eval_prompt.build_user(goal_summary=goal, interests=interests, opportunity=payload)
        call = prompts.pop(built, None)
        if call is None:
            continue
        matched.append(
            {
                "opportunity_id": row.opportunity_id,
                "title": row.title,
                "payload": payload,
                "a_score": row.score,
                "a_serendipity": row.serendipity_score,
                "a_elapsed_ms": call["elapsed_ms"],
                "a_tokens": (call["usage"] or {}).get("prompt_tokens", 0)
                + (call["usage"] or {}).get("completion_tokens", 0),
            }
        )
    db.close()

    print("=== 入力の同一性 ===")
    print(f"  保存された評価入力 {len(saved)} 件")
    print(f"  DB 行から組み直して一致 {len(matched)} 件")
    if prompts:
        print(f"  **一致しなかった保存入力 {len(prompts)} 件**。同じ入力とは言えないため中止。")
        return None
    print("  すべて一致（**A に渡したものと同じ文字列**）\n")
    return matched


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start) + len(start)
    return text[i : text.index(end, i)]


def _ask_all(client: JevClient, targets: list[dict]) -> tuple[list[dict], int]:
    """A の評価工程と同じ並列数で投げる。"""

    goal, interests = _goal_and_interests()

    def one(target: dict) -> dict:
        started = time.perf_counter()
        try:
            res = client.ask(
                # **A に渡したのと同じ目標・興味・候補。**
                _build_state(
                    goal_summary=goal,
                    interest_connections=interests,
                    opportunity=target["payload"],
                ),
                {
                    "relevance": q.relevance_question(),
                    "serendipity": q.serendipity_question(),
                },
            )
        except JevError as exc:
            # **失敗を 0 点として扱わない。** 分からなかったことを分からないと持つ。
            return {**target, "error": str(exc), "status": exc.status_code}

        rel = res.answers.get("relevance")
        ser = res.answers.get("serendipity")
        return {
            **target,
            "jev_elapsed_ms": int((time.perf_counter() - started) * 1000),
            "model": res.model,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "relevance_raw": rel.score if rel else None,
            "relevance": q.to_0_100(rel.score if rel else None, q.RELEVANCE_LEVELS),
            "relevance_confidence": rel.confidence if rel else None,
            "serendipity_raw": ser.score if ser else None,
            "serendipity": q.to_0_100(ser.score if ser else None, q.SERENDIPITY_LEVELS),
            "serendipity_confidence": ser.confidence if ser else None,
        }

    started = time.perf_counter()
    with cost.track() as tracker, cost.step("evaluation"):
        results = map_parallel(targets, one, workers=DEFAULT_WORKERS)
    total_ms = int((time.perf_counter() - started) * 1000)

    _ask_all.tracker = tracker  # type: ignore[attr-defined]
    return results, total_ms


def _would_fall_back(r: dict) -> tuple[bool, str]:
    """本番ならフォールバックするか。**ここでは実 LLM を呼ばない。**"""
    threshold = get_settings().jev_min_confidence
    if "error" in r:
        return True, f"Jev が失敗（{r['error']}）"
    if r["relevance"] < 0 or r["serendipity"] < 0:
        return True, "点が返らなかった（**0 点ではない**）"
    lowest = min(
        r["relevance_confidence"] if r["relevance_confidence"] is not None else 1.0,
        r["serendipity_confidence"] if r["serendipity_confidence"] is not None else 1.0,
    )
    if lowest < threshold:
        which = (
            "関連性"
            if (r["relevance_confidence"] or 1.0) <= (r["serendipity_confidence"] or 1.0)
            else "意外性"
        )
        return True, f"{which}の confidence {lowest:.2f} < {threshold}"
    return False, ""


def _rank(items: list[tuple[str, int, int]]) -> list[str]:
    """A と同じ式で並べる（score + 0.3 x serendipity）。"""
    return [
        i
        for i, _, _ in sorted(items, key=lambda t: t[1] + _SERENDIPITY_WEIGHT * t[2], reverse=True)
    ]


def _save(results: list[dict], total_ms: int) -> None:
    tracker = _ask_all.tracker  # type: ignore[attr-defined]
    path = _DIR / "jev-comparison.json"
    path.write_text(
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                "source_run": _RUN["run_id"],
                "note": "**本番 B の実測ではない。** フォールバックせず Jev だけを呼んだ",
                "threshold": get_settings().jev_min_confidence,
                "workers": DEFAULT_WORKERS,
                "total_ms": total_ms,
                "usage": tracker.to_dict(),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"保存しました: {path}\n")


def _report(results: list[dict], total_ms: int, targets: list[dict]) -> None:
    tracker = _ask_all.tracker  # type: ignore[attr-defined]
    jev = tracker.by_step["evaluation"].jev

    print("=== ② Jev 14 件の実測 ===")
    per = [r["jev_elapsed_ms"] for r in results if "jev_elapsed_ms" in r]
    print(f"  全体          {total_ms} ms（並列 {DEFAULT_WORKERS}）")
    if per:
        print(f"  候補ごと      {min(per)}〜{max(per)} ms（中央 {sorted(per)[len(per) // 2]} ms）")
    print(f"  論理呼び出し  {jev.logical_calls}")
    print(f"  実リクエスト  {jev.request_attempts}  Retry {jev.retries}")
    print(f"  使用量不明    {jev.attempts_without_usage}  （**費用ゼロとは限らない**）")
    print(f"  入力トークン  {jev.input_tokens}")
    print(f"  費用          ${jev.usd:.6f}  （公式単価 x 実トークン。請求額ではない）")
    print(f"  モデル        {jev.models}")
    print()

    print("=== ③ フォールバック対象率（**実 LLM は呼んでいない**）===")
    flags = [(_would_fall_back(r), r) for r in results]
    fb = [(why, r) for (hit, why), r in flags if hit]
    print(f"  {len(fb)} / {len(results)} 件  ({len(fb) / len(results) * 100:.0f}%)")
    for why, r in fb:
        print(f"    {r['title'][:38]:40} {why}")
    print()

    print("=== confidence（関連性と意外性を分けて）===")
    ok = [r for r in results if "error" not in r]
    for label, key in (("関連性", "relevance_confidence"), ("意外性", "serendipity_confidence")):
        vals = [r[key] for r in ok if r[key] is not None]
        if vals:
            print(
                f"  {label}  最小 {min(vals):.2f}  中央 {sorted(vals)[len(vals) // 2]:.2f}  "
                f"最大 {max(vals):.2f}  閾値未満 {sum(1 for v in vals if v < 0.5)} 件"
            )
    print()

    print("=== ④ 候補別の評価差 ===")
    print(f"  {'候補':40} {'A':>12}  {'Jev':>12}  {'差':>10}")
    for r in sorted(results, key=lambda x: -x["a_score"]):
        if "error" in r:
            print(
                f"  {r['title'][:38]:40} {r['a_score']:5}/{r['a_serendipity']:<3}   "
                f"**失敗**（0 点ではない）"
            )
            continue
        print(
            f"  {r['title'][:38]:40} "
            f"{r['a_score']:5}/{r['a_serendipity']:<6} "
            f"{r['relevance']:5}/{r['serendipity']:<6} "
            f"{r['relevance'] - r['a_score']:+4}/{r['serendipity'] - r['a_serendipity']:+4}"
        )
    print()

    print("=== 順位の変化（A と同じ式で並べた場合）===")
    a_order = _rank([(r["opportunity_id"], r["a_score"], r["a_serendipity"]) for r in results])
    j_order = _rank(
        [
            (r["opportunity_id"], max(r.get("relevance", -1), 0), max(r.get("serendipity", -1), 0))
            for r in results
            if "error" not in r
        ]
    )
    titles = {r["opportunity_id"]: r["title"] for r in results}
    print(f"  {'順位':4} {'A':42} {'Jev':42}")
    for i in range(max(len(a_order), len(j_order))):
        a = titles.get(a_order[i], "")[:40] if i < len(a_order) else ""
        j = titles.get(j_order[i], "")[:40] if i < len(j_order) else ""
        mark = "  " if a == j else "<>"
        print(f"  {i + 1:2} {mark} {a:42} {j:42}")


if __name__ == "__main__":
    sys.exit(main())
