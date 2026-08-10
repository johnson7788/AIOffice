import app.main as main
from fastapi.testclient import TestClient


def test_register_login_me_flow():
    with TestClient(main.app) as c:
        r = c.post("/auth/register", json={"email": "a@x.com", "password": "pw12345"})
        assert r.status_code == 200
        tok = r.json()
        assert tok["token"] and tok["org_id"]

        # duplicate email rejected
        assert c.post("/auth/register", json={"email": "a@x.com", "password": "pw"}).status_code == 409

        # login returns same org
        r2 = c.post("/auth/login", json={"email": "a@x.com", "password": "pw12345"})
        assert r2.status_code == 200 and r2.json()["org_id"] == tok["org_id"]

        # wrong password
        assert c.post("/auth/login", json={"email": "a@x.com", "password": "nope"}).status_code == 401

        # /me with token
        me = c.get("/auth/me", headers={"Authorization": f"Bearer {tok['token']}"})
        assert me.status_code == 200 and me.json()["email"] == "a@x.com"


def test_me_requires_valid_token():
    with TestClient(main.app) as c:
        assert c.get("/auth/me").status_code == 401  # no bearer
        assert c.get("/auth/me", headers={"Authorization": "Bearer bad"}).status_code == 401
