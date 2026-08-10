import app.main as main
from fastapi.testclient import TestClient


def _auth(c: TestClient, email: str) -> dict:
    tok = c.post("/auth/register", json={"email": email, "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_resolve_append_load_roundtrip():
    with TestClient(main.app) as c:
        h = _auth(c, "proj-a@x.com")

        # resolve a chat for an unsaved doc → stable chatId under the default project
        ref = c.post("/projects/resolve-chat", json={"tempChatId": "unsaved-1"}, headers=h).json()
        chat_id = ref["chatId"]
        assert c.post("/projects/resolve-chat", json={"tempChatId": "unsaved-1"}, headers=h).json()["chatId"] == chat_id

        c.post("/projects/append-chat", json={**ref, "role": "user", "text": "make a report"}, headers=h)
        c.post(
            "/projects/append-chat",
            json={**ref, "role": "assistant", "text": "done", "tools": [{"name": "web_search", "summary": "x"}]},
            headers=h,
        )
        msgs = c.get("/projects/chat", params={"chatId": chat_id}, headers=h).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert [m["seq"] for m in msgs] == [1, 2]
        assert msgs[1]["tools"][0]["name"] == "web_search"


def test_rebind_chat_follows_the_saved_doc():
    with TestClient(main.app) as c:
        h = _auth(c, "proj-b@x.com")
        ref = c.post("/projects/resolve-chat", json={"tempChatId": "unsaved-2"}, headers=h).json()
        c.post("/projects/append-chat", json={**ref, "role": "user", "text": "hi"}, headers=h)

        rebound = c.post(
            "/projects/rebind-chat",
            json={"projectId": ref["projectId"], "tempChatId": "unsaved-2", "newFilePath": "doc-99"},
            headers=h,
        ).json()
        assert rebound["chatId"] == ref["chatId"]  # same thread, history preserved

        # resolving by the saved doc id now finds the same chat
        again = c.post("/projects/resolve-chat", json={"filePath": "doc-99"}, headers=h).json()
        assert again["chatId"] == ref["chatId"]
        assert len(c.get("/projects/chat", params={"chatId": ref["chatId"]}, headers=h).json()) == 1


def test_projects_crud_and_timeline():
    with TestClient(main.app) as c:
        h = _auth(c, "proj-c@x.com")

        listed = c.get("/projects", headers=h).json()
        assert len(listed) == 1 and listed[0]["isDefault"] is True
        default_id = listed[0]["id"]

        pid = c.post("/projects", json={"name": "Research"}, headers=h).json()["id"]
        assert c.patch(f"/projects/{pid}", json={"name": "Research 2"}, headers=h).status_code == 200
        assert c.patch(f"/projects/{default_id}", json={"name": "nope"}, headers=h).status_code == 400

        # a chat with a message shows up in the default project's timeline
        ref = c.post("/projects/resolve-chat", json={"filePath": "doc-x"}, headers=h).json()
        c.post("/projects/append-chat", json={**ref, "role": "user", "text": "first line\nsecond"}, headers=h)
        tl = c.get(f"/projects/{default_id}/timeline", headers=h).json()
        assert tl and tl[0]["preview"] == "first line" and tl[0]["filePath"] == "doc-x"

        # move that file into the new project, then delete the project (reparents to default)
        c.post("/projects/move-file", json={"filePath": "doc-x", "projectId": pid}, headers=h)
        assert c.delete(f"/projects/{pid}", headers=h).status_code == 200
        assert c.delete(f"/projects/{default_id}", headers=h).status_code == 400


def test_cross_tenant_chat_isolation():
    with TestClient(main.app) as c:
        ha = _auth(c, "iso-a@x.com")
        hb = _auth(c, "iso-b@x.com")
        ref = c.post("/projects/resolve-chat", json={"filePath": "shared-key"}, headers=ha).json()
        # B resolving the same key gets its OWN separate chat, and can't read A's
        refb = c.post("/projects/resolve-chat", json={"filePath": "shared-key"}, headers=hb).json()
        assert refb["chatId"] != ref["chatId"]
        assert c.get("/projects/chat", params={"chatId": ref["chatId"]}, headers=hb).status_code == 404
