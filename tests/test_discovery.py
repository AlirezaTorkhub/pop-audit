from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "zabbix-service"))

from app.discovery import (  # noqa: E402
    SiteDiscovery,
    detect_device_type,
    infer_radio_type,
    parse_direction,
    related_site_codes,
)


def host(hostid: str, name: str, *, groups=None, templates=None, ip="10.0.0.1"):
    return {
        "hostid": hostid,
        "host": name,
        "name": name,
        "status": "0",
        "description": "",
        "interfaces": [{
            "interfaceid": "1",
            "ip": ip,
            "dns": "",
            "type": "1",
            "main": "1",
            "port": "10050",
        }],
        "groups": [{"groupid": str(i), "name": value} for i, value in enumerate(groups or [])],
        "parentTemplates": [{"templateid": str(i), "name": value} for i, value in enumerate(templates or [])],
    }


def test_baseband_related_codes_match_alternate_first_digit():
    codes = related_site_codes("2244")
    assert "2244" in codes
    assert "3244" in codes
    assert "7244" in codes
    assert "8244" in codes


def test_radio_direction_includes_only_requested_site_as_source():
    outgoing = parse_direction("Gandi-2213-To-Harat-950-Huawei", "2213")
    incoming = parse_direction("Harat-950-To-Gandi-2213-Huawei", "2213")

    assert outgoing[0] == "2213"
    assert outgoing[1] == "950"
    assert incoming[0] is None


def test_radio_type_aliases_are_normalized():
    assert infer_radio_type("Gandi-2213-To-Harat-950-Huawei") == "RTN"
    assert infer_radio_type("Gandi-2213-To-POP-EBand") == "EBand"
    assert infer_radio_type("Gandi-2213-To-POP-Intracome") == "Intracom"
    assert infer_radio_type("Gandi-2213-To-POP-NRays") == "NRay"


def test_ncs_group_is_classified_before_generic_switch():
    candidate = host(
        "ncs-1",
        "TH-BH-NCS-Gandi-Agg",
        groups=["LTE-Backhaul-Switch-Aggregation"],
    )
    assert detect_device_type(candidate) == ("Cisco", "ncs540")


class FakeZabbix:
    def __init__(self, groups):
        self.groups = groups

    def login(self):
        return "authenticated"

    def get_group_by_name(self, name):
        if name not in self.groups:
            return None
        return {"groupid": name, "name": name}

    def get_hosts_by_group(self, group_id):
        return self.groups.get(group_id, [])


def test_full_discovery_finds_bb2_ncs_and_only_outgoing_radios(monkeypatch):
    groups = {
        "LTE-Backhaul-eNodeB": [
            host("bb1", "Gandi-2244-eNodeB", groups=["LTE-Backhaul-eNodeB"]),
            host("bb2", "Gandi-3244-eNodeB", groups=["LTE-Backhaul-eNodeB"], ip="10.0.0.2"),
        ],
        "LTE-Backhaul-Switch": [
            host("sw1", "TH-BH-SW-2244-Gandi", groups=["LTE-Backhaul-Switch"], templates=["Cisco IOS"]),
        ],
        "LTE-Backhaul-Switch-Aggregation": [
            host("ncs1", "TH-BH-NCS-Gandi-Agg", groups=["LTE-Backhaul-Switch-Aggregation"]),
        ],
        "LTE-Backhaul-Radio": [
            host("eb1", "Gandi-2244-To-POP-EBand", groups=["LTE-Backhaul-Radio"]),
            host("incoming", "Harat-950-To-Gandi-2244-Huawei", groups=["LTE-Backhaul-Radio"]),
        ],
        "LTE-Backhaul-Radio-Huawei": [
            host("rtn1", "Gandi-2244-To-Harat-950-Huawei", groups=["LTE-Backhaul-Radio-Huawei"]),
        ],
    }

    discovery = SiteDiscovery()
    discovery.client = FakeZabbix(groups)
    result = discovery.discover("2244")

    assert [bb.role for bb in result.basebands] == ["BB1", "BB2"]
    assert [bb.zabbix_hostid for bb in result.basebands] == ["bb1", "bb2"]
    assert result.site_identity == "GANDI"

    ncs = [device for device in result.devices if device.device_type == "ncs540"]
    assert len(ncs) == 1
    assert ncs[0].hostname == "TH-BH-NCS-Gandi-Agg"

    radio_ids = {link.zabbix_hostid for link in result.radio_links}
    assert radio_ids == {"eb1", "rtn1"}
    assert "incoming" not in radio_ids
    assert {link.link_type for link in result.radio_links} == {"EBand", "RTN"}


def test_full_discovery_marks_missing_bb2_without_inventing_device():
    groups = {
        "LTE-Backhaul-eNodeB": [
            host("bb1", "Gandi-2244-eNodeB", groups=["LTE-Backhaul-eNodeB"]),
        ],
        "LTE-Backhaul-Switch": [
            host("sw1", "TH-BH-SW-2244-Gandi", groups=["LTE-Backhaul-Switch"], templates=["Cisco IOS"]),
        ],
        "LTE-Backhaul-Switch-Aggregation": [],
        "LTE-Backhaul-Radio": [],
        "LTE-Backhaul-Radio-Huawei": [],
    }
    discovery = SiteDiscovery()
    discovery.client = FakeZabbix(groups)
    result = discovery.discover("2244")

    assert len(result.basebands) == 1
    assert result.basebands[0].role == "BB1"
    assert not any(bb.role == "BB2" for bb in result.basebands)
