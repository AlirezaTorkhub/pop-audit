import unittest

from app.discovery import infer_radio_type, parse_direction


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


if __name__ == "__main__":
    unittest.main()
