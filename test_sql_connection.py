from unittest.mock import patch

import pytest

from config.sql_connection import build_sql_connection_string, resolve_sql_driver


@pytest.mark.parametrize(
    ("preferred", "installed", "expected"),
    [
        ("AUTO", ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"], "ODBC Driver 18 for SQL Server"),
        ("", ["ODBC Driver 17 for SQL Server"], "ODBC Driver 17 for SQL Server"),
        (None, ["ODBC Driver 17 for SQL Server", "ODBC Driver 19 for SQL Server", "ODBC Driver 20 for SQL Server"], "ODBC Driver 20 for SQL Server"),
        ("ODBC Driver 17 for SQL Server", ["ODBC Driver 17 for SQL Server"], "ODBC Driver 17 for SQL Server"),
    ],
)
def test_driver_resolution(preferred, installed, expected):
    with patch("config.sql_connection.pyodbc.drivers", return_value=installed):
        assert resolve_sql_driver(preferred) == expected


def test_explicit_missing_driver_does_not_fall_back():
    with patch("config.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 17 for SQL Server"]):
        with pytest.raises(RuntimeError, match="not installed"):
            resolve_sql_driver("ODBC Driver 18 for SQL Server")


def test_auto_rejects_legacy_below_minimum_and_unrelated_drivers():
    installed = ["SQL Server", "SQL Server Native Client 11.0", "Access", "Excel", "ODBC Driver 16 for SQL Server"]
    with patch("config.sql_connection.pyodbc.drivers", return_value=installed):
        with pytest.raises(RuntimeError, match="ODBC Driver 17\\+") as error:
            resolve_sql_driver("AUTO")
    assert "secret" not in str(error.value).lower()


def test_connection_string_uses_resolved_driver_and_security_flags():
    with patch("config.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 19 for SQL Server"]):
        value = build_sql_connection_string(
            driver="AUTO", server="sql.example.local", database="runtime",
            username="user", password="secret", encrypt="yes",
            trust_server_certificate=False,
        )
    assert "DRIVER={ODBC Driver 19 for SQL Server};" in value
    assert "Encrypt=yes;" in value
    assert "TrustServerCertificate=no;" in value
