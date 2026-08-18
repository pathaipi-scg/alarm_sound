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


# InfluxDB 1.8
INFLUX_HOST = os.getenv("INFLUX_HOST")
INFLUX_PORT = int(os.getenv("INFLUX_PORT", "8086"))
INFLUX_DB = os.getenv("INFLUX_DB")
INFLUX_USER = os.getenv("INFLUX_USER")
INFLUX_PASS = os.getenv("INFLUX_PASS")

# Poller
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

#print("CONFIG MODULE =", __file__)
#print("ENV PATH =", env_path)
#print("LOADED OPC =", OPC_URL)


# Filesystem paths (default to production values; override in .env per machine)
MP3_FOLDER = os.getenv("MP3_FOLDER", r"")
BROWSER_SCRIPT = os.getenv("BROWSER_SCRIPT", r"D:\AI\opc_service\app\browser.py")

MODBUS_RELOAD_BROWSER = int(os.getenv("MODBUS_RELOAD_BROWSER", "12001"))
MODBUS_RELOAD_POLLER = int(os.getenv("MODBUS_RELOAD_POLLER", "12002"))
MODBUS_RELOAD_ALARM = int(os.getenv("MODBUS_RELOAD_ALARM", "12003"))
MODBUS_RELOAD_TEST = int(os.getenv("MODBUS_RELOAD_TEST", "12004"))
MODBUS_RELOAD_EAK = int(os.getenv("MODBUS_RELOAD_EAK", "12005"))


# =====================================================
# OPC System Tags
# =====================================================

SYSTEM_TAG_PREFIX = "ns=2;s=SERVER.SYSTEM."

RELOAD_ALARM_NODE = SYSTEM_TAG_PREFIX + "RELOAD_ALARM"
LIVE_STATUS_NODE  = SYSTEM_TAG_PREFIX + "LIVE_STATUS"
TEST_SOUND_NODE   = SYSTEM_TAG_PREFIX + "TEST_SOUND"
TEST_ALM_NODE     = SYSTEM_TAG_PREFIX + "TEST_ALM"
