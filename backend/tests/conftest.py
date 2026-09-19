import os
import tempfile
from pathlib import Path

import pytest

# main を import する前に、テスト専用の DB / 設定へ差し替える。
_TMP_DB = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["AGENT_STUB_MODE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from db.base import Base  # noqa: E402
from db.session import engine  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """テスト同士が DB の状態を共有しないよう、毎回作り直す。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def profile_payload() -> dict:
    return {
        "name": "Naoya",
        "location": "Tokyo, Japan",
        "languages": ["Japanese", "English"],
        "occupation": "Backend Engineer",
        "skills": ["Java", "Python", "AWS", "AI Agent"],
        "experience": ["Backend development", "Personal AI Agent development"],
        "interests": ["AI", "Startup", "Music", "DJ"],
        "goals": ["Build AI products", "Start a company", "Work internationally"],
        "about": "AI Agentや起業、音楽に興味があります。",
    }
