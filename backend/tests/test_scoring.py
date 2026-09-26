import json
from pathlib import Path

import pytest

from app.scoring import compare_runs, evaluate, summarize

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "sample-data.json").read_text(encoding="utf-8"))
CASES = {(s["id"], c["id"]): c for s in DATA["suites"] for c in s["cases"]}


@pytest.mark.parametrize("run", DATA["runs"], ids=[r["id"] for r in DATA["runs"]])
def test_scorer_matches_every_stored_result(run):
    for r in run["results"]:
        case = CASES[(run["suiteId"], r["caseId"])]
        ev = evaluate(case["checks"], r["actual"], r["latencyMs"], run["slaMs"])
        assert ev["verdict"] == r["verdict"], r["caseId"]
        assert ev["category"] == r["category"], r["caseId"]
        assert ev["reason"] == r["reason"], r["caseId"]
        assert ev["checks"] == r["checks"], r["caseId"]


def test_execution_error_is_a_failure():
    ev = evaluate([{"type": "contains_all", "values": ["x"]}], "", 0, 1000, "Boom")
    assert (ev["verdict"], ev["category"], ev["reason"]) == ("Fail", "Execution error", "Boom")


def test_latency_breach_only_when_everything_else_passes():
    checks = [{"type": "contains_all", "values": ["ok"]}]
    assert evaluate(checks, "ok", 3500, 3000)["category"] == "Latency SLA breach"
    assert evaluate(checks, "nope", 3500, 3000)["category"] == "Incomplete answer"


def test_refusal_becomes_unwarranted_refusal():
    ev = evaluate([{"type": "contains_all", "values": ["60"]}], "Sorry, I cannot help with that.", 100, 1000)
    assert ev["category"] == "Unwarranted refusal"


def test_summary_and_comparison_on_sample_runs():
    runs = {r["id"]: r for r in DATA["runs"]}
    a, b = runs["DS-R4"]["results"], runs["DS-R5"]["results"]
    s = summarize(b)
    assert (s["n"], s["Pass"], s["Fail"], s["Review"]) == (10, 5, 3, 2)
    assert round(s["passRate"], 3) == round(5 / 10, 3)
    diff = compare_runs(a, b)
    assert [p["caseId"] for p in diff["regressions"]] == ["DS-003", "DS-004", "DS-006"]
    assert [p["caseId"] for p in diff["degraded"]] == ["DS-010"] and diff["fixes"] == []
