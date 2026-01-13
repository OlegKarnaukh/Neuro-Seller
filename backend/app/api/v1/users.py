"""
Users API - Sync users between Base44 and Railway
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.models.user import User

router = APIRouter()


class EnsureUserRequest(BaseModel):
    """Request from Base44 to ensure user exists"""
    email: str
    full_name: str
    base44_id: str  # UUID from Base44


class UserResponse(BaseModel):
    """Response with Railway user data"""
    id: str
    email: Optional[str]
    full_name: Optional[str]
    base44_id: Optional[str]
    plan: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/ensure", response_model=UserResponse)
async def ensure_user(
    request: EnsureUserRequest,
    db: Session = Depends(get_db)
):
    """
    Ensure user exists in Railway database.
    If user exists (by base44_id or email) - update and return.
    If not exists - create new user.

    Called by Base44 after user login/registration.
    """
    # First try to find by base44_id
    user = db.query(User).filter(User.base44_id == request.base44_id).first()

    if not user:
        # Try to find by email
        user = db.query(User).filter(User.email == request.email).first()

    if user:
        # Update existing user
        user.email = request.email
        user.full_name = request.full_name
        user.base44_id = request.base44_id
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    else:
        # Create new user
        user = User(
            email=request.email,
            full_name=request.full_name,
            base44_id=request.base44_id,
            plan="free"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        base44_id=user.base44_id,
        plan=user.plan,
        created_at=user.created_at
    )


@router.get("/by-base44/{base44_id}", response_model=UserResponse)
async def get_user_by_base44_id(
    base44_id: str,
    db: Session = Depends(get_db)
):
    """
    Get user by Base44 ID.
    """
    user = db.query(User).filter(User.base44_id == base44_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        base44_id=user.base44_id,
        plan=user.plan,
        created_at=user.created_at
    )
