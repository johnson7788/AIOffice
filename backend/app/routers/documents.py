"""Document metadata + blob versions. All access is scoped to the caller's org."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..db import get_session
from ..locks import require_writable
from ..models import Document, DocumentVersion, User
from ..security import get_current_user
from ..settings import MAX_BLOB_MB, MAX_DOCS_PER_ORG, MAX_STORAGE_MB_PER_ORG

router = APIRouter(prefix="/documents", tags=["documents"])

_EXT_TYPE = {"docx": "docx", "pptx": "pptx", "xlsx": "xlsx", "pdf": "pdf", "md": "md"}


def _doc_type(title: str) -> str:
    ext = title.rsplit(".", 1)[-1].lower() if "." in title else ""
    return _EXT_TYPE.get(ext, "docx")


class DocumentOut(BaseModel):
    id: str
    title: str
    type: str
    updated: datetime


class VersionOut(BaseModel):
    id: str
    size: int
    created: datetime


async def _get_owned(doc_id: str, user: User, session: AsyncSession) -> Document:
    doc = await session.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


async def _read_body(request: Request) -> bytes:
    data = await request.body()
    if len(data) > MAX_BLOB_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "blob too large")
    return data


async def _check_quota(user: User, session: AsyncSession, new_docs: int, new_bytes: int) -> None:
    if MAX_DOCS_PER_ORG and new_docs:
        docs = await session.scalar(
            select(func.count(Document.id)).where(Document.org_id == user.org_id)
        )
        if (docs or 0) + new_docs > MAX_DOCS_PER_ORG:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "document quota exceeded")
    if MAX_STORAGE_MB_PER_ORG and new_bytes:
        used = await session.scalar(
            select(func.coalesce(func.sum(DocumentVersion.size), 0))
            .join(Document, Document.id == DocumentVersion.doc_id)
            .where(Document.org_id == user.org_id)
        )
        if (used or 0) + new_bytes > MAX_STORAGE_MB_PER_ORG * 1024 * 1024:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "storage quota exceeded")


async def _add_version(doc: Document, data: bytes, user: User, session: AsyncSession) -> DocumentVersion:
    ver = DocumentVersion(doc_id=doc.id, blob_key="", size=len(data))
    session.add(ver)
    await session.flush()  # need ver.id for the key
    ver.blob_key = f"org/{user.org_id}/doc/{doc.id}/{ver.id}"
    storage.put_blob(ver.blob_key, data)
    doc.blob_key = ver.blob_key
    return ver


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
) -> list[DocumentOut]:
    rows = await session.scalars(
        select(Document)
        .where(Document.org_id == user.org_id)
        .order_by(Document.updated.desc())
        .limit(limit)
    )
    return [DocumentOut(id=d.id, title=d.title, type=d.type, updated=d.updated) for d in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    request: Request,
    title: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    data = await _read_body(request)
    await _check_quota(user, session, new_docs=1, new_bytes=len(data))
    doc = Document(org_id=user.org_id, owner_id=user.id, title=title, type=_doc_type(title))
    session.add(doc)
    await session.flush()
    if data:
        await _add_version(doc, data, user, session)
    await session.commit()
    return DocumentOut(id=doc.id, title=doc.title, type=doc.type, updated=doc.updated)


@router.put("/{doc_id}/blob", response_model=VersionOut)
async def put_blob(
    doc_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionOut:
    doc = await _get_owned(doc_id, user, session)
    await require_writable(doc_id, user, session)
    data = await _read_body(request)
    await _check_quota(user, session, new_docs=0, new_bytes=len(data))
    ver = await _add_version(doc, data, user, session)
    await session.commit()
    return VersionOut(id=ver.id, size=ver.size, created=ver.created)


@router.get("/{doc_id}/blob")
async def get_blob(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    doc = await _get_owned(doc_id, user, session)
    if not doc.blob_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no blob for this document")
    return Response(
        content=storage.get_blob(doc.blob_key),
        media_type="application/octet-stream",
        headers={"Content-Disposition": storage.content_disposition(doc.title)},
    )


@router.get("/{doc_id}/versions", response_model=list[VersionOut])
async def list_versions(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[VersionOut]:
    await _get_owned(doc_id, user, session)
    rows = await session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.doc_id == doc_id)
        .order_by(DocumentVersion.created.desc())
    )
    return [VersionOut(id=v.id, size=v.size, created=v.created) for v in rows]


@router.post("/{doc_id}/versions/{ver_id}/restore", response_model=VersionOut)
async def restore_version(
    doc_id: str,
    ver_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VersionOut:
    doc = await _get_owned(doc_id, user, session)
    await require_writable(doc_id, user, session)
    old = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == ver_id, DocumentVersion.doc_id == doc_id
        )
    )
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    data = storage.get_blob(old.blob_key)
    await _check_quota(user, session, new_docs=0, new_bytes=len(data))
    ver = await _add_version(doc, data, user, session)  # copy old bytes forward as latest
    await session.commit()
    return VersionOut(id=ver.id, size=ver.size, created=ver.created)


# ── Thumbnails: client engines render a small PNG on save; we just store/serve it.
# Keyed off the doc (not a version) so it overwrites in place — no schema column
# needed, so this stays create_all-safe on existing DBs (no Alembic).
def _thumb_key(doc: Document) -> str:
    return f"org/{doc.org_id}/doc/{doc.id}/thumb"


@router.put("/{doc_id}/thumb", status_code=status.HTTP_204_NO_CONTENT)
async def put_thumb(
    doc_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    doc = await _get_owned(doc_id, user, session)
    storage.put_blob(_thumb_key(doc), await _read_body(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{doc_id}/thumb")
async def get_thumb(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    doc = await _get_owned(doc_id, user, session)
    try:
        data = storage.get_blob(_thumb_key(doc))
    except Exception:  # missing thumb (local FileNotFoundError / S3 NoSuchKey)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no thumbnail")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-cache"})
