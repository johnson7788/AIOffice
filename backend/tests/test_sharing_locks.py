"""M5 collaboration/productionization: locks, shares, version restore, quota, rate limit."""
import asyncio
from datetime import datetime, timedelta, timezone

import app.main as main
import app.ratelimit as ratelimit
import app.routers.documents as docs_mod
from app.db import SessionLocal
from app.models import DocumentLock
from fastapi.testclient import TestClient


def _reg(c: TestClient, email: str) -> dict:
    r = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()
    r["headers"] = {"Authorization": f"Bearer {r['token']}"}
    return r


def _run(coro):
    return asyncio.run(coro)


async def _put_lock(doc_id: str, org_id: str, user_id: str, expires: datetime) -> None:
    async with SessionLocal() as s:
        lock = await s.get(DocumentLock, doc_id)
        if lock is None:
            s.add(DocumentLock(doc_id=doc_id, org_id=org_id, user_id=user_id, expires=expires))
        else:
            lock.user_id, lock.expires = user_id, expires
        await s.commit()


def test_lock_acquire_renew_release():
    with TestClient(main.app) as c:
        a = _reg(c, "lock-a@x.com")
        did = c.post("/documents", params={"title": "l.docx"}, content=b"V1", headers=a["headers"]).json()["id"]
        r = c.post(f"/documents/{did}/lock", headers=a["headers"])
        assert r.status_code == 200 and r.json()["mine"] is True
        assert c.post(f"/documents/{did}/lock", headers=a["headers"]).status_code == 200  # renew
        assert c.delete(f"/documents/{did}/lock", headers=a["headers"]).status_code == 204


def test_lock_blocks_other_writer():
    with TestClient(main.app) as c:
        a = _reg(c, "lock-owner@x.com")
        did = c.post("/documents", params={"title": "l.docx"}, content=b"V1", headers=a["headers"]).json()["id"]
        # someone else in the same org holds a live lock
        future = datetime.now(timezone.utc) + timedelta(seconds=60)
        _run(_put_lock(did, a["org_id"], "other-user", future))

        assert c.put(f"/documents/{did}/blob", content=b"V2", headers=a["headers"]).status_code == 409
        assert c.post(f"/documents/{did}/lock", headers=a["headers"]).status_code == 409

        # once it lapses, the owner steals it and can save
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        _run(_put_lock(did, a["org_id"], "other-user", past))
        assert c.post(f"/documents/{did}/lock", headers=a["headers"]).json()["mine"] is True
        assert c.put(f"/documents/{did}/blob", content=b"V2", headers=a["headers"]).status_code == 200


def test_share_public_readonly_and_revoke():
    with TestClient(main.app) as c:
        a = _reg(c, "share-a@x.com")
        b = _reg(c, "share-b@x.com")
        did = c.post("/documents", params={"title": "s.docx"}, content=b"SHARED", headers=a["headers"]).json()["id"]

        # cross-tenant cannot share A's doc
        assert c.post(f"/documents/{did}/share", headers=b["headers"]).status_code == 404

        token = c.post(f"/documents/{did}/share", headers=a["headers"]).json()["token"]
        # public, no auth
        assert c.get(f"/share/{token}").json()["title"] == "s.docx"
        assert c.get(f"/share/{token}/blob").content == b"SHARED"

        # revoke -> public access gone
        assert c.delete(f"/documents/{did}/share/{token}", headers=a["headers"]).status_code == 204
        assert c.get(f"/share/{token}").status_code == 404
        assert c.get(f"/share/{token}/blob").status_code == 404


def test_version_restore():
    with TestClient(main.app) as c:
        a = _reg(c, "restore@x.com")
        did = c.post("/documents", params={"title": "r.docx"}, content=b"V1", headers=a["headers"]).json()["id"]
        c.put(f"/documents/{did}/blob", content=b"V2", headers=a["headers"])
        vers = c.get(f"/documents/{did}/versions", headers=a["headers"]).json()
        v1 = vers[-1]["id"]  # oldest
        assert c.post(f"/documents/{did}/versions/{v1}/restore", headers=a["headers"]).status_code == 200
        assert c.get(f"/documents/{did}/blob", headers=a["headers"]).content == b"V1"  # restored latest


def test_doc_quota():
    orig = docs_mod.MAX_DOCS_PER_ORG
    try:
        with TestClient(main.app) as c:
            a = _reg(c, "quota@x.com")
            # New orgs start with seed docs; set the cap one above the current
            # count so exactly one more create succeeds and the next is blocked.
            seeded = len(c.get("/documents", headers=a["headers"]).json())
            docs_mod.MAX_DOCS_PER_ORG = seeded + 1
            assert c.post("/documents", params={"title": "1.docx"}, content=b"x", headers=a["headers"]).status_code == 201
            assert c.post("/documents", params={"title": "2.docx"}, content=b"x", headers=a["headers"]).status_code == 402
    finally:
        docs_mod.MAX_DOCS_PER_ORG = orig


def test_rate_limit():
    orig = ratelimit.MAX
    ratelimit.MAX = 3
    ratelimit._counts.clear()
    try:
        with TestClient(main.app) as c:
            a = _reg(c, "rate@x.com")  # counts toward the ip bucket; use a fresh window
            ratelimit._counts.clear()
            codes = [c.get("/documents", headers=a["headers"]).status_code for _ in range(5)]
            assert 429 in codes and codes.count(200) <= 3
    finally:
        ratelimit.MAX = orig
        ratelimit._counts.clear()
