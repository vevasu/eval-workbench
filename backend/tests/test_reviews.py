import pytest

from app.routers.reviews import is_spot_check

PASSING = [{"type": "not_contains", "values": ["…"], "category": "Incomplete answer"}]


@pytest.fixture(scope="module")
def team(client, admin):
    """A project of its own: a test run with results for review, and live traffic with spot checks."""
    client.post("/admin/projects", headers=admin, json={"name": "Review team", "id": "review-team"})
    key = client.post("/admin/projects/review-team/keys", headers=admin, json={"name": "t"}).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}
    suite = client.post("/suites", headers=auth, json={"name": "Poems", "slaMs": 5000}).json()["id"]
    cases = [("Write a haiku about rain", [{"type": "human", "rubric": "is a real haiku"}]),
             ("Name Ann and Bob", [{"type": "contains_all", "values": ["Ann", "Bob"]}]),
             ("Say hi", [{"type": "contains_all", "values": ["hi"]}])]
    ids = [client.post(f"/suites/{suite}/cases", headers=auth, json={"input": i, "checks": c}).json()["id"] for i, c in cases]
    run = client.post("/runs", headers=auth, json={"suiteId": suite, "version": "v1"}).json()["run"]["id"]
    outputs = ["Rain on the tin roof / the garden drinks its fill / puddles hold the sky", "Hello Ann", "hi there"]
    client.post(f"/runs/{run}/results", headers=auth, json={"results": [
        {"caseId": c, "actual": o, "latencyMs": 100} for c, o in zip(ids, outputs)]})
    client.post(f"/runs/{run}/complete", headers=auth)
    live = [client.post("/ingest", headers=auth, json={"suiteId": "poems-live", "input": f"q{i}", "actual": "fine",
                                                       "checks": PASSING}).json() for i in range(20)]  # ids in a row, so one is picked
    return auth, suite, run, ids, live


def queue(client, auth, **params):
    return client.get("/reviews", headers=auth, params=params).json()


def test_results_the_checks_could_not_decide_wait_for_review(client, team):
    auth, suite, run, ids, _ = team
    q = queue(client, auth, source="runs")
    assert {i["caseId"]: i["category"] for i in q["items"]} == {ids[0]: "Awaiting human review", ids[1]: "Partial match"}
    assert q["counts"]["pending"] == 2 and q["counts"]["done"] == 0
    assert queue(client, auth, source="runs", reason="Partial match")["total"] == 1
    assert queue(client, auth, suite="nope")["counts"] == {"pending": 0, "spot": 0, "done": 0}


def test_a_decision_replaces_the_verdict_and_can_be_undone(client, team):
    auth, suite, run, ids, _ = team
    url = f"/runs/{run}/results/{ids[0]}/review"
    assert client.post(url, headers=auth, json={"verdict": "Fail"}).status_code == 422  # a failure needs a reason
    got = client.post(url, headers=auth, json={"verdict": "Pass", "note": "A proper 5-7-5.", "reviewer": "Priya"}).json()
    assert (got["verdict"], got["category"]) == ("Pass", None)
    assert got["review"]["autoVerdict"] == "Review" and got["review"]["autoCategory"] == "Awaiting human review"
    assert got["review"]["reviewer"] == "Priya" and got["review"]["note"] == "A proper 5-7-5."
    summary = client.get(f"/runs/{run}/summary", headers=auth).json()
    assert (summary["Pass"], summary["Review"]) == (2, 1)  # pass rates use the decision
    # Changing the decision keeps the original automatic verdict.
    again = client.post(url, headers=auth, json={"verdict": "Fail", "category": "Format violation", "reviewer": "Sam"}).json()
    assert (again["verdict"], again["category"], again["review"]["autoVerdict"]) == ("Fail", "Format violation", "Review")
    q = queue(client, auth, source="runs")
    assert q["counts"] == {"pending": 1, "spot": 0, "done": 1}
    done = queue(client, auth, kind="done")["items"][0]
    assert done["caseId"] == ids[0] and done["review"]["reviewer"] == "Sam"
    state = client.get("/state", headers=auth).json()
    stored = next(r for r in state["runs"][0]["results"] if r["caseId"] == ids[0])
    assert stored["verdict"] == "Fail" and stored["review"]["category"] == "Format violation"
    undone = client.delete(url, headers=auth).json()
    assert (undone["verdict"], undone["category"], undone["review"]) == ("Review", "Awaiting human review", None)
    assert queue(client, auth, source="runs")["counts"]["pending"] == 2


def test_any_result_can_be_reviewed_even_a_pass(client, team):
    auth, suite, run, ids, _ = team
    got = client.post(f"/runs/{run}/results/{ids[2]}/review", headers=auth,
                      json={"verdict": "Fail", "category": "Off-topic response", "note": "Should greet, not echo."}).json()
    assert (got["verdict"], got["review"]["autoVerdict"]) == ("Fail", "Pass")
    client.delete(f"/runs/{run}/results/{ids[2]}/review", headers=auth)
    assert client.post(f"/runs/{run}/results/NOPE/review", headers=auth, json={"verdict": "Pass"}).status_code == 404


def test_spot_checks_pick_one_in_twenty_passing_production_requests(client, team):
    auth, *_ , live = team
    assert [is_spot_check(c) for c in ["LIVE-00020", "LIVE-00021", "LIVE-00040", "DS-020", "LIVE-x"]] == [True, False, True, False, False]
    spot = queue(client, auth, kind="spot")
    picked = [x["result"]["caseId"] for x in live if is_spot_check(x["result"]["caseId"])]
    assert len(picked) == 1
    assert sorted(i["caseId"] for i in spot["items"]) == sorted(picked)
    assert all(i["source"] == "live" and i["verdict"] == "Pass" for i in spot["items"])


def test_other_projects_cannot_review_this_projects_results(client, team, auth):
    _, suite, run, ids, _ = team
    assert client.post(f"/runs/{run}/results/{ids[0]}/review", headers=auth, json={"verdict": "Pass"}).status_code == 404
    assert queue(client, auth, suite=suite)["counts"] == {"pending": 0, "spot": 0, "done": 0}
