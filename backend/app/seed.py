"""Seed a new org with starter documents on register, so first-time users have
something to open right away. Manifest-driven: drop a real template file into
app/seed/ and list it in manifest.json — no code change."""
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from .models import Document, DocumentVersion, Organization, User
from .routers.documents import _doc_type

_SEED_DIR = Path(__file__).parent / "seed"


async def seed_org_documents(session: AsyncSession, org: Organization, user: User) -> None:
    manifest = _SEED_DIR / "manifest.json"
    if not manifest.exists():
        return
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        src = _SEED_DIR / entry["file"]
        if not src.exists():
            continue
        data = src.read_bytes()
        title = entry["title"]
        doc = Document(org_id=org.id, owner_id=user.id, title=title, type=_doc_type(title))
        session.add(doc)
        await session.flush()  # need doc.id for the blob key
        ver = DocumentVersion(doc_id=doc.id, blob_key="", size=len(data))
        session.add(ver)
        await session.flush()  # need ver.id
        ver.blob_key = f"org/{org.id}/doc/{doc.id}/{ver.id}"
        storage.put_blob(ver.blob_key, data)
        doc.blob_key = ver.blob_key
