import tempfile

from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from app import db, migrate


def _use(monkeypatch, engine):
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(migrate, "engine", engine)


def test_a_new_database_is_built_by_the_migrations(monkeypatch):
    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/new.db")
    _use(monkeypatch, engine)
    migrate.upgrade()
    assert {"project", "apikey", "suite", "result", "span", "accessrequest", "alembic_version"} <= set(inspect(engine).get_table_names())
    assert migrate.schema_drift() == []


def test_a_database_from_before_migrations_is_stamped_and_keeps_its_data(monkeypatch):
    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/old.db")
    SQLModel.metadata.create_all(engine)  # how the server used to create tables
    with engine.begin() as c:
        c.execute(text("INSERT INTO project (id, name, created_at) VALUES ('kept', 'Kept', 1)"))
    _use(monkeypatch, engine)
    migrate.upgrade()
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == migrate.BASELINE
        assert c.execute(text("SELECT name FROM project WHERE id = 'kept'")).scalar() == "Kept"
    assert migrate.schema_drift() == []
    migrate.upgrade()  # running again on every startup is harmless
