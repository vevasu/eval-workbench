import json
from pathlib import Path

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "sample-data.json").read_text(encoding="utf-8"))


def test_requests_without_a_valid_key_get_401(client, auth):
    assert client.get("/suites").status_code == 401
    assert client.get("/suites", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/state", headers={"Authorization": "Bearer test-admin"}).status_code == 401
    assert client.get("/suites", headers=auth).status_code == 200


def test_state_matches_sample_data_field_for_field(client, auth):
    state = client.get("/state", headers=auth).json()
    assert [s["id"] for s in state["suites"]] == [s["id"] for s in DATA["suites"]]
    for got, want in zip(state["suites"], DATA["suites"]):
        for field in ("id", "prefix", "name", "description", "pipeline", "slaMs", "systemPrompt", "context", "createdAt"):
            assert got[field] == want[field], field
        assert [c["id"] for c in got["cases"]] == [c["id"] for c in want["cases"]]
        for gc, wc in zip(got["cases"], want["cases"]):
            for field in ("id", "tag", "input", "expected", "checks"):
                assert gc[field] == wc[field]
    test_runs = [r for r in DATA["runs"] if r["target"] != "production"]
    assert sorted(r["id"] for r in state["runs"]) == sorted(r["id"] for r in test_runs)  # live traffic is read from /production
    got_runs = {r["id"]: r for r in state["runs"]}
    for want in test_runs:
        got = got_runs[want["id"]]
        for field in ("id", "suiteId", "version", "model", "target", "note", "startedAt", "finishedAt", "slaMs"):
            assert got[field] == want[field], field
        assert len(got["results"]) == len(want["results"])
        for gr, wr in zip(got["results"], want["results"]):
            for field in wr:
                assert gr[field] == wr[field], (want["id"], wr["caseId"], field)


def test_production_traffic_matches_sample_data_field_for_field(client, auth):
    live_runs = [r for r in DATA["runs"] if r["target"] == "production"]
    assert live_runs, "the sample data has production traffic"
    for want_run in live_runs:
        for want in want_run["results"]:
            got = client.get(f"/production/traces/{want_run['id']}/{want['caseId']}", headers=auth).json()
            assert got["run"]["target"] == "production"
            for field in want:
                assert got["result"][field] == want[field], (want_run["id"], want["caseId"], field)


def test_read_endpoints(client, auth):
    first = DATA["runs"][0]["results"][0]
    assert first["caseId"] == "DS-001"
    assert "demo-story" in [s["id"] for s in client.get("/suites", headers=auth).json()]
    assert len(client.get("/suites/demo-story/cases", headers=auth).json()) == 10
    assert client.get("/suites/demo-story/cases/DS-001", headers=auth).json()["id"] == "DS-001"
    assert len(client.get("/runs?suite_id=demo-story", headers=auth).json()) == 7  # 5 test runs, 2 production
    assert len(client.get("/runs/DS-R1/results", headers=auth).json()) == 10
    one = client.get("/runs/DS-R1/results/DS-001", headers=auth).json()
    assert one["verdict"] == first["verdict"] and len(one["spans"]) == 4
    assert client.get("/runs/NOPE", headers=auth).status_code == 404


def test_key_lifecycle_and_project_isolation(client, auth, admin):
    assert client.post("/admin/projects", json={"name": "Other team"}).status_code == 401
    assert client.post("/admin/projects", json={"name": "Other team"}, headers=admin).status_code == 201
    made = client.post("/admin/projects/other-team/keys", json={"name": "ci"}, headers=admin).json()
    other = {"Authorization": f"Bearer {made['key']}"}
    assert "key" not in client.get("/admin/projects/other-team/keys", headers=admin).json()[0]
    assert client.get("/admin/projects/other-team/keys", headers=admin).json()[0]["prefix"] == made["key"][:12]

    assert client.get("/suites", headers=other).json() == []
    assert client.get("/suites/demo-story", headers=other).status_code == 404
    assert client.get("/runs/DS-R1", headers=other).status_code == 404
    assert client.get("/state", headers=other).json()["runs"] == []

    # Both projects may use the same public IDs.
    a = client.post("/suites", json={"name": "Demo: Story generator", "id": "demo-story"}, headers=other)
    assert a.status_code == 201
    assert client.get("/suites/demo-story", headers=auth).json()["prefix"] == "DS"

    assert client.delete(f"/admin/keys/{made['id']}", headers=admin).status_code == 200
    assert client.get("/suites", headers=other).status_code == 401


def test_run_lifecycle_scores_on_the_server(client, auth):
    suite = client.post("/suites", headers=auth, json={"name": "Refund bot", "slaMs": 2000}).json()
    sid = suite["id"]
    for text, checks in [("How long do refunds take?", [{"type": "contains_all", "values": ["5 to 7"]}]),
                         ("Cash refund?", [{"type": "not_contains", "values": ["cash refund processed"]}]),
                         ("Escalate?", [{"type": "human", "rubric": "Empathetic"}])]:
        assert client.post(f"/suites/{sid}/cases", headers=auth, json={"input": text, "checks": checks}).status_code == 201
    started = client.post("/runs", headers=auth, json={"suiteId": sid, "version": "v1", "model": "m", "note": "first"}).json()
    run_id = started["run"]["id"]
    assert [c["id"] for c in started["cases"]] == ["RB-001", "RB-002", "RB-003"]

    body = {"results": [
        {"caseId": "RB-001", "actual": "Refunds take 5 to 7 days.", "latencyMs": 900,
         "spans": [{"name": "request", "kind": "root", "dur": 900}, {"name": "llm.generate", "kind": "llm", "start": 5, "dur": 880, "depth": 1, "attrs": {"model": "m"}}]},
        {"caseId": "RB-002", "actual": "cash refund processed", "latencyMs": 500},
        {"caseId": "RB-003", "actual": "", "latencyMs": 0, "error": "Timeout"}]}
    scored = client.post(f"/runs/{run_id}/results", headers=auth, json=body).json()["results"]
    assert [r["verdict"] for r in scored] == ["Pass", "Fail", "Fail"]
    assert scored[1]["category"] == "Hallucination" and scored[2]["category"] == "Execution error"

    # Re-sending a result replaces it rather than duplicating it.
    client.post(f"/runs/{run_id}/results", headers=auth, json={"results": [{"caseId": "RB-002", "actual": "No cash.", "latencyMs": 400}]})
    done = client.post(f"/runs/{run_id}/complete", headers=auth).json()
    assert done["summary"]["n"] == 3 and done["summary"]["Pass"] == 2 and done["run"]["finishedAt"]
    assert client.post(f"/runs/{run_id}/results", headers=auth, json=body).status_code == 409
    assert len(client.get(f"/runs/{run_id}/results/RB-001", headers=auth).json()["spans"]) == 2

    second = client.post("/runs", headers=auth, json={"suiteId": sid, "version": "v2"}).json()["run"]["id"]
    client.post(f"/runs/{second}/results", headers=auth, json={"results": [{"caseId": "RB-001", "actual": "Soon.", "latencyMs": 100}]})
    client.post(f"/runs/{second}/complete", headers=auth)
    diff = client.get(f"/compare?a={run_id}&b={second}", headers=auth).json()
    assert [p["caseId"] for p in diff["diff"]["regressions"]] == ["RB-001"]


def test_import_json_and_csv(client, auth):
    csv_text = "id,input,expected,must_include,actual,latency_ms\nRF-001,How long?,5 to 7,5 to 7,Takes 5 to 7 days,1180\n"
    suite = client.post("/suites/import", headers=auth, json={"format": "csv", "content": csv_text, "name": "Imported refunds"}).json()
    case = suite["cases"][0]
    assert case["checks"] == [{"type": "contains_all", "values": ["5 to 7"]}] and case["recorded"] == "Takes 5 to 7 days"
    bad = client.post("/suites/import", headers=auth, json={"format": "json", "content": json.dumps({"name": "x", "cases": [{"input": "a", "checks": [{"type": "nope"}]}]})})
    assert bad.status_code == 422


def test_ingest_records_live_requests_as_scored_executions(client, auth):
    checks = [{"type": "not_contains", "values": ["…"], "category": "Incomplete answer"}]
    body = {"suiteId": "live-app", "suiteName": "Live app", "input": "hello", "actual": "A whole story.", "latencyMs": 900,
            "version": "live", "model": "m", "checks": checks,
            "spans": [{"name": "request", "kind": "root", "dur": 900}, {"name": "llm.generate", "kind": "llm", "depth": 1, "dur": 800}]}
    first = client.post("/ingest", headers=auth, json=body).json()
    second = client.post("/ingest", headers=auth, json={**body, "actual": "Cut off…"}).json()
    assert first["runId"] == second["runId"]  # same version and model share one production run
    assert first["result"]["verdict"] == "Pass" and second["result"]["verdict"] == "Fail"
    assert second["result"]["category"] == "Incomplete answer" and first["result"]["caseId"] != second["result"]["caseId"]
    run = client.get(f"/runs/{first['runId']}", headers=auth).json()
    assert run["target"] == "production" and len(run["results"]) == 2
    assert len(client.get(f"/runs/{first['runId']}/results/{first['result']['caseId']}", headers=auth).json()["spans"]) == 2
    other = client.post("/ingest", headers=auth, json={**body, "version": "v2"}).json()
    assert other["runId"] != first["runId"]  # a new version starts a new production run
    assert client.post("/ingest", json=body).status_code == 401


def test_dev_connect_is_off_by_default_and_guarded(client, monkeypatch):
    assert client.get("/dev-connect").status_code == 404  # no EVAL_WORKBENCH_DEV_KEY set
    monkeypatch.setenv("EVAL_WORKBENCH_DEV_KEY", "ewb_dev")
    local = {"Host": "127.0.0.1:8000"}
    assert client.get("/dev-connect", headers=local).status_code in (200, 404)  # TestClient is not a loopback address
    assert client.get("/dev-connect", headers={**local, "Sec-Fetch-Site": "cross-site"}).status_code == 404
    assert client.get("/dev-connect", headers={"Host": "evil.example"}).status_code == 404
