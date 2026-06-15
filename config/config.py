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