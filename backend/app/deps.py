from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin_required")
    return user
