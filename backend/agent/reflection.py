"""⑧ Reflection。前回までの反応から、次の探索で何を増やし何を減らすかを決める。

**LLM を使わず、コードで決定的に集計する。** 毎 run の冒頭で、そのユーザーの
全フィードバックと Opportunity の status から作り直す（冪等）。フィードバックを
受けるたびに差分で足し引きすると、同じ候補への 👍 → 👎 の付け直しや、途中で
落ちた run のぶんだけ値がずれていくため。

## 何を鍵にするか

**構造が決まった値だけ**を鍵にする。

  - `type:<OpportunityType>`      ハッカソン・コミュニティなど
  - `format:<OpportunityFormat>`  現地 / オンライン / ハイブリッド

**タイトル・説明などの自由文は使わない。** Web 上の書き手が決めた文で、
学習結果に入ると以後のすべての run の探索計画に効き続ける（memory poisoning）。
enum の値に閉じていれば、書き手が動かせるのは「どの種類に数えられるか」までに留まる。

**source（ドメイン）も使わない。** connpass や Peatix のような集約サイトは
主催者も内容もばらばらで、1 件の 👎 で集約サイト全体を下げてしまう。
探索計画が `site:` で狭まる方向に働き、意外な機会に出会う余地も減る。

`type:other` も鍵にしない。分類できなかった候補の寄せ集めで、種類の好みを表さない。
下げると、抽出が種類を決めきれなかっただけの候補まで一律に下がる。

## どこに置くか

学んだことは Agent Memory（`agent_memories`）に置く（`save`）。
**UserProfile は書き換えない。** プロフィールは「その人がどんな人か」、
Memory は「Agent がその人について学んだこと」（.claude/rules/architecture.md）。
プロフィールの興味を書き換えて学習を表すと、本人が書いた内容と Agent の推測が
見分けられなくなり、本人が直す手段も失われる。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from math import copysign

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ai.evaluation import _SERENDIPITY_WEIGHT, SERENDIPITY_WEIGHT_RANGE
from models import AgentMemory, Feedback, Opportunity
from schemas.feedback import Reaction
from schemas.opportunity import OpportunityFormat, OpportunityStatus, OpportunityType

# --------------------------------------------------------------------------
# 重みと閾値
# --------------------------------------------------------------------------

# 1 件の候補から読み取る信号の強さ（`signal_of`）。
#
#   👍 / 気になる        +1  画面で 1 回押しただけ
#   予定に追加 / 参加     +2  時間を割くと決めた。クリックより強い根拠
#   👎                   −1
_POSITIVE_STATUS = {
    OpportunityStatus.INTERESTED: 1.0,
    OpportunityStatus.REGISTERED: 2.0,
    OpportunityStatus.ATTENDED: 2.0,
}

# 1 つの鍵（種類・形式）が持てる重みの上限。**反応が積み重なっても振れすぎない。**
# 👎 を 10 回押したから 10 倍嫌い、とは読まない。
MAX_WEIGHT = 3.0

# 意外性の重みを学ぶのに要る候補の数。1 件の 👍 で製品の芯を動かさない。
SERENDIPITY_MIN_SAMPLES = 2
# 反応した候補の serendipity_score が 50 から平均 1 点ずれるごとに動かす量。
# 平均で 50 点ずれると ±0.15（既定 0.3 → 0.45 / 0.15）。範囲は SERENDIPITY_WEIGHT_RANGE で切る。
_SERENDIPITY_STEP = 0.003
_SERENDIPITY_NEUTRAL = 50

_TYPES = frozenset(t.value for t in OpportunityType if t is not OpportunityType.OTHER)
_FORMATS = frozenset(f.value for f in OpportunityFormat)
_REACTIONS = frozenset(r.value for r in Reaction)

# 画面に出す名前。鍵は enum の値なので、ここに無い名前は出てこない。
_TYPE_LABELS = {
    "event": "イベント",
    "hackathon": "ハッカソン",
    "job": "求人",
    "freelance": "業務委託",
    "community": "コミュニティ",
    "accelerator": "アクセラレータ",
    "competition": "コンテスト",
    "scholarship": "奨学金",
}
_FORMAT_LABELS = {
    "offline": "現地開催",
    "online": "オンライン開催",
    "hybrid": "ハイブリッド開催",
}
# 件数の読み方。並び順がそのまま表示順になる。
_COUNT_LABELS = (
    ("like", "👍"),
    ("dislike", "👎"),
    ("interested", "「気になる」"),
    ("registered", "「予定に追加」"),
    ("attended", "「参加した」"),
)
# 振り返りの Log に並べる鍵の数。**Log を増やしすぎない。**
_MAX_LOGGED_KEYS = 4

# Agent Memory の種類（models/memory.py）。**この 2 種類だけを毎 run 置き換える。**
# search_suggestion など、ここで作らない種類には触らない。
PREFERENCE = "preference"
INSIGHT = "insight"
SERENDIPITY_KEY = "serendipity_weight"
_INSIGHT_KEY = "feedback"


# --------------------------------------------------------------------------
# 入れ物
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """1 件の候補から読み取った反応。**自由文は持たない。**"""

    opportunity_id: str
    keys: tuple[str, ...]
    value: float
    counts: Mapping[str, int]
    serendipity_score: int | None = None


@dataclass(frozen=True)
class Preference:
    """1 つの鍵（`type:hackathon` など）について学んだこと。"""

    key: str
    # 反応の合計を ±MAX_WEIGHT で切ったもの。正なら反応が良い。
    weight: float
    # この鍵に数えた候補の数（同じ候補への反応は 1 と数える）。
    evidence: int
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def label(self) -> str:
        kind, _, value = self.key.partition(":")
        labels = _TYPE_LABELS if kind == "type" else _FORMAT_LABELS
        return labels.get(value, value)


@dataclass(frozen=True)
class Learned:
    """1 回の振り返りの結果。この run の探索計画と順位付けに使う。"""

    preferences: tuple[Preference, ...] = ()
    # 学んだ意外性の重み。根拠が足りなければ None（既定の重みを使う）。
    serendipity_weight: float | None = None
    serendipity_samples: int = 0
    # 反応があった候補の数（種類を特定できなかったものも含む）。
    reacted: int = 0

    @property
    def by_key(self) -> dict[str, Preference]:
        return {p.key: p for p in self.preferences}


# 反応がまだ無い（または振り返りに失敗した）ときの値。何も変えない。
NOTHING = Learned()


# --------------------------------------------------------------------------
# 集計（純粋関数）
# --------------------------------------------------------------------------


def signal_of(reaction: str | None, status: str | None) -> float:
    """1 件の候補から読み取る信号。**同じ候補の信号は足し合わせない。**

    - 最新の反応が 👎 なら −1。参加済みでも「行ったが合わなかった」と読む
    - それ以外は 👍・気になる・予定に追加・参加 のうち最も強いもの
    - 👎 は status=dismissed も立てる（`record_feedback`）。**status 側では数えない**
      （同じ 1 回の 👎 を二重に数えない）

    足し合わせない理由: 👍 して「気になる」に入れて予定に追加した 1 件が +4 になると、
    1 件の候補だけで種類の好みが上限まで振れてしまう。
    """
    if reaction == Reaction.DISLIKE:
        return -1.0
    liked = 1.0 if reaction == Reaction.LIKE else 0.0
    return max(liked, _POSITIVE_STATUS.get(status, 0.0))


def keys_of(opportunity_type: str | None, opportunity_format: str | None) -> tuple[str, ...]:
    """候補を数える鍵。**enum に無い値は捨てる**（旧い行や壊れた値で鍵を増やさない）。"""
    keys: list[str] = []
    if opportunity_type in _TYPES:
        keys.append(f"type:{opportunity_type}")
    if opportunity_format in _FORMATS:
        keys.append(f"format:{opportunity_format}")
    return tuple(keys)


def _counts_of(reaction: str | None, status: str | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if reaction in _REACTIONS:
        counts[reaction] = 1
    if status in _POSITIVE_STATUS:
        counts[str(status)] = 1
    return counts


def learn(signals: Iterable[Signal]) -> Learned:
    """反応を鍵ごとに集計する。**同じ入力からは必ず同じ結果になる。**"""
    signals = [s for s in signals if s.value]
    totals: dict[str, float] = defaultdict(float)
    evidence: Counter[str] = Counter()
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for s in signals:
        for key in s.keys:
            totals[key] += s.value
            evidence[key] += 1
            counts[key].update(s.counts)

    preferences = sorted(
        (
            Preference(
                key=key,
                weight=_clamp(total, MAX_WEIGHT),
                evidence=evidence[key],
                counts=dict(counts[key]),
            )
            for key, total in totals.items()
        ),
        # 種類を先、形式を後。その中では反応の強い順。並びは Log と Memory の順になる。
        key=lambda p: (not p.key.startswith("type:"), -abs(p.weight), p.key),
    )
    weight, samples = _learn_serendipity_weight(signals)
    return Learned(
        preferences=tuple(preferences),
        serendipity_weight=weight,
        serendipity_samples=samples,
        reacted=len(signals),
    )


def _learn_serendipity_weight(signals: list[Signal]) -> tuple[float | None, int]:
    """反応した候補の意外性の傾向から、選定での意外性の重みを決める。

    👍 した候補の serendipity_score が高ければ上げ、👎 した候補が高ければ下げる。
    **狭い範囲（SERENDIPITY_WEIGHT_RANGE）でしか動かさない。** 意外性はこの製品の芯で、
    反応が少し偏っただけで王道ばかり、または目標から遠いものばかりにしない。
    """
    samples = [
        copysign(1.0, s.value) * (s.serendipity_score - _SERENDIPITY_NEUTRAL)
        for s in signals
        if s.serendipity_score is not None
    ]
    if len(samples) < SERENDIPITY_MIN_SAMPLES:
        return None, len(samples)
    tilt = sum(samples) / len(samples)
    low, high = SERENDIPITY_WEIGHT_RANGE
    weight = min(max(_SERENDIPITY_WEIGHT + tilt * _SERENDIPITY_STEP, low), high)
    return round(weight, 2), len(samples)


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


# --------------------------------------------------------------------------
# DB
# --------------------------------------------------------------------------


def collect(db: Session, user_id: str) -> list[Signal]:
    """そのユーザーの反応を候補ごとに 1 つへまとめる。

    👍👎 は**最新のものだけ**を採る（付け直しを上書きとして扱う）。
    候補は**そのユーザーのものだけ**読む。他人の候補に付いた反応は数えない。
    """
    latest: dict[str, str] = {}
    for opportunity_id, reaction in (
        db.query(Feedback.opportunity_id, Feedback.reaction)
        .filter(Feedback.user_id == user_id)
        .order_by(Feedback.created_at, Feedback.id)
    ):
        latest[opportunity_id] = reaction

    rows = (
        db.query(Opportunity)
        .filter(
            Opportunity.user_id == user_id,
            or_(
                Opportunity.opportunity_id.in_(list(latest)),
                Opportunity.status.in_([str(s) for s in _POSITIVE_STATUS]),
            ),
        )
        .order_by(Opportunity.opportunity_id)
        .all()
    )

    signals: list[Signal] = []
    for row in rows:
        reaction = latest.get(row.opportunity_id)
        if reaction not in _REACTIONS:
            reaction = None
        signals.append(
            Signal(
                opportunity_id=row.opportunity_id,
                keys=keys_of(row.type, row.format),
                value=signal_of(reaction, row.status),
                counts=_counts_of(reaction, row.status),
                serendipity_score=row.serendipity_score,
            )
        )
    return signals


def save(db: Session, user_id: str, learned: Learned) -> None:
    """学んだことで、そのユーザーの Agent Memory を置き換える（#49）。

    **差分で更新しない。** 毎 run すべての反応から作り直した結果で丸ごと入れ替える。
    消すのと入れるのは同じ transaction で行い、途中で落ちても半端な Memory を残さない。

      preference  key=`type:hackathon` など / weight / meta に件数
                  key=`serendipity_weight`   / weight に学んだ重み
      insight     value に学んだことの文（コードが鍵と件数から組み立てる）

    反応が無くなった（候補が消えた等）ときは、前の学習も消える。
    """
    db.query(AgentMemory).filter(
        AgentMemory.user_id == user_id, AgentMemory.kind.in_((PREFERENCE, INSIGHT))
    ).delete(synchronize_session=False)
    for p in learned.preferences:
        db.add(
            AgentMemory(
                user_id=user_id,
                kind=PREFERENCE,
                key=p.key,
                weight=p.weight,
                meta={"evidence": p.evidence, "counts": dict(p.counts)},
            )
        )
    if learned.serendipity_weight is not None:
        db.add(
            AgentMemory(
                user_id=user_id,
                kind=PREFERENCE,
                key=SERENDIPITY_KEY,
                weight=learned.serendipity_weight,
                meta={"samples": learned.serendipity_samples, "default": _SERENDIPITY_WEIGHT},
            )
        )
    if text := insight(learned):
        db.add(
            AgentMemory(
                user_id=user_id,
                kind=INSIGHT,
                key=_INSIGHT_KEY,
                value=text,
                meta={"reacted": learned.reacted},
            )
        )
    db.commit()


def reflect(db: Session, user_id: str) -> Learned:
    """前回までの反応を振り返り、Agent Memory に残す。run の冒頭で 1 回だけ呼ぶ。

    **保存した内容をそのまま返す。** 毎回すべての反応から作り直すので、
    読み戻しても同じ値になる。
    """
    learned = learn(collect(db, user_id))
    save(db, user_id, learned)
    return learned


# --------------------------------------------------------------------------
# 文（コードが enum の鍵と件数から組み立てる。Web 由来の文は入らない）
# --------------------------------------------------------------------------


def _counts_text(counts: Mapping[str, int]) -> str:
    return "・".join(f"{label}{n}件" for key, label in _COUNT_LABELS if (n := counts.get(key)))


def insight(learned: Learned) -> str | None:
    """Agent が学んだことを文にする（Memory の insight）。学んだことが無ければ None。

    例: 「ハッカソンへの反応が悪い（👎2件）。コミュニティへの反応が良い（👍1件）。」
    """
    parts: list[str] = []
    for p in learned.preferences:
        if p.weight > 0:
            parts.append(f"{p.label}への反応が良い（{_counts_text(p.counts)}）")
        elif p.weight < 0:
            parts.append(f"{p.label}への反応が悪い（{_counts_text(p.counts)}）")
    weight = learned.serendipity_weight
    if weight is not None and weight > _SERENDIPITY_WEIGHT:
        parts.append("意外性の高い候補への反応が良い")
    elif weight is not None and weight < _SERENDIPITY_WEIGHT:
        parts.append("意外性より目標に近い候補への反応が良い")
    return "".join(f"{part}。" for part in parts) or None


def describe(learned: Learned) -> str | None:
    """振り返りの Log。反応がまだ無ければ None（**Log を増やさない**）。

    例: 「前回までの反応を振り返りました: ハッカソンに👎2件、コミュニティに👍1件」
    """
    if not learned.reacted:
        return None
    if not learned.preferences:
        return (
            "前回までの反応を振り返りました（種類を特定できない候補のみのため、今回は反映しません）"
        )
    shown = learned.preferences[:_MAX_LOGGED_KEYS]
    text = "、".join(f"{p.label}に{_counts_text(p.counts)}" for p in shown)
    if rest := len(learned.preferences) - len(shown):
        text += f" ほか{rest}種類"
    return f"前回までの反応を振り返りました: {text}"
