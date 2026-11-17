import os
import tempfile
import unittest

from openpyxl import Workbook

os.environ.setdefault(
    "REPORT_DIR",
    os.path.join(tempfile.gettempdir(), "pop-audit-report-tests"),
)

from app.main import build_eband  # noqa: E402


class EBandReportTests(unittest.TestCase):
    def test_capacity_is_reported_without_capacity_health(self):
        workbook = Workbook()
        results = {
            "links": [
                {
                    "link_type": "EBAND",
                    "name": "sample-eband",
                    "analysis": {
                        "status": "PASS",
                        "checks": {
                            "difference": {
                                "slots": [
                                    {
                                        "slot": 1,
                                        "rx": {"value": "-30"},
                                        "tx": {"value": "-30"},
                                        "rx_calloff": {"value": "-30"},
                                        "tx_calloff": {"value": "-30"},
                                        "difference": {"value": 0, "status": "PASS"},
                                        "zabbix_difference": {"value": 0},
                                        "capacity": {"metric": {"value": "1159824384"}},
                                        "rx_modulation": {
                                            "metric": {"value": "5"},
                                            "health": {"status": "PASS"},
                                        },
                                        "rx_health": {"status": "PASS"},
                                    }
                                ]
                            },
                            "interfaces": {"status": "PASS"},
                        },
                    },
                }
            ]
        }

        build_eband(workbook, results)
        sheet = workbook["EBand"]
        headers = [cell.value for cell in sheet[1]]

        self.assertIn("Capacity", headers)
        self.assertNotIn("Capacity Health", headers)
        capacity_column = headers.index("Capacity") + 1
        self.assertEqual("1159824384", sheet.cell(2, capacity_column).value)


if __name__ == "__main__":
    unittest.main()
