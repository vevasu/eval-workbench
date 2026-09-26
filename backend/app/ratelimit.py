import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .settings import trust_proxy

_hits: dict = defaultdict(deque)
_lock = threading.Lock()


def hit(key: str, limit: int, window_seconds: float) -> None:
    """Count one request against `key`. Raises 429 when more than `limit` happened in the window. In memory, per process."""
    now = time.time()
    with _lock:
        q = _hits[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window_seconds - (now - q[0])))
            raise HTTPException(status_code=429, detail=f"Too many requests. Try again in {retry} seconds.",
                                headers={"Retry-After": str(retry)})
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    if trust_proxy():
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
