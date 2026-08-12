"""Installed extension skills (Anthropic Agent Skills format: a zip with a
SKILL.md). Org-scoped like documents/assets (cross-tenant -> 404). The zip is
stored at org/{org}/skill/{id}. Everything is served back as text/context for
the browser agent — the backend NEVER executes any script inside a skill.

Progressive disclosure: the agent sees each enabled skill's name+description
(GET /skills), pulls the SKILL.md body on demand (GET /skills/{id}), and reads a
reference file only when needed (GET /skills/{id}/file?path=)."""
import io
import ipaddress
import socket
import zipfile
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..db import get_session
from ..models import Skill, User
from ..security import get_current_user
from ..settings import MAX_BLOB_MB, MAX_SKILLS_PER_ORG, MAX_STORAGE_MB_PER_ORG

router = APIRouter(prefix="/skills", tags=["skills"])

# zip-bomb guards: reject packs with too many members or too much uncompressed data.
_MAX_MEMBERS = 2000
_MAX_UNCOMPRESSED = MAX_BLOB_MB * 1024 * 1024 * 4
# only text-ish files are ever returned to the agent (no binaries, no scripts run).
_TEXT_EXT = {"md", "markdown", "txt", "json", "yaml", "yml", "csv", "py", "mjs", "js", "ts", "html", "xml", "sh"}
# install-by-URL response cap + timeout
_MAX_DOWNLOAD = MAX_BLOB_MB * 1024 * 1024


def _blob_key(org_id: str, skill_id: str) -> str:
    return f"org/{org_id}/skill/{skill_id}"


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    version: str | None
    source: str
    enabled: bool
    size: int
    created: datetime


class SkillDetail(SkillOut):
    body: str  # SKILL.md markdown body (frontmatter stripped)
    files: list[str]  # every member path in the pack


class InstallIn(BaseModel):
    url: str


class PatchIn(BaseModel):
    enabled: bool | None = None


def _out(s: Skill) -> SkillOut:
    return SkillOut(
        id=s.id, name=s.name, description=s.description, version=s.version,
        source=s.source, enabled=s.enabled, size=s.size, created=s.created,
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into (frontmatter dict, body). Minimal YAML: only
    single-line `key: value` (value may be quoted). No pyyaml dependency."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        fm[key.strip().lower()] = val
    return fm, body


def _safe_members(zf: zipfile.ZipFile) -> list[str]:
    """Validated member paths (zip-slip + zip-bomb guards). Raises on abuse."""
    members: list[str] = []
    total = 0
    for info in zf.infolist():
        name = info.filename
        if info.is_dir():
            continue
        # zip-slip: no absolute paths, no parent traversal, no drive letters
        if name.startswith("/") or name.startswith("\\") or ".." in name.split("/") or ":" in name:
            raise ValueError(f"unsafe path in zip: {name}")
        total += info.file_size
        if total > _MAX_UNCOMPRESSED or len(members) >= _MAX_MEMBERS:
            raise ValueError("skill package too large")
        members.append(name)
    return members


def _find_skill_md(members: list[str]) -> str | None:
    """SKILL.md at the top level or one directory deep; shallowest wins."""
    cands = [m for m in members if m.rsplit("/", 1)[-1] == "SKILL.md" and m.count("/") <= 1]
    return min(cands, key=lambda m: m.count("/")) if cands else None


def _parse_skill(blob: bytes) -> tuple[str, str, str | None, str, list[str]]:
    """Return (name, description, version, body, files). Raises ValueError on
    invalid packages (caller maps to 400)."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = _safe_members(zf)
        skill_md = _find_skill_md(members)
        if not skill_md:
            raise ValueError("no SKILL.md found in package")
        raw = zf.read(skill_md).decode("utf-8", "replace")
    fm, body = _parse_frontmatter(raw)
    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name or not description:
        raise ValueError("SKILL.md frontmatter must define name and description")
    return name, description, fm.get("version") or None, body, members


async def _get_owned(skill_id: str, user: User, session: AsyncSession) -> Skill:
    s = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.org_id == user.org_id)
    )
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill not found")
    return s


async def _check_limits(user: User, session: AsyncSession, new_bytes: int) -> None:
    if MAX_SKILLS_PER_ORG:
        count = await session.scalar(
            select(func.count(Skill.id)).where(Skill.org_id == user.org_id)
        )
        if (count or 0) >= MAX_SKILLS_PER_ORG:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "skill quota exceeded")
    if MAX_STORAGE_MB_PER_ORG and new_bytes:
        used = await session.scalar(
            select(func.coalesce(func.sum(Skill.size), 0)).where(Skill.org_id == user.org_id)
        )
        if (used or 0) + new_bytes > MAX_STORAGE_MB_PER_ORG * 1024 * 1024:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "storage quota exceeded")


async def _install_blob(user: User, blob: bytes, source: str, session: AsyncSession) -> SkillOut:
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")
    if len(blob) > MAX_BLOB_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "skill package too large")
    try:
        name, description, version, _body, _files = _parse_skill(blob)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid skill: {e}")
    await _check_limits(user, session, len(blob))
    # (org, name) unique: replace an existing skill of the same name (re-install/upgrade)
    existing = await session.scalar(
        select(Skill).where(Skill.org_id == user.org_id, Skill.name == name)
    )
    if existing is not None:
        existing.description = description
        existing.version = version
        existing.source = source
        existing.size = len(blob)
        s = existing
    else:
        s = Skill(
            org_id=user.org_id, name=name, description=description, version=version,
            source=source, size=len(blob),
        )
        session.add(s)
    await session.flush()
    storage.put_blob(_blob_key(user.org_id, s.id), blob)
    await session.commit()
    return _out(s)


@router.get("", response_model=list[SkillOut])
async def list_skills(
    enabled: int | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SkillOut]:
    stmt = select(Skill).where(Skill.org_id == user.org_id)
    if enabled is not None:
        stmt = stmt.where(Skill.enabled == bool(enabled))
    rows = await session.scalars(stmt.order_by(Skill.created.desc()))
    return [_out(s) for s in rows]


@router.post("/upload", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def upload_skill(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    blob = await request.body()
    return await _install_blob(user, blob, "upload", session)


def _assert_public_host(host: str) -> None:
    """SSRF guard: block private/loopback/link-local/metadata targets."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot resolve host")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "host not allowed")


@router.post("/install", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def install_skill(
    body: InstallIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    parsed = urlparse(body.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only https URLs allowed")
    _assert_public_host(parsed.hostname)
    try:
        # follow_redirects off: a redirect could hop to an internal host past the check
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            r = await client.get(body.url)
            r.raise_for_status()
            blob = r.content
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"download failed: {e}")
    if len(blob) > _MAX_DOWNLOAD:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "skill package too large")
    return await _install_blob(user, blob, f"url:{parsed.hostname}", session)


@router.get("/{skill_id}", response_model=SkillDetail)
async def get_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SkillDetail:
    s = await _get_owned(skill_id, user, session)
    try:
        _n, _d, _v, body, files = _parse_skill(storage.get_blob(_blob_key(user.org_id, s.id)))
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"corrupt skill: {e}")
    return SkillDetail(**_out(s).model_dump(), body=body, files=files)


@router.get("/{skill_id}/file")
async def get_skill_file(
    skill_id: str,
    path: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    s = await _get_owned(skill_id, user, session)
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext not in _TEXT_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a text file")
    with zipfile.ZipFile(io.BytesIO(storage.get_blob(_blob_key(user.org_id, s.id)))) as zf:
        members = _safe_members(zf)
        if path not in members:  # path must be an exact listed member (no traversal)
            raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
        text = zf.read(path).decode("utf-8", "replace")
    return {"path": path, "text": text}


@router.patch("/{skill_id}", response_model=SkillOut)
async def patch_skill(
    skill_id: str,
    body: PatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SkillOut:
    s = await _get_owned(skill_id, user, session)
    if body.enabled is not None:
        s.enabled = body.enabled
    await session.commit()
    return _out(s)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    s = await _get_owned(skill_id, user, session)
    await session.delete(s)
    await session.commit()
    from fastapi.responses import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)
