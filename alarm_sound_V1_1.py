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
RELOAD_NODE = "ns=2;s=LP2.SYSTEM.ALARM.RELOAD_ALARM"

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
            "mp3_file": row.Mp3File
        })

    return alarms


# =====================================================
# SOUND
# =====================================================

def play_sound(mp3_file):

    full_path = str(Path(MP3_FOLDER) / mp3_file)

    print(f"PLAY => {full_path}")

    try:

        pygame.mixer.music.load(full_path)
        pygame.mixer.music.play()

    except Exception as ex:

        print("PLAY ERROR")
        print(ex)


# =====================================================
# OPC SUB
# =====================================================

class AlarmHandler:

    def __init__(self, mapping):

        self.mapping = mapping
        self.reload_request = False

    def datachange_notification(self, node, value, data):

        nodeid = node.nodeid.to_string()
        if nodeid == RELOAD_NODE and value == 1:

            print()
            print("RELOAD ALARM REQUEST")
            self.reload_request = True
            return
        
        print(f"{node} => {value}")
        print(
            time.strftime("%H:%M:%S"),
            nodeid,
            value
        )

        if value != 1:
            return

        if nodeid not in self.mapping:
            return

        alarm = self.mapping[nodeid]

        play_sound(alarm["mp3_file"])


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

        reload_node = client.get_node(RELOAD_NODE)

        await sub.subscribe_data_change(
            reload_node
        )

        print("SUB:", RELOAD_NODE)
        subscribed_nodes = set()

        for alarm in alarms:
            
            node = client.get_node(alarm["node_id"])

            await sub.subscribe_data_change(node)

            subscribed_nodes.add(
                alarm["node_id"]
            )

            print(
                "SUB:",
                alarm["node_id"]
            )

        print()
        print("Waiting alarm...")

        while True:

            if handler.reload_request:

                print()
                print("RELOADING ALARM LIST...")

                alarms = load_alarm_mapping()

                node_mapping = {}

                for a in alarms:

                    node_mapping[a["node_id"]] = a

                    if a["node_id"] not in subscribed_nodes:

                        node = client.get_node(
                            a["node_id"]
                        )

                        await sub.subscribe_data_change(
                            node
                        )

                        subscribed_nodes.add(
                            a["node_id"]
                        )

                        print(
                            "NEW SUB:",
                            a["node_id"]
                        )

                handler.mapping = node_mapping

                print(
                    "TOTAL ALARM:",
                    len(node_mapping)
                )

                handler.reload_request = False

                print("RELOAD DONE")
                
                try:

                    await reload_node.write_value(0)

                except Exception as ex:

                    print(ex)

            await asyncio.sleep(1)


if __name__ == "__main__":

    asyncio.run(main())