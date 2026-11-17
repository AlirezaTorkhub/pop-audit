from __future__ import annotations

import sys
import unittest
from pathlib import Path

from openpyxl import Workbook

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.main import build_cisco  # noqa: E402


class CiscoLogsWorksheetTests(unittest.TestCase):
    def test_keeps_devices_with_same_ip_separate_by_zabbix_host_id(self):
        event_a = {
            "timestamp": "*Nov 17 10:00:01.000",
            "severity": "INFO",
            "facility": "SYS",
            "mnemonic": "CONFIG_I",
            "message": "synthetic event alpha",
            "raw": "*Nov 17 10:00:01.000: %SYS-6-CONFIG_I: synthetic event alpha",
        }
        event_b = {
            "timestamp": "*Nov 17 10:00:02.000",
            "severity": "WARNING",
            "facility": "LINK",
            "mnemonic": "UPDOWN",
            "message": "synthetic event beta",
            "raw": "*Nov 17 10:00:02.000: %LINK-4-UPDOWN: synthetic event beta",
        }

        result = {
            "results": [
                {
                    "hostname": "Switch-Alpha",
                    "ip": "192.0.2.10",
                    "zabbix_hostid": "10001",
                    "status": "PASS",
                    "checks": {
                        "logging": {"status": "PASS", "recent_10": [event_a]},
                    },
                    "raw_commands": {"show logging": {"status": "PASS"}},
                },
                {
                    "hostname": "Switch-Beta",
                    "ip": "192.0.2.10",
                    "zabbix_hostid": "10002",
                    "status": "WARNING",
                    "checks": {
                        "logging": {"status": "PASS", "recent_10": [event_b]},
                    },
                    "raw_commands": {"show logging": {"status": "PASS"}},
                },
            ]
        }

        workbook = Workbook()
        build_cisco(workbook, result)

        worksheet = workbook["Cisco Logs"]
        rows = list(worksheet.iter_rows(min_row=2, values_only=True))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2], "10001")
        self.assertEqual(rows[1][2], "10002")
        self.assertEqual(rows[0][1], rows[1][1])
        self.assertEqual(rows[0][8], "synthetic event alpha")
        self.assertEqual(rows[1][8], "synthetic event beta")


if __name__ == "__main__":
    unittest.main()
