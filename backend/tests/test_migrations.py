"""Alembic migrations: schema matches the models, legacy DBs upgrade."""
import os
import subprocess
import sys
import tempfile
import textwrap

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_migrated_schema_matches_models(client):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.config.database import Base, engine

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_legacy_database_is_stamped_and_upgraded():
    """A DB created by the old `create_all` (no alembic_version) keeps its
    data and gains the new tables/columns."""
    tmp = tempfile.mkdtemp(prefix="pivot-legacy-")
    script = textwrap.dedent("""
        import os, sqlalchemy as sa
        from alembic import command
        from alembic.config import Config
        from app.config.database import engine, init_db

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "0001_baseline")
        with engine.begin() as c:
            c.execute(sa.text("DROP TABLE alembic_version"))
            c.execute(sa.text(
                "INSERT INTO datasets (filename, stored_filename, total_rows, total_columns) "
                "VALUES ('old.csv', 'x.csv', 3, 2)"))
        init_db()
        insp = sa.inspect(engine)
        assert "saved_pivots" in insp.get_table_names()
        assert "refreshed_at" in [c["name"] for c in insp.get_columns("datasets")]
        with engine.connect() as c:
            assert c.execute(sa.text("SELECT filename FROM datasets")).scalar() == "old.csv"
            assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "0002_reports"
        print("OK")
    """)
    env = dict(os.environ, DB_PATH=os.path.join(tmp, "legacy.db"),
               UPLOAD_DIR=os.path.join(tmp, "u"), REPORTS_DIR=os.path.join(tmp, "r"),
               LOG_DIR=os.path.join(tmp, "l"))
    out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout
