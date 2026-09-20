import asyncio
import importlib.util
import json
import runpy
import sqlite3
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from alarm_runtime import load_runtime_mapping
from test_alarm_runtime import FakeClient


@pytest.fixture
def app():
    # Import the real application without audio initialization or worker threads.
    with patch("pygame.mixer.init"), patch("threading.Thread.start"):
        spec = importlib.util.spec_from_file_location("line_test_app", "alarm_sound_v11.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class Database:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("ATTACH DATABASE ':memory:' AS dbo")
        self.db.executescript("""
            CREATE TABLE dbo.Alarm_Lists (
                AlarmId INTEGER, TagId INTEGER, TagPath TEXT, Mp3File TEXT,
                Repeat INTEGER, AlarmMode TEXT, ThresholdHigh REAL,
                ThresholdLow REAL, EnableAlarm INTEGER, LineName TEXT);
            CREATE TABLE dbo.TagMaster (TagId INTEGER, NodeId TEXT, IsActive INTEGER, LineName TEXT, Path TEXT);
        """)
        for alarm_id, line, enabled in [(1, "SB11", 1), (2, "SB12", 1),
                                         (3, "SB11", 0), (4, "SB12", 0)]:
            self.db.execute("INSERT INTO dbo.Alarm_Lists VALUES (?, ?, ?, ?, 2, 'HIGH', 10, NULL, ?, ?)",
                            (alarm_id, alarm_id, line, "alarm.mp3", enabled, line))
            self.db.execute("INSERT INTO dbo.TagMaster VALUES (?, ?, 1, ?, ?)",
                            (alarm_id, f"node-{line}-{alarm_id}",line,line))
        self.calls = []

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.result = self.db.execute(sql, params)

    def fetchall(self):
        names = [column[0] for column in self.result.description]
        return [SimpleNamespace(**dict(zip(names, row))) for row in self.result.fetchall()]

    def close(self):
        pass  # Application closes each logical connection; fixture owns the database.


@pytest.fixture
def database(app, monkeypatch):
    db = Database()
    monkeypatch.setattr(app, "_sql_connection", lambda: db)
    yield db
    db.db.close()


@pytest.mark.parametrize("line,expected", [("SB11", 1), ("SB12", 2)])
def test_mapping_and_reload_isolate_both_lines(app, database, monkeypatch, line, expected):
    monkeypatch.setattr(app, "LINE_NAME", line)
    handler = app.AlarmHandler()
    client = FakeClient()
    subscription = None
    for is_reload in (False, True):
        alarms = load_runtime_mapping(app.load_alarm_mapping, handler.engine,
                                      app.runtime_status, is_reload=is_reload)
        assert [a["alarm_id"] for a in alarms] == [expected]
        subscription = asyncio.run(app.reload_subscriptions(client, subscription, alarms, handler))
        assert subscription.nodes == [f"node-{line}-{expected}"]
        assert set(handler.mapping) == {f"node-{line}-{expected}"}
        assert app.runtime_status.enabled_mappings == 1
        assert app.runtime_status.subscribed_alarm_node_ids == 1
    assert all("a.LineName = ?" in sql and params == (line,)
               for sql, params in database.calls)
    assert client.subscriptions[0].deleted


def test_legacy_mapping_query_has_no_line_column(app, database, monkeypatch):
    monkeypatch.setattr(app, "LINE_NAME", "")
    assert [a["alarm_id"] for a in app.load_alarm_mapping()] == [1, 2]
    sql, params = database.calls[-1]
    assert "LineName" not in sql
    assert params == ()


@pytest.mark.parametrize("line", ["SB11", "SB12", ""])
def test_history_insert_line_and_legacy(app, monkeypatch, line):
    monkeypatch.setattr(app, "LINE_NAME", line)
    connection = Mock()
    monkeypatch.setattr(app, "_sql_connection", lambda: connection)
    payload = dict(alarm_id=1, tag_id=2, tag_path="tag", alarm_mode="HIGH",
                   threshold_high=10, threshold_low=None, current_value=11,
                   mp3_file="alarm.mp3")
    app._persist_alarm_history(payload)
    sql, params = connection.cursor.return_value.execute.call_args.args
    assert params[:8] == (1, 2, "tag", "HIGH", 10, None, 11, "alarm.mp3")
    if line:
        assert "INSERT INTO dbo.Alarm_History" in sql
        assert "LineName" in sql
        assert params[8:] == (line,)
    else:
        assert "LineName" not in sql
        assert len(params) == 8
    connection.commit.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize("raw,expected", [("SB11", "SB11"), (" sb12 ", "SB12"),
                                         ("", ""), ("  ", ""), (None, "")])
def test_config_line_name(app, monkeypatch, raw, expected):
    monkeypatch.delenv("LINE_ID", raising=False)
    if raw is None:
        monkeypatch.delenv("LINE_NAME", raising=False)
    else:
        monkeypatch.setenv("LINE_NAME", raw)
    with patch("dotenv.load_dotenv"):
        config = runpy.run_path(str(Path("config/config.py")))
    assert config["LINE_NAME"] == expected


@pytest.mark.parametrize('canonical,legacy,expected', [
    ('SB11','SB12','SB11'), ('',' sb12 ','SB12'), ('  ','LP2','LP2'), ('CB','','CB'), ('','',''),
])
def test_deprecated_input_alias_normalizes_to_line_name(app, monkeypatch, canonical, legacy, expected):
    monkeypatch.setenv('LINE_NAME',canonical)
    monkeypatch.setenv('LINE_ID',legacy)
    with patch('dotenv.load_dotenv'):
        config = runpy.run_path(str(Path('config/config.py')))
    assert config['LINE_NAME'] == expected
    assert 'LINE_ID' not in config


def test_copied_foreign_tagid_is_not_subscribed(app, database, monkeypatch):
    monkeypatch.setattr(app,'LINE_NAME','SB11')
    database.db.execute('UPDATE dbo.Alarm_Lists SET TagId=2 WHERE AlarmId=1')
    assert app.load_alarm_mapping() == []


@pytest.mark.parametrize("line", ["SB11", "SB12", ""])
def test_runtime_and_startup_expose_line(monkeypatch, capsys, line):
    monkeypatch.setattr("config.config.LINE_NAME", line)
    with patch("pygame.mixer.init"), patch("threading.Thread.start"):
        spec = importlib.util.spec_from_file_location("status_test_app", "alarm_sound_v11.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    assert json.loads(json.dumps(asdict(module.runtime_status)))["line_name"] == (line or None)
    # Stop before any real OPC or SQL connection.
    with patch.object(module, "Client", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(module.main())
    assert f"LINE_NAME = {line or '(legacy: unset)'}" in capsys.readouterr().out
