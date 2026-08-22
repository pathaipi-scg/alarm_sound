"""Development-only, read-only SQL alarm simulator.

This process never connects to OPC, writes Alarm_Lists/Alarm_History, or sends
the production reload signal. Each invocation reloads one enabled mapping from
SQL and injects synthetic values through the canonical transition engine.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pyodbc

from alarm_runtime import AlarmTransitionEngine, normalize_repeat
from config.config import MP3_FOLDER, sql_connection_string


def load_enabled_alarm(alarm_id: int) -> dict:
    connection = pyodbc.connect(sql_connection_string())
    try:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT a.AlarmId, a.TagId, a.TagPath, a.AlarmMode,
                      a.ThresholdHigh, a.ThresholdLow, a.Mp3File, a.[Repeat], t.NodeId
               FROM Alarm_Lists a INNER JOIN TagMaster t ON a.TagId=t.TagId
               WHERE a.AlarmId=? AND a.EnableAlarm=1 AND t.IsActive=1
                 AND UPPER(a.AlarmMode) IN ('HIGH', 'LOW')""",
            alarm_id,
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Enabled Alarm mapping was not found.")
        return {
            "alarm_id": int(row[0]), "tag_id": int(row[1]), "tag_path": str(row[2]),
            "alarm_mode": str(row[3]), "threshold_high": row[4], "threshold_low": row[5],
            "mp3_file": str(row[6]), "repeat": row[7], "node_id": str(row[8]),
        }
    finally:
        connection.close()


def synthetic_values(alarm: dict) -> tuple[float | int, float | int]:
    mode = alarm["alarm_mode"].upper()
    high, low = alarm["threshold_high"], alarm["threshold_low"]
    if high is None and low is None:
        return (0, 1) if mode == "HIGH" else (1, 0)
    if mode == "HIGH" and high is not None:
        return float(high), float(high) + 1
    if mode == "LOW" and low is not None:
        return float(low), float(low) - 1
    raise RuntimeError("Mapping mode/threshold combination is not executable.")


def run_simulation(alarm: dict, trigger_callback) -> list[dict]:
    engine = AlarmTransitionEngine({alarm["node_id"]: [alarm]}, trigger_callback)
    inactive, active = synthetic_values(alarm)
    return engine.process_value(alarm["node_id"], inactive) + engine.process_value(alarm["node_id"], active)


def play_bounded(alarm: dict, max_seconds: float) -> dict:
    import pygame

    path = (Path(MP3_FOLDER) / alarm["mp3_file"]).resolve()
    root = Path(MP3_FOLDER).resolve()
    if path.parent != root or not path.is_file():
        raise RuntimeError("Mapped MP3 is missing from the configured development folder.")
    pygame.mixer.init()
    requested_repeats = normalize_repeat(alarm.get("repeat"), 3)
    pygame.mixer.music.load(str(path))
    pygame.mixer.music.play(loops=max(requested_repeats - 1, 0))
    deadline = time.monotonic() + max_seconds
    while pygame.mixer.music.get_busy() and time.monotonic() < deadline:
        time.sleep(0.1)
    bounded_stop = pygame.mixer.music.get_busy()
    if bounded_stop:
        pygame.mixer.music.stop()
    return {
        "audio_initialized": True,
        "audio_backend": "pygame/SDL default notebook output",
        "mixer_format": pygame.mixer.get_init(),
        "playback_requested": True,
        "requested_repeats": requested_repeats,
        "bounded_stop": bool(bounded_stop),
        "software_result": "playback_started",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alarm-id", type=int, required=True)
    parser.add_argument("--play", action="store_true", help="Authorize notebook-local pygame output")
    parser.add_argument("--max-seconds", type=float, default=15.0)
    args = parser.parse_args()
    alarm = load_enabled_alarm(args.alarm_id)
    playback = {"playback_requested": False, "software_result": "dry_run"}

    def on_trigger(mapping, _value):
        nonlocal playback
        if args.play:
            playback = play_bounded(mapping, max(0.5, min(args.max_seconds, 30.0)))

    events = run_simulation(alarm, on_trigger)
    print(json.dumps({
        "simulator": "notebook_read_only",
        "alarm": {key: alarm[key] for key in (
            "alarm_id", "tag_id", "tag_path", "alarm_mode", "threshold_high",
            "threshold_low", "mp3_file", "repeat", "node_id"
        )},
        "events": events,
        "history_write": False,
        "opc_write": False,
        "production_reload": False,
        "playback": playback,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
