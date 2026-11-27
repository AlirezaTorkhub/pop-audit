from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException

from app.eband import analyze_eband
from app.rtn import analyze_generic_radio, analyze_rtn


app = FastAPI(
    title="POP Audit Radio Service",
    version="2.0.0",
)

ZABBIX_SERVICE_URL = os.getenv(
    "ZABBIX_SERVICE_URL",
    "http://zabbix-service:8002",
)
RADIO_MODULATION_HISTORY_HOURS = max(
    1,
    min(168, int(os.getenv("RADIO_MODULATION_HISTORY_HOURS", "12"))),
)

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


def zabbix_get(path: str, timeout: int = 30, params: dict | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{ZABBIX_SERVICE_URL}{path}",
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_zabbix_host_items(hostid: str) -> list[dict]:
    return zabbix_get(f"/host/{quote(str(hostid), safe='')}/items").get("items", [])


def get_zabbix_host_triggers(hostid: str) -> list[dict]:
    return zabbix_get(f"/host/{quote(str(hostid), safe='')}/triggers").get("triggers", [])


def get_zabbix_host_history(
    hostid: str,
    item: dict,
    time_from: int,
    time_till: int,
) -> list[dict]:
    return zabbix_get(
        f"/host/{quote(str(hostid), safe='')}/history",
        timeout=60,
        params={
            "itemid": str(item.get("itemid")),
            "value_type": int(item.get("value_type")),
            "time_from": time_from,
            "time_till": time_till,
            "limit": 10000,
        },
    ).get("history", [])


def normalize_link(link: dict) -> dict:
    hostid = link.get("hostid") or link.get("zabbix_hostid")
    radio_type = link.get("type") or link.get("link_type") or ""
    return {
        **link,
        "hostid": str(hostid) if hostid is not None else "",
        "type": str(radio_type).upper(),
        "hostname": link.get("hostname") or link.get("name") or "",
    }


def extract_status(analysis: dict) -> str:
    status = analysis.get("status")
    return status if status in STATUS_PRIORITY else "UNKNOWN"


def _history_for_rtn(
    hostid: str,
    items: list[dict],
    now: int,
) -> tuple[dict[str, list[dict]], list[dict]]:
    time_from = now - RADIO_MODULATION_HISTORY_HOURS * 3600
    history: dict[str, list[dict]] = {}
    errors = []
    for item in items:
        key = str(item.get("key_") or "")
        if not key.lower().startswith("modulation_huawei["):
            continue
        try:
            value_type = int(item.get("value_type"))
            if value_type not in (0, 3):
                errors.append({
                    "itemid": str(item.get("itemid")),
                    "key": key,
                    "error": f"Unsupported non-numeric Zabbix value_type: {value_type}",
                })
                history[str(item.get("itemid"))] = []
                continue
            records = get_zabbix_host_history(
                hostid,
                item,
                time_from,
                now,
            )
            history[str(item.get("itemid"))] = records
        except Exception as exc:
            itemid = str(item.get("itemid"))
            history[itemid] = []
            errors.append({
                "itemid": itemid,
                "key": key,
                "error": str(exc),
            })
    return history, errors


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "radio-service",
        "modulation_history_hours": RADIO_MODULATION_HISTORY_HOURS,
    }


@app.post("/analyze")
def analyze(payload: dict):
    links = payload.get("links", payload.get("radio_links", []))
    if not isinstance(links, list):
        raise HTTPException(status_code=400, detail="links must be a list")

    results = []
    for raw_link in links:
        if not isinstance(raw_link, dict):
            results.append({
                "status": "UNKNOWN",
                "error": "Invalid radio link payload.",
            })
            continue

        link = normalize_link(raw_link)
        hostid = link.get("hostid", "")
        radio_type = link.get("type", "")

        if not hostid:
            results.append({
                **link,
                "status": "UNKNOWN",
                "error": "Missing Zabbix hostid.",
            })
            continue

        try:
            items = get_zabbix_host_items(hostid)
            triggers = get_zabbix_host_triggers(hostid)

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
                now = int(time.time())
                history, history_errors = _history_for_rtn(
                    hostid, items, now
                )
                analysis = analyze_rtn(
                    items,
                    triggers,
                    history,
                    history_hours=RADIO_MODULATION_HISTORY_HOURS,
                    now=now,
                )
                analysis["history_retrieval_errors"] = history_errors
            elif radio_type in {"INTRACOM", "NRAY"}:
                analysis = analyze_generic_radio(
                    items,
                    triggers,
                    radio_type,
                )
            else:
                analysis = {
                    "type": radio_type or "UNKNOWN",
                    "status": "UNKNOWN",
                    "reason": "Radio technology could not be identified from Zabbix metadata.",
                    "item_count": len(items),
                }

            results.append({
                **link,
                "status": extract_status(analysis),
                "analysis": analysis,
            })
        except requests.HTTPError as exc:
            results.append({
                **link,
                "status": "UNKNOWN",
                "error": f"Zabbix request failed: {exc}",
            })
        except Exception as exc:
            results.append({
                **link,
                "status": "UNKNOWN",
                "error": str(exc),
            })

    return {
        "status": aggregate_status([item.get("status", "UNKNOWN") for item in results]),
        "link_count": len(results),
        "links": results,
    }
