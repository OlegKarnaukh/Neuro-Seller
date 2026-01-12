"""
Pydantic schemas for billing
"""
from pydantic import BaseModel
from typing import List
from datetime import datetime


class BillingUsage(BaseModel):
    plan: str
    tokens_limit: int
    tokens_used: int
    tokens_remaining: int
    usage_percent: float
    period_start: datetime
    period_end: datetime


class BillingHistory(BaseModel):
    period_start: datetime
    period_end: datetime
    plan: str
    tokens_used: int
    tokens_limit: int
    overage: int


class BillingResponse(BaseModel):
    current: BillingUsage
    history: List[BillingHistory] = []
