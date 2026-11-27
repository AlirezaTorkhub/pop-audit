from __future__ import annotations

from typing import Any, Optional


def to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def base_result(
    *,
    status: str,
    value: Any = None,
    threshold: Any = None,
    operator: Optional[str] = None,
    source: str = "ZABBIX_TRIGGER",
    trigger_description: Optional[str] = None,
    zabbix_priority: Optional[int] = None,
    reason: str = "",
) -> dict:
    return {
        "status": status,
        "value": value,
        "threshold": threshold,
        "operator": operator,
        "source": source,
        "trigger_description": trigger_description,
        "zabbix_priority": zabbix_priority,
        "reason": reason,
    }


def evaluate_difference(difference: Any, threshold: float = 7.0) -> dict:
    value = to_float(difference)
    if value is None:
        return base_result(
            status="NOT_AVAILABLE",
            threshold=threshold,
            operator="<",
            reason="Difference value is not available.",
        )
    if value < threshold:
        return base_result(
            status="PASS",
            value=value,
            threshold=threshold,
            operator="<",
            reason=f"Difference {value:.2f} dB is below the verified 7 dB limit.",
        )
    return base_result(
        status="CRITICAL",
        value=value,
        threshold=threshold,
        operator="<",
        trigger_description="Calloff at or above 7 dB",
        zabbix_priority=4,
        reason=f"Difference {value:.2f} dB is at or above the 7 dB limit.",
    )


def evaluate_rx_level(rx: Any) -> dict:
    value = to_float(rx)
    if value is None:
        return base_result(
            status="NOT_AVAILABLE",
            reason="RX level is not available.",
        )
    if value < -45:
        return base_result(
            status="CRITICAL",
            value=value,
            threshold=-45,
            operator=">=",
            trigger_description="RX-Level is low",
            zabbix_priority=5,
            reason=f"RX level {value:.2f} dBm is below the critical -45 dBm threshold.",
        )
    if value < -37:
        return base_result(
            status="WARNING",
            value=value,
            threshold=-37,
            operator=">=",
            trigger_description="RX-Level is low",
            zabbix_priority=2,
            reason=f"RX level {value:.2f} dBm is below the -37 dBm threshold.",
        )
    return base_result(
        status="PASS",
        value=value,
        threshold=-37,
        operator=">=",
        reason=f"RX level {value:.2f} dBm is within the verified range.",
    )


def evaluate_capacity(capacity: Any) -> dict:
    """Legacy informational helper; capacity is not an EBand health gate."""
    value = to_float(capacity)
    if value is None:
        return base_result(status="NOT_AVAILABLE", reason="Link capacity is not available.")
    return base_result(
        status="UNKNOWN",
        value=value,
        source="METRIC_ONLY",
        reason="Capacity is retained only as a profile input; no capacity health verdict is used.",
    )


def get_modulation_profile(capacity: Any) -> Optional[dict]:
    value = to_float(capacity)
    if value is None:
        return None
    if value == 4_640_141_312:
        return {
            "name": "5G",
            "capacity": 4_640_141_312,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 256,
            "trigger_description": "(5G)Eband change modulation (the number is less than 256)",
            "zabbix_priority": 4,
        }
    if value == 9_280_282_624:
        return {
            "name": "10G",
            "capacity": 9_280_282_624,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 256,
            "trigger_description": "(10G)Eband change modulation (the number is less than 256)",
            "zabbix_priority": 4,
        }
    if value == 2_486_405_120:
        return {
            "name": "2.5G",
            "capacity": 2_486_405_120,
            "rx_warning_threshold": 16,
            "rx_critical_threshold": 4,
            "trigger_description": "2.5G Eband modulation change",
            "zabbix_priority": 3,
        }
    if value in (1_159_824_384, 1_253_464_064):
        return {
            "name": "1G",
            "capacity": value,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 4,
            "trigger_description": "(1G)Eband change modulation (the number is less than 4)",
            "zabbix_priority": 4,
        }
    return None


def evaluate_rx_modulation(modulation: Any, capacity: Any) -> dict:
    modulation_value = to_float(modulation)
    if modulation_value is None:
        return base_result(status="NOT_AVAILABLE", reason="RX modulation is not available.")
    profile = get_modulation_profile(capacity)
    if profile is None:
        return base_result(
            status="UNKNOWN",
            value=modulation_value,
            source="ZABBIX_TRIGGER",
            reason="No verified modulation rule matches the current capacity profile.",
        )
    warning_threshold = profile.get("rx_warning_threshold")
    critical_threshold = profile.get("rx_critical_threshold")
    if warning_threshold is not None and modulation_value < warning_threshold:
        if critical_threshold is not None and modulation_value < critical_threshold:
            return base_result(
                status="CRITICAL",
                value=modulation_value,
                threshold=critical_threshold,
                operator=">=",
                trigger_description=profile["trigger_description"],
                zabbix_priority=4,
                reason=f"RX modulation {modulation_value:g} is below the critical threshold for {profile['name']}.",
            )
        return base_result(
            status="WARNING",
            value=modulation_value,
            threshold=warning_threshold,
            operator=">=",
            trigger_description="(2.5G)Eband change modulation (the number is less than 16)",
            zabbix_priority=3,
            reason=f"RX modulation {modulation_value:g} is below the warning threshold for {profile['name']}.",
        )
    if critical_threshold is not None and modulation_value < critical_threshold:
        return base_result(
            status="CRITICAL",
            value=modulation_value,
            threshold=critical_threshold,
            operator=">=",
            trigger_description=profile["trigger_description"],
            zabbix_priority=profile["zabbix_priority"],
            reason=f"RX modulation {modulation_value:g} is below the verified threshold for {profile['name']}.",
        )
    return base_result(
        status="PASS",
        value=modulation_value,
        threshold=critical_threshold,
        operator=">=",
        reason=f"RX modulation {modulation_value:g} meets the verified requirement for {profile['name']}.",
    )


def evaluate_interface_state(admin_status: Any, oper_status: Any) -> dict:
    try:
        admin = int(float(admin_status))
        oper = int(float(oper_status))
    except (TypeError, ValueError):
        return base_result(
            status="NOT_AVAILABLE",
            reason="Interface admin/oper status is not available or invalid.",
        )
    if admin == 2:
        return base_result(
            status="PASS",
            value={"admin_status": admin, "oper_status": oper},
            reason="Interface is administratively disabled.",
        )
    if admin == 1 and oper == 1:
        return base_result(
            status="PASS",
            value={"admin_status": admin, "oper_status": oper},
            reason="Interface is administratively enabled and operationally up.",
        )
    if admin == 1 and oper != 1:
        return base_result(
            status="CRITICAL",
            value={"admin_status": admin, "oper_status": oper},
            reason="Interface is administratively enabled but operationally down.",
        )
    return base_result(
        status="UNKNOWN",
        value={"admin_status": admin, "oper_status": oper},
        reason="Interface returned an unrecognized admin/oper state.",
    )


def aggregate_status(statuses: list[str]) -> str:
    if "CRITICAL" in statuses:
        return "CRITICAL"
    if "WARNING" in statuses:
        return "WARNING"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    if "NOT_AVAILABLE" in statuses:
        return "NOT_AVAILABLE"
    if not statuses:
        return "UNKNOWN"
    return "PASS"
