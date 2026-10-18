"""Initialize, seed, or reset only the project's isolated local demo database."""

import argparse
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
SOCKET = ROOT / ".local/pgsocket"
DATABASE = "ogaflow_demo"


def local_dsn(database=DATABASE):
    return psycopg.conninfo.make_conninfo(
        host=str(SOCKET), port=55432, user="ogaflow_local", dbname=database
    )


def check_local(connection):
    row = connection.execute(
        "SELECT current_database(), current_user, inet_server_addr(), current_setting('data_directory')"
    ).fetchone()
    if (
        row[0] != DATABASE
        or row[1] != "ogaflow_local"
        or row[2] is not None
        or Path(row[3]).resolve() != (ROOT / ".local/pgdata").resolve()
    ):
        raise RuntimeError("Refusing operation outside the project-local demo cluster")


def initialize():
    with psycopg.connect(local_dsn("postgres"), autocommit=True) as connection:
        row = connection.execute(
            "SELECT current_setting('data_directory'), inet_server_addr()"
        ).fetchone()
        if (
            Path(row[0]).resolve() != (ROOT / ".local/pgdata").resolve()
            or row[1] is not None
        ):
            raise RuntimeError("Refusing non-project cluster")
        if not connection.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)
        ).fetchone():
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(DATABASE)
                )
            )
    with psycopg.connect(local_dsn()) as connection:
        check_local(connection)
        connection.execute((ROOT / "database/schema.sql").read_text())


def seed():
    with psycopg.connect(local_dsn()) as connection:
        check_local(connection)
        connection.execute((ROOT / "database/seed.sql").read_text())


def reset(confirmation):
    if confirmation != DATABASE:
        raise ValueError("Reset requires --confirm ogaflow_demo")
    with psycopg.connect(local_dsn()) as connection:
        check_local(connection)
        connection.execute(
            "TRUNCATE agent_actions, escalations, agent_runs, order_items, orders, payments, products, customers"
        )
        # Remove only the known outer transaction wrapper so reset is one transaction.
        seed_sql = (
            (ROOT / "database/seed.sql")
            .read_text()
            .replace("BEGIN;\n", "")
            .replace("COMMIT;\n", "")
        )
        connection.execute(seed_sql)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "seed", "reset", "dsn"])
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.action == "init":
        initialize()
    elif args.action == "seed":
        seed()
    elif args.action == "reset":
        reset(args.confirm)
    else:
        print(local_dsn())


if __name__ == "__main__":
    main()
