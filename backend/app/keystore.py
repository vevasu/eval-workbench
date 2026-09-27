"""Encrypts secrets a project saves, such as the model key for the AI judge. They are never returned by the API.

The encryption key comes from EVAL_WORKBENCH_SECRET, or from EVAL_WORKBENCH_ADMIN_KEY when that is not set. Changing
it makes saved keys unreadable, so projects would have to enter them again.
"""
import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException


def _fernet() -> Fernet:
    secret = os.environ.get("EVAL_WORKBENCH_SECRET") or os.environ.get("EVAL_WORKBENCH_ADMIN_KEY")
    if not secret:
        raise HTTPException(status_code=503, detail="Saving model keys needs EVAL_WORKBENCH_SECRET set on the server.")
    digest = hashlib.sha256(("eval-workbench/project-secrets:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(token: Optional[str]) -> Optional[str]:
    """The saved secret, or None if there is none or it can no longer be read."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, HTTPException):
        return None


def hint(key: str) -> str:
    """Enough of a key to recognise it: its start and last four characters."""
    return (key[:3] + "…" + key[-4:]) if len(key) > 10 else "…"
