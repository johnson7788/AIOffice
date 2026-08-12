import io
import zipfile

import app.main as main
import app.routers.skills as skills
from fastapi.testclient import TestClient

SKILL_MD = (
    "---\n"
    "name: pdf-formatter\n"
    'description: "Formats references in APA style."\n'
    "version: 1.2.0\n"
    "---\n"
    "# PDF Formatter\n\nDo the thing.\n"
)


def _auth(c: TestClient, email: str) -> dict:
    tok = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _skill_zip(skill_md: str = SKILL_MD, extra: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", skill_md)
        for path, content in (extra or {}).items():
            zf.writestr(path, content)
    return buf.getvalue()


def test_upload_list_get_file_patch_delete_roundtrip():
    with TestClient(main.app) as c:
        h = _auth(c, "sk@x.com")
        blob = _skill_zip(extra={"references/style.md": "APA rules here"})
        r = c.post("/skills/upload", content=blob, headers=h)
        assert r.status_code == 201
        s = r.json()
        assert s["name"] == "pdf-formatter" and s["version"] == "1.2.0" and s["enabled"] is True
        assert s["source"] == "upload"

        listed = c.get("/skills", headers=h).json()
        assert any(x["id"] == s["id"] for x in listed)
        # enabled filter
        assert c.get("/skills", params={"enabled": 1}, headers=h).json()

        detail = c.get(f"/skills/{s['id']}", headers=h).json()
        assert "Do the thing." in detail["body"] and "SKILL.md" in detail["files"]
        assert "references/style.md" in detail["files"]

        fr = c.get(f"/skills/{s['id']}/file", params={"path": "references/style.md"}, headers=h)
        assert fr.status_code == 200 and fr.json()["text"] == "APA rules here"

        # disable
        pr = c.patch(f"/skills/{s['id']}", json={"enabled": False}, headers=h)
        assert pr.status_code == 200 and pr.json()["enabled"] is False
        assert all(x["id"] != s["id"] for x in c.get("/skills", params={"enabled": 1}, headers=h).json())

        assert c.delete(f"/skills/{s['id']}", headers=h).status_code == 204
        assert all(x["id"] != s["id"] for x in c.get("/skills", headers=h).json())


def test_upload_missing_frontmatter_400():
    with TestClient(main.app) as c:
        h = _auth(c, "sk2@x.com")
        bad = _skill_zip("# no frontmatter\njust body")
        assert c.post("/skills/upload", content=bad, headers=h).status_code == 400
        # name present, description missing
        bad2 = _skill_zip("---\nname: x\n---\nbody")
        assert c.post("/skills/upload", content=bad2, headers=h).status_code == 400


def test_upload_no_skill_md_400():
    with TestClient(main.app) as c:
        h = _auth(c, "sk3@x.com")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hi")
        assert c.post("/skills/upload", content=buf.getvalue(), headers=h).status_code == 400


def test_zip_slip_rejected():
    with TestClient(main.app) as c:
        h = _auth(c, "sk4@x.com")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", SKILL_MD)
            zf.writestr("../evil.md", "pwned")
        assert c.post("/skills/upload", content=buf.getvalue(), headers=h).status_code == 400


def test_file_non_text_rejected():
    with TestClient(main.app) as c:
        h = _auth(c, "sk5@x.com")
        blob = _skill_zip(extra={"assets/logo.png": "\x89PNG"})
        sid = c.post("/skills/upload", content=blob, headers=h).json()["id"]
        r = c.get(f"/skills/{sid}/file", params={"path": "assets/logo.png"}, headers=h)
        assert r.status_code == 400


def test_reinstall_same_name_replaces():
    with TestClient(main.app) as c:
        h = _auth(c, "sk6@x.com")
        c.post("/skills/upload", content=_skill_zip(), headers=h)
        v2 = _skill_zip(SKILL_MD.replace("1.2.0", "2.0.0"))
        c.post("/skills/upload", content=v2, headers=h)
        listed = c.get("/skills", headers=h).json()
        same = [x for x in listed if x["name"] == "pdf-formatter"]
        assert len(same) == 1 and same[0]["version"] == "2.0.0"


def test_cross_tenant_404():
    with TestClient(main.app) as c:
        ha = _auth(c, "ska@x.com")
        hb = _auth(c, "skb@x.com")
        sid = c.post("/skills/upload", content=_skill_zip(), headers=ha).json()["id"]
        assert c.get(f"/skills/{sid}", headers=hb).status_code == 404
        assert c.patch(f"/skills/{sid}", json={"enabled": False}, headers=hb).status_code == 404
        assert c.delete(f"/skills/{sid}", headers=hb).status_code == 404
        assert all(x["id"] != sid for x in c.get("/skills", headers=hb).json())


def test_register_seeds_humanizer_skill():
    # new orgs get the bundled 去AI味 example skill, enabled, source=seed
    with TestClient(main.app) as c:
        h = _auth(c, "skseed@x.com")
        listed = c.get("/skills", params={"enabled": 1}, headers=h).json()
        seed = [x for x in listed if x["source"] == "seed"]
        assert seed and seed[0]["name"] == "humanizer" and seed[0]["enabled"] is True


def test_install_ssrf_blocked(monkeypatch):
    with TestClient(main.app) as c:
        h = _auth(c, "sks@x.com")
        # non-https rejected before any network
        assert c.post("/skills/install", json={"url": "http://example.com/s.zip"}, headers=h).status_code == 400
        # https to an internal host rejected by _assert_public_host
        monkeypatch.setattr(
            skills.socket, "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))],
        )
        assert c.post("/skills/install", json={"url": "https://internal.local/s.zip"}, headers=h).status_code == 400
