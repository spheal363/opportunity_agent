"""Opportunity Agent Backend。

uvicorn main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai.llm import close_client
from api import api_router
from api.errors import register_error_handlers
from config import get_settings
from db.session import init_db
from logging_config import get_logger, setup_logging
from tools.fetch import close_fetcher
from tools.search import close_provider

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("backend started env=%s stub_mode=%s", settings.app_env, settings.agent_stub_mode)
    yield
    close_client()
    close_provider()
    close_fetcher()


app = FastAPI(
    title="Opportunity Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)
app.include_router(api_router)
