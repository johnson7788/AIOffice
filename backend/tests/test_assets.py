import io
import zipfile
import zlib

import app.main as main
from fastapi.testclient import TestClient

# 1x1 transparent PNG
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\xdac\xfc\x0f\x00\x02\x05"
    b"\x01\x02\xa2\xff\xff\xff\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _auth(c: TestClient, email: str) -> dict:
    tok = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _docx_with_media(images: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        for i in range(1, images + 1):
            zf.writestr(f"word/media/image{i}.png", PNG)
        zf.writestr("word/media/audio1.wav", b"RIFF")  # non-image media, must be skipped
    return buf.getvalue()


def _pdf_with_image() -> bytes:
    raw = zlib.compress(b"\xff\x00\x00")  # 1x1 red RGB
    content = b"q 1 0 0 1 0 0 cm /Im0 Do Q"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % len(raw)
        + raw
        + b"\nendstream",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, b in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + b + b"\nendobj\n"
    xp = len(out)
    n = len(objs) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % n
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (n, xp)
    return out


def test_upload_list_blob_delete_roundtrip():
    with TestClient(main.app) as c:
        h = _auth(c, "gal@x.com")
        r = c.post("/gallery", params={"name": "logo.png"}, content=PNG,
                   headers={**h, "Content-Type": "image/png"})
        assert r.status_code == 201
        a = r.json()
        assert a["mime"] == "image/png" and a["source"] == "upload"

        listed = c.get("/gallery", headers=h).json()
        assert any(x["id"] == a["id"] for x in listed)

        blob = c.get(f"/gallery/{a['id']}/blob", headers=h)
        assert blob.status_code == 200 and blob.content == PNG
        assert blob.headers["content-type"] == "image/png"

        assert c.delete(f"/gallery/{a['id']}", headers=h).status_code == 204
        assert all(x["id"] != a["id"] for x in c.get("/gallery", headers=h).json())


def test_upload_rejects_non_image():
    with TestClient(main.app) as c:
        h = _auth(c, "gal2@x.com")
        r = c.post("/gallery", params={"name": "notes.txt"}, content=b"hello",
                   headers={**h, "Content-Type": "text/plain"})
        assert r.status_code == 400


def test_cross_tenant_isolation():
    with TestClient(main.app) as c:
        ha = _auth(c, "ga@x.com")
        hb = _auth(c, "gb@x.com")
        aid = c.post("/gallery", params={"name": "a.png"}, content=PNG,
                     headers={**ha, "Content-Type": "image/png"}).json()["id"]
        assert c.get(f"/gallery/{aid}/blob", headers=hb).status_code == 404
        assert c.delete(f"/gallery/{aid}", headers=hb).status_code == 404
        assert all(x["id"] != aid for x in c.get("/gallery", headers=hb).json())


def test_search_filter():
    with TestClient(main.app) as c:
        h = _auth(c, "gs@x.com")
        for nm in ("cat-photo.png", "dog-photo.png"):
            c.post("/gallery", params={"name": nm}, content=PNG, headers={**h, "Content-Type": "image/png"})
        res = c.get("/gallery", params={"q": "cat"}, headers=h).json()
        assert [x["name"] for x in res] == ["cat-photo.png"]


def test_extract_from_office():
    with TestClient(main.app) as c:
        h = _auth(c, "gx@x.com")
        did = c.post("/documents", params={"title": "deck.docx"}, content=_docx_with_media(3),
                     headers=h).json()["id"]
        created = c.post(f"/gallery/extract-from/{did}", headers=h).json()
        assert len(created) == 3  # 3 images, the .wav skipped
        assert all(x["source"] == f"doc:{did}" and x["mime"] == "image/png" for x in created)
        # extracted assets now show in the gallery
        assert len([x for x in c.get("/gallery", headers=h).json() if x["source"] == f"doc:{did}"]) == 3


def test_extract_from_pdf():
    with TestClient(main.app) as c:
        h = _auth(c, "gp@x.com")
        did = c.post("/documents", params={"title": "scan.pdf"}, content=_pdf_with_image(),
                     headers=h).json()["id"]
        created = c.post(f"/gallery/extract-from/{did}", headers=h).json()
        assert len(created) == 1
        assert created[0]["source"] == f"doc:{did}"
        # the extracted image is fetchable
        assert c.get(f"/gallery/{created[0]['id']}/blob", headers=h).status_code == 200


def test_extract_cross_tenant_404():
    with TestClient(main.app) as c:
        ha = _auth(c, "gxa@x.com")
        hb = _auth(c, "gxb@x.com")
        did = c.post("/documents", params={"title": "d.docx"}, content=_docx_with_media(1),
                     headers=ha).json()["id"]
        assert c.post(f"/gallery/extract-from/{did}", headers=hb).status_code == 404
