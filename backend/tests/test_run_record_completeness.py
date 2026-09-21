"""実験レポートが、DB の項目を落としていないこと（#65）。

**欄を落とすと「取れていない」と読み違える。**

実際に `eligibility` を落とし、「参加条件が 0 / 18 件」と報告した。
DB には 4 件入っており、モデルは 5 件返していた。
"""

import ast
import pathlib

# レポートに必ず載せる項目。**判断に使うものは落とさない。**
REQUIRED = {
    "opportunity_id",
    "type",
    "title",
    "description",
    "url",
    "source",
    "start_at",
    "end_at",
    "deadline",
    "location",
    "eligibility",
    "cost",
    "cost_kind",
    "format",
    "score",
    "serendipity_score",
    "match_reasons",
    "reason",
    "verified",
    "verification_source",
    "availability",
    "availability_reason",
    "availability_checked_at",
    "deadline_kind",
    "deadline_quote",
    "status",
}


def _recorded_keys() -> set[str]:
    """`run_comparison.py` が opportunities に書き出す欄を読み取る。"""
    source = (pathlib.Path(__file__).parent.parent / "scripts/run_comparison.py").read_text()
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        names = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "opportunity_id" in names and "availability" in names:
            keys |= names
    return keys


def test_the_report_keeps_every_field_used_for_judging():
    missing = REQUIRED - _recorded_keys()
    assert not missing, f"レポートから落ちている欄: {sorted(missing)}"
