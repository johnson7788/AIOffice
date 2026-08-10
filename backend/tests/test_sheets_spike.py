"""M4.5 sheets xlsx spike — decision proof: option B (backend service).

The genoffice sheets engine is a Rust binary (calamine + IronCalc) that speaks
line-delimited JSON over stdin/stdout and holds workbook sessions IN-PROCESS,
addressing files by filesystem path. That maps 1:1 onto a backend that spawns
one subprocess per session (option B) — it does NOT map cleanly onto in-browser
WASM (option A), which would need a virtual FS for every PathBuf command plus
in-worker streaming-session state and a multi-MB .wasm (the native binary is
already ~8 MB). So the spike picks B.

This test proves the binary is drivable by a plain (non-Electron) host exactly
the way a FastAPI subprocess manager would drive it: send `open`, get workbook
metadata back. It is SKIPPED unless the sidecar has been built at the genoffice
path (cargo build --release in apps/sheets/native/xlsx-engine).
"""
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

SIDECAR = Path(
    "/Users/admin/git/genoffice/apps/sheets/native/xlsx-engine/target/release/xlsx-sidecar"
)

# Minimal valid xlsx: Sheet1 with A1="Hello", B1=42.
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


def _mini_xlsx(path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in _PARTS.items():
            z.writestr(name, content)
    path.write_bytes(buf.getvalue())


@pytest.mark.skipif(not SIDECAR.exists(), reason="xlsx sidecar not built")
def test_sidecar_open_over_stdio(tmp_path):
    xlsx = tmp_path / "mini.xlsx"
    _mini_xlsx(xlsx)
    req = json.dumps({"version": 1, "requestId": "r1", "command": "open", "path": str(xlsx)})
    proc = subprocess.run(
        [str(SIDECAR)], input=req + "\n", capture_output=True, text=True, timeout=30
    )
    line = proc.stdout.strip().splitlines()[0]
    resp = json.loads(line)
    assert resp["ok"] is True, resp
    assert resp["result"]["sheets"][0]["name"] == "Sheet1"
    assert resp["result"]["sessionId"]  # in-process session handle (option B state model)
