"""Single-writer lock: at most one live writer per document.

TTL-based, no background reaper — a lock past its `expires` is treated as free
and silently stolen on the next acquire. `require_writable` is the write-path
guard: it rejects (409) only when *another* user holds a live lock, so an
existing client that never explicitly locks can still save (it just isn't
protected against a concurrent writer that did lock).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Document, DocumentLock, User
from .security import get_current_user
from .settings import LOCK_TTL_SEC

router = APIRouter(prefix="/documents", tags=["locks"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _live(lock: DocumentLock | None) -> bool:
    if lock is None:
        return False
    exp = lock.expires
    if exp.tzinfo is None:  # sqlite may hand back naive datetimes
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > _now()


async def _get_owned(doc_id: str, user: User, session: AsyncSession) -> Document:
    doc = await session.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


async def require_writable(doc_id: str, user: User, session: AsyncSession) -> None:
    """Raise 409 if another user holds a live lock on the doc."""
    lock = await session.get(DocumentLock, doc_id)
    if _live(lock) and lock.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "document is locked by another user")


class LockOut(BaseModel):
    doc_id: str
    holder: str
    expires: datetime
    mine: bool


@router.post("/{doc_id}/lock", response_model=LockOut)
async def acquire_lock(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LockOut:
    """Acquire or renew the lock. Steals an expired lock; 409 if another user holds a live one."""
    await _get_owned(doc_id, user, session)
    lock = await session.get(DocumentLock, doc_id)
    if _live(lock) and lock.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "document is locked by another user")
    expires = _now() + timedelta(seconds=LOCK_TTL_SEC)
    if lock is None:
        lock = DocumentLock(doc_id=doc_id, org_id=user.org_id, user_id=user.id, expires=expires)
        session.add(lock)
    else:
        lock.user_id = user.id
        lock.expires = expires
    await session.commit()
    return LockOut(doc_id=doc_id, holder=user.id, expires=expires, mine=True)


@router.delete("/{doc_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
async def release_lock(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Release the lock. Only the holder can release; a no-op otherwise."""
    await _get_owned(doc_id, user, session)
    lock = await session.get(DocumentLock, doc_id)
    if lock is not None and lock.user_id == user.id:
        await session.delete(lock)
        await session.commit()
