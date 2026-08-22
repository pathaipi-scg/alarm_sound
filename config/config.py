from dotenv import load_dotenv
from pathlib import Path
import os

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# OPC
OPC_URL = os.getenv("OPC_URL")

# SQL
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DB = os.getenv("SQL_DB")
SQL_USER = os.getenv("SQL_USER")
SQL_PASS = os.getenv("SQL_PASS")
SQL_ENCRYPT = os.getenv("SQL_ENCRYPT", "yes").strip().lower()
SQL_TRUST_SERVER_CERTIFICATE = os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
if SQL_ENCRYPT not in {"yes", "no"}:
    raise RuntimeError("SQL_ENCRYPT must be yes or no")


import pyodbc
drivers = pyodbc.drivers()

for d in (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",
):
    if d in drivers:
        SQL_DRIVER = d
        break
else:
    raise RuntimeError(
        f"No supported SQL Server ODBC Driver found.\n"
        f"Installed drivers: {drivers}"
    )


def sql_connection_string():
    trust = "yes" if SQL_TRUST_SERVER_CERTIFICATE else "no"
    return (
        f"DRIVER={{{SQL_DRIVER}}};SERVER={SQL_SERVER};DATABASE={SQL_DB};"
        f"UID={SQL_USER};PWD={SQL_PASS};Encrypt={SQL_ENCRYPT};"
        f"TrustServerCertificate={trust};"
    )


#print("CONFIG MODULE =", __file__)
#print("ENV PATH =", env_path)
#print("LOADED OPC =", OPC_URL)


# Filesystem paths are deployment configuration; no production path is a code default.
MP3_FOLDER = os.getenv("MP3_FOLDER", r"")
# =====================================================
# OPC System Tags
# =====================================================

RELOAD_ALARM_NODE = os.getenv("RELOAD_ALARM_NODE", "").strip()
