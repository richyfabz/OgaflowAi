from unittest.mock import Mock

import pytest

from scripts.demo_database import check_local, reset


def test_reset_refuses_without_exact_confirmation():
    with pytest.raises(ValueError, match="confirm"):
        reset(None)
    with pytest.raises(ValueError):
        reset("production")


@pytest.mark.parametrize(
    "record",
    [
        ("production", "ogaflow_local", None, "/tmp/other"),
        ("ogaflow_demo", "postgres", None, "/tmp/other"),
        ("ogaflow_demo", "ogaflow_local", "127.0.0.1", "/tmp/other"),
        ("ogaflow_demo", "ogaflow_local", None, "/tmp/other"),
    ],
)
def test_database_safety_rejects_other_targets(record):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = record
    with pytest.raises(RuntimeError, match="Refusing"):
        check_local(connection)
