from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.main import logging_command_for_device, parse_logging  # noqa: E402


class ParseLoggingTests(unittest.TestCase):
    def test_ncs_uses_last_ten_logging_command(self):
        self.assertEqual(
            logging_command_for_device({"device_type": "ncs"}),
            "show logging last 10",
        )
        self.assertEqual(
            logging_command_for_device({"device_type": "NCS"}),
            "show logging last 10",
        )

    def test_non_ncs_keeps_full_logging_command(self):
        self.assertEqual(
            logging_command_for_device({"device_type": "switch"}),
            "show logging",
        )
        self.assertEqual(
            logging_command_for_device({}),
            "show logging",
        )

    def test_returns_latest_ten_syslog_events_newest_first(self):
        lines = [
            "Syslog logging: enabled",
            "Log Buffer (4096 bytes):",
        ]
        for number in range(1, 13):
            lines.append(
                f"*Nov 17 10:00:{number:02d}.000: "
                f"%SYS-6-TEST_EVENT: synthetic event {number}"
            )

        result = parse_logging("\n".join(lines))

        self.assertEqual(len(result["recent_10"]), 10)
        self.assertEqual(
            result["recent_10"][0]["message"],
            "synthetic event 12",
        )
        self.assertEqual(
            result["recent_10"][-1]["message"],
            "synthetic event 3",
        )
        self.assertEqual(
            result["recent_10"][0]["timestamp"],
            "*Nov 17 10:00:12.000",
        )
        self.assertEqual(result["severity_counts"]["INFO"], 12)
        self.assertEqual(result["recent_20"][-1].endswith("synthetic event 12"), True)

    def test_extracts_facility_severity_and_mnemonic(self):
        result = parse_logging(
            "*Nov 17 10:00:01.000: %LINK-3-UPDOWN: Interface Gi1/0/1 changed state"
        )

        event = result["recent_10"][0]
        self.assertEqual(event["facility"], "LINK")
        self.assertEqual(event["severity"], "ERROR")
        self.assertEqual(event["level"], 3)
        self.assertEqual(event["mnemonic"], "UPDOWN")
        self.assertEqual(result["status"], "WARNING")

    def test_ignores_non_syslog_banner_lines(self):
        result = parse_logging(
            "Syslog logging: enabled\n"
            "Console logging: disabled\n"
            "Log Buffer (4096 bytes):"
        )

        self.assertEqual(result["recent_10"], [])
        self.assertTrue(result["recent_20"])


if __name__ == "__main__":
    unittest.main()
