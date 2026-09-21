"""実験レポートが、DB の項目を落としていないこと（#65）。

**欄を落とすと「取れていない」と読み違える。**

2 度やった。`eligibility` を落として「参加条件 0 / 18 件」と報告し、
`recommended_action` を落として「行動 None」と報告した。どちらも DB には
入っていた。

**列を手で並べるのをやめ、モデルの列をそのまま出す**ようにした。
ここではその約束を固定する。

`row_dict` は `scripts/_experiment.py` に置いてある。`run_comparison` は
import しただけで環境変数を書き換えるため、テストから切り離してある。
"""

from scripts._experiment import row_dict


def test_every_model_column_is_written_out():
    """**モデルの列がすべて出る。** 手で並べた一覧に依存しない。"""
    from sqlalchemy import inspect as sa_inspect

    from models import Opportunity

    row = Opportunity(opportunity_id="o1", user_id="u1", title="t", type="event")
    written = set(row_dict(row))
    expected = {c.key for c in sa_inspect(Opportunity).mapper.column_attrs}

    assert written == expected


def test_the_fields_we_lost_before_are_present():
    """**同じ取りこぼしを繰り返さない。**"""
    from models import Opportunity

    row = Opportunity(opportunity_id="o1", user_id="u1", title="t", type="event")
    written = set(row_dict(row))

    assert {"eligibility", "recommended_action", "url_is_source_only"} <= written
