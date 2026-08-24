from dotenv import load_dotenv
from pathlib import Path
import os

from config.sql_connection import build_sql_connection_string

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


SQL_DRIVER = os.getenv("SQL_DRIVER", "AUTO")


def sql_connection_string():
    return build_sql_connection_string(
        driver=SQL_DRIVER, server=SQL_SERVER, database=SQL_DB,
        username=SQL_USER, password=SQL_PASS, encrypt=SQL_ENCRYPT,
        trust_server_certificate=SQL_TRUST_SERVER_CERTIFICATE,
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
