from __future__ import annotations

import importlib.util
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "report-service" / "app" / "main.py"

spec = importlib.util.spec_from_file_location("pop_audit_report", SOURCE)
report = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(report)


def test_workbook_contains_unified_links_ncs_crc_and_latest_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)

    results = {
        "cisco": {
            "status": "COMPLETED",
            "data": {
                "status": "WARNING",
                "results": [
                    {
                        "hostname": "TH-BH-SW-2213-Gandi",
                        "ip": "192.0.2.11",
                        "zabbix_hostid": "sw-1",
                        "device_type": "switch",
                        "role": "primary_switch",
                        "status": "WARNING",
                        "checks": {
                            "interfaces": {
                                "status": "WARNING",
                                "data": [{
                                    "interface": "Gi1/0/1",
                                    "description": "Uplink",
                                    "health": "WARNING",
                                    "crc": 4,
                                    "input_errors": 4,
                                    "output_errors": 0,
                                }],
                            },
                            "logging": {
                                "status": "WARNING",
                                "latest": ["%LINK-4-STATE: link state changed"],
                            },
                        },
                    },
                    {
                        "hostname": "TH-BH-NCS-Gandi-Agg",
                        "ip": "192.0.2.12",
                        "zabbix_hostid": "ncs-1",
                        "device_type": "ncs540",
                        "role": "ncs_aggregation",
                        "status": "PASS",
                        "checks": {
                            "interfaces": {
                                "status": "PASS",
                                "data": [{
                                    "interface": "Gi0/0/0/0",
                                    "description": "Uplink",
                                    "health": "PASS",
                                    "crc": 0,
                                    "input_errors": 0,
                                    "output_errors": 0,
                                }],
                            },
                            "logging": {
                                "status": "PASS",
                                "latest": ["%SYS-6-INFO: NCS event"],
                            },
                        },
                    },
                ],
            },
        },
        "ericsson": {
            "status": "COMPLETED",
            "data": {
                "status": "WARNING",
                "results": [
                    {
                        "hostname": "Gandi-2213-eNodeB",
                        "role": "BB1",
                        "ip": "192.0.2.21",
                        "status": "WARNING",
                        "checks": {
                            "lt_all": {"status": "PASS"},
                            "cells": {"status": "PASS", "count": 9},
                            "clock": {"status": "PASS", "state": "RNT_TIME_LOCKED", "value": 6},
                            "door_alarm": {"status": "PASS", "count": 0},
                            "ac_alarm": {"status": "WARNING", "count": 1},
                            "alarms": {"status": "WARNING", "total": 1, "critical": 0, "major": 0, "alarms": []},
                        },
                    },
                    {
                        "hostname": "Gandi-3213-eNodeB",
                        "role": "BB2",
                        "ip": "192.0.2.22",
                        "status": "PASS",
                        "checks": {
                            "lt_all": {"status": "PASS"},
                            "cells": {"status": "PASS", "count": 9},
                            "clock": {"status": "PASS", "state": "RNT_TIME_LOCKED", "value": 6},
                            "door_alarm": {"status": "PASS", "count": 0},
                            "ac_alarm": {"status": "PASS", "count": 0},
                            "alarms": {"status": "PASS", "total": 0, "critical": 0, "major": 0, "alarms": []},
                        },
                    },
                ],
            },
        },
        "radio": {
            "status": "COMPLETED",
            "data": {
                "status": "WARNING",
                "links": [
                    {
                        "link_type": "EBand",
                        "name": "Gandi-2213-To-Harat-EBand",
                        "status": "PASS",
                        "analysis": {
                            "status": "PASS",
                            "checks": {
                                "difference": {
                                    "slots": [{
                                        "slot": 1,
                                        "rx": {"value": -42},
                                        "tx": {"value": -45},
                                        "difference": {"value": 3.0, "status": "PASS"},
                                    }],
                                },
                            },
                        },
                    },
                    {
                        "link_type": "RTN",
                        "name": "Gandi-2213-To-Harat-Huawei",
                        "status": "WARNING",
                        "analysis": {
                            "status": "WARNING",
                            "links": [{
                                "destination": "HARAT",
                                "status": "WARNING",
                                "modulation": [{
                                    "value": 128,
                                    "clock": 1800000000,
                                    "status": "WARNING",
                                    "history_comparison": {
                                        "maximum": 256,
                                        "reason": "Current below historical maximum",
                                    },
                                }],
                            }],
                        },
                    },
                    {
                        "link_type": "Intracom",
                        "name": "Gandi-2213-To-POP-Intracom",
                        "status": "PASS",
                        "analysis": {
                            "status": "PASS",
                            "rx": [{"direction": "RX", "value": 100000, "units": "bps", "timestamp": 1800000000}],
                            "tx": [{"direction": "TX", "value": 200000, "units": "bps", "timestamp": 1800000000}],
                        },
                    },
                    {
                        "link_type": "NRay",
                        "name": "Gandi-2213-To-POP-NRay",
                        "status": "PASS",
                        "analysis": {
                            "status": "PASS",
                            "rx": [{"direction": "RX", "value": 300000, "units": "bps", "timestamp": 1800000000}],
                            "tx": [{"direction": "TX", "value": 400000, "units": "bps", "timestamp": 1800000000}],
                        },
                    },
                ],
            },
        },
    }

    output, overall = report.create_workbook("2213", results)
    assert output.exists()
    assert overall == "WARNING"

    workbook = load_workbook(output, data_only=True)
    assert "Links" in workbook.sheetnames
    assert "Basebands" in workbook.sheetnames
    assert "NCS 540" in workbook.sheetnames
    assert "Switch Problems" in workbook.sheetnames
    assert "Switch Logs" in workbook.sheetnames
    assert "Capacity Health" not in workbook.sheetnames

    links = workbook["Links"]
    values = list(links.values)
    types = {row[0] for row in values[1:]}
    assert {"EBand", "RTN", "Intracom", "NRay"}.issubset(types)

    numeric_values = [cell.value for row in links.iter_rows() for cell in row if isinstance(cell.value, (int, float))]
    assert 3.0 in numeric_values
    assert 128 in numeric_values
    assert 256 in numeric_values
    assert 100000 in numeric_values
    assert 400000 in numeric_values

    basebands = workbook["Basebands"]
    roles = {row[0] for row in basebands.iter_rows(min_row=2, values_only=True)}
    assert {"BB1", "BB2"}.issubset(roles)

    ncs_names = {row[0] for row in workbook["NCS 540"].iter_rows(min_row=2, values_only=True)}
    assert "TH-BH-NCS-Gandi-Agg" in ncs_names

    problem_rows = list(workbook["Switch Problems"].iter_rows(min_row=2, values_only=True))
    assert len(problem_rows) == 1
    assert problem_rows[0][5] == 4

    log_rows = list(workbook["Switch Logs"].iter_rows(min_row=2, values_only=True))
    assert len(log_rows) == 2
