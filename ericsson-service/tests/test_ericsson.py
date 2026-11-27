import app.main as ericsson


def test_cell_parser_requires_unlocked_and_enabled_states():
    parsed = ericsson.parse_cells(
        "1 1 (UNLOCKED) 1 (ENABLED) EUtranCellFDD=cell-1\n"
        "2 0 (LOCKED) 0 (DISABLED) EUtranCellFDD=cell-2\n"
    )
    assert parsed["count"] == 2
    assert parsed["status"] == "WARNING"
    assert [cell["status"] for cell in parsed["cells"]] == ["PASS", "WARNING"]
    assert ericsson.parse_cells("unparseable").get("status") == "UNKNOWN"


def test_only_door_and_power_cooling_alarm_families_affect_field_health():
    unrelated = ericsson.parse_alarms(
        "2026-11-27 10:00:00 C License Key File Fault\n"
    )
    assert unrelated["status"] == "PASS"
    assert unrelated["ignored_count"] == 1

    door = ericsson.parse_alarms(
        "2026-11-27 10:00:00 C Door Open Alarm\n"
    )
    assert door["status"] == "CRITICAL"
    assert door["relevant_count"] == 1

    power = ericsson.parse_alarms(
        "2026-11-27 10:00:00 w AC Power Supply Warning\n"
    )
    assert power["status"] == "WARNING"


def test_radio_clock_requires_exact_locked_state():
    assert ericsson.parse_clock("radioClockState 6 (RNT_TIME_LOCKED)")["status"] == "PASS"
    assert ericsson.parse_clock("radioClockState 5 (HOLDOVER)")["status"] == "WARNING"
    assert ericsson.parse_clock("missing")["status"] == "NOT_AVAILABLE"


def test_moshell_command_order_is_preserved(monkeypatch):
    class FakeChannel:
        def __init__(self):
            self.sent = []

        def settimeout(self, value):
            pass

        def send(self, value):
            self.sent.append(value.strip())

        def recv_ready(self):
            return False

    class FakeSSH:
        def __init__(self):
            self.channel = FakeChannel()

        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kwargs):
            pass

        def invoke_shell(self):
            return self.channel

        def close(self):
            pass

    fake_ssh = FakeSSH()
    monkeypatch.setattr(ericsson.paramiko, "SSHClient", lambda: fake_ssh)
    monkeypatch.setattr(ericsson.paramiko, "AutoAddPolicy", lambda: object())
    monkeypatch.setattr(ericsson.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ericsson, "MOSHELL_HOST", "moshell.example.invalid")
    monkeypatch.setattr(ericsson, "MOSHELL_USER", "test-user")
    monkeypatch.setattr(ericsson, "MOSHELL_PASSWORD", "test-password")
    monkeypatch.setattr(ericsson, "MOSHELL_PATH", "/opt/moshell/moshell")

    ericsson.run_moshell_session("192.0.2.20")
    commands = fake_ssh.channel.sent
    ordered = ["lt all", "st cel", "alt", "get . clock", "q"]
    positions = [commands.index(command) for command in ordered]
    assert positions == sorted(positions)
