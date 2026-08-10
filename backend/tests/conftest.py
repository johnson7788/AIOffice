"""Point the app at throwaway sqlite + local-FS storage before it imports."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aioffice-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ.setdefault("JWT_SECRET", "test-secret")
