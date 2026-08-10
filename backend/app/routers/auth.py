"""Email+password auth. Registering creates a personal Organization (tenant)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Organization, User
from ..seed import seed_org_documents
from ..security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    org_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str
    user_id: str
    org_id: str


class UserOut(BaseModel):
    id: str
    email: str
    org_id: str
    role: str


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    exists = await session.scalar(select(User).where(User.email == body.email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    org = Organization(name=body.org_name or f"{body.email}'s workspace")
    session.add(org)
    await session.flush()
    user = User(org_id=org.id, email=body.email, pwd_hash=hash_password(body.password))
    session.add(user)
    await session.flush()
    await seed_org_documents(session, org, user)
    await session.commit()
    return TokenOut(token=create_token(user.id, org.id), user_id=user.id, org_id=org.id)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.pwd_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(token=create_token(user.id, user.org_id), user_id=user.id, org_id=user.org_id)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, org_id=user.org_id, role=user.role)
