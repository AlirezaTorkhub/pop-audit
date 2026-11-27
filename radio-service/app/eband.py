from __future__ import annotations

from typing import Any

from .radio_rules import (
    aggregate_status,
    evaluate_difference,
    evaluate_interface_state,
    evaluate_rx_level,
    evaluate_rx_modulation,
)


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def metric_value(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    return to_float(item.get("lastvalue"))


def metric_result(item: dict[str, Any] | None, name: str) -> dict[str, Any]:
    if not item or item.get("lastvalue") in (None, ""):
        return {
            "availability": "NOT_AVAILABLE",
            "name": name,
            "value": None,
            "message": f"{name} is not available.",
        }
    return {
        "availability": "AVAILABLE",
        "name": name,
        "value": item.get("lastvalue"),
        "units": item.get("units", ""),
        "itemid": item.get("itemid"),
        "key": item.get("key_"),
        "lastclock": item.get("lastclock"),
    }


def analyze_eband_slot(
    slot: int,
    rx: dict[str, Any] | None,
    tx: dict[str, Any] | None,
    rx_calloff: dict[str, Any] | None,
    tx_calloff: dict[str, Any] | None,
    zabbix_difference: dict[str, Any] | None,
) -> dict[str, Any]:
    rx_value = metric_value(rx)
    tx_value = metric_value(tx)
    rx_calloff_value = metric_value(rx_calloff)
    tx_calloff_value = metric_value(tx_calloff)

    if None in (rx_value, tx_value, rx_calloff_value, tx_calloff_value):
        difference_value = None
    else:
        difference_value = (
            (-rx_value + tx_value)
            - (-rx_calloff_value + tx_calloff_value)
        )

    output = {
        "slot": slot,
        "rx": metric_result(rx, f"RX slot {slot}"),
        "tx": metric_result(tx, f"TX slot {slot}"),
        "rx_calloff": metric_result(rx_calloff, "RX Calloff"),
        "tx_calloff": metric_result(tx_calloff, "TX Calloff"),
        "difference": evaluate_difference(difference_value),
    }

    if zabbix_difference:
        zabbix_value = metric_value(zabbix_difference)
        output["zabbix_difference"] = metric_result(
            zabbix_difference, "Zabbix Difference"
        )
        if difference_value is not None and zabbix_value is not None:
            output["comparison"] = {
                "calculated": difference_value,
                "zabbix": zabbix_value,
                "delta": difference_value - zabbix_value,
            }
    return output


def analyze_eband(
    hostid: str,
    hostname: str,
    items: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rx_calloff = items.get("rx_calloff")
    tx_calloff = items.get("tx_calloff")
    slots: list[dict[str, Any]] = []

    for slot, rx_key, tx_key, diff_key in (
        (1, "RX.110101", "TX.110101", "rx_tx_diff"),
        (2, "RX.110201", "TX.110201", "rx_tx_diff_slot2"),
    ):
        slot_result = analyze_eband_slot(
            slot=slot,
            rx=items.get(rx_key),
            tx=items.get(tx_key),
            rx_calloff=rx_calloff,
            tx_calloff=tx_calloff,
            zabbix_difference=items.get(diff_key),
        )
        slot_result["rx_health"] = evaluate_rx_level(
            metric_value(items.get(rx_key))
        )

        # Capacity remains an internal profile input for existing modulation
        # rules only. It is deliberately absent from report/UI health output.
        capacity_key = (
            "actualTxCapacity.110101"
            if slot == 1
            else "actualTxCapacity.110201"
        )
        capacity_value = metric_value(items.get(capacity_key))
        modulation_key = (
            "actualRxAcmTC.110101"
            if slot == 1
            else "actualRxAcmTC.110201"
        )
        modulation_item = items.get(modulation_key)
        slot_result["rx_modulation"] = {
            "metric": metric_result(
                modulation_item, f"RX Modulation slot {slot}"
            ),
            "health": evaluate_rx_modulation(
                metric_value(modulation_item), capacity_value
            ),
        }
        slots.append(slot_result)

    tx_modulation = {
        "slot1": metric_result(
            items.get("actualTxAcmTC.110101"), "TX Modulation slot 1"
        ),
        "slot2": metric_result(
            items.get("actualTxAcmTC.110201"), "TX Modulation slot 2"
        ),
        "health": {
            "status": "UNKNOWN",
            "reason": "No verified Zabbix health rule for TX modulation has been identified.",
        },
    }

    snir = {
        "slot1": metric_result(items.get("actualSnir.110101"), "SNIR slot 1"),
        "slot2": metric_result(items.get("actualSnir.110201"), "SNIR slot 2"),
        "health": {
            "status": "UNKNOWN",
            "reason": "SNIR data is available, but no verified health threshold has been identified.",
        },
    }

    errors: dict[str, Any] = {}
    for metric_name, key in (
        ("BBER", "BBER.110101"),
        ("BBE", "BBE.110101"),
        ("ESR", "ESR.110101"),
        ("ES", "ES.110101"),
    ):
        slot2_key = key.replace("110101", "110201")
        errors[metric_name] = {
            "slot1": metric_result(items.get(key), f"{metric_name} slot 1"),
            "slot2": metric_result(items.get(slot2_key), f"{metric_name} slot 2"),
        }
    errors["health"] = {
        "status": "UNKNOWN",
        "reason": "No verified Zabbix health threshold has been identified for BBER/BBE/ESR/ES.",
    }

    interface_health = []
    for interface_key in (
        "LANXPort:slot=1;port=1",
        "LANXPort:slot=1;port=2",
        "LANXPort:slot=1;port=3",
        "LANXPort:slot=1;port=4",
        "WANXPort:slot=1;port=5",
        "RadioLinkTerminal:slot=1;rltNumber=1",
        "CarrierTermination:slot=1;ctNumber=1",
        "CarrierTermination:slot=2;ctNumber=1",
    ):
        admin_item = items.get(f"ifAdminStatus[{interface_key}]")
        oper_item = items.get(f"ifOperStatus[{interface_key}]")
        if not admin_item or not oper_item:
            continue
        interface_health.append({
            "interface": interface_key,
            "health": evaluate_interface_state(
                metric_value(admin_item), metric_value(oper_item)
            ),
            "admin": metric_result(admin_item, "Admin status"),
            "oper": metric_result(oper_item, "Operational status"),
        })

    slot_health_statuses = []
    for slot in slots:
        slot_health_statuses.extend([
            slot["difference"]["status"],
            slot["rx_health"]["status"],
            slot["rx_modulation"]["health"]["status"],
        ])
    slot_overall = aggregate_status(slot_health_statuses)

    interface_statuses = [
        item["health"]["status"] for item in interface_health
    ]
    interface_overall = (
        aggregate_status(interface_statuses)
        if interface_statuses
        else "NOT_AVAILABLE"
    )
    final_status = aggregate_status([slot_overall, interface_overall])

    return {
        "hostid": hostid,
        "hostname": hostname,
        "technology": "EBAND",
        "status": final_status,
        "checks": {
            "difference": {"status": slot_overall, "slots": slots},
            "modulation": {
                "rx": {
                    "slot1": slots[0]["rx_modulation"],
                    "slot2": slots[1]["rx_modulation"],
                },
                "tx": tx_modulation,
            },
            "snir": snir,
            "errors": errors,
            "interfaces": {
                "status": interface_overall,
                "data": interface_health,
            },
        },
    }
