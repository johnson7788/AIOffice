"""Private image gallery. A user's own images: uploaded, or extracted from a
document they own. Org-scoped like documents (cross-tenant → 404). Blobs stored
at org/{org}/asset/{id}. Extraction runs server-side: OOXML (docx/pptx/xlsx) via
stdlib zipfile, PDF via pypdf — no office library needed."""
import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..db import get_session
from ..models import Asset, Document, User
from ..security import get_current_user
from ..settings import MAX_BLOB_MB, MAX_STORAGE_MB_PER_ORG

# prefix /gallery, NOT /assets: the docs SPA is served at base "/" and emits its
# build bundles to /assets/* — a /assets API would shadow them at nginx.
router = APIRouter(prefix="/gallery", tags=["gallery"])

# image extension → mime (extracted files carry no content-type)
_EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "bmp": "image/bmp", "webp": "image/webp", "tiff": "image/tiff", "tif": "image/tiff",
    "svg": "image/svg+xml", "emf": "image/emf", "wmf": "image/wmf",
}
# OOXML media dirs (docx=word, pptx=ppt, xlsx=xl)
_MEDIA_PREFIXES = ("word/media/", "ppt/media/", "xl/media/")


class AssetOut(BaseModel):
    id: str
    name: str
    mime: str
    size: int
    source: str
    created: datetime


def _mime_from_name(name: str) -> str | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _EXT_MIME.get(ext)


def _doc_type_from_name(name: str) -> str | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext if ext in ("docx", "pptx", "xlsx", "pdf") else None


def _blob_key(org_id: str, asset_id: str) -> str:
    return f"org/{org_id}/asset/{asset_id}"


async def _get_owned(asset_id: str, user: User, session: AsyncSession) -> Asset:
    a = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.org_id == user.org_id)
    )
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found")
    return a


async def _check_storage(user: User, session: AsyncSession, new_bytes: int) -> None:
    # ponytail: assets share the org storage cap with documents; sum asset bytes only
    # (doc bytes already guarded in documents._check_quota). Split caps if it matters.
    if MAX_STORAGE_MB_PER_ORG and new_bytes:
        used = await session.scalar(
            select(func.coalesce(func.sum(Asset.size), 0)).where(Asset.org_id == user.org_id)
        )
        if (used or 0) + new_bytes > MAX_STORAGE_MB_PER_ORG * 1024 * 1024:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "storage quota exceeded")


def _add_asset(user: User, name: str, mime: str, data: bytes, source: str, session: AsyncSession) -> Asset:
    a = Asset(org_id=user.org_id, name=name, mime=mime, size=len(data), source=source)
    session.add(a)
    return a


@router.get("", response_model=list[AssetOut])
async def list_assets(
    q: str = "",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = 200,
) -> list[AssetOut]:
    stmt = select(Asset).where(Asset.org_id == user.org_id)
    if q.strip():
        stmt = stmt.where(Asset.name.ilike(f"%{q.strip()}%"))
    rows = await session.scalars(stmt.order_by(Asset.created.desc()).limit(limit))
    return [
        AssetOut(id=a.id, name=a.name, mime=a.mime, size=a.size, source=a.source, created=a.created)
        for a in rows
    ]


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    request: Request,
    name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetOut:
    mime = (request.headers.get("content-type") or "").split(";")[0].strip()
    if not mime or mime == "application/octet-stream":
        mime = _mime_from_name(name) or ""
    if not mime.startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an image")
    data = await request.body()
    if len(data) > MAX_BLOB_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "image too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")
    await _check_storage(user, session, len(data))
    a = _add_asset(user, name, mime, data, "upload", session)
    await session.flush()
    storage.put_blob(_blob_key(user.org_id, a.id), data)
    await session.commit()
    return AssetOut(id=a.id, name=a.name, mime=a.mime, size=a.size, source=a.source, created=a.created)


@router.get("/{asset_id}/blob")
async def get_asset_blob(
    asset_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    a = await _get_owned(asset_id, user, session)
    return Response(
        content=storage.get_blob(_blob_key(user.org_id, a.id)),
        media_type=a.mime,
        headers={"Cache-Control": "no-cache"},
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    a = await _get_owned(asset_id, user, session)
    await session.delete(a)
    await session.commit()
    # ponytail: blob left in storage (orphaned); add a GC sweep if it matters
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _extract_images(doc_type: str, blob: bytes) -> list[tuple[str, str, bytes]]:
    """Return [(name, mime, bytes)] for every image inside the document."""
    out: list[tuple[str, str, bytes]] = []
    if doc_type in ("docx", "pptx", "xlsx"):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                n = info.filename
                if not any(n.startswith(p) for p in _MEDIA_PREFIXES):
                    continue
                mime = _mime_from_name(n)
                if not mime:  # skip non-image media (e.g. embedded audio/video)
                    continue
                out.append((n.rsplit("/", 1)[-1], mime, zf.read(n)))
    elif doc_type == "pdf":
        from pypdf import PdfReader  # lazy: only PDFs need it

        reader = PdfReader(io.BytesIO(blob))
        seen = 0
        for page in reader.pages:
            for img in page.images:
                mime = _mime_from_name(img.name) or "image/png"
                seen += 1
                out.append((img.name or f"image{seen}.png", mime, img.data))
    return out


async def _persist_extracted(
    user: User, images: list[tuple[str, str, bytes]], source: str, session: AsyncSession
) -> list[AssetOut]:
    await _check_storage(user, session, sum(len(d) for _, _, d in images))
    created: list[Asset] = []
    for name, mime, data in images:
        a = _add_asset(user, name, mime, data, source, session)
        await session.flush()
        storage.put_blob(_blob_key(user.org_id, a.id), data)
        created.append(a)
    await session.commit()
    return [
        AssetOut(id=a.id, name=a.name, mime=a.mime, size=a.size, source=a.source, created=a.created)
        for a in created
    ]


@router.post("/extract-from/{doc_id}", response_model=list[AssetOut])
async def extract_from(
    doc_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AssetOut]:
    doc = await session.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    if not doc.blob_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document has no content")
    try:
        images = _extract_images(doc.type, storage.get_blob(doc.blob_key))
    except Exception as e:  # noqa: BLE001 — corrupt/unsupported file
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"cannot extract: {e}")
    return await _persist_extracted(user, images, f"doc:{doc_id}", session)


@router.post("/extract", response_model=list[AssetOut])
async def extract_upload(
    request: Request,
    name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AssetOut]:
    """Extract images from a document the user uploads here (docx/pptx/xlsx/pdf),
    without persisting the document itself — only the extracted images are kept."""
    doc_type = _doc_type_from_name(name)
    if not doc_type:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload a docx/pptx/xlsx/pdf file")
    data = await request.body()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")
    if len(data) > MAX_BLOB_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
    try:
        images = _extract_images(doc_type, data)
    except Exception as e:  # noqa: BLE001 — corrupt/unsupported file
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"cannot extract: {e}")
    return await _persist_extracted(user, images, f"file:{name}", session)
