import app.main as cisco


def test_ios_interface_missing_counters_remain_unknown_not_zero():
    output = """GigabitEthernet1/0/1 is up, line protocol is up
  Hardware is Gigabit Ethernet
  MTU 1500 bytes, BW 1000000 Kbit/sec
"""
    parsed = cisco.parse_interfaces_detail(output)
    assert len(parsed) == 1
    assert parsed[0]["crc"] is None
    assert parsed[0]["input_errors"] is None
    assert parsed[0]["output_errors"] is None


def test_interface_states_and_speed_mismatch():
    assert cisco.classify_interface({
        "interface": "Gi1/0/1", "status_raw": "disabled"
    })["health"] == "PASS"
    assert cisco.classify_interface({
        "interface": "Gi1/0/1", "status_raw": "notconnect"
    })["health"] == "WARNING"
    assert cisco.is_expected_speed("GigabitEthernet1/0/1", "a-100") is False
    assert cisco.is_expected_speed("GigabitEthernet1/0/1", "a-1000") is True


def test_syslog_critical_and_warning_severity_are_not_inverted():
    critical = cisco.parse_logging("%SYS-3-ERROR: hardware failure\n")
    warning = cisco.parse_logging("%LINK-4-UPDOWN: interface warning\n")
    assert critical["status"] == "CRITICAL"
    assert critical["recent_10"]
    assert warning["status"] == "WARNING"


def test_ncs_uses_ios_xr_specific_commands(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.commands = []

        def send_command(self, command, **kwargs):
            self.commands.append(command)
            if command == "show interfaces description":
                return (
                    "Interface Status Protocol Description\n"
                    "GigabitEthernet0/0/0/0 up up Uplink-to-PE\n"
                )
            if command == "show interfaces":
                return (
                    "GigabitEthernet0/0/0/0 is up, line protocol is up\n"
                    "  Hardware is GigabitEthernet\n"
                    "  Description: Uplink-to-PE\n"
                    "  MTU 1514 bytes, BW 1000000 Kbit/sec\n"
                    "  0 input errors, 0 CRC, 0 frame\n"
                    "  0 output errors, 0 output drops\n"
                )
            if command == "show logging last 10":
                return "%SYS-6-INFO: NCS operational\n"
            return ""

        def disconnect(self):
            pass

    fake = FakeConnection()
    monkeypatch.setattr(cisco, "connect_device", lambda ip, device_type="cisco_ios": fake)
    result = cisco.audit_ncs_device({
        "hostname": "Bijan-NCS540",
        "ip": "192.0.2.10",
        "zabbix_hostid": "ncs-1",
    })
    assert result["device_type"] == "ncs540"
    assert result["checks"]["interfaces"]["count"] == 1
    assert "show interfaces description" in fake.commands
    assert "show interfaces" in fake.commands
    assert "show logging last 10" in fake.commands
    assert "show interfaces status" not in fake.commands
