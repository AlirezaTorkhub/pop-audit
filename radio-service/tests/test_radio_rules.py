import unittest

from app.eband import analyze_eband
from app.radio_rules import evaluate_difference as evaluate_eband_difference
from app.rtn import evaluate_difference as evaluate_rtn_difference


class DifferenceThresholdTests(unittest.TestCase):
    def test_eband_difference_is_not_ok_at_seven_or_above(self):
        self.assertEqual("PASS", evaluate_eband_difference(6.99)["status"])
        self.assertEqual("CRITICAL", evaluate_eband_difference(7.0)["status"])
        self.assertEqual("CRITICAL", evaluate_eband_difference(7.01)["status"])

    def test_rtn_difference_is_not_ok_at_seven_or_above(self):
        self.assertEqual("PASS", evaluate_rtn_difference(6.99)["status"])
        self.assertEqual("WARNING", evaluate_rtn_difference(7.0)["status"])
        self.assertEqual("WARNING", evaluate_rtn_difference(7.01)["status"])

    def test_missing_difference_is_not_available(self):
        self.assertEqual("NOT_AVAILABLE", evaluate_eband_difference(None)["status"])
        self.assertEqual("NOT_AVAILABLE", evaluate_rtn_difference(None)["status"])


class EBandCapacityHealthTests(unittest.TestCase):
    @staticmethod
    def make_item(itemid, value, units=""):
        return {
            "itemid": str(itemid),
            "lastvalue": str(value),
            "units": units,
            "lastclock": "1760000000",
        }

    def test_capacity_is_retained_but_does_not_affect_link_health(self):
        # 1G is a known modulation profile and is below the legacy
        # Capacity Health threshold. RX modulation 5 is valid for this
        # profile, so capacity itself must not make the link unhealthy.
        capacity_1g = 1_159_824_384
        items = {
            "rx_calloff": self.make_item(1, -30, "dBm"),
            "tx_calloff": self.make_item(2, -30, "dBm"),
            "RX.110101": self.make_item(3, -30, "dBm"),
            "TX.110101": self.make_item(4, -30, "dBm"),
            "rx_tx_diff": self.make_item(5, 0, "dB"),
            "actualTxCapacity.110101": self.make_item(6, capacity_1g, "bps"),
            "actualRxAcmTC.110101": self.make_item(7, 5),
            "RX.110201": self.make_item(8, -30, "dBm"),
            "TX.110201": self.make_item(9, -30, "dBm"),
            "rx_tx_diff_slot2": self.make_item(10, 0, "dB"),
            "actualTxCapacity.110201": self.make_item(11, capacity_1g, "bps"),
            "actualRxAcmTC.110201": self.make_item(12, 5),
            "ifAdminStatus[LANXPort:slot=1;port=1]": self.make_item(13, 1),
            "ifOperStatus[LANXPort:slot=1;port=1]": self.make_item(14, 1),
        }

        result = analyze_eband("host-1", "sample-eband", items)
        first_slot = result["checks"]["difference"]["slots"][0]

        self.assertEqual("PASS", result["status"])
        self.assertEqual(str(capacity_1g), first_slot["capacity"]["metric"]["value"])
        self.assertNotIn("health", first_slot["capacity"])


if __name__ == "__main__":
    unittest.main()
