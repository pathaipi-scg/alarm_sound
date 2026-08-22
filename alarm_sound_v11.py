import asyncio
import json
import queue
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config.config import *

import pygame
import pyodbc
from asyncua import Client
from alarm_runtime import (
    AlarmRuntimeStatus,
    AlarmTransitionEngine,
    ReloadSignalTracker,
    create_reload_subscription,
    group_alarms_by_node,
    load_runtime_mapping,
    normalize_repeat,
    perform_health_read,
    replace_alarm_subscription,
    should_trigger as runtime_should_trigger,
    utc_now,
)


# =====================================================
# CONFIG
# =====================================================

RELOAD_MEASUREMENT = "system"
RELOAD_FIELD = "reload_alarm_sound"

# OPC connection watchdog
OPC_HEALTHCHECK_INTERVAL = 5.0
OPC_HEALTHCHECK_TIMEOUT = 5.0
runtime_status = AlarmRuntimeStatus()


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
    return normalize_repeat(value, default)


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
            repeat = normalize_repeat(item.get("repeat"), 3)
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
            return pyodbc.connect(sql_connection_string())
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
          AND t.IsActive = 1
          AND UPPER(a.AlarmMode) IN ('HIGH', 'LOW')
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
    """Compatibility wrapper; runtime and simulator share alarm_runtime."""
    return runtime_should_trigger(alarm, value)
# =====================================================
# OPC SUB
# =====================================================

class AlarmHandler:
    def __init__(self, mapping=None):
        self.engine = AlarmTransitionEngine(mapping or {}, self._trigger)

    @property
    def mapping(self):
        return self.engine.mapping

    @mapping.setter
    def mapping(self, value):
        self.engine.replace_mapping(value)

    @property
    def active(self):
        return self.engine.active

    def _trigger(self, alarm, value):
        print(f"[TRIGGER] AlarmId={alarm['alarm_id']}")
        log_alarm_history(alarm, value)
        enqueue_sound(alarm["mp3_file"], normalize_repeat(alarm.get("repeat"), 3))

    def datachange_notification(self, node, value, data):
        nodeid = node.nodeid.to_string()
        print(f"{node} => {value}")
        print(time.strftime("%H:%M:%S"), nodeid, value)

        for event in self.engine.process_value(nodeid, value):
            print(f"[ALARM {event['event'].upper()}] AlarmId={event['alarm_id']} Active={event['active']}")



class SystemHandler:

    def __init__(self, status):
        self.reload_requested = False
        self.tracker = ReloadSignalTracker(status)

    def datachange_notification(self, node, value, data):

        nodeid = node.nodeid.to_string()

        print(f"[SYSTEM] {nodeid} => {value}")

        if nodeid != RELOAD_ALARM_NODE:
            return

        # ครั้งแรกที่ Subscribe เข้ามา ให้จำค่าไว้เฉย ๆ
        if not self.tracker.initialized:
            self.tracker.observe(value)
            return

        # ค่าเดิม ไม่ต้องทำอะไร
        if not self.tracker.observe(value):
            return

        # ค่าเปลี่ยนจริง จึงสั่ง Reload
        self.reload_requested = True

# =====================================================
# MAIN
# =====================================================

def build_node_mapping(alarms):
    print()
    print("=== ALARM LIST ===")

    node_mapping = group_alarms_by_node(alarms)
    for alarm in alarms:
        print(
        f"AlarmId={alarm['alarm_id']}"
        f" Tag={alarm['tag_path']}"
        f" Mode={alarm['alarm_mode']}"
        f" Repeat={alarm['repeat']}"
        f" MP3={alarm['mp3_file']}"
        )
    return node_mapping


async def reload_subscriptions(client, sub, alarms, handler):
    new_sub, node_ids = await replace_alarm_subscription(client, sub, alarms, handler)
    runtime_status.subscribed_alarm_node_ids = len(node_ids)
    return new_sub

async def main():
    alarm_handler = AlarmHandler()
    connected_once = False

    print("OPC_URL =", OPC_URL)

    while True:
        try:
            print("Connecting OPC...")
            async with Client(OPC_URL) as client:
                print()
                print("Connected OPC")
                runtime_status.opc_connected = True
                if connected_once:
                    runtime_status.last_reconnect_time = utc_now()
                connected_once = True

                # Reload SQL on every successful OPC session. A counter change
                # while this process was offline therefore cannot leave stale
                # Alarm mappings after reconnect.
                alarms = load_runtime_mapping(
                    load_alarm_mapping, alarm_handler.engine, runtime_status
                )
                build_node_mapping(alarms)
                system_handler = SystemHandler(runtime_status)
                alarm_sub = await reload_subscriptions(
                    client, None, alarms, alarm_handler
                )
                _system_sub = await create_reload_subscription(
                    client, RELOAD_ALARM_NODE, system_handler
                )

                print("System subscription ready")
                print("[RUNTIME STATUS]", json.dumps(asdict(runtime_status), default=str))

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
                            await perform_health_read(
                                health_node, runtime_status, OPC_HEALTHCHECK_TIMEOUT
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
                        alarms = load_runtime_mapping(
                            load_alarm_mapping,
                            alarm_handler.engine,
                            runtime_status,
                            is_reload=True,
                        )
                        build_node_mapping(alarms)
                        alarm_sub = await reload_subscriptions(
                            client,
                            alarm_sub,
                            alarms,
                            alarm_handler
                        )
                        print("RELOAD DONE")
                        print("[RUNTIME STATUS]", json.dumps(asdict(runtime_status), default=str))
                    except Exception as ex:
                        runtime_status.last_reload_error = "mapping_or_subscription_reload_failed"
                        print("RELOAD ERROR:", ex)

        except asyncio.CancelledError:
            raise
        except Exception as ex:
            runtime_status.opc_connected = False
            runtime_status.reconnect_count += 1
            print("OPC SESSION ERROR:", ex)
            print("Reconnecting OPC in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
