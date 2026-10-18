from collections.abc import Iterator
from contextlib import contextmanager

from app.core.database import Database
from app.repositories.operations import OperationsRepository


class UnitOfWork:
    """Commit business state and its audit together, or roll back both."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[OperationsRepository]:
        with self.database.connect() as connection:
            yield OperationsRepository(connection)
