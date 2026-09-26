import os

from fastapi import APIRouter, HTTPException, Request

from ..settings import is_production

router = APIRouter(tags=["dev"], include_in_schema=False)

LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


@router.get("/dev-connect")
def dev_connect(request: Request):
    """Local-development shortcut: lets the web app served from this backend connect without pasting a key.

    Off unless EVAL_WORKBENCH_DEV_KEY is set. Only answers loopback clients asking for their own origin, so other
    websites open in the same browser cannot read the key.
    """
    key = os.environ.get("EVAL_WORKBENCH_DEV_KEY", "")
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    client = request.client.host if request.client else ""
    same_origin = request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")
    if is_production() or not key or hostname not in LOCAL_HOSTS or client not in ("127.0.0.1", "::1") or not same_origin:
        raise HTTPException(status_code=404)
    return {"url": f"{request.url.scheme}://{host}", "key": key}
