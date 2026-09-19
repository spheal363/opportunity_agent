from fastapi import APIRouter

from api.routes import agent, calendar, health, opportunities, profile

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(profile.router)
api_router.include_router(agent.router)
api_router.include_router(opportunities.router)
api_router.include_router(calendar.router)

__all__ = ["api_router"]
