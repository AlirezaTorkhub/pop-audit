from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cisco-service" / "app" / "main.py"

spec = importlib.util.spec_from_file_location("pop_audit_cisco", SOURCE)
cisco = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(cisco)


def test_ncs_interface_description_parser_extracts_states_and_descriptions():
    output = """Interface                      Status          Protocol    Description
GigabitEthernet0/0/0/0          up              up           Uplink to POP
GigabitEthernet0/0/0/1          down            down         Backup link
"""
    parsed = cisco.parse_ncs_interfaces_description(output)

    assert len(parsed) == 2
    assert parsed[0]["interface"] == "GigabitEthernet0/0/0/0"
    assert parsed[0]["health"] == "PASS"
    assert parsed[0]["description"] == "Uplink to POP"
    assert parsed[1]["health"] == "WARNING"


def test_ncs_profile_never_uses_ios_interface_status_command():
    assert "show interfaces description" in cisco.NCS_COMMANDS
    assert "show interfaces" in cisco.NCS_COMMANDS
    assert "show logging last 10" in cisco.NCS_COMMANDS
    assert "show interfaces status" not in cisco.NCS_COMMANDS


def test_ncs_audit_uses_ios_xr_driver_and_reports_crc(monkeypatch):
    calls = []

    class FakeConnection:
        def send_command(self, command, **kwargs):
            calls.append(("setup", command))
            return ""

        def disconnect(self):
            calls.append(("disconnect", None))

    def fake_connect(ip, device_type="cisco_ios"):
        calls.append(("connect", device_type))
        return FakeConnection()

    description = (
        "Interface                      Status          Protocol    Description\n"
        "GigabitEthernet0/0/0/0          up              up           Uplink to POP\n"
    )
    detail = (
        "GigabitEthernet0/0/0/0 is up, line protocol is up\n"
        "  Hardware is GigabitEthernet, address is 0011.2233.4455\n"
        "  MTU 1514 bytes, BW 1000000 Kbit/sec\n"
        "  2 input errors, 3 CRC\n"
        "  4 output errors, 0 output drops\n"
    )
    output_by_command = {
        "show version": "Cisco IOS XR Software, Version 7.0",
        "show inventory": "",
        "show interfaces description": description,
        "show interfaces": detail,
        "show logging last 10": "%SYS-3-ERROR: simulated error\n%SYS-6-INFO: simulated event",
    }

    def fake_run(connection, command):
        calls.append(("command", command))
        return {
            "status": "PASS",
            "command": command,
            "output": output_by_command.get(command, ""),
        }

    monkeypatch.setattr(cisco, "connect_device", fake_connect)
    monkeypatch.setattr(cisco, "run_command", fake_run)

    result = cisco.audit_ncs_device({
        "hostname": "TH-BH-NCS-Gandi-Agg",
        "ip": "192.0.2.10",
        "zabbix_hostid": "ncs-test",
        "device_type": "ncs540",
        "role": "ncs_aggregation",
    })

    command_names = [entry[1] for entry in calls if entry[0] == "command"]
    assert ("connect", "cisco_xr") in calls
    assert "show interfaces description" in command_names
    assert "show interfaces" in command_names
    assert "show logging last 10" in command_names
    assert "show interfaces status" not in command_names

    interface_check = result["checks"]["interfaces"]
    assert interface_check["problems"]["crc_count"] == 1
    assert interface_check["problems"]["crc"][0]["crc"] == 3
    assert result["checks"]["logging"]["event_count"] == 2
    assert result["checks"]["logging"]["status"] == "CRITICAL"


def test_missing_crc_is_unknown_not_zero():
    output = "GigabitEthernet0/0/0/0 is up, line protocol is up\n  2 input errors"
    parsed = cisco.parse_interfaces_detail(output)
    assert parsed
    assert parsed[0]["crc"] is None
