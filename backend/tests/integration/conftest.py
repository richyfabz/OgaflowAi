"""Real PostgreSQL tests in a disposable schema on the private local cluster."""

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.core.database import Database
from app.repositories.unit_of_work import UnitOfWork
from app.services.operations import OperationsService
from app.services.verification import StoredDemoVerifier
from psycopg import sql

from scripts.demo_database import local_dsn
from scripts.seed_demo import ROOT


@pytest.fixture
def database():
    dsn = local_dsn("postgres")
    try:
        connection = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip(
            "Local PostgreSQL is not running; run scripts/local_postgres.py start"
        )
    with connection:
        info = connection.execute(
            "SELECT current_setting('data_directory'), inet_server_addr()"
        ).fetchone()
        assert Path(info[0]).resolve() == (ROOT / ".local/pgdata").resolve()
        assert info[1] is None
        schema = "test_" + uuid4().hex
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
        )
        try:
            connection.execute((ROOT / "database/schema.sql").read_text())
            connection.execute((ROOT / "database/seed.sql").read_text())
            yield Database(
                psycopg.conninfo.make_conninfo(dsn, options=f"-c search_path={schema}")
            )
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.fixture
def service(database):
    return OperationsService(
        UnitOfWork(database), allow_demo=True, verifier=StoredDemoVerifier()
    )


@pytest.fixture
def run_id(service):
    return service.start_run("DEMO-PHONE-001", "start").run_id
