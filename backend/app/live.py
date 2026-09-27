"""Production monitoring: how live traffic is doing over a time window. Same as liveStats() in the frontend,
which computes this in demo mode.

A window is the half-open interval (from, to]. It is cut into buckets of equal length starting at `from`,
so every bucket has the same length whatever the time zone. The previous window of the same length is used
for the change figures.
"""
import math
from typing import Optional

from .scoring import summarize

HOUR = 3600 * 1000
DAY = 24 * HOUR


def _sum(rows: list, key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) if vals else None


def live_summary(rows: list) -> dict:
    out = summarize(rows)
    out["failRate"] = out["Fail"] / out["n"] if out["n"] else 0
    out["tokensIn"] = _sum(rows, "tokensIn")
    out["tokensOut"] = _sum(rows, "tokensOut")
    out["costUsd"] = _sum(rows, "costUsd")
    out["users"] = len({r["userId"] for r in rows if r.get("userId")})
    out["sessions"] = len({r["sessionId"] for r in rows if r.get("sessionId")})
    return out


def live_stats(rows: list, frm: int, to: int, bucket_ms: int) -> dict:
    """rows: production executions in (frm - (to - frm), to], oldest first, with camelCase keys."""
    length = to - frm
    cur = [r for r in rows if frm < r["timestamp"] <= to]
    prev = [r for r in rows if frm - length < r["timestamp"] <= frm]
    n_buckets = max(1, math.ceil(length / bucket_ms))
    buckets: list = [[] for _ in range(n_buckets)]
    for r in cur:
        i = min(n_buckets - 1, max(0, math.ceil((r["timestamp"] - frm) / bucket_ms) - 1))
        buckets[i].append(r)
    series = []
    for i, b in enumerate(buckets):
        s = summarize(b)
        series.append({"t": frm + i * bucket_ms, "n": s["n"], "Pass": s["Pass"], "Fail": s["Fail"], "Review": s["Review"],
                       "failRate": s["Fail"] / s["n"] if s["n"] else None, "p95": s["p95"]})
    versions: dict = {}
    for r in cur:
        versions.setdefault(r["runId"], []).append(r)
    by_version = []
    for run_id, rs in versions.items():
        s = summarize(rs)
        by_version.append({"runId": run_id, "suiteId": rs[0]["suiteId"], "version": rs[0]["version"], "model": rs[0]["model"],
                           "first": min(r["timestamp"] for r in rs), "last": max(r["timestamp"] for r in rs),
                           "n": s["n"], "Pass": s["Pass"], "Fail": s["Fail"], "Review": s["Review"], "passRate": s["passRate"],
                           "failRate": s["Fail"] / s["n"], "p95": s["p95"], "cats": s["cats"]})
    by_version.sort(key=lambda v: (v["first"], v["runId"]))
    previous: Optional[dict] = None
    if prev:
        p = live_summary(prev)
        previous = {"n": p["n"], "passRate": p["passRate"], "failRate": p["failRate"], "p95": p["p95"]}
    return {"from": frm, "to": to, "bucketMs": bucket_ms, "summary": live_summary(cur), "previous": previous,
            "series": series, "versions": by_version}


def default_bucket(length: int) -> int:
    return HOUR if length <= 2 * DAY else DAY

