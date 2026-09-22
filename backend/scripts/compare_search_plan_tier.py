"""② 検索計画を STANDARD と CHEAP で比べる（#26-b）。

**比べるのは 1 工程だけ。** 目標分析と同時に変えると、どちらが効いたか
切り分けられない。検索計画を先に選んだ理由は `docs/experiments/26-routing.md`。

    固定入力 3 件 × 2 設定 × 2 回 = 12 実リクエスト

**Retry も Fallback も無しで比べる。** 有りにすると、CHEAP が 1 回で
通らなかったぶんが STANDARD の費用として紛れ込み、比較にならない。
Schema を 1 回で通せるかどうかも品質の一部として数える。

**検索も本文取得も走らせない。** LLM を 1 回呼ぶだけで、その出力を見る。

使い方:

    .venv/bin/python -m scripts.compare_search_plan_tier --dry-run   # 実 API を呼ばない
    .venv/bin/python -m scripts.compare_search_plan_tier --confirm   # 実 API を呼ぶ
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scripts._experiment import Budget, BudgetExceededError, apply_recording_settings

apply_recording_settings()  # import より先。実費ヘッダを有効にする

from ai import cost, llm  # noqa: E402
from ai.llm import LLMError, generate_structured  # noqa: E402
from ai.orcarouter import ModelTier  # noqa: E402
from ai.prompts import search_plan as prompt  # noqa: E402
from ai.routing import Step  # noqa: E402
from ai.schemas.search_plan import SearchPlanOutput  # noqa: E402
from config import get_settings  # noqa: E402

REPEATS = 2
TIERS = (ModelTier.STANDARD, ModelTier.CHEAP)

# **Fallback を切る。** 有効なままだと、CHEAP が落ちた回が STANDARD へ上がり、
# その費用と時間が CHEAP の欄に乗る。どちらの実力か分からなくなる。
# 本番の挙動は変えない（この実験スクリプトの中だけ）。
llm._FALLBACK_TIERS = {t: () for t in ModelTier}

# 固定入力。**個人情報を含まない。** 性質を変えてある。
#
#   jp_engineer  日本在住・日本語・興味が 2 つ交差する（普通の入力）
#   global_only  活動地域が海外・興味が 1 つだけ（交差点が作りにくい）
#   sparse       目標が短く軸が 1 つだけ（補完したくなる入力）
CASES = [
    {
        "name": "jp_engineer",
        "goal_summary": "AIプロダクトの開発経験を増やし、将来は起業したい",
        "goal_directions": ["AI product development", "Entrepreneurship"],
        "interest_connections": ["AI × 音楽", "AI × 教育"],
        "location": "東京",
        # 入力に現れる語。出力がこれを保っているかを見る。
        "must_keep": ["AI"],
        "expect_japanese": True,
        # 探索の軸ごとに、覆えたと見なす語。**軸は英語、query は日本語**の
        # ことがあるので、語そのものの一致では測れない。
        "must_cover": {
            "AI product development": [
                "ハッカソン",
                "hackathon",
                "開発",
                "develop",
                "プロダクト",
                "product",
                "勉強会",
                "もくもく",
            ],
            "Entrepreneurship": [
                "起業",
                "スタートアップ",
                "startup",
                "アクセラレ",
                "accelerator",
                "創業",
                "founder",
                "ピッチ",
                "pitch",
                "incubat",
            ],
        },
    },
    {
        "name": "global_only",
        "goal_summary": "英語圏のテックコミュニティで活動の幅を広げたい",
        "goal_directions": ["International tech community"],
        "interest_connections": ["オープンソース × 英語"],
        "location": "Berlin",
        "must_keep": [],
        "expect_japanese": False,
        "must_cover": {
            "International tech community": [
                "community",
                "コミュニティ",
                "meetup",
                "ミートアップ",
                "tech",
            ],
        },
    },
    {
        "name": "sparse",
        "goal_summary": "デザインを学びたい",
        "goal_directions": ["Design"],
        "interest_connections": [],
        "location": None,
        "must_keep": [],
        "expect_japanese": False,
        "must_cover": {"Design": ["design", "デザイン"]},
    },
]

# 募集ページに当てるための語（prompt の規則 4）。
_RECRUITING = (
    "募集",
    "開催",
    "参加者",
    "エントリー",
    "申込",
    "申し込み",
    "call for",
    "apply",
    "registration",
    "ticket",
    "submit",
    "参加",
)
# 記事・解説に当たってしまう語（prompt の規則 4 が禁じている）。
_ARTICLE_WORDS = ("とは", "まとめ", "解説", "おすすめ一覧", "比較サイト")
_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
# 入力に無い年。**どの固定入力にも年は書いていない**ので、出たら補完である。
# 過去の年を入れると、その年のページばかりが引っかかる。
_YEAR = re.compile(r"(?:19|20)[0-9]{2}")


@dataclass
class Attempt:
    case: str
    tier: str
    run: int
    model: str | None = None
    ok: bool = False
    error: str | None = None
    latency_ms: int = 0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    jpy: float = 0.0
    actual_usd: float | None = None
    queries: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)


def _quality(case: dict, out: SearchPlanOutput) -> dict:
    """出力そのものを見る。**STANDARD と一致するかでは判定しない。**

    一致で測ると、STANDARD が間違えた入力で CHEAP が正しくても不合格になる。
    元の入力に対して何を保てているかを見る。
    """
    directions = out.search_directions[: prompt.MAX_DIRECTIONS]
    queries = [d.query for d in directions]
    joined = " ".join(queries)
    jp = [q for q in queries if _JAPANESE.search(q)]

    return {
        # 数がそのまま検索コストになる。prompt の規則 1。
        "count_in_range": prompt.MIN_DIRECTIONS <= len(directions) <= prompt.MAX_DIRECTIONS,
        "count": len(directions),
        # この製品の独自性。**LLM が出さないなら補完で埋まるが、出せたかを見る。**
        "has_serendipity": any(d.serendipity for d in directions),
        # 目標・制約の保持。入力に無い語で埋めていないかは queries を読んで判断する。
        "keeps_goal_terms": all(t.lower() in joined.lower() for t in case["must_keep"]),
        "keeps_location": (case["location"] is None or case["location"].lower() in joined.lower()),
        # 日本の催しの告知は日本語。prompt の規則 5。
        "japanese_ratio": round(len(jp) / len(queries), 2) if queries else 0.0,
        "japanese_ok": ((len(jp) * 2 >= len(queries)) if case["expect_japanese"] else True),
        # 募集ページへ当てる語。prompt の規則 4。
        "recruiting_words": sum(1 for q in queries if any(w in q.lower() for w in _RECRUITING)),
        "article_words": [w for w in _ARTICLE_WORDS if w in joined],
        # 目標の軸をどれも落としていないこと。**片方だけ扱う計画を作らせない。**
        "covers_all_goals": all(
            any(w.lower() in joined.lower() for w in words) for words in case["must_cover"].values()
        ),
        "uncovered_goals": [
            axis
            for axis, words in case["must_cover"].items()
            if not any(w.lower() in joined.lower() for w in words)
        ],
        # 根拠のない補完。入力に年は無い。
        "no_invented_year": not _YEAR.search(joined),
        "invented_years": sorted(set(_YEAR.findall(joined))),
        # 方向が一方向へ偏らないこと。
        "distinct_categories": len({d.category for d in directions}),
        "distinct_queries": len({q.strip().lower() for q in queries}),
    }


def _run_one(case: dict, tier: ModelTier, run: int, budget: Budget) -> Attempt:
    at = Attempt(case=case["name"], tier=tier.value, run=run)
    started = time.monotonic()
    with cost.track() as tracker, cost.step("search_plan"):
        try:
            result = generate_structured(
                schema=SearchPlanOutput,
                system=prompt.SYSTEM,
                user=prompt.build_user(
                    goal_summary=case["goal_summary"],
                    goal_directions=case["goal_directions"],
                    interests=case["interest_connections"],
                    location=case["location"],
                ),
                step=Step.SEARCH_PLAN,
                # **表ではなく明示した tier で比べる。**
                tier=tier,
                # Retry 無し。1 回で Schema を通せるかも品質として見る。
                max_attempts=1,
            )
        except LLMError as exc:
            at.error = type(exc).__name__
            budget.schema_failures += 1
            # **失敗しても課金は起きている。** 記録から落とさない。
            for u in getattr(exc, "usages", []):
                at.prompt_tokens += u.prompt_tokens
                at.completion_tokens += u.completion_tokens
                at.reasoning_tokens += u.reasoning_tokens
                at.model = u.model
                budget.llm_requests += 1
                budget.record_response(cost_usd=u.cost_usd, estimate_jpy=cost.estimate_jpy(u))
        else:
            at.ok = True
            out = result.data
            at.queries = [d.query for d in out.search_directions[: prompt.MAX_DIRECTIONS]]
            at.categories = [
                str(d.category) for d in out.search_directions[: prompt.MAX_DIRECTIONS]
            ]
            at.reasons = [d.reason for d in out.search_directions[: prompt.MAX_DIRECTIONS]]
            at.checks = _quality(case, out)
            for u in result.usages:
                at.prompt_tokens += u.prompt_tokens
                at.completion_tokens += u.completion_tokens
                at.reasoning_tokens += u.reasoning_tokens
                at.model = u.model
                budget.llm_requests += 1
                budget.record_response(cost_usd=u.cost_usd, estimate_jpy=cost.estimate_jpy(u))

    at.latency_ms = int((time.monotonic() - started) * 1000)
    at.attempts = tracker.by_step["search_plan"].request_attempts
    at.jpy = round(tracker.by_step["search_plan"].jpy, 4)
    step = tracker.by_step["search_plan"]
    # **実費が取れなかったら None。** 0 と書くと無料に見える。
    # 記録が 1 件も無いときも None。**「0 円」と「分からない」を混ぜない。**
    known = step.usage_records > 0 and step.responses_without_actual_cost == 0
    at.actual_usd = step.actual_usd if known else None
    budget.check()
    return at


def _summarise(rows: list[Attempt]) -> dict:
    by_tier: dict[str, dict] = {}
    for tier in (t.value for t in TIERS):
        mine = [r for r in rows if r.tier == tier]
        if not mine:
            continue
        ok = [r for r in mine if r.ok]
        actual = [r.actual_usd for r in mine if r.actual_usd is not None]
        by_tier[tier] = {
            "model": next((r.model for r in mine if r.model), None),
            "requests": len(mine),
            "schema_ok": f"{len(ok)}/{len(mine)}",
            "median_latency_ms": (
                int(statistics.median(r.latency_ms for r in mine)) if mine else 0
            ),
            "total_jpy": round(sum(r.jpy for r in mine), 4),
            "actual_usd": round(sum(actual), 6) if len(actual) == len(mine) else None,
            "actual_usd_note": (
                None if len(actual) == len(mine) else f"{len(mine) - len(actual)}件で実費が取れず"
            ),
            "reasoning_tokens": sum(r.reasoning_tokens for r in mine),
            "passed": {
                k: f"{sum(1 for r in ok if r.checks.get(k))}/{len(ok)}"
                for k in (
                    "count_in_range",
                    "has_serendipity",
                    "keeps_goal_terms",
                    "keeps_location",
                    "japanese_ok",
                    "covers_all_goals",
                    "no_invented_year",
                )
            },
            "median_distinct_categories": (
                statistics.median(r.checks["distinct_categories"] for r in ok) if ok else 0
            ),
            "any_article_words": sorted({w for r in ok for w in r.checks.get("article_words", [])}),
            "uncovered_goals": sorted({a for r in ok for a in r.checks.get("uncovered_goals", [])}),
            "invented_years": sorted({y for r in ok for y in r.checks.get("invented_years", [])}),
        }
    return by_tier


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="実 API を呼ぶ")
    ap.add_argument("--dry-run", action="store_true", help="呼ばずに計画だけ出す")
    ap.add_argument("--out", default="../docs/experiments/26-search-plan-tier-v2.json")
    args = ap.parse_args()

    settings = get_settings()
    planned = len(CASES) * len(TIERS) * REPEATS
    models = {
        ModelTier.STANDARD.value: settings.llm_model_standard,
        ModelTier.CHEAP.value: settings.llm_model_cheap,
    }

    print("=== 比較の計画 ===")
    print(f"工程      検索計画（step={Step.SEARCH_PLAN.value}）")
    for tier, model in models.items():
        print(f"{tier:<10}{model}")
    print(f"入力      {len(CASES)} 件（{', '.join(c['name'] for c in CASES)}）")
    print(f"実リクエスト {planned} 回（Retry・Fallback なし）")
    print("参考単価  gpt-4o-mini ¥23/¥90、gemini-2.5-flash ¥45/¥375（入力/出力 1M tokens）")
    print("          **公開価格からの見積もり。請求額ではない**（ai/cost.py）")
    print("参考費用  直近の実 run では検索計画 1 回が ¥0.84 / 14.3 秒（standard）")
    print(f"          12 回ぶんでおよそ ¥{0.84 * 12:.0f} 未満の見込み（cheap はより安い）")
    print("停止条件  scripts/_experiment.py の Budget（回数・費用・実費不明の件数）")
    print(f"実費記録  ORCAROUTER_INCLUDE_COST={settings.orcarouter_include_cost}")

    if args.dry_run or not args.confirm:
        print("\n--confirm を付けると実行します（--dry-run のままなら何も呼びません）")
        return 0

    budget = Budget()
    rows: list[Attempt] = []
    try:
        for case in CASES:
            for tier in TIERS:
                for run in range(1, REPEATS + 1):
                    at = _run_one(case, tier, run, budget)
                    rows.append(at)
                    mark = "ok " if at.ok else "NG "
                    print(f"  {mark}{case['name']:<12}{tier.value:<9}#{run}  {at.latency_ms:>6}ms")
    except BudgetExceededError as exc:
        print(f"\n停止しました: {exc}")

    out = {
        "step": Step.SEARCH_PLAN.value,
        "models": models,
        "repeats": REPEATS,
        "no_retry_no_fallback": True,
        "budget": budget.to_dict(),
        "summary": _summarise(rows),
        "attempts": [asdict(r) for r in rows],
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n書き出しました: {path}")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
