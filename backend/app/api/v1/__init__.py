"""
API v1 endpoints
"""
from fastapi import APIRouter
from app.api.v1 import agents, channels, constructor

api_router = APIRouter()

api_router.include_router(
    constructor.router,
    prefix="/constructor",
    tags=["Constructor"]
)

api_router.include_router(
    agents.router,
    prefix="/agents",
    tags=["Agents"]
)

api_router.include_router(
    channels.router,
    prefix="/channels",
    tags=["Channels"]
)
