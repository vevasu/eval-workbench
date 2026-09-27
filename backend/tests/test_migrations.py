import tempfile

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

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
    _use(monkeypatch, engine)
    command.upgrade(migrate._config(), migrate.BASELINE)  # the tables the server used to create with create_all
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text("INSERT INTO project (id, name, created_at) VALUES ('kept', 'Kept', 1)"))
    migrate.upgrade()
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == ScriptDirectory.from_config(migrate._config()).get_current_head()
        assert c.execute(text("SELECT name FROM project WHERE id = 'kept'")).scalar() == "Kept"
    assert migrate.schema_drift() == []
    migrate.upgrade()  # running again on every startup is harmless
