from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RTN_PATH = ROOT / "radio-service" / "app" / "rtn.py"

spec = importlib.util.spec_from_file_location("pop_audit_rtn", RTN_PATH)
rtn = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(rtn)


def test_rtn_modulation_equals_historical_maximum_is_healthy():
    now = 1_800_000_000
    history = [
        {"clock": str(now - 3 * 3600), "value": "64"},
        {"clock": str(now - 2 * 3600), "value": "128"},
        {"clock": str(now - 3600), "value": "256"},
    ]
    result = rtn.evaluate_modulation_history(
        256,
        now,
        history,
        hours=12,
        now=now,
    )
    assert result["status"] == "PASS"
    assert result["maximum"] == 256
    assert result["sample_count"] == 3


def test_rtn_modulation_below_historical_maximum_is_warning():
    now = 1_800_000_000
    history = [
        {"clock": str(now - 3 * 3600), "value": "64"},
        {"clock": str(now - 2 * 3600), "value": "128"},
        {"clock": str(now - 3600), "value": "256"},
    ]
    result = rtn.evaluate_modulation_history(
        128,
        now,
        history,
        hours=12,
        now=now,
    )
    assert result["status"] == "WARNING"
    assert result["maximum"] == 256


def test_rtn_modulation_missing_history_is_unknown():
    now = 1_800_000_000
    result = rtn.evaluate_modulation_history(
        256,
        now,
        [],
        hours=12,
        now=now,
    )
    assert result["status"] == "UNKNOWN"


def test_rtn_modulation_stale_current_sample_is_unknown():
    now = 1_800_000_000
    result = rtn.evaluate_modulation_history(
        256,
        now - 13 * 3600,
        [{"clock": str(now - 13 * 3600), "value": "256"}],
        hours=12,
        now=now,
    )
    assert result["status"] == "UNKNOWN"


def test_rtn_difference_boundary_is_not_ok_at_seven_db():
    assert rtn.evaluate_difference(6.99)["status"] == "PASS"
    assert rtn.evaluate_difference(7.0)["status"] == "WARNING"
    assert rtn.evaluate_difference(7.01)["status"] == "WARNING"


def test_unknown_rtn_destination_is_not_rejected():
    item = {
        "itemid": "123",
        "key_": "rx_tx_diff_newpop",
        "lastvalue": "8.0",
        "lastclock": "1800000000",
    }
    result = rtn.analyze_rtn([item], [])
    assert result["summary"]["difference_count"] == 1
    assert result["status"] == "WARNING"
