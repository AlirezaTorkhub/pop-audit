from __future__ import annotations

from typing import Any, Optional


# ============================================================
# Helpers
# ============================================================

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


# ============================================================
# Difference
# ============================================================

def evaluate_difference(
    difference: Any,
    threshold: float = 7.0,
) -> dict:

    value = to_float(difference)

    if value is None:
        return base_result(
            status="NOT_AVAILABLE",
            threshold=threshold,
            operator="<=",
            reason="Difference value is not available.",
        )

    if value <= threshold:
        return base_result(
            status="PASS",
            value=value,
            threshold=threshold,
            operator="<=",
            reason=(
                f"Difference {value:.2f} dB "
                f"is within the verified threshold."
            ),
        )

    return base_result(
        status="CRITICAL",
        value=value,
        threshold=threshold,
        operator="<=",
        trigger_description="Calloff above 7dbm",
        zabbix_priority=4,
        reason=(
            f"Difference {value:.2f} dB "
            f"exceeds the verified 7 dB threshold."
        ),
    )


# ============================================================
# RX Level
# ============================================================

def evaluate_rx_level(
    rx: Any,
) -> dict:

    value = to_float(rx)

    if value is None:
        return base_result(
            status="NOT_AVAILABLE",
            reason="RX level is not available.",
        )

    # Critical: RX < -45
    if value < -45:
        return base_result(
            status="CRITICAL",
            value=value,
            threshold=-45,
            operator=">=",
            trigger_description="RX-Level is low",
            zabbix_priority=5,
            reason=(
                f"RX level {value:.2f} dBm "
                f"is below the critical -45 dBm threshold."
            ),
        )

    # Warning: -45 <= RX < -37
    if value < -37:
        return base_result(
            status="WARNING",
            value=value,
            threshold=-37,
            operator=">=",
            trigger_description="RX-Level is low",
            zabbix_priority=2,
            reason=(
                f"RX level {value:.2f} dBm "
                f"is below the -37 dBm threshold."
            ),
        )

    return base_result(
        status="PASS",
        value=value,
        threshold=-37,
        operator=">=",
        reason=(
            f"RX level {value:.2f} dBm "
            f"is within the verified range."
        ),
    )


# ============================================================
# Capacity
# ============================================================

def evaluate_capacity(
    capacity: Any,
) -> dict:

    value = to_float(capacity)

    if value is None:
        return base_result(
            status="NOT_AVAILABLE",
            reason="Link capacity is not available.",
        )

    # < 807 Mbps
    if value < 807_000_000:
        return base_result(
            status="CRITICAL",
            value=value,
            threshold=807_000_000,
            operator=">=",
            trigger_description=(
                "Link Capacity is low (<807 Mbps)"
            ),
            zabbix_priority=5,
            reason=(
                f"Capacity {value:.0f} bps "
                f"is below 807 Mbps."
            ),
        )

    # < 2.2 Gbps
    if value < 2_200_000_000:
        return base_result(
            status="CRITICAL",
            value=value,
            threshold=2_200_000_000,
            operator=">=",
            trigger_description=(
                "Link Capacity is low (<2.2 Gbps)"
            ),
            zabbix_priority=4,
            reason=(
                f"Capacity {value:.0f} bps "
                f"is below 2.2 Gbps."
            ),
        )

    return base_result(
        status="PASS",
        value=value,
        threshold=2_200_000_000,
        operator=">=",
        reason=(
            f"Capacity {value:.0f} bps "
            f"is at or above 2.2 Gbps."
        ),
    )


# ============================================================
# Modulation profile detection
# ============================================================

def get_modulation_profile(
    capacity: Any,
) -> Optional[dict]:

    value = to_float(capacity)

    if value is None:
        return None

    # 5G
    if value == 4_640_141_312:
        return {
            "name": "5G",
            "capacity": 4_640_141_312,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 256,
            "trigger_description": (
                "(5G)Eband change modulation "
                "(the number is less than 256)"
            ),
            "zabbix_priority": 4,
        }

    # 10G
    if value == 9_280_282_624:
        return {
            "name": "10G",
            "capacity": 9_280_282_624,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 256,
            "trigger_description": (
                "(10G)Eband change modulation "
                "(the number is less than 256)"
            ),
            "zabbix_priority": 4,
        }

    # 2.5G
    if value == 2_486_405_120:
        return {
            "name": "2.5G",
            "capacity": 2_486_405_120,
            "rx_warning_threshold": 16,
            "rx_critical_threshold": 4,
            "trigger_description": (
                "2.5G Eband modulation change"
            ),
            "zabbix_priority": 3,
        }

    # 1G
    if value in (
        1_159_824_384,
        1_253_464_064,
    ):
        return {
            "name": "1G",
            "capacity": value,
            "rx_warning_threshold": None,
            "rx_critical_threshold": 4,
            "trigger_description": (
                "(1G)Eband change modulation "
                "(the number is less than 4)"
            ),
            "zabbix_priority": 4,
        }

    return None


# ============================================================
# RX Modulation
# ============================================================

def evaluate_rx_modulation(
    modulation: Any,
    capacity: Any,
) -> dict:

    modulation_value = to_float(
        modulation
    )

    if modulation_value is None:
        return base_result(
            status="NOT_AVAILABLE",
            reason="RX modulation is not available.",
        )

    profile = get_modulation_profile(
        capacity
    )

    if profile is None:
        return base_result(
            status="UNKNOWN",
            value=modulation_value,
            source="ZABBIX_TRIGGER",
            reason=(
                "No verified modulation rule "
                "matches the current capacity profile."
            ),
        )

    warning_threshold = profile.get(
        "rx_warning_threshold"
    )

    critical_threshold = profile.get(
        "rx_critical_threshold"
    )

    # 2.5G warning:
    # modulation < 16
    if (
        warning_threshold is not None
        and modulation_value < warning_threshold
    ):
        # 2.5G critical:
        # modulation < 4
        if (
            critical_threshold is not None
            and modulation_value < critical_threshold
        ):
            return base_result(
                status="CRITICAL",
                value=modulation_value,
                threshold=critical_threshold,
                operator=">=",
                trigger_description=(
                    "(2.5G)Eband change modulation "
                    "(the number is less than 4)"
                ),
                zabbix_priority=4,
                reason=(
                    f"RX modulation {modulation_value:g} "
                    f"is below the critical threshold "
                    f"for {profile['name']}."
                ),
            )

        return base_result(
            status="WARNING",
            value=modulation_value,
            threshold=warning_threshold,
            operator=">=",
            trigger_description=(
                "(2.5G)Eband change modulation "
                "(the number is less than 16)"
            ),
            zabbix_priority=3,
            reason=(
                f"RX modulation {modulation_value:g} "
                f"is below the warning threshold "
                f"for {profile['name']}."
            ),
        )

    # 5G / 10G / 1G
    if (
        critical_threshold is not None
        and modulation_value < critical_threshold
    ):
        return base_result(
            status="CRITICAL",
            value=modulation_value,
            threshold=critical_threshold,
            operator=">=",
            trigger_description=profile[
                "trigger_description"
            ],
            zabbix_priority=profile[
                "zabbix_priority"
            ],
            reason=(
                f"RX modulation {modulation_value:g} "
                f"is below the verified threshold "
                f"for {profile['name']}."
            ),
        )

    return base_result(
        status="PASS",
        value=modulation_value,
        threshold=critical_threshold,
        operator=">=",
        reason=(
            f"RX modulation {modulation_value:g} "
            f"meets the verified requirement "
            f"for {profile['name']}."
        ),
    )


# ============================================================
# Interface state
# ============================================================

def evaluate_interface_state(
    admin_status: Any,
    oper_status: Any,
) -> dict:

    try:
        admin = int(float(admin_status))
        oper = int(float(oper_status))
    except (TypeError, ValueError):
        return base_result(
            status="NOT_AVAILABLE",
            reason=(
                "Interface admin/oper status "
                "is not available or invalid."
            ),
        )

    if admin == 1 and oper == 2:
        return base_result(
            status="CRITICAL",
            value={
                "admin_status": admin,
                "oper_status": oper,
            },
            source="ZABBIX_TRIGGER",
            trigger_description=(
                "Interface is down"
            ),
            zabbix_priority=2,
            reason=(
                "Interface is administratively enabled "
                "but operationally down."
            ),
        )

    return base_result(
        status="PASS",
        value={
            "admin_status": admin,
            "oper_status": oper,
        },
        reason="Interface is not in the verified down condition.",
    )


# ============================================================
# Generic aggregation
# ============================================================

def aggregate_status(
    statuses: list[str],
) -> str:

    if "CRITICAL" in statuses:
        return "CRITICAL"

    if "WARNING" in statuses:
        return "WARNING"

    if "UNKNOWN" in statuses:
        return "UNKNOWN"

    if "NOT_AVAILABLE" in statuses:
        return "NOT_AVAILABLE"

    return "PASS"
