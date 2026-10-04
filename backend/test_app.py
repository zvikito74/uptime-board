import pytest

from app import create_app, run_checks, valid_url


def fake_checker(url):
    if "down" in url:
        return {"ok": False, "status_code": 503, "response_ms": 40, "error": None}
    return {"ok": True, "status_code": 200, "response_ms": 120, "error": None}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    app = create_app(db_path=db_path, start_checker=False, checker=fake_checker)
    return app.test_client()


def add(client, name, url):
    return client.post("/api/targets", json={"name": name, "url": url})


def test_health(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_add_and_list_target(client):
    assert add(client, "Example", "https://example.com").status_code == 201
    targets = client.get("/api/targets").get_json()
    assert len(targets) == 1
    assert targets[0]["status"] == "unknown"
    assert targets[0]["history"] == []


def test_rejects_bad_input(client):
    assert add(client, "", "https://example.com").status_code == 400
    assert add(client, "Bad", "ftp://example.com").status_code == 400
    assert add(client, "Bad", "not a url").status_code == 400


def test_rejects_duplicate_url(client):
    add(client, "One", "https://example.com")
    assert add(client, "Two", "https://example.com").status_code == 409


def test_check_records_up_and_down(client):
    add(client, "Good", "https://example.com")
    add(client, "Bad", "https://down.example.com")
    assert client.post("/api/check").get_json() == {"checked": 2}

    by_name = {t["name"]: t for t in client.get("/api/targets").get_json()}
    assert by_name["Good"]["status"] == "up"
    assert by_name["Good"]["uptime_24h"] == 100.0
    assert by_name["Good"]["last_response_ms"] == 120
    assert by_name["Bad"]["status"] == "down"
    assert by_name["Bad"]["uptime_24h"] == 0.0
    assert by_name["Bad"]["last_status_code"] == 503


def test_uptime_percentage_over_several_checks(client, db_path):
    add(client, "Flaky", "https://example.com")
    results = iter([True, True, False, True])
    run = lambda url: {"ok": next(results), "status_code": 200, "response_ms": 10, "error": None}
    for _ in range(4):
        run_checks(db_path, run)

    target = client.get("/api/targets").get_json()[0]
    assert target["uptime_24h"] == 75.0
    assert [h["ok"] for h in target["history"]] == [True, True, False, True]


def test_delete_target_removes_history(client):
    target_id = add(client, "Example", "https://example.com").get_json()["id"]
    client.post("/api/check")
    assert client.delete(f"/api/targets/{target_id}").status_code == 204
    assert client.get("/api/targets").get_json() == []
    assert client.delete(f"/api/targets/{target_id}").status_code == 404


def test_valid_url():
    assert valid_url("https://example.com/path")
    assert not valid_url("javascript:alert(1)")
    assert not valid_url("https://")
