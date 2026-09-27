def test_a_team_manages_its_suites_from_the_website(client, admin):
    client.post("/admin/projects", headers=admin, json={"name": "Editors", "id": "editors"})
    auth = {"Authorization": "Bearer " + client.post("/admin/projects/editors/keys", headers=admin, json={"name": "t"}).json()["key"]}
    # Upload a suite as CSV, the way the Import suite dialog sends it
    csv = "id,input,expected,must_include\nRF-001,How long do refunds take?,5 to 7 days,5 to 7\nRF-002,Refund in cash?,Declines,original payment\n"
    suite = client.post("/suites/import", headers=auth, json={"format": "csv", "content": csv, "name": "Refunds"}).json()
    assert suite["name"] == "Refunds" and [c["id"] for c in suite["cases"]] == ["RF-001", "RF-002"]
    sid = suite["id"]
    # Add, edit and delete a case
    added = client.post(f"/suites/{sid}/cases", headers=auth, json={"input": "Refund to a gift card?", "checks": [{"type": "contains_any", "values": ["gift"]}]}).json()
    assert client.patch(f"/suites/{sid}/cases/{added['id']}", headers=auth, json={"expected": "Explains gift card refunds"}).json()["expected"] == "Explains gift card refunds"
    assert client.delete(f"/suites/{sid}/cases/{added['id']}", headers=auth).status_code == 204
    assert client.delete(f"/suites/{sid}/cases/{added['id']}", headers=auth).status_code == 404
    # A run of the suite, and live traffic for it, go when the run or the suite is deleted
    run = client.post("/runs", headers=auth, json={"suiteId": sid, "version": "v1"}).json()["run"]["id"]
    client.post(f"/runs/{run}/results", headers=auth, json={"results": [{"caseId": "RF-001", "actual": "5 to 7 days"}]})
    assert client.delete(f"/runs/{run}", headers=auth).json()["deleted"] == {"results": 1}
    assert client.get(f"/runs/{run}", headers=auth).status_code == 404
    run2 = client.post("/runs", headers=auth, json={"suiteId": sid, "version": "v2"}).json()["run"]["id"]
    client.post(f"/runs/{run2}/results", headers=auth, json={"results": [{"caseId": "RF-002", "actual": "no"}]})
    client.post("/ingest", headers=auth, json={"suiteId": sid, "input": "hi", "actual": "hello"})
    gone = client.delete(f"/suites/{sid}", headers=auth).json()
    assert gone["deleted"] == {"cases": 2, "runs": 2, "results": 2}
    assert client.get("/state", headers=auth).json()["suites"] == []
    assert client.get("/production/traces", headers=auth).json()["traces"] == []


def test_teams_cannot_edit_each_others_suites(client, auth, admin):
    client.post("/admin/projects", headers=admin, json={"name": "Other", "id": "other-editors"})
    other = {"Authorization": "Bearer " + client.post("/admin/projects/other-editors/keys", headers=admin, json={"name": "t"}).json()["key"]}
    assert client.delete("/suites/demo-story", headers=other).status_code == 404
    assert client.delete("/suites/demo-story/cases/DS-001", headers=other).status_code == 404
    assert client.delete("/runs/DS-R1", headers=other).status_code == 404
    assert client.get("/suites/demo-story", headers=auth).status_code == 200
