"""DB 接続。MVP は SQLite、将来 PostgreSQL に差し替えられるよう SQLAlchemy を挟む。"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings
from db.base import Base
from db.migrate import add_missing_columns

_settings = get_settings()

# SQLite は既定で同一スレッド以外からの利用を禁止するため、FastAPI 用に解除する。
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """テーブルを作り、既存 DB には不足している列を足す。

    Migration ツールは入れていないが、**そのことと DB を消してよいことは別**。
    `create_all` は既存テーブルに列を足さないため、列を追加した後の
    既存 DB は `no such column` で落ちる。`add_missing_columns` が埋める。
    """
    import models  # noqa: F401  モデル登録のため

    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)


def get_db() -> Iterator[Session]:
    """FastAPI の依存性注入用。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
