"""移行が黙って何もしないことを防ぐ。

**列を足したつもりの DB がそのまま使われるのが、いちばん困る。**
後になって `no such column` で落ちるか、既定値のまま動き続ける。
"""

import pytest
from sqlalchemy import create_engine

from db.migrate import MigrationNotLoadedError, add_missing_columns


def test_refuses_to_run_without_registered_models(monkeypatch):
    """モデル未登録なら止める。**成功したように見せない。**

    実際にこれで踏んだ。`import models` を忘れたまま移行を呼び、
    `[]` が返って「足す列は無い」と読み違えた。
    """
    from sqlalchemy.orm import declarative_base

    monkeypatch.setattr("db.migrate.Base", declarative_base())
    with pytest.raises(MigrationNotLoadedError):
        add_missing_columns(create_engine("sqlite://"))


def test_adds_the_new_columns_to_an_existing_table(tmp_path):
    """**既存データを消さずに**列を足せること。"""
    import sqlite3

    import models  # noqa: F401  モデル登録のため

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    # 列を足す前の形（deadline_kind などが無い）
    db.execute(
        "CREATE TABLE opportunities ("
        "opportunity_id TEXT PRIMARY KEY, user_id TEXT, title TEXT, type TEXT)"
    )
    db.execute("INSERT INTO opportunities VALUES ('o1','u1','残っていること','event')")
    db.commit()
    db.close()

    engine = create_engine(f"sqlite:///{path}")
    added = add_missing_columns(engine)

    db = sqlite3.connect(path)
    cols = {r[1] for r in db.execute("PRAGMA table_info(opportunities)")}
    rows = db.execute("SELECT opportunity_id, title FROM opportunities").fetchall()

    assert "opportunities.deadline_kind" in added
    assert {"deadline_kind", "cost_kind", "deadline_is_date_only", "availability"} <= cols
    # **消えていない。**
    assert rows == [("o1", "残っていること")]

    # 2 回目は何も足さない（冪等）
    assert add_missing_columns(engine) == []
