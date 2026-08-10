"""End-to-end for the /sheets HTTP surface over the real Rust sidecar.

Skipped unless the sidecar binary is built (cargo build --release in
apps/sheets/native/xlsx-engine). Proves the reshaped session+base64 protocol:
open (bytes in) → read-range → manifest → read-entries → save (creates a doc
version) → close, all org-scoped.
"""
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.settings import XLSX_SIDECAR_BIN

pytestmark = pytest.mark.skipif(
    not Path(XLSX_SIDECAR_BIN).exists(), reason="xlsx sidecar not built"
)

_PARTS = {
    "[Content_Types].xml":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>',
    "_rels/.rels":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
    "xl/_rels/workbook.xml.rels":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>',
    "xl/workbook.xml":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
    "xl/worksheets/sheet1.xml":
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Hello</t></is></c>'
        '<c r="B1"><v>42</v></c></row></sheetData></worksheet>',
}


def _mini_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in _PARTS.items():
            z.writestr(name, content)
    return buf.getvalue()


def _auth(c: TestClient, email: str) -> dict:
    tok = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_open_read_save_roundtrip():
    with TestClient(main.app) as c:
        h = _auth(c, "sheetuser@x.com")
        wb = _mini_xlsx()

        opened = c.post("/sheets/open", content=wb, headers=h)
        assert opened.status_code == 200, opened.text
        meta = opened.json()
        sid = meta["sessionId"]
        sheet_id = meta["sheets"][0]["id"]
        assert meta["sheets"][0]["name"] == "Sheet1"

        rng = c.post(
            "/sheets/read-range",
            json={"sessionId": sid, "sheetId": sheet_id,
                  "range": {"startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 1}},
            headers=h,
        )
        assert rng.status_code == 200, rng.text

        man = c.post("/sheets/manifest", json={"sessionId": sid}, headers=h).json()
        names = [e["name"] for e in man["entries"]]
        assert "xl/worksheets/sheet1.xml" in names

        ent = c.post(
            "/sheets/read-entries",
            json={"sessionId": sid, "entries": ["xl/worksheets/sheet1.xml"]},
            headers=h,
        ).json()
        assert ent["entries"][0]["name"] == "xl/worksheets/sheet1.xml"
        assert ent["entries"][0]["contentB64"]

        # Save with no changes → still reassembles the archive and stores a doc.
        saved = c.post(
            "/sheets/save",
            json={"sessionId": sid, "title": "test.xlsx", "replacements": [],
                  "removals": [], "additions": []},
            headers=h,
        )
        assert saved.status_code == 200, saved.text
        out = saved.json()
        assert out["docId"] and out["size"] > 0
        new_sid = out["workbook"]["sessionId"]

        assert c.post("/sheets/close", json={"sessionId": new_sid}, headers=h).json()["ok"]


def test_cross_tenant_session_isolation():
    with TestClient(main.app) as c:
        ha = _auth(c, "sheet-a@x.com")
        hb = _auth(c, "sheet-b@x.com")
        sid = c.post("/sheets/open", content=_mini_xlsx(), headers=ha).json()["sessionId"]
        # tenant B cannot address A's session
        r = c.post("/sheets/manifest", json={"sessionId": sid}, headers=hb)
        assert r.status_code == 404
        c.post("/sheets/close", json={"sessionId": sid}, headers=ha)
