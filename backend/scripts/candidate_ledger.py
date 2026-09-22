"""候補の「モデルが言ったこと」と「出典で確かめたこと」を**分けて持つ**（#47）。

実測で起きた失敗が、そのまま設計の理由になっている。

    大学名とキャンパス名の取り違え   別の表の行を混ぜた
    予約フォームの取り違え         同じページの別セミナーの申込先を使った
    2025 年の回を 2026 年として提示  過去回のページを現行回として読んだ
    根拠のない「千代田区」          出典に無い値を足した

**だから、モデルの値を上書きして消さない。** 両方を残し、どちらを表示するかは
`status` で決める。**訂正できたら候補ごと捨てない。** 直せない項目だけ
`不明` か `矛盾あり` にする。推測で埋めない。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path


class Status(StrEnum):
    CONFIRMED = "確認済み"  # 日程・東京都内の会場を出典で確認
    CORRECTED = "訂正済み"  # 誤りを出典で直した。掲載してよい
    CONFLICT = "矛盾あり"  # 出典どうしが食い違い、決着しない
    INCOMPLETE = "情報不足"  # 出典に必要な記載が無い（誤りではない）
    OUT_OF_SCOPE = "条件外"  # 東京で現地参加できない等
    UNFETCHABLE = "取得不能"  # 出典に到達できず確認できない


@dataclass
class Correction:
    """1 項目の訂正。**何を、何から何へ、どの出典で。**"""

    field: str
    model_said: str
    corrected_to: str
    source: str


@dataclass
class Candidate:
    wish: str
    # --- モデルが最初に返した値。**上書きしない。** ---
    model: dict
    # --- 出典で確かめた値。確かめられた項目だけ入る。 ---
    verified: dict = field(default_factory=dict)
    corrections: list[Correction] = field(default_factory=list)
    # 直せなかった項目。**推測で埋めない。**
    unresolved: list[str] = field(default_factory=list)
    status: Status = Status.UNFETCHABLE
    evidence: list[str] = field(default_factory=list)
    # 受付・参加資格は**日程の確認とは別に記録する。**
    registration: str = "未確認"
    eligibility: str = "記載なし"
    eligibility_checked_against_user: bool = False

    def display(self, key: str) -> str:
        """表示に使う値。**確かめた値が優先。無ければモデルの値に『未確認』を付ける。**"""
        if key in self.verified:
            return str(self.verified[key])
        v = self.model.get(key)
        return f"{v}（未確認）" if v else "不明"

    def showable(self) -> bool:
        """一覧に出してよいか。**受付が未確認でも、日程・地域が確かなら出す。**"""
        return self.status in (Status.CONFIRMED, Status.CORRECTED)


def save(cands: list[Candidate], path: Path) -> None:
    path.write_text(
        json.dumps(
            [{**asdict(c), "status": str(c.status)} for c in cands], ensure_ascii=False, indent=1
        )
    )


def summary(cands: list[Candidate]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cands:
        out[str(c.status)] = out.get(str(c.status), 0) + 1
    return out
