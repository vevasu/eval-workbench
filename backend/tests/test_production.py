import pytest

from app.live import DAY, HOUR, live_stats
from app.scoring import evaluate, span_totals

T0 = 1_790_000_000_000  # a fixed "now" so windows and buckets are predictable
PASSING = [{"type": "not_contains", "values": ["…"], "category": "Incomplete answer"}]


@pytest.fixture(scope="module")
def live(client, admin):
    """A project of its own with live traffic from two versions, three users and two sessions."""
    client.post("/admin/projects", headers=admin, json={"name": "Live shop", "id": "live-shop"})
    key = client.post("/admin/projects/live-shop/keys", headers=admin, json={"name": "t"}).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}
    llm = {"name": "llm.call", "kind": "llm", "depth": 1, "dur": 500,
           "attrs": {"prompt_tokens": 100, "completion_tokens": 40, "cost_usd": 0.0012}}
    base = {"suiteId": "shop-bot", "suiteName": "Shop bot", "latencyMs": 800, "model": "gpt-4o", "checks": PASSING,
            "spans": [{"name": "request", "kind": "root", "dur": 800}, llm]}
    sent = [
        # v1: two days ago, all fine
        {"version": "v1", "timestamp": T0 - 2 * DAY + HOUR, "input": "Where is my order?", "actual": "It ships today.",
         "userId": "u1", "sessionId": "s1", "tags": ["orders"]},
        {"version": "v1", "timestamp": T0 - 2 * DAY + 2 * HOUR, "input": "And the refund?", "actual": "Refunds take 5 days.",
         "userId": "u1", "sessionId": "s1", "tags": ["refunds"], "metadata": {"plan": "pro"}},
        # v2: today, one cut off, one error, one slow, one without checks
        {"version": "v2", "timestamp": T0 - 3 * HOUR, "input": "Track parcel 55", "actual": "Your parcel is out for deliv…",
         "userId": "u2", "sessionId": "s2", "tags": ["orders"]},
        {"version": "v2", "timestamp": T0 - 2 * HOUR, "input": "Cancel it", "actual": "", "error": "TimeoutError: upstream",
         "userId": "u2", "sessionId": "s2"},
        {"version": "v2", "timestamp": T0 - HOUR, "input": "Opening hours?", "actual": "9 to 5.", "latencyMs": 9000,
         "userId": "u3"},
        {"version": "v2", "timestamp": T0, "input": "Say hi", "actual": "Hi!", "checks": [], "userId": "u3"},
    ]
    stored = [client.post("/ingest", headers=auth, json={**base, **body}).json() for body in sent]
    return auth, stored


def test_ingest_stores_who_and_what_it_cost(client, live):
    auth, stored = live
    first = stored[1]["result"]
    assert first["userId"] == "u1" and first["sessionId"] == "s1" and first["tags"] == ["refunds"]
    assert first["metadata"] == {"plan": "pro"}
    assert (first["tokensIn"], first["tokensOut"], first["costUsd"]) == (100, 40, 0.0012)
    verdicts = [(s["result"]["verdict"], s["result"]["category"]) for s in stored]
    assert verdicts == [("Pass", None), ("Pass", None), ("Fail", "Incomplete answer"), ("Fail", "Execution error"),
                        ("Fail", "Latency SLA breach"), ("Pass", None)]
    # Live traffic without checks is judged on errors and latency, not sent to review.
    assert "No content checks" in stored[5]["result"]["reason"]


def test_ingest_limits_trace_context(client, live):
    auth, _ = live
    body = {"suiteId": "shop-bot", "input": "x", "actual": "y"}
    assert client.post("/ingest", headers=auth, json={**body, "tags": [f"t{i}" for i in range(21)]}).status_code == 413
    assert client.post("/ingest", headers=auth, json={**body, "userId": "u" * 201}).status_code == 413
    assert client.post("/ingest", headers=auth, json={**body, "metadata": {"a": "b" * 5000}}).status_code == 413


def test_state_leaves_production_out(client, live):
    auth, stored = live
    state = client.get("/state", headers=auth).json()
    assert [s["id"] for s in state["suites"]] == ["shop-bot"]
    assert state["runs"] == []


def test_stats_for_a_day_and_for_a_week(client, live):
    auth, stored = live
    day = client.get(f"/production/stats?from={T0 - DAY}&to={T0}", headers=auth).json()
    s = day["summary"]
    assert (s["n"], s["Pass"], s["Fail"], s["Review"]) == (4, 1, 3, 0)
    assert s["failRate"] == 0.75 and s["users"] == 2 and s["sessions"] == 1
    assert s["tokensIn"] == 400 and s["tokensOut"] == 160
    assert s["cats"] == {"Incomplete answer": 1, "Execution error": 1, "Latency SLA breach": 1}
    assert day["bucketMs"] == HOUR and len(day["series"]) == 24
    assert day["series"][-1]["n"] == 1 and day["series"][-4]["n"] == 1 and day["series"][-4]["Fail"] == 1
    assert [v["version"] for v in day["versions"]] == ["v2"]
    assert day["previous"] == {"n": 2, "passRate": 1.0, "failRate": 0.0, "p95": 800}
    assert day["suites"] == [{"suiteId": "shop-bot", "name": "Shop bot", "n": 6, "last": T0}] and day["latest"] == T0

    week = client.get(f"/production/stats?from={T0 - 7 * DAY}&to={T0}", headers=auth).json()
    assert week["bucketMs"] == DAY and len(week["series"]) == 7 and week["summary"]["n"] == 6
    assert [(v["version"], v["n"], v["failRate"]) for v in week["versions"]] == [("v1", 2, 0.0), ("v2", 4, 0.75)]
    assert week["previous"] is None
    only_v1 = client.get(f"/production/stats?from={T0 - 7 * DAY}&to={T0}&version=v1", headers=auth).json()
    assert only_v1["summary"]["n"] == 2
    assert client.get(f"/production/stats?from={T0}&to={T0 - 1}", headers=auth).status_code == 422
    assert client.get(f"/production/stats?from={T0 - DAY}&to={T0}&bucket=1000", headers=auth).status_code == 422


def test_traces_filter_and_page(client, live):
    auth, stored = live

    def ids(query):
        return [t["caseId"] for t in client.get("/production/traces" + query, headers=auth).json()["traces"]]

    all_ids = [s["result"]["caseId"] for s in stored]
    assert ids("") == all_ids[::-1]  # newest first
    assert ids("?verdict=Fail") == [all_ids[4], all_ids[3], all_ids[2]]
    assert ids("?category=Execution%20error") == [all_ids[3]]
    assert ids("?user=u1") == [all_ids[1], all_ids[0]]
    assert ids("?session=s2") == [all_ids[3], all_ids[2]]
    assert ids("?tag=orders") == [all_ids[2], all_ids[0]]
    assert ids("?tag=order") == []  # a whole tag, not part of one
    assert ids("?q=REFUND") == [all_ids[1]]
    assert ids("?q=100%25") == []  # % is a literal character, not a wildcard
    assert ids("?version=v1") == [all_ids[1], all_ids[0]]
    assert ids(f"?from={T0 - DAY}&to={T0 - HOUR}") == [all_ids[4], all_ids[3], all_ids[2]]

    first = client.get("/production/traces?limit=4", headers=auth).json()
    assert len(first["traces"]) == 4 and first["next"] is not None
    rest = client.get(f"/production/traces?limit=4&before={first['next']}", headers=auth).json()
    assert [t["caseId"] for t in first["traces"] + rest["traces"]] == all_ids[::-1] and rest["next"] is None


def test_one_trace_with_its_session(client, live):
    auth, stored = live
    one = stored[1]
    got = client.get(f"/production/traces/{one['runId']}/{one['result']['caseId']}", headers=auth).json()
    assert got["run"]["target"] == "production" and got["run"]["version"] == "v1"
    assert got["suite"] == {"id": "shop-bot", "name": "Shop bot", "slaMs": 3000}
    assert [s["name"] for s in got["result"]["spans"]] == ["request", "llm.call"]
    assert [r["caseId"] for r in got["session"]] == [stored[0]["result"]["caseId"], one["result"]["caseId"]]
    assert client.get(f"/production/traces/{one['runId']}/LIVE-99999", headers=auth).status_code == 404


def test_other_projects_cannot_see_this_traffic(client, live, auth):
    _, stored = live
    one = stored[0]
    assert client.get("/production/traces?suite=shop-bot", headers=auth).json()["traces"] == []  # auth: the demo project
    assert client.get(f"/production/traces/{one['runId']}/{one['result']['caseId']}", headers=auth).status_code == 404
    assert "shop-bot" not in [s["suiteId"] for s in client.get("/production/stats", headers=auth).json()["suites"]]


def test_a_failing_trace_becomes_a_test_case(client, live):
    auth, stored = live
    bad = stored[2]
    origin = f"{bad['runId']}/{bad['result']['caseId']}"
    case = client.post("/suites/shop-bot/cases", headers=auth, json={
        "input": bad["result"]["input"], "expected": "The full tracking status, not cut off.", "tag": "From production",
        "checks": PASSING, "origin": origin}).json()
    assert case["origin"] == origin and case["id"].startswith("SB-")
    state = client.get("/state", headers=auth).json()
    assert state["suites"][0]["cases"][0]["origin"] == origin


def test_span_totals_and_live_scoring():
    spans = [{"attrs": {"input_tokens": 10, "output_tokens": 5}}, {"attrs": {"prompt_tokens": 3, "cost_usd": 0.5}},
             {"attrs": {"completion_tokens": True, "cost_usd": "free"}}, {"attrs": {}}]
    assert span_totals(spans) == {"tokensIn": 13, "tokensOut": 5, "costUsd": 0.5}
    assert span_totals([{"attrs": {}}]) == {"tokensIn": None, "tokensOut": None, "costUsd": None}
    assert evaluate([], "hi", 100, 3000)["verdict"] == "Review"  # test cases without checks still go to review
    assert evaluate([], "hi", 100, 3000, live=True)["verdict"] == "Pass"
    assert evaluate([], "hi", 5000, 3000, live=True)["category"] == "Latency SLA breach"
    assert evaluate([{"type": "human", "rubric": "tone"}], "hi", 100, 3000, live=True)["verdict"] == "Review"


def test_live_stats_windows_are_half_open():
    rows = [{"runId": "R1", "suiteId": "s", "caseId": str(i), "timestamp": ts, "verdict": "Pass", "category": None,
             "latencyMs": 100, "version": "v", "model": "m"} for i, ts in enumerate([0, 1, HOUR, 2 * HOUR])]
    out = live_stats(rows, 0, 2 * HOUR, HOUR)
    assert out["summary"]["n"] == 3  # the row at `from` belongs to the previous window
    assert [b["n"] for b in out["series"]] == [2, 1] and out["previous"]["n"] == 1
