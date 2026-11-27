from app.eband import analyze_eband
from app.radio_rules import evaluate_difference, evaluate_rx_level
from app.rtn import (
    analyze_generic_radio,
    analyze_rtn,
    evaluate_modulation_history,
    evaluate_packet_loss,
)


def test_eband_difference_boundary_is_not_healthy_at_seven_db():
    assert evaluate_difference(6.999)["status"] == "PASS"
    assert evaluate_difference(7)["status"] == "CRITICAL"
    assert evaluate_difference(None)["status"] == "NOT_AVAILABLE"


def test_eband_rx_boundaries():
    assert evaluate_rx_level(-45.01)["status"] == "CRITICAL"
    assert evaluate_rx_level(-45)["status"] == "WARNING"
    assert evaluate_rx_level(-37.01)["status"] == "WARNING"
    assert evaluate_rx_level(-37)["status"] == "PASS"


def test_huawei_history_requires_multiple_samples_and_current_must_equal_maximum():
    now = 1_800_000_000
    item = {"lastvalue": "14", "lastclock": now - 5}
    history = [
        {"value": "13", "clock": now - 3600},
        {"value": "14", "clock": now - 5},
    ]
    result = evaluate_modulation_history(item, history, now=now)
    assert result["status"] == "PASS"
    assert result["history_count"] == 2
    assert result["max"] == 14
    assert result["max_timestamp"] == now - 5

    insufficient = evaluate_modulation_history(item, history[:1], now=now)
    assert insufficient["status"] == "UNKNOWN"

    lower_than_max = evaluate_modulation_history(
        {"lastvalue": "13", "lastclock": now - 5},
        history,
        now=now,
    )
    assert lower_than_max["status"] == "WARNING"

    low_value = evaluate_modulation_history(
        {"lastvalue": "12", "lastclock": now - 5},
        [],
        now=now,
    )
    assert low_value["status"] == "WARNING"


def test_rtn_has_no_destination_whitelist_and_preserves_modulation_history():
    now = 1_800_000_000
    items = [{
        "itemid": "100",
        "name": "Huawei modulation",
        "key_": "modulation_huawei[UnlistedRemotePOP]",
        "value_type": "0",
        "units": "",
        "lastvalue": "15",
        "lastclock": str(now - 5),
    }]
    triggers = [{
        "triggerid": "t1",
        "description": "Modulation health - UnlistedRemotePOP",
        "expression": "{100.last()}<13",
        "priority": "2",
        "status": "0",
        "value": "0",
        "items": [{"itemid": "100"}],
    }]
    history = {
        "100": [
            {"value": "14", "clock": now - 3600},
            {"value": "15", "clock": now - 5},
        ]
    }
    result = analyze_rtn(items, triggers, history, now=now)
    assert result["status"] == "PASS"
    assert result["summary"]["modulation_count"] == 1
    assert result["modulation"][0]["link"] == "UnlistedRemotePOP"
    assert result["modulation"][0]["history"]["history_count"] == 2


def test_intracom_and_nray_metrics_keep_actual_values_units_and_triggers():
    item = {
        "itemid": "200",
        "name": "Incoming Traffic",
        "key_": "rx_traffic[link-a]",
        "value_type": "3",
        "units": "bps",
        "lastvalue": "123456",
        "lastclock": "1700000000",
    }
    trigger = {
        "triggerid": "t2",
        "description": "RX traffic threshold",
        "expression": "{200.last()}>500000",
        "priority": "2",
        "status": "0",
        "value": "0",
        "items": [{"itemid": "200"}],
    }
    for technology in ("INTRACOM", "NRAY"):
        result = analyze_generic_radio([item], [trigger], technology)
        assert result["type"] == technology
        assert result["metrics"][0]["value"] == 123456
        assert result["metrics"][0]["units"] == "bps"
        assert result["metrics"][0]["key"] == "rx_traffic[link-a]"
        assert result["metrics"][0]["status"] == "PASS"



def test_eband_retains_capacity_profile_input_without_capacity_health():
    items = {
        "RX.110101": {"lastvalue": "-37", "units": "dBm", "itemid": "1", "lastclock": "1700000000"},
        "TX.110101": {"lastvalue": "10", "units": "dBm", "itemid": "2", "lastclock": "1700000000"},
        "rx_calloff": {"lastvalue": "0", "units": "dB", "itemid": "3", "lastclock": "1700000000"},
        "tx_calloff": {"lastvalue": "0", "units": "dB", "itemid": "4", "lastclock": "1700000000"},
        "actualTxCapacity.110101": {"lastvalue": "2486405120", "units": "bps", "itemid": "5", "lastclock": "1700000000"},
        "actualRxAcmTC.110101": {"lastvalue": "16", "units": "", "itemid": "6", "lastclock": "1700000000"},
    }
    result = analyze_eband("host-1", "Bijan-2488-EBand", items)
    slot1 = result["checks"]["difference"]["slots"][0]
    assert slot1["capacity_profile_input"]["value"] == "2486405120"
    assert "capacity" not in slot1
    assert slot1["rx_health"]["status"] == "PASS"



def test_rtn_packet_loss_metric_and_existing_thresholds_are_preserved():
    assert evaluate_packet_loss(4.9)["status"] == "PASS"
    assert evaluate_packet_loss(5)["status"] == "WARNING"
    assert evaluate_packet_loss(80)["status"] == "WARNING"
    assert evaluate_packet_loss(81)["status"] == "CRITICAL"
    assert evaluate_packet_loss(None)["status"] == "NOT_AVAILABLE"

    items = [{
        "itemid": "300",
        "name": "Packet loss",
        "key_": "packetloss",
        "value_type": "0",
        "units": "%",
        "lastvalue": "6",
        "lastclock": "1700000000",
    }]
    result = analyze_rtn(items, [])
    assert result["packet_loss"]["value"] == 6
    assert result["packet_loss"]["units"] == "%"
    assert result["packet_loss"]["status"] == "WARNING"
