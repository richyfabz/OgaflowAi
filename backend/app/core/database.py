"""Short-lived PostgreSQL connections; no global pool or import-time I/O."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=5,
        ) as connection:
            connection.execute("SET statement_timeout = 10000")
            connection.execute("SET lock_timeout = 5000")
            yield connection
