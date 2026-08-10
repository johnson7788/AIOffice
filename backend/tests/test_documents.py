import app.main as main
from fastapi.testclient import TestClient


def _auth(c: TestClient, email: str) -> dict:
    tok = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_create_save_list_download_roundtrip():
    with TestClient(main.app) as c:
        h = _auth(c, "docuser@x.com")

        # create with initial blob
        r = c.post("/documents", params={"title": "report.docx"}, content=b"V1BYTES", headers=h)
        assert r.status_code == 201
        doc = r.json()
        assert doc["type"] == "docx"
        did = doc["id"]

        # download returns the stored bytes
        blob = c.get(f"/documents/{did}/blob", headers=h)
        assert blob.status_code == 200 and blob.content == b"V1BYTES"

        # save a new version
        assert c.put(f"/documents/{did}/blob", content=b"V2BYTES", headers=h).status_code == 200
        assert c.get(f"/documents/{did}/blob", headers=h).content == b"V2BYTES"

        # two versions recorded
        vers = c.get(f"/documents/{did}/versions", headers=h).json()
        assert len(vers) == 2

        # recent list includes it
        listed = c.get("/documents", headers=h).json()
        assert any(d["id"] == did for d in listed)


def test_cross_tenant_isolation():
    with TestClient(main.app) as c:
        ha = _auth(c, "tenant-a@x.com")
        hb = _auth(c, "tenant-b@x.com")
        did = c.post("/documents", params={"title": "a.docx"}, content=b"secret", headers=ha).json()["id"]

        # tenant B cannot read A's document, blob, or versions
        assert c.get(f"/documents/{did}/blob", headers=hb).status_code == 404
        assert c.put(f"/documents/{did}/blob", content=b"x", headers=hb).status_code == 404
        assert c.get(f"/documents/{did}/versions", headers=hb).status_code == 404
        # B's list holds only B's own (seed) docs, never A's document.
        assert all(d["id"] != did for d in c.get("/documents", headers=hb).json())


def test_thumbnail_put_get_missing():
    with TestClient(main.app) as c:
        h = _auth(c, "thumb@x.com")
        did = c.post("/documents", params={"title": "t.pptx"}, content=b"deck", headers=h).json()["id"]

        # no thumb yet → 404
        assert c.get(f"/documents/{did}/thumb", headers=h).status_code == 404
        # store then serve as image/png
        assert c.put(f"/documents/{did}/thumb", content=b"PNGBYTES", headers=h).status_code == 204
        r = c.get(f"/documents/{did}/thumb", headers=h)
        assert r.status_code == 200 and r.content == b"PNGBYTES"
        assert r.headers["content-type"] == "image/png"
        # cross-tenant cannot read/write it
        hb = _auth(c, "thumb-b@x.com")
        assert c.get(f"/documents/{did}/thumb", headers=hb).status_code == 404
        assert c.put(f"/documents/{did}/thumb", content=b"x", headers=hb).status_code == 404


def test_star_soft_delete_restore_purge():
    with TestClient(main.app) as c:
        h = _auth(c, "flags@x.com")
        did = c.post("/documents", params={"title": "f.docx"}, content=b"x", headers=h).json()["id"]

        # star it → appears starred in the list
        assert c.patch(f"/documents/{did}", json={"starred": True}, headers=h).json()["starred"] is True
        assert any(d["id"] == did and d["starred"] for d in c.get("/documents", headers=h).json())

        # soft-delete → gone from default list, present in trash
        assert c.delete(f"/documents/{did}", headers=h).status_code == 204
        assert all(d["id"] != did for d in c.get("/documents", headers=h).json())
        assert any(d["id"] == did for d in c.get("/documents", params={"trashed": "true"}, headers=h).json())

        # restore → back in default list
        assert c.post(f"/documents/{did}/restore-doc", headers=h).status_code == 204
        assert any(d["id"] == did for d in c.get("/documents", headers=h).json())

        # purge → gone everywhere; blob 404s
        assert c.delete(f"/documents/{did}/purge", headers=h).status_code == 204
        assert all(d["id"] != did for d in c.get("/documents", headers=h).json())
        assert c.get(f"/documents/{did}/blob", headers=h).status_code == 404


def test_blob_size_limit():
    from app.settings import MAX_BLOB_MB

    with TestClient(main.app) as c:
        h = _auth(c, "big@x.com")
        too_big = b"x" * (MAX_BLOB_MB * 1024 * 1024 + 1)
        assert c.post("/documents", params={"title": "big.docx"}, content=too_big, headers=h).status_code == 413
