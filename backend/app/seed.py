"""Seed a new org with starter documents on register, so first-time users have
something to open right away. Manifest-driven: drop a real template file into
app/seed/ and list it in manifest.json — no code change."""
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from .models import Document, DocumentVersion, Organization, Skill, User
from .routers.documents import _doc_type
from .routers.skills import _blob_key, _parse_skill

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


async def seed_org_skills(session: AsyncSession, org: Organization) -> None:
    """Install every bundled skill pack (seed/skills/*.zip) for a new org, so
    first-time users have a working example in the 技能中心. Same parse/store path
    as the /skills router; invalid packs are skipped."""
    skills_dir = _SEED_DIR / "skills"
    if not skills_dir.exists():
        return
    for src in sorted(skills_dir.glob("*.zip")):
        blob = src.read_bytes()
        try:
            name, description, version, _body, _files = _parse_skill(blob)
        except Exception:
            continue
        skill = Skill(
            org_id=org.id, name=name, description=description, version=version,
            source="seed", size=len(blob),
        )
        session.add(skill)
        await session.flush()  # need skill.id for the blob key
        storage.put_blob(_blob_key(org.id, skill.id), blob)
