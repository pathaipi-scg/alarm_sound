from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


def normalize_repeat(value, default: int = 3) -> int:
    try:
        repeat = int(value)
    except (TypeError, ValueError):
        repeat = default
    return repeat if repeat >= 1 else default


def should_trigger(alarm: dict, value) -> bool:
    mode = (alarm.get("alarm_mode") or "HIGH").upper()
    high = alarm.get("threshold_high")
    low = alarm.get("threshold_low")
    if high is None and low is None:
        try:
            digital_value = int(value)
        except (TypeError, ValueError):
            return False
        if mode == "HIGH":
            return digital_value == 1
        if mode == "LOW":
            return digital_value == 0
        return False
    try:
        analog_value = float(value)
    except (TypeError, ValueError):
        return False
    if mode == "HIGH" and high is not None:
        return analog_value > float(high)
    if mode == "LOW" and low is not None:
        return analog_value < float(low)
    return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def group_alarms_by_node(alarms: list[dict]) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    for alarm in alarms:
        mapping.setdefault(alarm["node_id"], []).append(alarm)
    return mapping


@dataclass(slots=True)
class AlarmRuntimeStatus:
    opc_connected: bool = False
    last_successful_health_read: str | None = None
    reconnect_count: int = 0
    last_reconnect_time: str | None = None
    mappings_loaded: int = 0
    subscribed_alarm_node_ids: int = 0
    last_reload_value: object | None = None
    last_successful_mapping_reload: str | None = None
    last_reload_error: str | None = None
    enabled_mappings: int = 0
    last_reload_time: str | None = None
    last_synthetic_alarm: int | None = None
    last_selected_mp3: str | None = None
    audio_initialized: bool = False
    last_playback_result: str | None = None
    line_name: str | None = None


@dataclass(slots=True)
class AlarmTransitionEngine:
    mapping: dict[str, list[dict]]
    on_trigger: Callable[[dict, object], None]
    active: dict[int, bool] = field(default_factory=dict)
    baseline_alarm_ids: set[int] = field(default_factory=set)

    def process_value(self, nodeid: str, value) -> list[dict]:
        events = []
        for alarm in self.mapping.get(nodeid, []):
            alarm_id = int(alarm["alarm_id"])
            triggered = should_trigger(alarm, value)
            if alarm_id in self.baseline_alarm_ids:
                self.active[alarm_id] = triggered
                self.baseline_alarm_ids.discard(alarm_id)
                events.append({"alarm_id": alarm_id, "event": "baseline", "active": triggered})
                continue
            was_active = self.active.get(alarm_id, False)
            if triggered and not was_active:
                self.active[alarm_id] = True
                self.on_trigger(alarm, value)
                events.append({"alarm_id": alarm_id, "event": "trigger", "active": True})
            elif not triggered and was_active:
                self.active[alarm_id] = False
                events.append({"alarm_id": alarm_id, "event": "clear", "active": False})
            else:
                events.append({"alarm_id": alarm_id, "event": "steady", "active": was_active})
        return events

    def replace_mapping(self, mapping: dict[str, list[dict]]) -> None:
        old_ids = set(self.active)
        new_ids = {int(a["alarm_id"]) for alarms in mapping.values() for a in alarms}
        self.mapping = mapping
        for alarm_id in list(self.active):
            if alarm_id not in new_ids:
                del self.active[alarm_id]
        self.baseline_alarm_ids = new_ids - old_ids


@dataclass(slots=True)
class ReloadSignalTracker:
    status: AlarmRuntimeStatus
    initialized: bool = False
    value: object | None = None

    def observe(self, value) -> bool:
        self.status.last_reload_value = value
        if not self.initialized:
            self.initialized = True
            self.value = value
            return False
        if value == self.value:
            return False
        self.value = value
        return True


def load_runtime_mapping(
    loader: Callable[[], list[dict]],
    engine: AlarmTransitionEngine,
    status: AlarmRuntimeStatus,
    *,
    is_reload: bool = False,
) -> list[dict]:
    try:
        alarms = loader()
        engine.replace_mapping(group_alarms_by_node(alarms))
        status.mappings_loaded = len(alarms)
        status.enabled_mappings = len(alarms)
        status.last_reload_error = None
        if is_reload:
            status.last_successful_mapping_reload = utc_now()
        return alarms
    except Exception:
        status.last_reload_error = "mapping_reload_failed"
        raise


async def replace_alarm_subscription(client, current_subscription, alarms, handler):
    subscription = await client.create_subscription(1000, handler)
    try:
        node_ids = {alarm["node_id"] for alarm in alarms}
        for node_id in sorted(node_ids):
            await subscription.subscribe_data_change(client.get_node(node_id))
        if current_subscription is not None:
            await current_subscription.delete()
    except Exception:
        try:
            await subscription.delete()
        except Exception:
            pass
        raise
    return subscription, node_ids


async def create_reload_subscription(client, reload_node: str, handler):
    subscription = await client.create_subscription(1000, handler)
    await subscription.subscribe_data_change(client.get_node(reload_node))
    return subscription


async def perform_health_read(node, status: AlarmRuntimeStatus, timeout: float) -> object:
    try:
        value = await asyncio.wait_for(node.read_value(), timeout=timeout)
    except Exception as exc:
        status.opc_connected = False
        raise ConnectionError("OPC health read failed") from exc
    status.last_successful_health_read = utc_now()
    return value
