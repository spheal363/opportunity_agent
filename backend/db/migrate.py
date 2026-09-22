"""既存 DB へ不足している列を足す。

**Migration ツールを入れていないことと、DB を消してよいことは別。**
`create_all` は無いテーブルを作るだけで、**既存テーブルに列は足さない。**
そのため列を追加すると、既存 DB では `no such column` で落ちる。

ここでは SQLAlchemy のモデル定義と実 DB を突き合わせ、**足りない列だけ**
`ALTER TABLE ADD COLUMN` する。

  - **何度実行しても壊れない**（既にある列は飛ばす）
  - **既存データを消さない**（DROP も再作成もしない）
  - 列の削除・型変更はしない（SQLite が ALTER で対応しないため）

型変更やテーブルの作り直しが要るときは、そのとき改めて手順を作る。
自動で消す仕組みは持たない。
"""

from sqlalchemy import Engine, inspect, text

from db.base import Base
from logging_config import get_logger

logger = get_logger(__name__)

# SQLite の ALTER TABLE ADD COLUMN は既定値に定数しか使えない。
# server_default を持つ列はここでは足さず、別途手当てする。
_UNSUPPORTED_DEFAULT = ("CURRENT_TIMESTAMP",)


class MigrationNotLoadedError(RuntimeError):
    """モデルが登録されていないまま移行を呼んだ。"""


def add_missing_columns(engine: Engine) -> list[str]:
    """モデルにあって DB に無い列を足す。足した列名を返す。

    **モデルを import していないと `Base.metadata` は空で、何も足さずに
    成功したように見える。** 列を足したつもりの DB がそのまま使われ、
    後で `no such column` になる。黙って何もしないほうが危ないので止める。
    """
    if not Base.metadata.sorted_tables:
        raise MigrationNotLoadedError(
            "モデルが登録されていません（`import models` が先に必要です）。"
            "このまま進むと、列を足さずに成功したように見えます"
        )

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all が作る
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                ddl = _add_column_ddl(table.name, column)
                if ddl is None:
                    logger.warning(
                        "migrate.skipped table=%s column=%s reason=unsupported_default",
                        table.name,
                        column.name,
                    )
                    continue
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")

    if added:
        logger.info("migrate.added columns=%s", ",".join(added))
    return added


def _add_column_ddl(table: str, column) -> str | None:
    """ALTER 文を組み立てる。既定値を表現できない列は None。"""
    type_sql = column.type.compile(dialect=None)
    parts = [f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {type_sql}']

    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        if isinstance(value, str):
            parts.append(f"DEFAULT '{value}'")
        elif isinstance(value, bool):
            parts.append(f"DEFAULT {int(value)}")
        elif isinstance(value, int | float):
            parts.append(f"DEFAULT {value}")
    elif column.server_default is not None:
        text_value = getattr(column.server_default.arg, "text", "")
        if any(t in str(text_value).upper() for t in _UNSUPPORTED_DEFAULT):
            return None

    return " ".join(parts)
