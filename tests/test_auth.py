import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELLING_AUTH", "on")
    monkeypatch.setenv("SPELLING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SPELLING_USERNAME", "Lexi")
    monkeypatch.setenv("SPELLING_PASSWORD", "spelling")
    import app.config
    importlib.reload(app.config)
    importlib.reload(importlib.import_module("app.auth"))
    main = importlib.reload(importlib.import_module("app.main"))
    return TestClient(main.app)


def test_pages_and_api_need_sign_in(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
    assert client.get("/api/home").status_code == 401
    assert client.get("/media/x.mp3").status_code == 401
    # The sign-in page and the app's code load without signing in.
    assert client.get("/login").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_sign_in_and_out(client):
    assert client.post("/api/login", json={"username": "Lexi", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"username": "Lexi", "password": "Spelling"}).status_code == 401
    r = client.post("/api/login", json={"username": " lexi ", "password": "spelling"})   # name ignores case
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/home").status_code == 200
    client.get("/logout")
    assert client.get("/api/home").status_code == 401


def test_forged_cookie_is_rejected(client):
    client.cookies.set("spelling_session", "lexi|9999999999|deadbeef")
    assert client.get("/api/home").status_code == 401
