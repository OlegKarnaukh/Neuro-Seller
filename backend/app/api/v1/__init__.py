"""
API v1 endpoints
"""
from fastapi import APIRouter
from app.api.v1 import constructor, agents, channels, auth, conversations, billing

api_router = APIRouter()

api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

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
    conversations.router,
    prefix="/conversations",
    tags=["Conversations"]
)

api_router.include_router(
    billing.router,
    prefix="/billing",
    tags=["Billing"]
)

api_router.include_router(
    channels.router,
    prefix="/channels",
    tags=["Channels"]
)
