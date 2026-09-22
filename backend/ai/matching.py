"""候補を希望と突き合わせ、おすすめを選ぶ（#47）。

**検索とは別の工程。** 時間と費用も別に記録する。

## 何をしないか

- **本文を取りに行かない。** 取得済みの情報だけで評価する。
- **候補ごとの個別呼び出しをしない。** まとめて 1 回で評価する。
- **評価に失敗したら、架空の点を付けない。** 未評価のまま一覧を残す。

## `match` の意味

**AI による希望との適合度の目安。**
正確さでも、受付中である確率でも、参加資格を満たす確率でもない。
受付が未確認であることを理由に下げさせない（別の軸で表示する）。
"""

from __future__ import annotations

from ai import cost
from ai.llm import LLMError, generate_structured
from ai.prompts import match as prompt
from ai.routing import Step
from ai.schemas.match import MAX_CANDIDATES, MatchJudgement, MatchOutput
from logging_config import get_logger

logger = get_logger(__name__)

# 上位に入れない候補。**終了済みと明確な条件外は、おすすめにしない。**
_NOT_RECOMMENDABLE = {"ended", "after_window"}


def recommendable(row) -> bool:
    """おすすめの対象か。**受付未確認は外さない**（評価とは別の軸）。"""
    if getattr(row, "availability", None) == "closed":
        return False
    sv = getattr(row, "searched_values", None) or {}
    if sv.get("schedule_fit") in ("期間外",) or sv.get("excluded"):
        return False
    return True


def _payload(row) -> dict:
    sv = row.searched_values or {}
    return {
        "opportunity_id": row.opportunity_id,
        "title": row.title,
        "when": sv.get("dates_raw") or (row.start_at.isoformat() if row.start_at else "不明"),
        "location": row.location,
        "region": row.region,
        "description": row.description,
        "wish": row.wish,
    }


def judge(
    rows: list,
    *,
    wishes: str,
    region: str | None,
    window: str | None,
) -> dict[str, MatchJudgement]:
    """まとめて評価する。**失敗したら空を返す（架空の点を付けない）。**"""
    if not rows:
        return {}
    targets = rows[:MAX_CANDIDATES]
    with cost.step(str(Step.EVALUATION)):
        try:
            out = generate_structured(
                schema=MatchOutput,
                system=prompt.SYSTEM,
                user=prompt.build_user(
                    wishes=wishes,
                    region=region,
                    window=window,
                    candidates=[_payload(r) for r in targets],
                ),
                step=Step.EVALUATION,
                max_tokens=8000,
            ).data
        except LLMError as exc:
            logger.warning("matching.failed reason=%s", exc)
            return {}

    known = {r.opportunity_id for r in targets}
    # **渡していない id は捨てる。** 作られた id で取り違えない。
    return {j.opportunity_id: j for j in out.judgements if j.opportunity_id in known}


def order(rows: list, judged: dict[str, MatchJudgement], limit: int = 3) -> list:
    """おすすめを選ぶ。**希望の多様性も見るが、不適合を上位へ入れない。**

    同じ希望ばかりにならないよう、1 巡目は希望ごとに最良の 1 件を取る。
    ただし**適合度の低い候補を、種類を揃えるためだけに入れない。**
    """
    scored = [(r, judged[r.opportunity_id]) for r in rows if r.opportunity_id in judged]
    scored.sort(key=lambda p: p[1].match, reverse=True)
    if not scored:
        return []
    # 上位群だけを多様性の対象にする。**下位を引き上げない。**
    best = scored[0][1].match
    floor = max(0, best - 25)

    picked: list = []
    used_wishes: set[str] = set()
    for row, j in scored:
        if len(picked) >= limit:
            break
        key = (row.wish or "").strip()
        if key and key in used_wishes:
            continue
        if j.match < floor:
            continue
        picked.append(row)
        used_wishes.add(key)
    # 希望の種類が足りなければ、適合度の高い順で埋める。
    for row, _ in scored:
        if len(picked) >= limit:
            break
        if row not in picked:
            picked.append(row)
    return picked[:limit]
