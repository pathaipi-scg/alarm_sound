import sys
import time
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.config import *

import pygame
import pyodbc

from asyncua import Client

import json
from urllib import request, parse
from urllib.error import URLError


# =====================================================
# CONFIG
# =====================================================

MP3_FOLDER = r"C:\Alarm"
#print("CONFIG FILE =", __file__)
#print("OPC_URL =", OPC_URL)

# hot-reload signal: the UI (alarm_list.py) writes reload_alarm_sound=1 to
# InfluxDB whenever Alarm_Lists changes (save / delete / refresh). This Mini-PC
# has no Modbus/internet but reads InfluxDB, so the signal lives there. After
# reloading we write the field back to 0 as an ack. Must match alarm_list.py.
RELOAD_MEASUREMENT = "system"
RELOAD_FIELD = "reload_alarm_sound"

pygame.mixer.init()


# =====================================================
# RELOAD SIGNAL
# =====================================================

# InfluxDB 1.8 talks plain HTTP, so we use stdlib urllib only -- the Mini-PC
# has no internet and cannot pip install the influxdb client.

def _influx_url(path, params):
    """Build http://host:port/<path>?<params>, adding auth if configured."""
    if INFLUX_USER:
        params = dict(params, u=INFLUX_USER, p=INFLUX_PASS or "")
    query = parse.urlencode(params)
    return f"http://{INFLUX_HOST}:{INFLUX_PORT}/{path}?{query}"


def read_reload_flag():
    """Return latest reload_alarm_sound value, or None on failure / no data."""
    try:
        url = _influx_url("query", {
            "db": INFLUX_DB,
            "q": f'SELECT last("{RELOAD_FIELD}") FROM "{RELOAD_MEASUREMENT}"',
        })
        with request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        # results -> series -> values[0] = [time, last]
        series = data["results"][0].get("series")
        if not series:
            return None
        return series[0]["values"][0][1]
    except (URLError, KeyError, IndexError, ValueError) as ex:
        print("READ RELOAD FLAG ERROR:", ex)
        return None


def write_reload_flag(value):
    """Write reload_alarm_sound back (0 = ack done) via line protocol."""
    try:
        url = _influx_url("write", {"db": INFLUX_DB})
        body = f"{RELOAD_MEASUREMENT} {RELOAD_FIELD}={int(value)}i".encode()
        req = request.Request(url, data=body, method="POST")
        with request.urlopen(req, timeout=5):
            pass
    except (URLError, ValueError) as ex:
        print("WRITE RELOAD FLAG ERROR:", ex)


# =====================================================
# SQL
# =====================================================

def load_alarm_mapping():

    conn = pyodbc.connect(
        "DRIVER={SQL Server};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DB};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASS};"
        "TrustServerCertificate=yes;"
    )

    sql = """
    SELECT
        a.AlarmId,
        a.TagId,
        a.TagPath,
        a.Mp3File,
        a.[Repeat],
        a.AlarmMode,
        a.ThresholdHigh,
        a.ThresholdLow,
        t.NodeId
    FROM Alarm_Lists a
    INNER JOIN TagMaster t
        ON a.TagId = t.TagId
    WHERE a.EnableAlarm = 1
    """

    cur = conn.cursor()
    cur.execute(sql)

    rows = cur.fetchall()

    conn.close()

    alarms = []

    for row in rows:

        alarms.append({
            "alarm_id": row.AlarmId,
            "tag_id": row.TagId,
            "tag_path": row.TagPath,
            "node_id": row.NodeId,
            "mp3_file": row.Mp3File,
            "repeat": row.Repeat,
            "alarm_mode": row.AlarmMode,
            "threshold_high": row.ThresholdHigh,
            "threshold_low": row.ThresholdLow
        })

    return alarms


# =====================================================
# SOUND
# =====================================================

def play_sound(mp3_file, repeat=3):

    full_path = str(Path(MP3_FOLDER) / mp3_file)

    # default to 3 plays when Repeat is NULL or invalid
    try:
        repeat = int(repeat)
    except (ValueError, TypeError):
        repeat = 3

    if repeat < 1:
        repeat = 3

    print(f"PLAY x{repeat} => {full_path}")

    try:

        pygame.mixer.music.load(full_path)
        # pygame loops = number of REPEATS after the first play
        pygame.mixer.music.play(loops=repeat - 1)

    except Exception as ex:

        print("PLAY ERROR")
        print(ex)


# =====================================================
# HISTORY
# =====================================================

def log_alarm_history(alarm, value):

    try:
        current = float(value)
    except (ValueError, TypeError):
        current = None

    try:

        conn = pyodbc.connect(
            "DRIVER={SQL Server};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DB};"
            f"UID={SQL_USER};"
            f"PWD={SQL_PASS};"
            "TrustServerCertificate=yes;"
        )

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO Alarm_History
                (AlarmId, TagId, TagPath, AlarmMode,
                 ThresholdHigh, ThresholdLow, CurrentValue,
                 Mp3File, CreatedTime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
            """,
            (
                alarm["alarm_id"],
                alarm["tag_id"],
                alarm["tag_path"],
                alarm.get("alarm_mode"),
                alarm.get("threshold_high"),
                alarm.get("threshold_low"),
                current,
                alarm["mp3_file"],
            ),
        )

        conn.commit()
        conn.close()

        print(f"HISTORY LOGGED => AlarmId={alarm['alarm_id']}")

    except Exception as ex:

        print("LOG HISTORY ERROR")
        print(ex)


# =====================================================
# ALARM CONDITION
# =====================================================

def should_trigger(alarm, value):
    """
    ตัดสินใจว่าค่าที่ได้ควรทำให้ alarm ร้องหรือไม่ โดยดูจาก ThresholdHigh / ThresholdLow
    ใน Alarm_Lists เท่านั้น:

      ThresholdHigh และ ThresholdLow เป็น NULL ทั้งคู่ -> digital : ร้องเมื่อ value == 1
      นอกนั้น                                        -> analog  : ร้องเมื่อ value > High หรือ value < Low
                                                                  (ฝั่งที่เป็น NULL จะถูกข้าม)
    """

    high = alarm.get("threshold_high")
    low = alarm.get("threshold_low")

    # ไม่มี threshold ทั้งคู่ -> digital
    if high is None and low is None:
        try:
            return int(value) == 1
        except (ValueError, TypeError):
            return False

    # analog
    try:
        v = float(value)
    except (ValueError, TypeError):
        return False

    if high is not None and v > float(high):
        return True

    if low is not None and v < float(low):
        return True

    return False


# =====================================================
# OPC SUB
# =====================================================

class AlarmHandler:

    def __init__(self, mapping):

        self.mapping = mapping

    def datachange_notification(self, node, value, data):

        nodeid = node.nodeid.to_string()
        print(f"{node} => {value}")
        print(
            time.strftime("%H:%M:%S"),
            nodeid,
            value
        )

        if nodeid not in self.mapping:
            return

        alarm = self.mapping[nodeid]

        if not should_trigger(alarm, value):
            return

        log_alarm_history(alarm, value)

        play_sound(alarm["mp3_file"], alarm.get("repeat"))


# =====================================================
# MAIN
# =====================================================

def build_node_mapping(alarms):

    print()
    print("=== ALARM LIST ===")

    node_mapping = {}

    for a in alarms:

        print(
            a["tag_path"],
            "=>",
            a["mp3_file"]
        )

        node_mapping[a["node_id"]] = a

    return node_mapping


async def subscribe_all(client, sub, alarms):
    """Subscribe data-change for every alarm node; return the handles."""

    handles = []

    for alarm in alarms:

        node = client.get_node(alarm["node_id"])

        handle = await sub.subscribe_data_change(node)
        handles.append(handle)

        print(
            "SUB:",
            alarm["node_id"]
        )

    return handles


async def main():

    alarms = load_alarm_mapping()
    node_mapping = build_node_mapping(alarms)

    handler = AlarmHandler(node_mapping)
    print("OPC_URL =", OPC_URL)
    print("Connecting OPC...")
    async with Client(OPC_URL) as client:

        print()
        print("Connected OPC")

        sub = await client.create_subscription(
            100,
            handler
        )

        await subscribe_all(client, sub, alarms)

        # clear any stale reload request at startup
        write_reload_flag(0)
        print("RELOAD FLAG cleared at startup")

        print()
        print("Waiting alarm...")

        while True:

            await asyncio.sleep(1)

            flag = read_reload_flag()

            if flag != 1:
                continue

            # Alarm_Lists changed in the UI -> reload everything
            print("RELOAD SIGNAL (reload_alarm_sound=1)")

            # silence any sound from an alarm that may no longer exist
            try:
                pygame.mixer.music.stop()
            except Exception as ex:
                print("STOP SOUND ERROR:", ex)

            try:
                alarms = load_alarm_mapping()
                node_mapping = build_node_mapping(alarms)
                handler.mapping = node_mapping

                # drop the old subscription and rebuild from the new list
                await sub.delete()
                sub = await client.create_subscription(100, handler)
                await subscribe_all(client, sub, alarms)

                print("RELOAD DONE")
            except Exception as ex:
                print("RELOAD ERROR:", ex)

            # ack back to the UI that reload finished (even if it errored,
            # so the UI does not hang waiting forever)
            write_reload_flag(0)


if __name__ == "__main__":

    asyncio.run(main())