from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ericsson-service" / "app" / "main.py"

spec = importlib.util.spec_from_file_location("pop_audit_ericsson", SOURCE)
ericsson = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(ericsson)


def test_door_and_ac_alarm_categories_are_separated():
    alarm_result = {
        "parsed": True,
        "total": 3,
        "alarms": [
            {
                "problem": "Door Open Alarm",
                "additional_text": "Cabinet door 1",
                "raw": "Door Open Alarm",
                "severity": "WARNING",
            },
            {
                "problem": "AC Mains Failure",
                "additional_text": "Rectifier input",
                "raw": "AC Mains Failure",
                "severity": "CRITICAL",
            },
            {
                "problem": "MAC Address Change",
                "additional_text": "Switch port event",
                "raw": "MAC Address Change",
                "severity": "MINOR",
            },
        ],
    }

    door = ericsson.parse_alarm_category(
        alarm_result,
        r"\bdoor\b|door.?open|cabinet.?door",
        "Door",
    )
    ac = ericsson.parse_alarm_category(
        alarm_result,
        r"\bAC\b|alternating current|rectifier|power supply|power system|mains|utility power",
        "AC",
    )

    assert door["status"] == "WARNING"
    assert door["count"] == 1
    assert ac["status"] == "CRITICAL"
    assert ac["count"] == 1


def test_mac_alarm_is_not_misclassified_as_ac():
    alarm_result = {
        "parsed": True,
        "total": 1,
        "alarms": [{
            "problem": "MAC Address Change",
            "additional_text": "Port event",
            "raw": "MAC Address Change",
            "severity": "MINOR",
        }],
    }
    ac = ericsson.parse_alarm_category(
        alarm_result,
        r"\bAC\b|alternating current|rectifier|power supply|power system|mains|utility power",
        "AC",
    )
    assert ac["status"] == "PASS"
    assert ac["count"] == 0


def test_unparseable_alarm_output_is_not_healthy():
    door = ericsson.parse_alarm_category(
        {"parsed": False, "total": None, "alarms": []},
        r"\bdoor\b",
        "Door",
    )
    assert door["status"] == "NOT_AVAILABLE"
