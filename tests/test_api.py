import pytest

from fintech.web import create_app


@pytest.fixture
def client():
    app = create_app(db_path=":memory:", testing=True)
    return app.test_client()


def login(c, name="ivan", pwd="password1"):
    c.post("/api/register", json={"login": name, "full_name": name.title(), "password": pwd})
    assert c.post("/api/login", json={"login": name, "password": pwd}).status_code == 200


def test_requires_auth(client):
    assert client.get("/api/accounts").status_code == 401


def test_full_flow(client):
    login(client)
    acc = client.post("/api/accounts").get_json()["number"]
    r = client.post(f"/api/accounts/{acc}/deposit", json={"amount": "500"}, headers={"Idempotency-Key": "d1"})
    assert r.status_code == 200
    accs = client.get("/api/accounts").get_json()
    assert accs[0]["balance"] == "500.00"
    r = client.post(f"/api/accounts/{acc}/withdraw", json={"amount": "abc"})
    assert r.status_code == 422
    hist = client.get(f"/api/accounts/{acc}/history").get_json()
    assert hist[0]["amount"] == "500.00"


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_loan_endpoint(client):
    j = client.get("/api/loan?amount=100000&rate=12&months=12").get_json()
    assert j["payments"][0]["payment"] == "8884.88"
    assert client.get("/api/loan?amount=0&rate=12&months=12").status_code == 422
