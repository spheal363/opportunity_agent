"""DB 接続。MVP は SQLite、将来 PostgreSQL に差し替えられるよう SQLAlchemy を挟む。"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings
from db.base import Base

_settings = get_settings()

# SQLite は既定で同一スレッド以外からの利用を禁止するため、FastAPI 用に解除する。
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """MVP では Migration ツールを使わず create_all で済ませる。"""
    import models  # noqa: F401  モデル登録のため

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI の依存性注入用。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
