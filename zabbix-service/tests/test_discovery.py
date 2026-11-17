import os
import unittest
from unittest.mock import patch

from app.discovery import (
    SiteDiscovery,
    infer_radio_type,
    is_host_enabled,
    matches_baseband_site_code,
    parse_direction,
)


class InferRadioTypeTests(unittest.TestCase):
    def test_canonical_radio_types(self):
        cases = {
            "Bijan-2488-To-Kurosh-EBand": "EBand",
            "Bijan-2488-To-Bolvar-RTN": "RTN",
            "TH-BH-2488-NRay": "NRay",
            "TH-BH-2488-NRays": "NRay",
            "TH-BH-2488-Intracom": "Intracom",
            "TH-BH-2488-Intracome": "Intracom",
            "unrecognized-radio-host": "Unknown",
        }

        for hostname, expected in cases.items():
            with self.subTest(hostname=hostname):
                self.assertEqual(infer_radio_type(hostname), expected)

    def test_outgoing_link_direction(self):
        source, destination, destination_name = parse_direction(
            "Bijan-2488-To-BolvarShahrzad-980A-Huawei",
            "2488",
        )

        self.assertEqual(source, "2488")
        self.assertEqual(destination, "980")
        self.assertIn("BolvarShahrzad", destination_name)


    def test_realistic_host_patterns(self):
        # Anonymized host patterns based on the supplied Zabbix host-search export.
        cases = {
            "SiteAlpha-1234-To-NodeBeta-Eband": "EBand",
            "SiteAlpha-1234-To-NodeGamma-Intracom": "Intracom",
            "SiteAlpha-1234-To-NodeDelta-Intracom": "Intracom",
            "SiteAlpha-1234-To-NodeEpsilon-Eband": "EBand",
            "SiteAlpha-1234-To-NodeZeta-Intracom": "Intracom",
            "SiteAlpha-1234-To-NodeEta-EBand": "EBand",
            "SiteAlpha-1234-To-NodeTheta-380-Huawei": "RTN",
            "SiteAlpha-1234-To-NodeIota-EBand-II": "EBand",
            "SiteAlpha-1234-To-NodeKappa-Intracom": "Intracom",
            "SiteAlpha-1234-to-NodeLambda-950-Huawei": "RTN",
            "SiteAlpha-1234-To-NodeMu-DW": "Unknown",
        }

        for hostname, expected in cases.items():
            with self.subTest(hostname=hostname):
                self.assertEqual(infer_radio_type(hostname), expected)

    def test_anonymized_outgoing_and_incoming_direction(self):
        outgoing = parse_direction(
            "SiteAlpha-1234-to-NodeLambda-950-Huawei",
            "1234",
        )
        incoming = parse_direction(
            "NodeGamma-2203-To-SiteAlpha-DW",
            "1234",
        )

        self.assertEqual(outgoing[0], "1234")
        self.assertEqual(outgoing[1], "950")
        self.assertIsNone(incoming[0])



class DiscoveryRuleTests(unittest.TestCase):
    def test_disabled_and_unknown_status_hosts_are_excluded(self):
        self.assertTrue(is_host_enabled({"status": "0"}))
        self.assertTrue(is_host_enabled({"status": 0}))
        self.assertFalse(is_host_enabled({"status": "1"}))
        self.assertFalse(is_host_enabled({"status": 1}))
        self.assertFalse(is_host_enabled({}))

    def test_secondary_baseband_uses_same_last_three_digits(self):
        self.assertTrue(matches_baseband_site_code("SiteAlpha-1234-eNodeB", "1234"))
        self.assertTrue(matches_baseband_site_code("SiteAlpha-7234-eNodeB", "1234"))
        self.assertFalse(matches_baseband_site_code("SiteAlpha-2235-eNodeB", "1234"))
        self.assertFalse(matches_baseband_site_code("SiteAlpha-12345-eNodeB", "1234"))
        self.assertFalse(matches_baseband_site_code("SiteAlpha-234-eNodeB", "1234"))

    def test_discovery_filters_disabled_hosts_and_keeps_distinct_ncs(self):
        def make_host(hostid, name, status, ip, groups=None, templates=None, inventory=None):
            return {
                "hostid": str(hostid),
                "host": name,
                "name": name,
                "status": str(status),
                "description": "",
                "interfaces": [
                    {
                        "interfaceid": str(hostid),
                        "ip": ip,
                        "dns": "",
                        "type": "1",
                        "main": "1",
                        "port": "10050",
                    }
                ],
                "groups": [{"name": value} for value in (groups or [])],
                "parentTemplates": [
                    {"name": value} for value in (templates or [])
                ],
                "inventory": inventory or {},
            }

        basebands = [
            make_host("bb-primary", "SiteAlpha-1234-eNodeB", 0, "10.0.0.1"),
            make_host("bb-secondary", "SiteAlpha-7234-eNodeB", 0, "10.0.0.2"),
            make_host("bb-disabled", "SiteAlpha-6234-eNodeB", 1, "10.0.0.3"),
        ]
        switches = [
            make_host(
                "switch-disabled",
                "TH-BH-SW-1234-SiteAlpha",
                1,
                "10.0.0.10",
                ["LTE-Backhaul-Switch"],
                ["FDI Cisco SW"],
                {"location": "SiteAlpha"},
            ),
            make_host(
                "switch-active",
                "TH-BH-SW-1234-SiteAlpha-II",
                0,
                "10.0.0.10",
                ["LTE-Backhaul-Switch"],
                ["FDI Cisco SW"],
                {"location": "SiteAlpha"},
            ),
        ]
        aggregation = [
            make_host(
                "ncs-active",
                "TH-BH-NCS-SiteAlpha-Agg",
                0,
                "10.0.0.10",
                ["Backbone", "LTE-Backhaul-Switch-Aggregation", "ptp"],
                ["FDI Cisco SW", "Cisco-PTP-Only", "Template Temperature NCS"],
                {"location": "SiteAlpha"},
            ),
            make_host(
                "ncs-disabled",
                "TH-BH-NCS-SiteAlpha-Old",
                1,
                "10.0.0.11",
                ["LTE-Backhaul-Switch-Aggregation"],
                ["FDI Cisco SW", "Template Temperature NCS"],
                {"location": "SiteAlpha"},
            ),
            make_host(
                "ncs-other-site",
                "TH-BH-NCS-SiteBeta-Agg",
                0,
                "10.0.0.12",
                ["LTE-Backhaul-Switch-Aggregation"],
                ["FDI Cisco SW", "Template Temperature NCS"],
                {"location": "SiteBeta"},
            ),
        ]
        radios = [
            make_host(
                "radio-active",
                "SiteAlpha-1234-To-NodeBeta-EBand",
                0,
                "10.0.0.20",
            ),
            make_host(
                "radio-disabled",
                "SiteAlpha-1234-To-NodeGamma-RTN",
                1,
                "10.0.0.21",
            ),
            make_host(
                "radio-incoming",
                "NodeDelta-2200-To-SiteAlpha-1234-EBand",
                0,
                "10.0.0.22",
            ),
        ]

        class FakeZabbixClient:
            groups = {
                "LTE-Backhaul-eNodeB": {"groupid": "baseband"},
                "LTE-Backhaul-Switch": {"groupid": "switch"},
                "LTE-Backhaul-Radio": {"groupid": "radio"},
                "LTE-Backhaul-Switch-Aggregation": {"groupid": "aggregation"},
            }
            hosts_by_group = {
                "baseband": basebands,
                "switch": switches,
                "radio": radios,
                "aggregation": aggregation,
            }

            def login(self):
                return "authenticated"

            def get_group_by_name(self, group_name):
                return self.groups.get(group_name)

            def get_hosts_by_group(self, group_id):
                return self.hosts_by_group.get(group_id, [])

        environment = {
            "ZABBIX_URL": "https://zabbix.example.invalid",
            "ZABBIX_USER": "test-user",
            "ZABBIX_PASSWORD": "test-password",
            "ZABBIX_GROUP_ENODEB": "LTE-Backhaul-eNodeB",
            "ZABBIX_GROUP_SWITCH": "LTE-Backhaul-Switch",
            "ZABBIX_GROUP_RADIO": "LTE-Backhaul-Radio",
            "ZABBIX_GROUP_SWITCH_AGGREGATION": "LTE-Backhaul-Switch-Aggregation",
        }

        with patch.dict(os.environ, environment):
            discovery = SiteDiscovery()

        discovery.client = FakeZabbixClient()
        result = discovery.discover("1234")

        self.assertEqual(
            {"bb-primary", "bb-secondary"},
            {item.zabbix_hostid for item in result.basebands},
        )
        self.assertEqual(
            {"switch-active", "ncs-active"},
            {item.zabbix_hostid for item in result.devices},
        )

        devices = {item.zabbix_hostid: item for item in result.devices}
        self.assertEqual("network", devices["switch-active"].role)
        self.assertEqual("ncs", devices["ncs-active"].role)
        self.assertEqual("ncs", devices["ncs-active"].device_type)
        # Same management IP does not make two different Zabbix hosts identical.
        self.assertEqual(
            devices["switch-active"].ip,
            devices["ncs-active"].ip,
        )

        self.assertEqual(
            ["radio-active"],
            [item.zabbix_hostid for item in result.radio_links],
        )

        # Multiple active NCS candidates for the same location are ambiguous:
        # discovery must warn and must not silently select either candidate.
        discovery.client.hosts_by_group["aggregation"].append(
            make_host(
                "ncs-active-duplicate",
                "TH-BH-NCS-SiteAlpha-SecondAgg",
                0,
                "10.0.0.13",
                ["LTE-Backhaul-Switch-Aggregation"],
                ["FDI Cisco SW", "Template Temperature NCS"],
                {"location": "SiteAlpha"},
            )
        )
        ambiguous_result = discovery.discover("1234")
        self.assertEqual(
            ["switch-active"],
            [item.zabbix_hostid for item in ambiguous_result.devices],
        )
        self.assertTrue(
            any("Multiple active NCS candidates" in warning
                for warning in ambiguous_result.warnings)
        )




if __name__ == "__main__":
    unittest.main()
