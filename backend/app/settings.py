"""Runtime settings from environment (repo-root .env).

Defaults run the whole stack locally with zero infra: SQLite file + local-FS
blob storage. Point DATABASE_URL at Postgres and S3_* at MinIO/S3 for prod.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# override=True: repo-root .env is authoritative, so shell-exported variables
# (which python-dotenv's default keeps) cannot shadow this app's own config.
load_dotenv(override=True)

# async SQLAlchemy URL; sqlite+aiosqlite for dev, postgresql+asyncpg for prod
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./aioffice.db")

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-insecure-change-me")
JWT_ALG = "HS256"
JWT_TTL_MIN = int(os.environ.get("JWT_TTL_MIN", "1440"))  # 24h access token (refresh: M5)

# blob storage: local FS unless S3_ENDPOINT is set
STORAGE_DIR = os.environ.get("STORAGE_DIR", "./storage")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")  # e.g. http://minio:9000
S3_BUCKET = os.environ.get("S3_BUCKET", "aioffice")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

MAX_BLOB_MB = int(os.environ.get("MAX_BLOB_MB", "50"))

# per-org quota (free plan). 0 disables the check.
MAX_DOCS_PER_ORG = int(os.environ.get("MAX_DOCS_PER_ORG", "500"))
MAX_STORAGE_MB_PER_ORG = int(os.environ.get("MAX_STORAGE_MB_PER_ORG", "2048"))
MAX_SKILLS_PER_ORG = int(os.environ.get("MAX_SKILLS_PER_ORG", "50"))  # 0 disables

# single-writer lock TTL (seconds); client renews before it lapses.
LOCK_TTL_SEC = int(os.environ.get("LOCK_TTL_SEC", "120"))

# rate limit: max requests per window per identity (user id, else client IP).
# ponytail: in-process fixed-window counter — swap for Redis when multi-replica.
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "300"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("RATE_LIMIT_WINDOW_SEC", "60"))

# SearXNG JSON search endpoint (self-hosted). Empty disables search (returns empty).
SEARXNG_URL = os.environ.get("SEARXNG_URL", "")

# xlsx sidecar (Rust calamine+ironcalc) binary path. Sheets read/recalc/zip run here.
# Dev default = vendored build in backend/xlsx-engine; prod bakes it into the image at /usr/local/bin.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
XLSX_SIDECAR_BIN = os.environ.get(
    "XLSX_SIDECAR_BIN",
    str(_BACKEND_ROOT / "xlsx-engine" / "target" / "release" / "xlsx-sidecar"),
)
