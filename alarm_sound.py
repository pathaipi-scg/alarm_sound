import sys
import time
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.config import *

import pygame
import pyodbc

from asyncua import Client


# =====================================================
# CONFIG
# =====================================================

MP3_FOLDER = r"C:\Alarm"
#print("CONFIG FILE =", __file__)
#print("OPC_URL =", OPC_URL)

pygame.mixer.init()


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

async def main():

    alarms = load_alarm_mapping()

    print()
    print("=== ALARM LIST ===")

    for a in alarms:

        print(
            a["tag_path"],
            "=>",
            a["mp3_file"]
        )

    node_mapping = {}

    for a in alarms:

        node_mapping[a["node_id"]] = a

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

        for alarm in alarms:

            node = client.get_node(alarm["node_id"])

            await sub.subscribe_data_change(node)

            print(
                "SUB:",
                alarm["node_id"]
            )

        print()
        print("Waiting alarm...")

        while True:

            await asyncio.sleep(1)


if __name__ == "__main__":

    asyncio.run(main())