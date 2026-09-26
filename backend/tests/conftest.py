import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["EVAL_WORKBENCH_ADMIN_KEY"] = "test-admin"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import ensure_demo_key, seed  # noqa: E402


@pytest.fixture(scope="session")
def demo_key():
    init_db()
    with Session(engine) as session:
        seed(session)
        return ensure_demo_key(session)


@pytest.fixture(scope="session")
def client(demo_key):
    return TestClient(app)


@pytest.fixture(scope="session")
def auth(demo_key):
    return {"Authorization": f"Bearer {demo_key}"}


@pytest.fixture(scope="session")
def admin():
    return {"Authorization": "Bearer test-admin"}
