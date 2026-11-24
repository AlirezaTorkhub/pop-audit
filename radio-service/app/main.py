from __future__ import annotations

import os
import re
from typing import Any

import requests
from fastapi import FastAPI, HTTPException

from app.eband import analyze_eband
from app.rtn import analyze_rtn


app = FastAPI(title="POP Audit Radio Service", version="1.1.0")

ZABBIX_SERVICE_URL = os.getenv("ZABBIX_SERVICE_URL", "http://zabbix-service:8002")
RADIO_MODULATION_HISTORY_HOURS = int(os.getenv("RADIO_MODULATION_HISTORY_HOURS", "12"))

STATUS_PRIORITY = {
    "CRITICAL": 5,
    "WARNING": 4,
    "UNKNOWN": 3,
    "NOT_AVAILABLE": 2,
    "PASS": 1,
}


def aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "UNKNOWN"
    return max(statuses, key=lambda value: STATUS_PRIORITY.get(value, 3))


def zabbix_get(path: str, timeout: int = 45) -> dict[str, Any]:
    response = requests.get(f"{ZABBIX_SERVICE_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_zabbix_host_items(hostid: str) -> list[dict]:
    return zabbix_get(f"/host/{hostid}/items").get("items", [])


def get_zabbix_host_triggers(hostid: str) -> list[dict]:
    return zabbix_get(f"/host/{hostid}/triggers").get("triggers", [])


def get_zabbix_item_history(hostid: str, itemid: str, hours: int) -> list[dict]:
    data = zabbix_get(
        f"/host/{hostid}/item/{itemid}/history?hours={hours}&limit=5000",
        timeout=60,
    )
    return data.get("history", [])


def normalize_link(link: dict) -> dict:
    hostid = link.get("hostid") or link.get("zabbix_hostid")
    radio_type = link.get("type") or link.get("link_type") or ""
    return {
        **link,
        "hostid": str(hostid) if hostid is not None else "",
        "type": str(radio_type).strip().upper(),
        "hostname": link.get("hostname") or link.get("name") or "",
    }


def extract_traffic_direction(item: dict) -> str | None:
    key = str(item.get("key_") or "").lower()
    name = str(item.get("name") or "").lower()
    combined = f"{key} {name}"

    if (
        key.startswith(("rx_traffic[", "rx_traffic", "ifhcin"))
        or re.search(r"\b(incoming|inbound|received|receive|rx)\b", combined)
    ):
        return "RX"

    if (
        key.startswith(("tx_traffic[", "tx_traffic", "ifhcout"))
        or re.search(r"\b(outgoing|outbound|transmitted|transmit|tx)\b", combined)
    ):
        return "TX"

    return None


def has_traffic_signature(item: dict) -> bool:
    key = str(item.get("key_") or "").lower()
    name = str(item.get("name") or "").lower()
    return (
        "traffic" in key
        or "traffic" in name
        or "ifhcin" in key
        or "ifhcout" in key
        or "bits received" in name
        or "bits sent" in name
        or "octets" in name
    )


def active_trigger_status(triggers: list[dict]) -> str | None:
    active_priorities = []
    for trigger in triggers:
        if str(trigger.get("value", "0")) != "1":
            continue
        if str(trigger.get("status", "0")) != "0":
            continue
        try:
            active_priorities.append(int(trigger.get("priority", 0)))
        except (TypeError, ValueError):
            continue

    if not active_priorities:
        return None
    highest = max(active_priorities)
    if highest >= 5:
        return "CRITICAL"
    if highest >= 2:
        return "WARNING"
    return "PASS"


def analyze_generic_traffic(
    items: list[dict],
    triggers: list[dict],
    technology: str,
) -> dict:
    rx_metrics = []
    tx_metrics = []

    for item in items:
        if not has_traffic_signature(item):
            continue
        direction = extract_traffic_direction(item)
        if direction not in {"RX", "TX"}:
            continue

        raw_value = item.get("lastvalue")
        try:
            numeric_value = float(raw_value) if raw_value not in (None, "") else None
        except (TypeError, ValueError):
            numeric_value = None

        entry = {
            "itemid": str(item.get("itemid") or ""),
            "name": item.get("name"),
            "key": item.get("key_"),
            "direction": direction,
            "value": numeric_value,
            "units": item.get("units") or "",
            "timestamp": item.get("lastclock"),
            "value_type": item.get("value_type"),
            "status": "PASS" if numeric_value is not None else "UNKNOWN",
        }
        (rx_metrics if direction == "RX" else tx_metrics).append(entry)

    metrics = rx_metrics + tx_metrics
    if not metrics:
        return {
            "type": technology,
            "status": "UNKNOWN",
            "reason": "No usable RX/TX traffic Items were found on this Host.",
            "rx": [],
            "tx": [],
        }

    metric_status = "PASS" if any(item["value"] is not None for item in metrics) else "UNKNOWN"
    trigger_status = active_trigger_status(triggers)
    statuses = [metric_status]
    if trigger_status:
        statuses.append(trigger_status)

    return {
        "type": technology,
        "status": aggregate_status(statuses),
        "rx": rx_metrics,
        "tx": tx_metrics,
        "trigger_status": trigger_status,
        "metric_count": len(metrics),
        "reason": "Traffic values are taken from active Zabbix Items; no local traffic thresholds are invented.",
    }


def extract_status(analysis: dict) -> str:
    status = analysis.get("status")
    return status if status in STATUS_PRIORITY else "UNKNOWN"


@app.get("/health")
def health():
    return {"status": "ok", "service": "radio-service"}


@app.post("/analyze")
def analyze(payload: dict):
    links = payload.get("links", payload.get("radio_links", []))
    if not isinstance(links, list):
        raise HTTPException(status_code=400, detail="links must be a list")

    results = []
    for raw_link in links:
        if not isinstance(raw_link, dict):
            results.append({"status": "UNKNOWN", "error": "Invalid radio link payload."})
            continue

        link = normalize_link(raw_link)
        hostid = link["hostid"]
        radio_type = link["type"]

        if not hostid:
            results.append({**link, "status": "UNKNOWN", "error": "Missing Zabbix hostid"})
            continue

        try:
            items = get_zabbix_host_items(hostid)
            if radio_type == "EBAND":
                items_by_key = {
                    str(item.get("key_")): item
                    for item in items
                    if isinstance(item, dict) and item.get("key_")
                }
                analysis = analyze_eband(
                    hostid,
                    link.get("hostname", ""),
                    items_by_key,
                )

            elif radio_type == "RTN":
                triggers = get_zabbix_host_triggers(hostid)
                modulation_items = [
                    item for item in items
                    if str(item.get("key_") or "").lower().startswith("modulation_huawei[")
                ]
                history_by_itemid = {}
                for item in modulation_items:
                    itemid = str(item.get("itemid") or "")
                    if not itemid:
                        continue
                    history_by_itemid[itemid] = get_zabbix_item_history(
                        hostid,
                        itemid,
                        RADIO_MODULATION_HISTORY_HOURS,
                    )

                analysis = analyze_rtn(
                    items,
                    triggers,
                    history_by_itemid=history_by_itemid,
                    history_hours=RADIO_MODULATION_HISTORY_HOURS,
                )

            elif radio_type in {"INTRACOM", "NRAY"}:
                triggers = get_zabbix_host_triggers(hostid)
                analysis = analyze_generic_traffic(items, triggers, radio_type)

            else:
                analysis = {
                    "type": radio_type or "UNKNOWN",
                    "status": "NOT_AVAILABLE",
                    "reason": "No Analyzer is configured for this radio technology.",
                }

            results.append({
                **link,
                "status": extract_status(analysis),
                "analysis": analysis,
            })

        except Exception as exc:
            results.append({
                **link,
                "status": "UNKNOWN",
                "error": str(exc),
            })

    overall_status = aggregate_status([
        result.get("status", "UNKNOWN")
        for result in results
    ])

    return {
        "status": overall_status,
        "link_count": len(results),
        "links": results,
    }
