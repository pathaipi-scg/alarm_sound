import asyncio

import pytest

from alarm_runtime import (
    AlarmRuntimeStatus,
    AlarmTransitionEngine,
    ReloadSignalTracker,
    create_reload_subscription,
    load_runtime_mapping,
    normalize_repeat,
    perform_health_read,
    replace_alarm_subscription,
    should_trigger,
)
from alarm_simulator import run_simulation


def alarm(mode="HIGH", high=10, low=None, alarm_id=1):
    return {
        "alarm_id": alarm_id, "node_id": "node", "tag_id": 2, "tag_path": "Test/Tag",
        "alarm_mode": mode, "threshold_high": high, "threshold_low": low,
        "mp3_file": "test.mp3", "repeat": 2,
    }


def test_high_low_and_digital_are_exact():
    high = alarm()
    low = alarm("LOW", None, 10)
    assert [should_trigger(high, value) for value in (9, 10, 11)] == [False, False, True]
    assert [should_trigger(low, value) for value in (11, 10, 9)] == [False, False, True]
    assert should_trigger(alarm("HIGH", None, None), 1)
    assert not should_trigger(alarm("HIGH", None, None), 0)
    assert should_trigger(alarm("LOW", None, None), 0)
    assert not should_trigger(alarm("CHANGE", None, None), 1)


def test_transition_only_triggers_on_activation_and_reactivation():
    triggers = []
    engine = AlarmTransitionEngine({"node": [alarm()]}, lambda item, value: triggers.append((item, value)))
    events = [engine.process_value("node", value)[0]["event"] for value in (9, 11, 12, 9, 11)]
    assert events == ["steady", "trigger", "steady", "clear", "trigger"]
    assert len(triggers) == 2


def test_reload_preserves_active_and_baselines_only_new_mapping():
    triggers = []
    first = alarm(alarm_id=1)
    engine = AlarmTransitionEngine({"node": [first]}, lambda item, value: triggers.append(item["alarm_id"]))
    engine.process_value("node", 11)
    second = alarm(alarm_id=2)
    engine.replace_mapping({"node": [first, second]})
    events = engine.process_value("node", 11)
    assert [event["event"] for event in events] == ["steady", "baseline"]
    assert triggers == [1]
    engine.process_value("node", 9)
    engine.process_value("node", 11)
    assert triggers == [1, 1, 2]


def test_repeat_legacy_fallback():
    assert normalize_repeat(2) == 2
    assert normalize_repeat(None) == 3
    assert normalize_repeat(0) == 3
    assert normalize_repeat("bad") == 3


def test_simulator_uses_engine_and_one_transition():
    triggers = []
    events = run_simulation(alarm(), lambda item, value: triggers.append((item["alarm_id"], value)))
    assert [event["event"] for event in events] == ["steady", "trigger"]
    assert triggers == [(1, 11.0)]


def test_reload_signal_first_value_is_baseline_equal_is_ignored_and_change_reloads_once():
    status = AlarmRuntimeStatus()
    tracker = ReloadSignalTracker(status)
    assert tracker.observe(7) is False
    assert tracker.observe(7) is False
    assert tracker.observe(8) is True
    assert tracker.observe(8) is False
    assert status.last_reload_value == 8


def test_every_session_start_loads_current_mapping_and_reconnect_does_not_replay():
    calls = []
    current = [alarm(alarm_id=1)]
    triggers = []
    engine = AlarmTransitionEngine({}, lambda item, _value: triggers.append(item["alarm_id"]))
    status = AlarmRuntimeStatus()

    def loader():
        calls.append(True)
        return list(current)

    load_runtime_mapping(loader, engine, status)
    assert engine.process_value("node", 11)[0]["event"] == "baseline"
    load_runtime_mapping(loader, engine, status)
    assert engine.process_value("node", 11)[0]["event"] == "steady"
    assert len(calls) == 2
    assert triggers == []


class FakeNode:
    def __init__(self, node_id, value=1, error=None):
        self.nodeid = type("NodeId", (), {"to_string": lambda self: node_id})()
        self.value = value
        self.error = error

    async def read_value(self):
        if self.error:
            raise self.error
        return self.value


class FakeSubscription:
    def __init__(self, handler):
        self.handler = handler
        self.nodes = []
        self.deleted = False

    async def subscribe_data_change(self, node):
        self.nodes.append(node.nodeid.to_string())

    async def delete(self):
        self.deleted = True


class FakeClient:
    def __init__(self):
        self.subscriptions = []

    async def create_subscription(self, _interval, handler):
        subscription = FakeSubscription(handler)
        self.subscriptions.append(subscription)
        return subscription

    def get_node(self, node_id):
        return FakeNode(node_id)


def test_reload_subscription_rebuild_removes_old_nodes_and_adds_new_nodes():
    client = FakeClient()
    first = [alarm(alarm_id=1), alarm(alarm_id=2) | {"node_id": "removed"}]
    old, nodes = asyncio.run(replace_alarm_subscription(client, None, first, object()))
    assert nodes == {"node", "removed"}
    second = [alarm(alarm_id=1), alarm(alarm_id=3) | {"node_id": "added"}]
    new, nodes = asyncio.run(replace_alarm_subscription(client, old, second, object()))
    assert old.deleted is True
    assert set(new.nodes) == {"node", "added"}
    assert nodes == {"node", "added"}


def test_reconnect_restores_alarm_and_reload_subscriptions():
    first_client = FakeClient()
    second_client = FakeClient()
    alarms = [alarm()]
    asyncio.run(replace_alarm_subscription(first_client, None, alarms, object()))
    asyncio.run(create_reload_subscription(first_client, "reload", object()))
    asyncio.run(replace_alarm_subscription(second_client, None, alarms, object()))
    asyncio.run(create_reload_subscription(second_client, "reload", object()))
    assert [sub.nodes for sub in first_client.subscriptions] == [["node"], ["reload"]]
    assert [sub.nodes for sub in second_client.subscriptions] == [["node"], ["reload"]]


def test_mapping_reload_preserves_active_and_baselines_new_active_alarm():
    triggers = []
    engine = AlarmTransitionEngine({}, lambda item, _value: triggers.append(item["alarm_id"]))
    status = AlarmRuntimeStatus()
    first = alarm(alarm_id=1)
    load_runtime_mapping(lambda: [first], engine, status)
    engine.process_value("node", 9)
    engine.process_value("node", 11)
    second = alarm(alarm_id=2)
    load_runtime_mapping(lambda: [first, second], engine, status, is_reload=True)
    events = engine.process_value("node", 11)
    assert [event["event"] for event in events] == ["steady", "baseline"]
    assert triggers == [1]
    assert status.last_successful_mapping_reload is not None


def test_health_failure_marks_disconnected_and_requests_controlled_reconnect():
    status = AlarmRuntimeStatus(opc_connected=True)
    with pytest.raises(ConnectionError, match="health read failed"):
        asyncio.run(perform_health_read(FakeNode("reload", error=RuntimeError("lost")), status, 1))
    assert status.opc_connected is False


def test_successful_health_read_updates_status():
    status = AlarmRuntimeStatus(opc_connected=True)
    assert asyncio.run(perform_health_read(FakeNode("reload", value=9), status, 1)) == 9
    assert status.last_successful_health_read is not None
