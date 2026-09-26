from app.settings import limits


def test_anyone_can_request_access_but_gets_nothing_until_approved(client, admin):
    r = client.post("/access-requests", json={"email": "Ada@Example.com", "name": "Ada Labs", "useCase": "Evaluating a support bot"})
    assert r.status_code == 201 and r.json() == {"status": "received"}
    assert client.post("/access-requests", json={"email": "ada@example.com"}).status_code == 201  # duplicate: still one row
    assert client.post("/access-requests", json={"email": "not-an-email"}).status_code == 422
    client.post("/access-requests", json={"email": "bot@spam.com", "website": "http://spam"})  # honeypot filled in

    assert client.get("/admin/access-requests").status_code == 401  # only the operator can list them
    pending = client.get("/admin/access-requests?status=pending", headers=admin).json()
    assert [p["email"] for p in pending] == ["ada@example.com"] and pending[0]["useCase"] == "Evaluating a support bot"


def test_approving_creates_an_isolated_project_and_a_working_key(client, admin, auth):
    req = client.post("/access-requests", json={"email": "grace@example.com", "name": "Grace Co"}).status_code
    assert req == 201
    rid = next(p["id"] for p in client.get("/admin/access-requests?status=pending", headers=admin).json() if p["email"] == "grace@example.com")
    assert client.post(f"/admin/access-requests/{rid}/approve").status_code == 401
    out = client.post(f"/admin/access-requests/{rid}/approve", headers=admin).json()
    assert out["projectId"] == "grace-co" and out["key"].startswith("ewb_")

    theirs = {"Authorization": f"Bearer {out['key']}"}
    assert client.get("/suites", headers=theirs).json() == []          # their own empty project
    assert "demo-story" not in [s["id"] for s in client.get("/suites", headers=theirs).json()]
    assert client.get("/runs/DS-R1", headers=theirs).status_code == 404  # cannot see the demo project's data
    assert client.post(f"/admin/access-requests/{rid}/approve", headers=admin).status_code == 409
    approved = client.get("/admin/access-requests?status=approved", headers=admin).json()
    assert any(a["projectId"] == "grace-co" for a in approved)


def test_rejecting_a_request(client, admin):
    client.post("/access-requests", json={"email": "nope@example.com"})
    rid = next(p["id"] for p in client.get("/admin/access-requests", headers=admin).json() if p["email"] == "nope@example.com")
    assert client.post(f"/admin/access-requests/{rid}/reject", headers=admin).json()["status"] == "rejected"


def test_access_requests_are_rate_limited_per_client(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ACCESS_REQUESTS_PER_HOUR", "2")
    codes = [client.post("/access-requests", json={"email": f"user{i}@example.com"}).status_code for i in range(4)]
    assert codes == [201, 201, 429, 429]


def test_guessing_api_keys_gets_blocked(client):
    codes = [client.get("/suites", headers={"Authorization": f"Bearer ewb_guess{i}"}).status_code for i in range(32)]
    assert codes[0] == 401 and codes[-1] == 429


def test_guessing_the_admin_key_gets_blocked(client):
    codes = [client.get("/admin/projects", headers={"Authorization": f"Bearer guess{i}"}).status_code for i in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def _trace(**over):
    return {"suiteId": "limits-app", "suiteName": "Limits app", "input": "hi", "actual": "ok", "latencyMs": 5, **over}


def test_size_limits_reject_oversized_input(client, auth, monkeypatch):
    monkeypatch.setenv("MAX_TEXT_CHARS", "50")
    assert client.post("/ingest", headers=auth, json=_trace(actual="x" * 51)).status_code == 413
    monkeypatch.setenv("MAX_SPANS_PER_EXECUTION", "2")
    spans = [{"name": f"s{i}"} for i in range(3)]
    assert client.post("/ingest", headers=auth, json=_trace(spans=spans)).status_code == 413
    assert client.post("/ingest", headers=auth, json=_trace()).status_code == 201


def test_per_project_allowance_stops_storing_after_the_cap(client, auth, monkeypatch):
    used = client.get("/usage", headers=auth).json()["executions"]
    monkeypatch.setenv("MAX_RESULTS_PER_PROJECT", str(used + 1))
    assert client.post("/ingest", headers=auth, json=_trace()).status_code == 201
    over = client.post("/ingest", headers=auth, json=_trace())
    assert over.status_code == 429 and "allowance" in over.json()["detail"]
    usage = client.get("/usage", headers=auth).json()
    assert usage["executions"] == used + 1 and usage["executionsLimit"] == used + 1


def test_suite_cap_and_ingest_rate_limit(client, auth, monkeypatch):
    monkeypatch.setenv("MAX_SUITES_PER_PROJECT", str(client.get("/usage", headers=auth).json()["suites"]))
    assert client.post("/suites", headers=auth, json={"name": "One too many"}).status_code == 429
    monkeypatch.delenv("MAX_SUITES_PER_PROJECT")
    monkeypatch.setenv("RATE_LIMIT_INGEST_PER_MIN", "2")
    codes = [client.post("/ingest", headers=auth, json=_trace()).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_batch_size_limit(client, auth, monkeypatch):
    run = client.post("/runs", headers=auth, json={"suiteId": "demo-story"}).json()["run"]["id"]
    monkeypatch.setenv("MAX_RESULTS_PER_BATCH", "1")
    two = {"results": [{"caseId": "DS-001", "actual": "a"}, {"caseId": "DS-002", "actual": "b"}]}
    assert client.post(f"/runs/{run}/results", headers=auth, json=two).status_code == 413


def test_production_mode_turns_off_dev_shortcuts(client, monkeypatch):
    monkeypatch.setenv("EVAL_WORKBENCH_DEV_KEY", "ewb_dev")
    monkeypatch.setenv("EVAL_WORKBENCH_ENV", "production")
    assert client.get("/dev-connect", headers={"Host": "127.0.0.1:8000"}).status_code == 404
    assert client.get("/health").headers["x-content-type-options"] == "nosniff"
    assert limits()["max_results"] == 10000  # documented default
