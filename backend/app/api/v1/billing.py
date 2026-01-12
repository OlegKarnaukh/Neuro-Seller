"""
Billing endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.schemas.billing import BillingResponse, BillingUsage, BillingHistory

router = APIRouter()


@router.get("/current", response_model=BillingResponse)
async def get_billing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current billing information and usage"""
    # Calculate current period (month)
    now = datetime.utcnow()
    period_start = datetime(now.year, now.month, 1)

    # Next month
    if now.month == 12:
        period_end = datetime(now.year + 1, 1, 1)
    else:
        period_end = datetime(now.year, now.month + 1, 1)

    # Calculate usage
    tokens_remaining = max(0, current_user.tokens_limit - current_user.tokens_used)
    usage_percent = (current_user.tokens_used / current_user.tokens_limit * 100) if current_user.tokens_limit > 0 else 0

    # Current usage
    current_usage = BillingUsage(
        plan=current_user.plan,
        tokens_limit=current_user.tokens_limit,
        tokens_used=current_user.tokens_used,
        tokens_remaining=tokens_remaining,
        usage_percent=round(usage_percent, 2),
        period_start=period_start,
        period_end=period_end
    )

    # History (для MVP - пока пустая, потом добавим хранение истории)
    history = []

    # Можно добавить прошлый период как пример
    last_period_start = period_start - timedelta(days=30)
    last_period_end = period_start

    history.append(BillingHistory(
        period_start=last_period_start,
        period_end=last_period_end,
        plan=current_user.plan,
        tokens_used=current_user.tokens_used,
        tokens_limit=current_user.tokens_limit,
        overage=0
    ))

    return BillingResponse(
        current=current_usage,
        history=history
    )
