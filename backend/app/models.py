"""ORM models. Every resource carries org_id; queries filter on it (tenant isolation)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(32), default="free")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    pwd_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="owner")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(16))  # docx | pptx | xlsx | pdf | md
    blob_key: Mapped[str | None] = mapped_column(String(256), nullable=True)  # latest version blob
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    blob_key: Mapped[str] = mapped_column(String(256))
    size: Mapped[int] = mapped_column(default=0)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped["Document"] = relationship(back_populates="versions")


class DocumentLock(Base):
    """Single-writer lock, one row per document (doc_id is the PK). TTL-based:
    the holder renews before expiry; a stale lock is freely stealable. No
    heartbeat thread — enforcement is a timestamp comparison at write time."""

    __tablename__ = "document_locks"
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Share(Base):
    """Public read-only share link. token is an unguessable key; anyone with it
    reads the document's latest blob without auth. Revocable."""

    __tablename__ = "shares"
    token: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocFlags(Base):
    """Per-document management flags (star + soft-delete). A separate table so
    adding these needs no ALTER on documents — create_all makes it on existing
    DBs (no Alembic). One row per doc, created lazily on first flag write."""

    __tablename__ = "doc_flags"
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base):
    """A user's private image (uploaded, or extracted from a document). Org-scoped
    like everything else. Blob at org/{org}/asset/{id}. source = 'upload' or
    'doc:<docId>'. Separate table → create_all-safe on existing DBs (no Alembic)."""

    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(64), default="upload")  # upload | doc:<docId>
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Conversation(Base):
    """One chat thread. chat_key = the document id it's bound to, or a temp key
    for an unsaved doc (rebound to the doc id once it hits storage)."""

    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    chat_key: Mapped[str] = mapped_column(String(256), index=True)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conv_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    text: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
