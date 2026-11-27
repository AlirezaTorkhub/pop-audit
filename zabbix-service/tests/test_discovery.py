from app.discovery import SiteDiscovery


def host(hostid, name, ip, groups):
    return {
        "hostid": str(hostid),
        "host": name,
        "name": name,
        "description": "",
        "interfaces": [{
            "interfaceid": str(hostid),
            "ip": ip,
            "dns": "",
            "type": "1",
            "main": "1",
            "port": "10050",
        }],
        "groups": [{"groupid": str(group), "name": group} for group in groups],
        "parentTemplates": [],
        "inventory": {},
    }


class FakeZabbix:
    def __init__(self, group_hosts):
        self.group_hosts = group_hosts
        self.login_called = False

    def login(self):
        self.login_called = True

    def get_group_by_name(self, name):
        return {"groupid": name, "name": name} if name in self.group_hosts else None

    def get_hosts_by_group(self, groupid):
        return self.group_hosts[groupid]


def test_discovery_selects_exact_bb1_and_last_three_digit_bb2_and_outgoing_radio_only():
    bb_group = "LTE-Backhaul-eNodeB"
    switch_group = "LTE-Backhaul-Switch"
    ncs_group = "LTE-Backhaul-Switch-Aggregation"
    radio_group = "LTE-Backhaul-Radio"
    huawei_group = "LTE-Backhaul-Radio-Huawei"

    group_hosts = {
        bb_group: [
            host("bb1", "Bijan-2488-eNodeB", "10.0.0.1", [bb_group]),
            host("bb2", "Bijan-7488-eNodeB", "10.0.0.2", [bb_group]),
        ],
        switch_group: [
            host("sw1", "Bijan-2488-TTH-BH-SW-1", "10.0.1.1", [switch_group]),
        ],
        ncs_group: [
            host("ncs1", "Bijan-NCS540-Aggregation", "10.0.1.2", [ncs_group]),
        ],
        radio_group: [
            host("eb1", "Bijan-2488-To-Kurosh-EBand", "10.0.2.1", [radio_group]),
            host("incoming", "Kurosh-2357-To-Bijan-2488-EBand", "10.0.2.2", [radio_group]),
            host("ic1", "Bijan-2488-To-Kurosh-Intracom", "10.0.2.3", [radio_group]),
            host("nr1", "Bijan-2488-To-Kurosh-NRay", "10.0.2.4", [radio_group]),
        ],
        huawei_group: [
            host("rtn1", "Bijan-2488-To-Kurosh-Huawei-RTN", "10.0.2.5", [huawei_group]),
        ],
    }

    client = FakeZabbix(group_hosts)
    result = SiteDiscovery(client).discover("2488")

    assert client.login_called
    assert [item.name for item in result.basebands] == ["BB1", "BB2"]
    assert [item.zabbix_hostid for item in result.basebands] == ["bb1", "bb2"]
    assert result.devices[0].zabbix_hostid == "sw1"
    assert result.ncs_devices[0].zabbix_hostid == "ncs1"
    assert result.ncs_status == "UNKNOWN"
    assert {item.link_type for item in result.radio_links} == {
        "EBAND", "RTN", "INTRACOM", "NRAY"
    }
    assert "incoming" not in {item.zabbix_hostid for item in result.radio_links}


def test_non_exact_four_digit_candidate_is_bb2_not_bb1():
    bb_group = "LTE-Backhaul-eNodeB"
    group_hosts = {
        bb_group: [
            host("bb2", "Bijan-7488-eNodeB", "10.0.0.2", [bb_group]),
        ],
        "LTE-Backhaul-Switch": [],
        "LTE-Backhaul-Switch-Aggregation": [],
        "LTE-Backhaul-Radio": [],
        "LTE-Backhaul-Radio-Huawei": [],
    }
    result = SiteDiscovery(FakeZabbix(group_hosts)).discover("2488")
    assert result.basebands[0].name == "BB1"
    assert result.basebands[0].exists is False
    assert result.basebands[0].status == "NOT_EXISTS"
    assert result.basebands[1].name == "BB2"
    assert result.basebands[1].zabbix_hostid == "bb2"


def test_missing_required_baseband_group_is_not_reported_as_missing_hardware():
    result = SiteDiscovery(FakeZabbix({
        "LTE-Backhaul-Switch": [],
        "LTE-Backhaul-Switch-Aggregation": [],
        "LTE-Backhaul-Radio": [],
        "LTE-Backhaul-Radio-Huawei": [],
    })).discover("2488")
    assert [item.status for item in result.basebands] == [
        "NOT_AVAILABLE", "NOT_AVAILABLE"
    ]
