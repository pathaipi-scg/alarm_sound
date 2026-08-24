from __future__ import annotations

import re

import pyodbc

MINIMUM_SQL_DRIVER_VERSION = 17
_SQL_DRIVER_PATTERN = re.compile(r"^ODBC Driver ([0-9]+) for SQL Server$")


def resolve_sql_driver(preferred: str | None = None) -> str:
    installed = list(pyodbc.drivers())
    requested = (preferred or "").strip()
    if requested and requested.upper() != "AUTO":
        if requested in installed:
            return requested
        raise RuntimeError(
            f"Configured SQL_DRIVER is not installed: {requested!r}. "
            f"Installed ODBC drivers: {installed!r}"
        )

    supported = []
    for driver in installed:
        match = _SQL_DRIVER_PATTERN.fullmatch(driver)
        if match and int(match.group(1)) >= MINIMUM_SQL_DRIVER_VERSION:
            supported.append((int(match.group(1)), driver))
    if supported:
        return max(supported, key=lambda item: item[0])[1]
    raise RuntimeError(
        "No supported Microsoft SQL Server ODBC driver is installed "
        f"(ODBC Driver {MINIMUM_SQL_DRIVER_VERSION}+ required). "
        f"Installed ODBC drivers: {installed!r}"
    )


def build_sql_connection_string(
    *, driver: str | None, server: str | None, database: str | None,
    username: str | None, password: str | None, encrypt: str,
    trust_server_certificate: bool,
) -> str:
    resolved_driver = resolve_sql_driver(driver)
    trust = "yes" if trust_server_certificate else "no"
    return (
        f"DRIVER={{{resolved_driver}}};SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
    )
