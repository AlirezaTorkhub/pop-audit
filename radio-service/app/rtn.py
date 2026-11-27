from __future__ import annotations

import math
import re
import time
from typing import Any


def to_float(value: Any) -> float | None:
    import math
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def aggregate_status(statuses: list[str]) -> str:
    order = {
        "CRITICAL": 5,
        "WARNING": 4,
        "UNKNOWN": 3,
        "NOT_AVAILABLE": 2,
        "PASS": 1,
    }
    if not statuses:
        return "UNKNOWN"
    return max(statuses, key=lambda value: order.get(value, 3))


def decode_zabbix_encoded(text: str) -> str:
    if not text:
        return text
    values = []
    for part in text.split("."):
        try:
            value = int(part)
        except (TypeError, ValueError):
            return text
        if not 0 <= value <= 255:
            return text
        values.append(value)
    while values and values[0] == 26:
        values.pop(0)
    if not values:
        return ""
    decoded = "".join(chr(value) for value in values)
    printable = sum(
        1 for character in decoded
        if character.isprintable() or character in "\r\n\t"
    )
    if decoded and printable / len(decoded) >= 0.85:
        return decoded
    return text


def extract_item_ids(expression: str) -> list[str]:
    return re.findall(r"\{(\d+)\}", expression or "")


def build_trigger_index(triggers: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for trigger in triggers:
        if str(trigger.get("status", "0")) != "0":
            continue
        trigger_items = trigger.get("items") or []
        ids = [
            str(item.get("itemid", "")).strip()
            for item in trigger_items
            if item.get("itemid")
        ]
        if not ids:
            ids = extract_item_ids(trigger.get("expression", ""))
        for itemid in ids:
            if itemid:
                result.setdefault(itemid, []).append(trigger)
    return result


def _trigger_summary(triggers: list[dict]) -> dict[str, Any]:
    mapped = []
    active = []
    for trigger in triggers:
        priority = int(trigger.get("priority", 0) or 0)
        value = str(trigger.get("value", "0"))
        entry = {
            "triggerid": trigger.get("triggerid"),
            "description": trigger.get("description", ""),
            "priority": priority,
            "value": value,
            "lastchange": trigger.get("lastchange"),
            "status": trigger.get("status"),
        }
        mapped.append(entry)
        if value == "1":
            active.append(entry)

    active_priorities = [int(item["priority"]) for item in active]
    if not active and mapped:
        status = "PASS"
        reason = "Associated enabled Zabbix triggers are currently OK."
    elif active:
        highest = max(active_priorities, default=0)
        if highest >= 4:
            status = "CRITICAL"
        elif highest >= 2:
            status = "WARNING"
        else:
            status = "UNKNOWN"
        reason = "One or more associated Zabbix triggers are in PROBLEM state."
    else:
        status = "UNKNOWN"
        reason = "No associated Zabbix trigger provides a verified health verdict."

    return {
        "status": status,
        "reason": reason,
        "active_count": len(active),
        "triggers": mapped,
    }


def _item_link_name(item: dict, related_triggers: list[dict]) -> str:
    key = str(item.get("key_", "") or "")
    match = re.search(r"\[(.*)\]", key)
    parameter = match.group(1).strip() if match else ""
    decoded = decode_zabbix_encoded(parameter) if parameter else ""
    if decoded and not re.fullmatch(r"[\d.]+", decoded):
        return decoded

    for trigger in related_triggers:
        description = str(trigger.get("description", "")).strip()
        if description:
            return description
    return str(item.get("name") or key or "Unlabelled radio metric")


def _metric(item: dict) -> dict[str, Any]:
    return {
        "itemid": str(item.get("itemid") or ""),
        "name": item.get("name"),
        "key": item.get("key_"),
        "value": to_float(item.get("lastvalue")),
        "raw_value": item.get("lastvalue"),
        "units": item.get("units") or "",
        "clock": int(item.get("lastclock") or 0),
        "value_type": item.get("value_type"),
    }


def evaluate_modulation_history(
    item: dict,
    history: list[dict],
    *,
    now: int | None = None,
    history_hours: int = 12,
    minimum_samples: int = 2,
) -> dict[str, Any]:
    now = int(now or time.time())
    current = to_float(item.get("lastvalue"))
    current_clock = int(item.get("lastclock") or 0)
    threshold_status = (
        "WARNING" if current is not None and current < 13 else None
    )
    points = []
    for record in history or []:
        value = to_float(record.get("value"))
        clock = int(record.get("clock") or 0)
        if value is not None and clock:
            points.append({"value": value, "clock": clock})
    points.sort(key=lambda entry: entry["clock"])

    recent_from = now - history_hours * 3600
    points = [entry for entry in points if entry["clock"] >= recent_from]
    stale = not current_clock or current_clock < recent_from or current_clock > now + 300

    summary = {
        "current": current,
        "current_timestamp": current_clock or None,
        "max": max((entry["value"] for entry in points), default=None),
        "max_timestamp": None,
        "history_count": len(points),
        "history_hours": history_hours,
        "first_history_timestamp": points[0]["clock"] if points else None,
        "last_history_timestamp": points[-1]["clock"] if points else None,
        "stale": stale,
        "threshold": 13,
    }

    if summary["max"] is not None:
        maxima = [
            entry for entry in points
            if math.isclose(entry["value"], summary["max"], rel_tol=1e-9, abs_tol=1e-9)
        ]
        summary["max_timestamp"] = maxima[-1]["clock"] if maxima else None

    if current is None:
        status = "NOT_AVAILABLE"
        reason = "Current Huawei modulation value is not available."
    elif current < 13:
        status = "WARNING"
        reason = "Current Huawei modulation is below 13."
    elif stale:
        status = "UNKNOWN"
        reason = "Current modulation timestamp is stale or unavailable."
    elif len(points) < minimum_samples:
        status = "UNKNOWN"
        reason = (
            f"Insufficient numerical history in the last {history_hours} hours "
            f"({len(points)} samples; {minimum_samples} required)."
        )
    else:
        max_value = summary["max"]
        if max_value is not None and math.isclose(
            current, max_value, rel_tol=1e-9, abs_tol=1e-9
        ):
            status = "PASS"
            reason = "Current modulation equals the maximum value in the available history window."
        else:
            status = "WARNING"
            reason = "Current modulation is below the maximum value observed in the history window."

    return {
        "status": status,
        "reason": reason,
        **summary,
    }


def _history_points(history: dict[str, list[dict]], itemid: str) -> list[dict]:
    value = history.get(str(itemid), [])
    if isinstance(value, dict):
        return value.get("history", []) or []
    return value if isinstance(value, list) else []



def evaluate_packet_loss(value: Any) -> dict[str, Any]:
    numeric = to_float(value)
    if numeric is None:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "warning_threshold": 5,
            "critical_threshold": 80,
            "description": "Packet loss unavailable.",
        }
    if numeric > 80:
        status = "CRITICAL"
        description = "Packet loss above 80%."
    elif numeric >= 5:
        status = "WARNING"
        description = "Packet loss is at or above 5%."
    else:
        status = "PASS"
        description = "Packet loss is below 5%."
    return {
        "status": status,
        "value": numeric,
        "warning_threshold": 5,
        "critical_threshold": 80,
        "description": description,
    }


def _packet_loss_record(
    items: list[dict],
    trigger_index: dict[str, list[dict]],
) -> dict[str, Any] | None:
    for item in items:
        key = str(item.get("key_") or "").lower()
        name = str(item.get("name") or "").lower()
        if key != "packetloss" and "packet loss" not in name:
            continue
        metric = _metric(item)
        related = trigger_index.get(metric["itemid"], [])
        trigger_health = _trigger_summary(related)
        check = evaluate_packet_loss(metric["value"])
        if trigger_health["status"] in ("CRITICAL", "WARNING"):
            status = aggregate_status([check["status"], trigger_health["status"]])
        else:
            status = check["status"]
        return {
            **metric,
            **check,
            "trigger_health": trigger_health,
            "status": status,
        }
    return None


def _metric_records(
    items: list[dict],
    trigger_index: dict[str, list[dict]],
    history: dict[str, list[dict]] | None = None,
    *,
    history_hours: int = 12,
    now: int | None = None,
) -> list[dict[str, Any]]:
    records = []
    for item in items:
        key = str(item.get("key_") or "")
        lower = key.lower()
        if not lower.startswith("modulation_huawei["):
            continue
        metric = _metric(item)
        related = trigger_index.get(metric["itemid"], [])
        metric["link"] = _item_link_name(item, related)
        metric["trigger_health"] = _trigger_summary(related)
        metric["history"] = evaluate_modulation_history(
            item,
            _history_points(history or {}, metric["itemid"]),
            now=now,
            history_hours=history_hours,
        )
        trigger_status = metric["trigger_health"]["status"]
        history_status = metric["history"]["status"]
        metric["status"] = aggregate_status([
            history_status,
            trigger_status if trigger_status in ("CRITICAL", "WARNING") else history_status,
        ])
        records.append(metric)
    return records


def _traffic_records(
    items: list[dict],
    trigger_index: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    records = []
    for item in items:
        key = str(item.get("key_") or "")
        lower_key = key.lower()
        name = str(item.get("name") or "").lower()
        direction = None
        if re.search(r"(^|[^a-z])rx[_ .-]?traffic|ifhcin", lower_key + " " + name):
            direction = "RX"
        elif re.search(r"(^|[^a-z])tx[_ .-]?traffic|ifhcout", lower_key + " " + name):
            direction = "TX"
        if not direction:
            continue
        metric = _metric(item)
        related = trigger_index.get(metric["itemid"], [])
        parameter_match = re.search(r"\[(.*)\]", key)
        source = parameter_match.group(1).strip() if parameter_match else None
        decoded_source = decode_zabbix_encoded(source) if source else None
        metric.update({
            "direction": direction,
            "source": source,
            "decoded_source": decoded_source,
            "link": _item_link_name(item, related),
            "destination": _item_link_name(item, related),
            "trigger_health": _trigger_summary(related),
        })
        # Do not invent a traffic threshold: only enabled Zabbix triggers
        # are permitted to provide a traffic health verdict.
        metric["status"] = metric["trigger_health"]["status"]
        records.append(metric)
    return records


def _difference_records(
    items: list[dict],
    trigger_index: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    records = []
    for item in items:
        key = str(item.get("key_") or "")
        lower_key = key.lower()
        name = str(item.get("name") or "").lower()
        if "rx_tx_diff" not in lower_key and "rx tx diff" not in name:
            continue
        metric = _metric(item)
        related = trigger_index.get(metric["itemid"], [])
        metric["link"] = _item_link_name(item, related)
        metric["trigger_health"] = _trigger_summary(related)
        value = metric["value"]
        if value is None:
            metric["status"] = "NOT_AVAILABLE"
            metric["reason"] = "RX/TX difference is unavailable."
        elif abs(value) < 7:
            metric["status"] = "PASS"
            metric["reason"] = "Absolute RX/TX difference is below 7."
        else:
            metric["status"] = "WARNING"
            metric["reason"] = "Absolute RX/TX difference is at least 7."
        records.append(metric)
    return records


def analyze_rtn(
    items: list[dict],
    triggers: list[dict],
    history: dict[str, list[dict]] | None = None,
    *,
    history_hours: int = 12,
    now: int | None = None,
) -> dict[str, Any]:
    trigger_index = build_trigger_index(triggers)
    modulation = _metric_records(
        items, trigger_index, history,
        history_hours=history_hours, now=now,
    )
    traffic = _traffic_records(items, trigger_index)
    differences = _difference_records(items, trigger_index)
    packet_loss = _packet_loss_record(items, trigger_index)

    grouped: dict[str, dict[str, Any]] = {}
    for record in modulation + traffic + differences:
        link_name = str(record.get("link") or "Unlabelled link")
        link = grouped.setdefault(
            link_name,
            {
                "destination": link_name,
                "modulation": [],
                "difference": [],
                "traffic": {"RX": [], "TX": []},
                "status": "UNKNOWN",
            },
        )
        if record in modulation:
            link["modulation"].append(record)
        elif record in traffic:
            link["traffic"][record["direction"]].append(record)
        else:
            link["difference"].append(record)

    for link in grouped.values():
        statuses = []
        statuses.extend(item["status"] for item in link["modulation"])
        statuses.extend(item["status"] for item in link["difference"])
        statuses.extend(
            item["status"]
            for direction in ("RX", "TX")
            for item in link["traffic"][direction]
        )
        link["status"] = aggregate_status(statuses)

    all_statuses = [entry["status"] for entry in grouped.values()]
    if packet_loss is not None:
        all_statuses.append(packet_loss["status"])
    return {
        "type": "RTN",
        "status": aggregate_status(all_statuses),
        "history_window_hours": history_hours,
        "summary": {
            "link_count": len(grouped),
            "modulation_count": len(modulation),
            "difference_count": len(differences),
            "traffic_count": len(traffic),
        },
        "links": list(grouped.values()),
        "modulation": modulation,
        "difference": differences,
        "traffic": traffic,
        "packet_loss": packet_loss,
    }


def analyze_generic_radio(
    items: list[dict],
    triggers: list[dict],
    radio_type: str,
) -> dict[str, Any]:
    trigger_index = build_trigger_index(triggers)
    metrics = []
    for item in items:
        key = str(item.get("key_") or "")
        name = str(item.get("name") or "")
        lower = (key + " " + name).lower()
        if not any(token in lower for token in (
            "traffic", "ifhcin", "ifhcout", "rx.", "tx.",
            "rxpower", "txpower", "packetloss", "snr", "snir",
        )):
            continue
        metric = _metric(item)
        related = trigger_index.get(metric["itemid"], [])
        metric["link"] = _item_link_name(item, related)
        metric["trigger_health"] = _trigger_summary(related)
        metric["status"] = metric["trigger_health"]["status"]
        metrics.append(metric)

    status = aggregate_status([entry["status"] for entry in metrics])
    return {
        "type": radio_type,
        "status": status,
        "metric_count": len(metrics),
        "metrics": metrics,
        "triggers": [
            _trigger_summary([trigger]) for trigger in triggers
            if str(trigger.get("status", "0")) == "0"
        ],
        "reason": (
            "Metrics and Zabbix triggers are preserved without applying "
            "unverified vendor-specific thresholds."
        ),
    }
