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


if __name__ == "__main__":
    unittest.main()
