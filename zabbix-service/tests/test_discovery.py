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


    def test_real_gandi_2213_host_patterns(self):
        # Hostname patterns taken from the supplied Zabbix host-search export.
        cases = {
            "Gandi-2213-To-Delvin-Eband": "EBand",
            "Gandi-2213-To-Eskan-Intracom": "Intracom",
            "Gandi-2213-To-Hakim-Intracom": "Intracom",
            "Gandi-2213-To-Hemat-Eband": "EBand",
            "Gandi-2213-To-Hemat-Intracom": "Intracom",
            "Gandi-2213-To-IdeNegar-EBand": "EBand",
            "Gandi-2213-To-LCT-380-Huawei": "RTN",
            "Gandi-2213-To-LCT-EBand-II": "EBand",
            "Gandi-2213-To-Soroush-Intracom": "Intracom",
            "Gandi-2213-to-Harat-950-Huawei": "RTN",
            "Gandi-2213-To-AmirAbad-DW": "Unknown",
        }

        for hostname, expected in cases.items():
            with self.subTest(hostname=hostname):
                self.assertEqual(infer_radio_type(hostname), expected)

    def test_gandi_2213_outgoing_and_incoming_direction(self):
        outgoing = parse_direction(
            "Gandi-2213-to-Harat-950-Huawei",
            "2213",
        )
        incoming = parse_direction(
            "AmirAbad-2203-To-Gandi-DW",
            "2213",
        )

        self.assertEqual(outgoing[0], "2213")
        self.assertEqual(outgoing[1], "950")
        self.assertIsNone(incoming[0])


if __name__ == "__main__":
    unittest.main()
