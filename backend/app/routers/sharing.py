"""Public read-only share links.

Owner endpoints (auth, org-scoped) live under /documents/{id}/share*.
Public endpoints (no auth) live under /share/{token}: anyone with the token
reads the document's latest blob. Read-only — there is no public write path.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..db import get_session
from ..models import Document, Share, User
from ..security import get_current_user

owner_router = APIRouter(prefix="/documents", tags=["shares"])
public_router = APIRouter(prefix="/share", tags=["shares"])


class ShareOut(BaseModel):
    token: str
    doc_id: str
    created: datetime


class ShareMeta(BaseModel):
    doc_id: str
    title: str
    type: str


async def _get_owned(doc_id: str, user: User, session: AsyncSession) -> Document:
    doc = await session.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


async def _active_share(token: str, session: AsyncSession) -> Share:
    share = await session.get(Share, token)
    if share is None or share.revoked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "share not found")
    return share


@owner_router.post("/{doc_id}/share", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
async def create_share(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ShareOut:
    await _get_owned(doc_id, user, session)
    share = Share(doc_id=doc_id, org_id=user.org_id)
    session.add(share)
    await session.commit()
    return ShareOut(token=share.token, doc_id=doc_id, created=share.created)


@owner_router.get("/{doc_id}/shares", response_model=list[ShareOut])
async def list_shares(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ShareOut]:
    await _get_owned(doc_id, user, session)
    rows = await session.scalars(
        select(Share).where(Share.doc_id == doc_id, Share.revoked.is_(False))
    )
    return [ShareOut(token=s.token, doc_id=s.doc_id, created=s.created) for s in rows]


@owner_router.delete("/{doc_id}/share/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    doc_id: str,
    token: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_owned(doc_id, user, session)
    share = await session.get(Share, token)
    if share is not None and share.doc_id == doc_id and share.org_id == user.org_id:
        share.revoked = True
        await session.commit()


@public_router.get("/{token}", response_model=ShareMeta)
async def share_meta(token: str, session: AsyncSession = Depends(get_session)) -> ShareMeta:
    share = await _active_share(token, session)
    doc = await session.get(Document, share.doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return ShareMeta(doc_id=doc.id, title=doc.title, type=doc.type)


@public_router.get("/{token}/blob")
async def share_blob(token: str, session: AsyncSession = Depends(get_session)) -> Response:
    share = await _active_share(token, session)
    doc = await session.get(Document, share.doc_id)
    if doc is None or not doc.blob_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no blob for this document")
    return Response(
        content=storage.get_blob(doc.blob_key),
        media_type="application/octet-stream",
        headers={"Content-Disposition": storage.content_disposition(doc.title)},
    )
