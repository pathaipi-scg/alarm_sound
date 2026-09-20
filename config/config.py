from dotenv import load_dotenv
from pathlib import Path
import os

from config.sql_connection import build_sql_connection_string

_profile = os.environ.get("ALARM_SOUND_ENV_FILE")
env_path = Path(__file__).resolve().parent / ".env"
if _profile is not None:
    if not _profile.strip():
        raise RuntimeError("ALARM_SOUND_ENV_FILE must not be blank")
    env_path = Path(_profile)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parents[1] / env_path
    if not env_path.is_file():
        raise RuntimeError(f"Environment profile does not exist: {env_path}")
load_dotenv(env_path, override=_profile is not None)

# Blank/unset retains the legacy single-line SQL behavior.
# LINE_ID is a deprecated input alias only; runtime and SQL use LineName.
LINE_NAME = (os.getenv("LINE_NAME", "").strip() or os.getenv("LINE_ID", "").strip()).upper()

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
