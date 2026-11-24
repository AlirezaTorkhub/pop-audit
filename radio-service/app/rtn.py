from __future__ import annotations

import re
import time
from typing import Any


DESTINATIONS = {
    "BOLVARSHAHRZAD",
    "BORJMINA",
    "GHOBA",
    "HOSEINIEHERSHAD",
    "MAHABGHODS",
    "SHAMS",
    "ZOMOROD",
}


def to_float(value: Any):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    return max(
        statuses,
        key=lambda x: order.get(x, 3),
    )


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

    try:
        decoded = "".join(chr(value) for value in values)
    except ValueError:
        return text

    printable = sum(
        1
        for character in decoded
        if character.isprintable()
        or character in "\r\n\t"
    )

    if decoded and printable / len(decoded) >= 0.85:
        return decoded

    return text


def evaluate_modulation(value: Any) -> dict:
    value = to_float(value)

    if value is None:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "threshold": 13,
            "description": "Modulation value unavailable",
        }

    if value < 13:
        return {
            "status": "WARNING",
            "value": value,
            "threshold": 13,
            "description": "Modulation below 13",
        }

    return {
        "status": "PASS",
        "value": value,
        "threshold": 13,
        "description": "Modulation is normal",
    }


def evaluate_difference(value: Any) -> dict:
    value = to_float(value)

    if value is None:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "threshold": 7,
            "description": "Difference unavailable",
        }

    if value >= 7:
        return {
            "status": "WARNING",
            "value": value,
            "threshold": 7,
            "description": "Difference at or above 7",
        }

    return {
        "status": "PASS",
        "value": value,
        "threshold": 7,
        "description": "Difference is normal",
    }


def evaluate_traffic(value: Any) -> dict:
    value = to_float(value)

    if value is None:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "warning_threshold": 350_000_000,
            "high_threshold": 410_000_000,
            "description": "Traffic unavailable",
        }

    if value > 410_000_000:
        return {
            "status": "WARNING",
            "value": value,
            "warning_threshold": 350_000_000,
            "high_threshold": 410_000_000,
            "description": "Traffic above 410 Mbps",
        }

    if value > 350_000_000:
        return {
            "status": "WARNING",
            "value": value,
            "warning_threshold": 350_000_000,
            "high_threshold": 410_000_000,
            "description": "Traffic above 350 Mbps",
        }

    return {
        "status": "PASS",
        "value": value,
        "warning_threshold": 350_000_000,
        "high_threshold": 410_000_000,
        "description": "Traffic is normal",
    }


def evaluate_packet_loss(value: Any) -> dict:
    value = to_float(value)

    if value is None:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "warning_threshold": 5,
            "critical_threshold": 80,
            "description": "Packet loss unavailable",
        }

    if value > 80:
        return {
            "status": "CRITICAL",
            "value": value,
            "warning_threshold": 5,
            "critical_threshold": 80,
            "description": "Packet loss above 80%",
        }

    if value > 20:
        return {
            "status": "WARNING",
            "value": value,
            "warning_threshold": 5,
            "critical_threshold": 80,
            "description": "Packet loss above 20%",
        }

    if value >= 5:
        return {
            "status": "WARNING",
            "value": value,
            "warning_threshold": 5,
            "critical_threshold": 80,
            "description": "Packet loss at/above 5%",
        }

    return {
        "status": "PASS",
        "value": value,
        "warning_threshold": 5,
        "critical_threshold": 80,
        "description": "Packet loss is normal",
    }


def extract_item_ids(expression: str) -> list[str]:
    return re.findall(
        r"\{(\d+)\}",
        expression or "",
    )


def extract_destination(
    description: str,
) -> str | None:
    """Extract a destination without restricting it to a legacy POP allow-list."""
    upper = re.sub(r"[_-]+", " ", (description or "").upper())

    # Keep recognizable legacy aliases for backwards-compatible display.
    for destination in DESTINATIONS:
        if destination in upper.replace(" ", ""):
            return destination

    match = re.search(
        r"\\b(?:TO|TOWARD|TOWARDS|FOR|DESTINATION)\\s+"
        r"([A-Z][A-Z0-9]*(?:\\s+[A-Z][A-Z0-9]*){0,2})",
        upper,
    )
    if match:
        candidate = re.sub(r"\\s+", " ", match.group(1)).strip()
        return candidate or None

    return None


def build_trigger_index(
    triggers: list[dict],
) -> dict[str, list[dict]]:

    result: dict[str, list[dict]] = {}

    for trigger in triggers:

        trigger_items = (
            trigger.get("items")
            or []
        )

        for item in trigger_items:

            itemid = str(
                item.get("itemid", "")
            ).strip()

            if not itemid:
                continue

            result.setdefault(
                itemid,
                [],
            ).append(trigger)

        if not trigger_items:

            for itemid in extract_item_ids(
                trigger.get(
                    "expression",
                    "",
                )
            ):

                result.setdefault(
                    itemid,
                    [],
                ).append(trigger)

    return result


def modulation_links(
    items: list[dict],
    triggers: list[dict],
) -> list[dict]:

    trigger_index = build_trigger_index(
        triggers
    )

    result = []

    for item in items:

        key = str(
            item.get("key_", "")
        )

        if not key.lower().startswith(
            "modulation_huawei["
        ):
            continue

        itemid = str(
            item.get("itemid", "")
        )

        related = trigger_index.get(
            itemid,
            [],
        )

        destinations = []

        for trigger in related:

            destination = extract_destination(
                trigger.get(
                    "description",
                    "",
                )
            )

            if (
                destination
                and destination not in destinations
            ):
                destinations.append(
                    destination
                )

        if not destinations:
            destinations = [None]

        link_name = key

        prefix = "Modulation_huawei["

        if (
            key.startswith(prefix)
            and key.endswith("]")
        ):
            link_name = key[
                len(prefix):-1
            ]

        for destination in destinations:

            result.append({
                "itemid": itemid,
                "key": key,
                "link": link_name,
                "destination": destination,
                "value": to_float(
                    item.get("lastvalue")
                ),
                "clock": item.get(
                    "lastclock"
                ),
            })

    return result


def traffic_items(
    items: list[dict],
    triggers: list[dict],
) -> list[dict]:

    trigger_index = build_trigger_index(
        triggers
    )

    result = []

    for item in items:

        key = str(
            item.get("key_", "")
        )

        lower_key = key.lower()

        if not (
            lower_key.startswith(
                "rx_traffic["
            )
            or lower_key.startswith(
                "tx_traffic["
            )
        ):
            continue

        direction = (
            "RX"
            if lower_key.startswith(
                "rx_traffic["
            )
            else "TX"
        )

        encoded = ""

        if "[" in key:
            encoded = key.split(
                "[",
                1,
            )[1].rstrip("]")

        itemid = str(
            item.get("itemid")
        )

        related = trigger_index.get(
            itemid,
            [],
        )

        destinations = []

        for trigger in related:

            name = trigger.get(
                "description",
                "",
            )

            upper_name = name.upper()

            if "TRAFFIC" not in upper_name:
                continue

            destination = extract_destination(
                name
            )

            if (
                destination
                and destination not in destinations
            ):
                destinations.append(
                    destination
                )

        if not destinations:
            destinations = [None]

        for destination in destinations:

            result.append({
                "itemid": itemid,
                "key": key,
                "direction": direction,
                "source": encoded,
                "decoded_source": (
                    decode_zabbix_encoded(
                        encoded
                    )
                ),
                "destination": destination,
                "value": to_float(
                    item.get("lastvalue")
                ),
                "clock": item.get(
                    "lastclock"
                ),
            })

    return result


def difference_items(
    items: list[dict],
) -> list[dict]:

    latest: dict[str, dict] = {}

    for item in items:

        key = str(
            item.get("key_", "")
        )

        lower_key = key.lower()

        if not lower_key.startswith(
            "rx_tx_diff_"
        ):
            continue

        destination = key[
            len("rx_tx_diff_"):
        ]

        if destination.endswith("_1"):
            destination = destination[:-2]

        destination = destination.upper()

        current_clock = int(
            item.get("lastclock") or 0
        )

        entry = {
            "itemid": str(
                item.get("itemid")
            ),
            "key": key,
            "destination": destination,
            "value": to_float(
                item.get("lastvalue")
            ),
            "clock": item.get(
                "lastclock"
            ),
        }

        previous = latest.get(
            destination
        )

        if (
            previous is None
            or current_clock
            >= int(previous.get("clock") or 0)
        ):
            latest[destination] = entry

    return list(
        latest.values()
    )


def packet_loss_item(
    items: list[dict],
) -> dict | None:

    for item in items:

        key = str(
            item.get("key_", "")
        ).lower()

        if key != "packetloss":
            continue

        value = to_float(
            item.get("lastvalue")
        )

        return {
            "itemid": str(
                item.get("itemid")
            ),
            "key": item.get("key_"),
            "value": value,
            "clock": item.get(
                "lastclock"
            ),
            **evaluate_packet_loss(value),
        }

    return None


def ensure_link(
    link_results: dict[str, dict],
    destination: str,
) -> dict:

    return link_results.setdefault(
        destination,
        {
            "destination": destination,
            "modulation": [],
            "difference": None,
            "traffic": {
                "RX": [],
                "TX": [],
            },
            "statuses": [],
        },
    )


def evaluate_modulation_history(
    current_value: Any,
    current_clock: Any,
    history: list[dict] | None,
    *,
    hours: int = 12,
    now: int | None = None,
) -> dict:
    """Compare the current value with real numeric Zabbix history samples."""
    now = int(now if now is not None else time.time())
    window_start = now - hours * 3600
    current = to_float(current_value)

    try:
        current_ts = int(current_clock)
    except (TypeError, ValueError):
        current_ts = 0

    if current is None:
        return {
            "status": "UNKNOWN",
            "current": None,
            "maximum": None,
            "sample_count": 0,
            "hours": hours,
            "reason": "Current modulation is not a valid numeric value.",
        }

    if current_ts < window_start or current_ts > now + 60:
        return {
            "status": "UNKNOWN",
            "current": current,
            "maximum": None,
            "sample_count": 0,
            "hours": hours,
            "current_timestamp": current_ts or None,
            "reason": "Current modulation sample is stale or has an invalid timestamp.",
        }

    samples: list[tuple[int, float]] = []
    for sample in history or []:
        value = to_float(sample.get("value"))
        try:
            clock = int(sample.get("clock") or 0)
        except (TypeError, ValueError):
            continue
        if value is not None and window_start <= clock <= now:
            samples.append((clock, value))

    if not samples:
        return {
            "status": "UNKNOWN",
            "current": current,
            "maximum": None,
            "sample_count": 0,
            "hours": hours,
            "current_timestamp": current_ts,
            "reason": "No numeric Zabbix history samples were returned for the requested window.",
        }

    # Make sure the current measurement participates in the maximum even if
    # Zabbix history and item.lastvalue are sampled on slightly different ticks.
    if not any(clock == current_ts for clock, _ in samples):
        samples.append((current_ts, current))

    maximum = max(value for _, value in samples)
    max_clock = max(clock for clock, value in samples if value == maximum)
    if current == maximum:
        status = "PASS"
        reason = "Current modulation equals the maximum observed modulation in the last 12 hours."
    else:
        status = "WARNING"
        reason = "Current modulation is below the maximum observed modulation in the last 12 hours."

    return {
        "status": status,
        "current": current,
        "maximum": maximum,
        "sample_count": len(samples),
        "hours": hours,
        "current_timestamp": current_ts,
        "maximum_timestamp": max_clock,
        "reason": reason,
    }


def analyze_rtn(
    items: list[dict],
    triggers: list[dict],
    history_by_itemid: dict[str, list[dict]] | None = None,
    history_hours: int = 12,
) -> dict:

    history_by_itemid = history_by_itemid or {}

    modulation = modulation_links(
        items,
        triggers,
    )

    differences = difference_items(
        items
    )

    traffic = traffic_items(
        items,
        triggers,
    )

    packet_loss = packet_loss_item(
        items
    )

    link_results: dict[
        str,
        dict,
    ] = {}

    # ---------------------------------------------------------
    # Difference
    # ---------------------------------------------------------

    for entry in differences:

        destination = entry[
            "destination"
        ]

        # Destination names are dynamic; do not reject newly deployed POPs.
        if not destination:
            destination = entry.get("key") or "UNKNOWN-LINK"

        link = ensure_link(
            link_results,
            destination,
        )

        check = evaluate_difference(
            entry["value"]
        )

        link["difference"] = {
            "itemid": entry["itemid"],
            "value": entry["value"],
            **check,
        }

        link["statuses"].append(
            check["status"]
        )

    # ---------------------------------------------------------
    # Modulation
    # ---------------------------------------------------------

    for entry in modulation:

        destination = entry.get("destination") or entry.get("link") or "UNKNOWN-LINK"

        link = ensure_link(
            link_results,
            destination,
        )

        threshold_check = evaluate_modulation(entry["value"])
        history_check = evaluate_modulation_history(
            entry["value"],
            entry.get("clock"),
            history_by_itemid.get(str(entry["itemid"]), []),
            hours=history_hours,
        )

        check_status = aggregate_status([
            threshold_check["status"],
            history_check["status"],
        ])
        link["modulation"].append({
            "itemid": entry["itemid"],
            "link": entry["link"],
            "value": entry["value"],
            "clock": entry.get("clock"),
            "status": check_status,
            "threshold_check": threshold_check,
            "history_comparison": history_check,
        })

        link["statuses"].append(check_status)

    # ---------------------------------------------------------
    # Traffic
    # ---------------------------------------------------------

    traffic_results = []

    for entry in traffic:

        check = evaluate_traffic(
            entry["value"]
        )

        traffic_entry = {
            "itemid": entry["itemid"],
            "direction": entry["direction"],
            "source": entry["source"],
            "decoded_source": entry[
                "decoded_source"
            ],
            "destination": entry[
                "destination"
            ],
            "value": entry["value"],
            **check,
        }

        traffic_results.append(
            traffic_entry
        )

        destination = entry.get("destination") or entry.get("decoded_source") or entry.get("source") or "UNKNOWN-LINK"

        link = ensure_link(
            link_results,
            destination,
        )

        direction = entry[
            "direction"
        ]

        link["traffic"][
            direction
        ].append({
            "itemid": entry[
                "itemid"
            ],
            "source": entry[
                "source"
            ],
            "decoded_source": entry[
                "decoded_source"
            ],
            "value": entry[
                "value"
            ],
            **check,
        })

        link["statuses"].append(
            check["status"]
        )

    # ---------------------------------------------------------
    # Finalize each destination
    # ---------------------------------------------------------

    for link in link_results.values():

        link["status"] = aggregate_status(
            link["statuses"]
        )

        link.pop(
            "statuses",
            None,
        )

    # ---------------------------------------------------------
    # Overall status
    # ---------------------------------------------------------

    status_inputs = [
        link["status"]
        for link in link_results.values()
    ]

    if packet_loss is not None:
        status_inputs.append(
            packet_loss["status"]
        )

    overall_status = aggregate_status(
        status_inputs
    )

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    return {
        "type": "RTN",
        "status": overall_status,
        "summary": {
            "link_count": len(
                link_results
            ),
            "modulation_count": len(
                modulation
            ),
            "difference_count": len(
                differences
            ),
            "traffic_count": len(
                traffic_results
            ),
        },
        "links": list(
            link_results.values()
        ),
        "packet_loss": packet_loss,
        "traffic": traffic_results,
    }
