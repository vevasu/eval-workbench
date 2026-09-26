"""Deployment settings, read from the environment at call time so they can be changed without a code edit."""
import os


def is_production() -> bool:
    return os.environ.get("EVAL_WORKBENCH_ENV", "development").lower() == "production"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def limits() -> dict:
    """Per-project beta allowances and request size caps."""
    return {
        "max_results": _int("MAX_RESULTS_PER_PROJECT", 10000),   # stored executions (traces and run results)
        "max_suites": _int("MAX_SUITES_PER_PROJECT", 50),
        "max_text_chars": _int("MAX_TEXT_CHARS", 20000),          # one input or output
        "max_spans": _int("MAX_SPANS_PER_EXECUTION", 200),
        "max_checks": _int("MAX_CHECKS_PER_CASE", 20),
        "max_batch": _int("MAX_RESULTS_PER_BATCH", 100),
        "ingest_per_minute": _int("RATE_LIMIT_INGEST_PER_MIN", 120),
        "access_requests_per_hour": _int("RATE_LIMIT_ACCESS_REQUESTS_PER_HOUR", 5),
    }


def trust_proxy() -> bool:
    """Set TRUST_PROXY=1 when running behind a load balancer, so the client IP comes from X-Forwarded-For."""
    return os.environ.get("TRUST_PROXY", "") == "1"
