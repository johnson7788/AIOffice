"""ProjectApi persistence: projects + conversations + messages, org-scoped.

Backs the browser `window.projectApi` (frontend packages/project-store ipc.ts).
genoffice keys chats by file path; here the key is the server document id (a
temp key for an unsaved doc, rebound to the doc id once it's saved).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Conversation, Document, Message, Project, User
from ..security import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


# ── schemas ────────────────────────────────────────────────────────────────
class ResolveChatIn(BaseModel):
    filePath: str | None = None
    tempChatId: str | None = None


class ChatRef(BaseModel):
    projectId: str
    chatId: str


class AppendChatIn(BaseModel):
    projectId: str
    chatId: str
    role: str
    text: str = ""
    tools: list | None = None
    attachments: list | None = None


class RebindChatIn(BaseModel):
    projectId: str
    tempChatId: str
    newChatId: str | None = None
    newFilePath: str | None = None


class ChatMessageOut(BaseModel):
    seq: int
    ts: str
    role: str
    text: str
    tools: list | None = None
    attachments: list | None = None


class CreateProjectIn(BaseModel):
    name: str


class RenameProjectIn(BaseModel):
    name: str


class MoveFileIn(BaseModel):
    filePath: str
    projectId: str


class ProjectSummaryOut(BaseModel):
    id: str
    name: str
    createdAt: datetime
    updatedAt: datetime
    fileCount: int
    lastActiveAt: datetime
    isDefault: bool


class TimelineEntryOut(BaseModel):
    filePath: str
    fileName: str
    chatId: str
    ts: str
    role: str
    preview: str
    seq: int


# ── helpers ────────────────────────────────────────────────────────────────
async def _default_project(user: User, session: AsyncSession) -> Project:
    proj = await session.scalar(
        select(Project).where(Project.org_id == user.org_id, Project.is_default.is_(True))
    )
    if proj is None:
        proj = Project(org_id=user.org_id, name="工作台", is_default=True)
        session.add(proj)
        await session.flush()
    return proj


async def _owned_project(pid: str, user: User, session: AsyncSession) -> Project:
    proj = await session.scalar(
        select(Project).where(Project.id == pid, Project.org_id == user.org_id)
    )
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return proj


async def _owned_conv(chat_id: str, user: User, session: AsyncSession) -> Conversation:
    conv = await session.scalar(
        select(Conversation).where(Conversation.id == chat_id, Conversation.org_id == user.org_id)
    )
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conv


async def _find_by_key(key: str, user: User, session: AsyncSession) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(
            Conversation.org_id == user.org_id, Conversation.chat_key == key
        )
    )


# ── chat routes ────────────────────────────────────────────────────────────
@router.post("/resolve-chat", response_model=ChatRef)
async def resolve_chat(
    body: ResolveChatIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatRef:
    key = body.filePath or body.tempChatId or "default"
    conv = await _find_by_key(key, user, session)
    if conv is None:
        proj = await _default_project(user, session)
        conv = Conversation(org_id=user.org_id, project_id=proj.id, chat_key=key)
        session.add(conv)
        await session.flush()
    await session.commit()
    return ChatRef(projectId=conv.project_id, chatId=conv.id)


@router.post("/append-chat")
async def append_chat(
    body: AppendChatIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _owned_conv(body.chatId, user, session)
    max_seq = await session.scalar(
        select(func.max(Message.seq)).where(Message.conv_id == conv.id)
    )
    msg = Message(
        conv_id=conv.id,
        seq=(max_seq or 0) + 1,
        role=body.role,
        text=body.text,
        tools=body.tools,
        attachments=body.attachments,
    )
    session.add(msg)
    conv.updated = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True}


@router.get("/chat", response_model=list[ChatMessageOut])
async def load_chat(
    chatId: str,
    limit: int = 200,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageOut]:
    conv = await _owned_conv(chatId, user, session)
    rows = list(
        await session.scalars(
            select(Message)
            .where(Message.conv_id == conv.id)
            .order_by(Message.seq.desc())
            .limit(limit)
        )
    )
    rows.reverse()  # return oldest→newest of the last `limit`
    return [
        ChatMessageOut(
            seq=m.seq, ts=m.ts.isoformat(), role=m.role, text=m.text,
            tools=m.tools, attachments=m.attachments,
        )
        for m in rows
    ]


@router.post("/rebind-chat", response_model=ChatRef)
async def rebind_chat(
    body: RebindChatIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatRef:
    conv = await _find_by_key(body.tempChatId, user, session)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    conv.chat_key = body.newFilePath or body.newChatId or conv.chat_key
    await session.commit()
    return ChatRef(projectId=conv.project_id, chatId=conv.id)


# ── project routes ─────────────────────────────────────────────────────────
async def _summary(proj: Project, session: AsyncSession) -> ProjectSummaryOut:
    convs = list(
        await session.scalars(select(Conversation).where(Conversation.project_id == proj.id))
    )
    last = proj.updated
    for c in convs:
        if c.updated > last:
            last = c.updated
    return ProjectSummaryOut(
        id=proj.id, name=proj.name, createdAt=proj.created, updatedAt=proj.updated,
        fileCount=len(convs), lastActiveAt=last, isDefault=proj.is_default,
    )


@router.get("", response_model=list[ProjectSummaryOut])
async def list_projects(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectSummaryOut]:
    await _default_project(user, session)  # ensure one exists
    await session.commit()
    projs = list(
        await session.scalars(
            select(Project).where(Project.org_id == user.org_id).order_by(Project.created)
        )
    )
    return [await _summary(p, session) for p in projs]


@router.post("", response_model=ProjectSummaryOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectSummaryOut:
    proj = Project(org_id=user.org_id, name=body.name)
    session.add(proj)
    await session.commit()
    return await _summary(proj, session)


@router.patch("/{pid}")
async def rename_project(
    pid: str,
    body: RenameProjectIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    proj = await _owned_project(pid, user, session)
    if proj.is_default:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot rename default project")
    proj.name = body.name
    await session.commit()
    return {"ok": True}


@router.delete("/{pid}")
async def delete_project(
    pid: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    proj = await _owned_project(pid, user, session)
    if proj.is_default:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete default project")
    # reparent conversations to the default project, then drop the project
    default = await _default_project(user, session)
    for c in await session.scalars(select(Conversation).where(Conversation.project_id == pid)):
        c.project_id = default.id
    await session.delete(proj)
    await session.commit()
    return {"ok": True}


@router.post("/move-file")
async def move_file(
    body: MoveFileIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _owned_project(body.projectId, user, session)
    conv = await _find_by_key(body.filePath, user, session)
    if conv is not None:
        conv.project_id = body.projectId
        await session.commit()
    return {"ok": True}


@router.get("/{pid}/timeline", response_model=list[TimelineEntryOut])
async def get_timeline(
    pid: str,
    limit: int = 50,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TimelineEntryOut]:
    await _owned_project(pid, user, session)
    convs = {
        c.id: c
        for c in await session.scalars(
            select(Conversation).where(Conversation.project_id == pid)
        )
    }
    if not convs:
        return []
    rows = await session.scalars(
        select(Message)
        .where(Message.conv_id.in_(list(convs)))
        .order_by(Message.ts.desc())
        .limit(limit)
    )
    # map any doc-id chat_key to its title for a friendlier file name
    titles = {
        d.id: d.title
        for d in await session.scalars(
            select(Document).where(Document.org_id == user.org_id)
        )
    }
    out = []
    for m in rows:
        conv = convs[m.conv_id]
        key = conv.chat_key
        name = titles.get(key, key)
        out.append(
            TimelineEntryOut(
                filePath=key, fileName=name, chatId=conv.id, ts=m.ts.isoformat(),
                role=m.role, preview=m.text.splitlines()[0][:120] if m.text else "", seq=m.seq,
            )
        )
    return out
