"""Sheets (xlsx) engine endpoints — thin HTTP over the Rust xlsx-sidecar.

The sidecar addresses workbooks by filesystem path and holds calamine/IronCalc
sessions in-process. This router owns a per-session temp working file so the
BROWSER never handles fs paths: the client sends xlsx bytes to /open and then
addresses everything by the returned sessionId. The write-planning gateway runs
client-side (genoffice's xlsx-* modules); it ships changed entry bytes here and
the sidecar reassembles the zip (save_archive), which we store as a new version.

ponytail: session table is an in-process dict + temp dir per session, reaped on
/close. Fine for single-replica; a shared store (Redis + object temp) only if we
scale the backend out — the sidecar itself is already single-process (see
xlsx_sidecar.py), so sessions are pinned to this replica regardless.
"""
import base64
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..locks import require_writable
from ..models import User
from ..security import get_current_user
from ..settings import MAX_BLOB_MB
from ..xlsx_sidecar import SidecarError, sidecar
from .documents import _add_version, _check_quota, _get_owned

router = APIRouter(prefix="/sheets", tags=["sheets"])


class _Session:
    __slots__ = ("org_id", "dir", "path")

    def __init__(self, org_id: str, work_dir: Path, path: Path) -> None:
        self.org_id = org_id
        self.dir = work_dir
        self.path = path


# sessionId (from the sidecar) → working-file state, org-scoped.
_sessions: dict[str, _Session] = {}


def _own(session_id: str, user: User) -> _Session:
    s = _sessions.get(session_id)
    if s is None or s.org_id != user.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workbook session not found")
    return s


async def _read_body(request: Request) -> bytes:
    data = await request.body()
    if len(data) > MAX_BLOB_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "workbook too large")
    return data


@router.post("/open")
async def open_workbook(request: Request, user: User = Depends(get_current_user)) -> dict:
    """Body = raw xlsx bytes (client fetched the doc blob, or built a blank).
    Returns the sidecar's workbook metadata + the sessionId to address it."""
    data = await _read_body(request)
    work_dir = Path(tempfile.mkdtemp(prefix="aioffice-xlsx-"))
    path = work_dir / "workbook.xlsx"
    path.write_bytes(data)
    try:
        result = await sidecar().request("open", path=str(path))
    except SidecarError as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    session_id = result["sessionId"]
    _sessions[session_id] = _Session(user.org_id, work_dir, path)
    return result


class RangeIn(BaseModel):
    sessionId: str
    sheetId: str
    range: dict


@router.post("/read-range")
async def read_range(body: RangeIn, user: User = Depends(get_current_user)) -> dict:
    _own(body.sessionId, user)
    return await sidecar().request(
        "read_range", sessionId=body.sessionId, sheetId=body.sheetId, range=body.range
    )


class FormulasIn(BaseModel):
    sessionId: str
    sheetId: str


@router.post("/read-formulas")
async def read_formulas(body: FormulasIn, user: User = Depends(get_current_user)) -> dict:
    _own(body.sessionId, user)
    return await sidecar().request(
        "read_formula_cells", sessionId=body.sessionId, sheetId=body.sheetId
    )


class MediaIn(BaseModel):
    sessionId: str
    visualId: str


@router.post("/read-media")
async def read_media(body: MediaIn, user: User = Depends(get_current_user)) -> dict:
    _own(body.sessionId, user)
    return await sidecar().request(
        "read_media", sessionId=body.sessionId, visualId=body.visualId
    )


class RecalcIn(BaseModel):
    sessionId: str
    edits: list[dict]
    reads: list[dict]


@router.post("/recalc")
async def recalc(body: RecalcIn, user: User = Depends(get_current_user)) -> dict:
    s = _own(body.sessionId, user)
    # recalc_cells is path-addressed (loads the file fresh), not session-addressed.
    return await sidecar().request(
        "recalc_cells", path=str(s.path), edits=body.edits, reads=body.reads
    )


class ManifestIn(BaseModel):
    sessionId: str


@router.post("/manifest")
async def manifest(body: ManifestIn, user: User = Depends(get_current_user)) -> dict:
    s = _own(body.sessionId, user)
    return await sidecar().request("archive_manifest", path=str(s.path))


class ReadEntriesIn(BaseModel):
    sessionId: str
    entries: list[str]


@router.post("/read-entries")
async def read_entries(body: ReadEntriesIn, user: User = Depends(get_current_user)) -> dict:
    """Sidecar extracts entries to files; we return their bytes as base64 so the
    client's gateway never sees a server path."""
    s = _own(body.sessionId, user)
    out_dir = Path(tempfile.mkdtemp(prefix="aioffice-xlsx-read-", dir=s.dir))
    try:
        result = await sidecar().request(
            "read_entries", path=str(s.path), entries=body.entries, outputDir=str(out_dir)
        )
        entries = [
            {"name": e["name"], "contentB64": base64.b64encode(Path(e["path"]).read_bytes()).decode()}
            for e in result["entries"]
        ]
        return {"entries": entries}
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


class ScanEntriesIn(BaseModel):
    sessionId: str
    entries: list[str]
    needle: str


@router.post("/scan-entries")
async def scan_entries(body: ScanEntriesIn, user: User = Depends(get_current_user)) -> dict:
    s = _own(body.sessionId, user)
    return await sidecar().request(
        "scan_entries", path=str(s.path), entries=body.entries, needle=body.needle
    )


class NamedContent(BaseModel):
    name: str
    contentB64: str


class SaveIn(BaseModel):
    sessionId: str
    docId: str | None = None
    title: str | None = None
    replacements: list[NamedContent] = []
    removals: list[str] = []
    additions: list[NamedContent] = []


@router.post("/save")
async def save_workbook(
    body: SaveIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Apply the client gateway's plan (changed entry bytes) via the sidecar's
    save_archive, store the result as a new document version, and reopen a fresh
    session on the saved file (genoffice resets the sidecar session on save)."""
    from ..models import Document  # local import: avoid cycle at module load

    s = _own(body.sessionId, user)

    def _materialize(items: list[NamedContent], tag: str) -> list[dict]:
        out = []
        for i, it in enumerate(items):
            p = s.dir / f"{tag}-{i}.bin"
            p.write_bytes(base64.b64decode(it.contentB64))
            out.append({"name": it.name, "contentPath": str(p)})
        return out

    replacements = _materialize(body.replacements, "replace")
    additions = _materialize(body.additions, "add")
    target = s.dir / "saved.xlsx"
    await sidecar().request(
        "save_archive",
        sourcePath=str(s.path),
        targetPath=str(target),
        replacements=replacements,
        removals=body.removals,
        additions=additions,
    )
    data = target.read_bytes()

    # Persist as a new version (existing doc) or a new document.
    if body.docId:
        doc = await _get_owned(body.docId, user, session)
        await require_writable(body.docId, user, session)
        await _check_quota(user, session, new_docs=0, new_bytes=len(data))
        await _add_version(doc, data, user, session)
        doc_id = doc.id
    else:
        await _check_quota(user, session, new_docs=1, new_bytes=len(data))
        doc = Document(
            org_id=user.org_id, owner_id=user.id, title=body.title or "工作簿.xlsx", type="xlsx"
        )
        session.add(doc)
        await session.flush()
        await _add_version(doc, data, user, session)
        doc_id = doc.id
    await session.commit()

    # Promote the saved file as the new source, then reopen a fresh session so
    # later diffs are against the saved state and read_range sees saved values.
    s.path.write_bytes(data)
    await sidecar().request("close", sessionId=body.sessionId)
    _sessions.pop(body.sessionId, None)
    reopened = await sidecar().request("open", path=str(s.path))
    new_id = reopened["sessionId"]
    _sessions[new_id] = _Session(user.org_id, s.dir, s.path)
    return {"docId": doc_id, "size": len(data), "workbook": reopened}


class CloseIn(BaseModel):
    sessionId: str


@router.post("/close")
async def close_workbook(body: CloseIn, user: User = Depends(get_current_user)) -> dict:
    s = _sessions.pop(body.sessionId, None)
    if s is None or s.org_id != user.org_id:
        return {"ok": True}
    try:
        await sidecar().request("close", sessionId=body.sessionId)
    except SidecarError:
        pass
    shutil.rmtree(s.dir, ignore_errors=True)
    return {"ok": True}
