import asyncio
import json
import queue
import sys
import threading
import time
from pathlib import Path
from urllib import parse, request
from urllib.error import URLError

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.config import *

import pygame
import pyodbc
from asyncua import Client


# =====================================================
# CONFIG
# =====================================================

MP3_FOLDER = r"C:\Alarm"
RELOAD_MEASUREMENT = "system"
RELOAD_FIELD = "reload_alarm_sound"

# OPC connection watchdog
OPC_HEALTHCHECK_INTERVAL = 5.0
OPC_HEALTHCHECK_TIMEOUT = 5.0


# =====================================================
# INITIALIZE
# =====================================================

try:
    pygame.mixer.init()
except Exception as ex:
    print("PYGAME INIT ERROR:", ex)

sound_command_queue = queue.Queue()
sql_log_queue = queue.Queue()


# =====================================================
# UTILS
# =====================================================

def _normalize_repeat(value, default=3):
    try:
        repeat = int(value)
    except (TypeError, ValueError):
        repeat = default
    if repeat < 1:
        repeat = default
    return repeat


# =====================================================
# SOUND WORKER
# =====================================================

def sound_worker():
    while True:
        try:
            item = sound_command_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            action = item.get("action")
            if action == "stop":
                try:
                    pygame.mixer.music.stop()
                except Exception as ex:
                    print("STOP SOUND ERROR:", ex)
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
                continue

            if action != "play":
                continue

            mp3_file = item.get("mp3_file")
            repeat = _normalize_repeat(item.get("repeat"), 3)
            full_path = str(Path(MP3_FOLDER) / mp3_file)

            print(f"[SOUND] {full_path}")
            if not Path(full_path).exists():
                print("MP3 NOT FOUND:", full_path)
                continue

            try:
                pygame.mixer.music.stop()
            except Exception as ex:
                print("STOP SOUND ERROR:", ex)

            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

            pygame.mixer.music.load(full_path)
            pygame.mixer.music.play(loops=max(repeat - 1, 0))
            print("BUSY =", pygame.mixer.music.get_busy())
        except Exception as ex:
            print("SOUND WORKER ERROR:", ex)
        finally:
            sound_command_queue.task_done()


threading.Thread(target=sound_worker, daemon=True).start()


# =====================================================
# SQL WORKER
# =====================================================

def _sql_connection():
    while True:
        try:
            return pyodbc.connect(
                f"DRIVER={{{SQL_DRIVER}}};"
                f"SERVER={SQL_SERVER};"
                f"DATABASE={SQL_DB};"
                f"UID={SQL_USER};"
                f"PWD={SQL_PASS};"
                "TrustServerCertificate=yes;"
            )
        except Exception as ex:
            print("SQL CONNECT ERROR:", ex)
            time.sleep(5)


def _persist_alarm_history(payload):
    conn = None
    try:
        conn = _sql_connection()
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
                payload["alarm_id"],
                payload["tag_id"],
                payload["tag_path"],
                payload.get("alarm_mode"),
                payload.get("threshold_high"),
                payload.get("threshold_low"),
                payload["current_value"],
                payload["mp3_file"],
            ),
        )
        conn.commit()
        print(f"HISTORY LOGGED => AlarmId={payload['alarm_id']}")
    except Exception as ex:
        print("LOG HISTORY ERROR")
        print(ex)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def sql_log_worker():
    while True:
        try:
            payload = sql_log_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            _persist_alarm_history(payload)
        except Exception as ex:
            print("SQL WORKER ERROR:", ex)
        finally:
            sql_log_queue.task_done()


threading.Thread(target=sql_log_worker, daemon=True).start()


# =====================================================
# RELOAD SIGNAL
# =====================================================

def _influx_url(path, params):
    """Build http://host:port/<path>?<params>, adding auth if configured."""
    if INFLUX_USER:
        params = dict(params, u=INFLUX_USER, p=INFLUX_PASS or "")
    query = parse.urlencode(params)
    return f"http://{INFLUX_HOST}:{INFLUX_PORT}/{path}?{query}"

# =====================================================
# SQL
# =====================================================

def load_alarm_mapping():
    while True:
        try:
            conn = _sql_connection()
            break
        except Exception as ex:
            print("LOAD ALARM MAPPING ERROR:", ex)
            time.sleep(5)

    try:
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

        alarms = []
        for row in rows:
            alarms.append(
                {
                    "alarm_id": row.AlarmId,
                    "tag_id": row.TagId,
                    "tag_path": row.TagPath,
                    "node_id": row.NodeId,
                    "mp3_file": row.Mp3File,
                    "repeat": row.Repeat,
                    "alarm_mode": row.AlarmMode,
                    "threshold_high": row.ThresholdHigh,
                    "threshold_low": row.ThresholdLow,
                }
            )
        return alarms
    except Exception as ex:
        print("LOAD ALARM MAPPING ERROR:", ex)
        time.sleep(5)
        return load_alarm_mapping()
    finally:
        try:
            conn.close()
        except Exception:
            pass


# =====================================================
# SOUND
# =====================================================

def enqueue_sound(mp3_file, repeat=3):
    sound_command_queue.put({"action": "play", "mp3_file": mp3_file, "repeat": repeat})


# =====================================================
# HISTORY
# =====================================================

def log_alarm_history(alarm, value):
    try:
        current = float(value)
    except (ValueError, TypeError):
        current = None

    sql_log_queue.put(
        {
            "alarm_id": alarm["alarm_id"],
            "tag_id": alarm["tag_id"],
            "tag_path": alarm["tag_path"],
            "alarm_mode": alarm.get("alarm_mode"),
            "threshold_high": alarm.get("threshold_high"),
            "threshold_low": alarm.get("threshold_low"),
            "current_value": current,
            "mp3_file": alarm["mp3_file"],
        }
    )


# =====================================================
# ALARM CONDITION
# =====================================================
def should_trigger(alarm, value):

    mode = (alarm.get("alarm_mode") or "HIGH").upper()

    high = alarm.get("threshold_high")
    low = alarm.get("threshold_low")

    # ----------------------------
    # Digital Alarm
    # ----------------------------
    if high is None and low is None:

        try:
            v = int(value)
        except (ValueError, TypeError):
            return False

        if mode == "LOW":
            return v == 0

        return v == 1

    # ----------------------------
    # Analog Alarm
    # ----------------------------
    try:
        v = float(value)
    except (ValueError, TypeError):
        return False

    if mode == "HIGH":
        if high is None:
            return False
        return v > float(high)

    if mode == "LOW":
        if low is None:
            return False
        return v < float(low)

    return False
# =====================================================
# OPC SUB
# =====================================================

class AlarmHandler:
    def __init__(self, mapping):
        self.mapping = mapping
        self.active = {}

    def datachange_notification(self, node, value, data):
        nodeid = node.nodeid.to_string()
        print(f"{node} => {value}")
        print(time.strftime("%H:%M:%S"), nodeid, value)

        if nodeid not in self.mapping:
            return

        alarms = self.mapping[nodeid]

        for alarm in alarms:
            alarm_id = alarm["alarm_id"]
            trigger = should_trigger(alarm, value)
            active = self.active.get(alarm_id, False)

            print(
                f"[CHECK] "
                f"AlarmId={alarm_id} "
                f"Tag={alarm['tag_path']} "
                f"Mode={alarm.get('alarm_mode')} "
                f"High={alarm.get('threshold_high')} "
                f"Low={alarm.get('threshold_low')} "
                f"Value={value} "
                f"Trigger={trigger} "
                f"Active={active}"
            )
            # เกิด Alarm ครั้งแรก
            if trigger and not active:
                print(f"[TRIGGER] AlarmId={alarm_id}")
                self.active[alarm_id] = True
                log_alarm_history(alarm, value)
                enqueue_sound(
                    alarm["mp3_file"],
                    alarm.get("repeat") or 3
                )

            # Alarm หาย
            elif not trigger and active:
                print(f"[CLEAR] AlarmId={alarm_id}")
                self.active[alarm_id] = False



class SystemHandler:

    def __init__(self):
        self.reload_requested = False
        self.reload_value = None

    def datachange_notification(self, node, value, data):

        nodeid = node.nodeid.to_string()

        print(f"[SYSTEM] {nodeid} => {value}")

        if nodeid != RELOAD_ALARM_NODE:
            return

        # ครั้งแรกที่ Subscribe เข้ามา ให้จำค่าไว้เฉย ๆ
        if self.reload_value is None:
            self.reload_value = value
            return

        # ค่าเดิม ไม่ต้องทำอะไร
        if value == self.reload_value:
            return

        # ค่าเปลี่ยนจริง จึงสั่ง Reload
        self.reload_value = value
        self.reload_requested = True

# =====================================================
# MAIN
# =====================================================

def build_node_mapping(alarms):
    print()
    print("=== ALARM LIST ===")

    node_mapping = {}
    for alarm in alarms:
        print(
        f"AlarmId={alarm['alarm_id']}"
        f" Tag={alarm['tag_path']}"
        f" Mode={alarm['alarm_mode']}"
        f" Repeat={alarm['repeat']}"
        f" MP3={alarm['mp3_file']}"
        )
        nodeid = alarm["node_id"]
        if nodeid not in node_mapping:
            node_mapping[nodeid] = []
        node_mapping[nodeid].append(alarm)

    return node_mapping


async def subscribe_all(client, sub, alarms):

    handles = []
    subscribed = set()
    for alarm in alarms:
        nodeid = alarm["node_id"]
        if nodeid in subscribed:
            continue
        subscribed.add(nodeid)
        node = client.get_node(nodeid)
        handle = await sub.subscribe_data_change(node)
        handles.append(handle)
        print("SUB:", nodeid)
        
    return handles


async def reload_subscriptions(client, sub, alarms, handler):
    try:
        if sub is not None:
            await sub.delete()
    except Exception as ex:
        print("DELETE SUB ERROR:", ex)

    new_sub = await client.create_subscription(1000, handler)
    await subscribe_all(client, new_sub, alarms)
    return new_sub

async def subscribe_system(client, sub):

    node = client.get_node(RELOAD_ALARM_NODE)

    await sub.subscribe_data_change(node)

    print("SUB:", RELOAD_ALARM_NODE)

async def main():
    alarms = load_alarm_mapping()
    node_mapping = build_node_mapping(alarms)
    #handler = AlarmHandler(node_mapping)

    print("OPC_URL =", OPC_URL)

    while True:
        try:
            print("Connecting OPC...")
            async with Client(OPC_URL) as client:
                print()
                print("Connected OPC")

                alarm_handler = AlarmHandler(node_mapping)
                system_handler = SystemHandler()

                alarm_sub = await client.create_subscription(
                    1000,
                    alarm_handler
                )

                system_sub = await client.create_subscription(
                    1000,
                    system_handler
                )

                await subscribe_all(
                    client,
                    alarm_sub,
                    alarms
                )

                await subscribe_system(
                    client,
                    system_sub
                )

                print("System subscription ready")

                # Use the reload node as a lightweight OPC heartbeat.
                # If asyncua's internal publish loop gets disconnected and only
                # retries internally, this explicit read will fail and force the
                # outer session loop to create a fresh Client + subscriptions.
                health_node = client.get_node(RELOAD_ALARM_NODE)
                last_healthcheck = 0.0

                while True:
                    await asyncio.sleep(1)

                    now = time.monotonic()
                    if now - last_healthcheck >= OPC_HEALTHCHECK_INTERVAL:
                        last_healthcheck = now
                        try:
                            await asyncio.wait_for(
                                health_node.read_value(),
                                timeout=OPC_HEALTHCHECK_TIMEOUT
                            )
                        except Exception as ex:
                            print("OPC HEALTH CHECK FAILED:", ex)
                            raise ConnectionError(
                                "OPC connection lost - rebuilding session"
                            ) from ex

                    if not system_handler.reload_requested:
                        continue

                    system_handler.reload_requested = False

                    print("RELOAD SIGNAL")

                    sound_command_queue.put({"action": "stop"})

                    try:
                        alarms = load_alarm_mapping()
                        node_mapping = build_node_mapping(alarms)
                        #handler.mapping = node_mapping
                        alarm_handler.mapping = node_mapping
                        alarm_handler.active.clear()
                        alarm_sub = await reload_subscriptions(
                            client,
                            alarm_sub,
                            alarms,
                            alarm_handler
                        )
                        print("RELOAD DONE")
                    except Exception as ex:
                        print("RELOAD ERROR:", ex)

        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print("OPC SESSION ERROR:", ex)
            print("Reconnecting OPC in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
