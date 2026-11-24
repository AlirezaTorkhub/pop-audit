from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .client import ZabbixClient
from .discovery import SiteDiscovery
from .metric_models import HostMetricInventory, MetricCandidate
from .radio_metrics import classify_item


app = FastAPI(title="POP Audit - Zabbix Service", version="1.1.0")


class DiscoveryRequest(BaseModel):
    site_code: str


def authenticated_client() -> ZabbixClient:
    client = ZabbixClient()
    client.login()
    return client


@app.get("/health")
def health():
    return {"service": "zabbix-service", "status": "ok"}


@app.post("/discover")
def discover(request: DiscoveryRequest):
    try:
        result = SiteDiscovery().discover(request.site_code)
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/groups")
def debug_groups():
    try:
        client = authenticated_client()
        groups = [
            "LTE-Backhaul-eNodeB",
            "LTE-Backhaul-Switch",
            "LTE-Backhaul-Switch-Aggregation",
            "LTE-Backhaul-Radio",
            "LTE-Backhaul-Radio-Huawei",
        ]
        output = {}
        for group_name in groups:
            group = client.get_group_by_name(group_name)
            if not group:
                output[group_name] = {"found": False, "hosts": []}
                continue
            hosts = client.get_hosts_by_group(group["groupid"])
            output[group_name] = {
                "found": True,
                "groupid": group["groupid"],
                "host_count": len(hosts),
                "hosts": hosts,
            }
        return output
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/all-groups")
def debug_all_groups():
    try:
        client = authenticated_client()
        groups = client.get_all_groups()
        return {"count": len(groups), "groups": groups}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/host/{hostid}/items")
def debug_host_items(hostid: str):
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")
        items = client.get_items(hostid)
        return {
            "host": {"hostid": host["hostid"], "name": host["name"]},
            "item_count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/host/{hostid}/metrics")
def debug_host_metrics(hostid: str):
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")
        items = client.get_items(hostid)
        categories = {}
        for item in items:
            metric_type = classify_item(item)
            metric = MetricCandidate(
                itemid=item["itemid"],
                name=item["name"],
                key=item["key_"],
                value_type=item["value_type"],
                units=item["units"],
                lastvalue=item["lastvalue"],
                lastclock=item["lastclock"],
                metric_type=metric_type,
            )
            categories.setdefault(metric_type, []).append(metric)
        return HostMetricInventory(
            hostid=hostid,
            hostname=host["name"],
            item_count=len(items),
            metrics=categories,
        ).model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/host/{hostid}/items")
def get_host_items(hostid: str):
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")
        items = client.get_items(hostid)
        return {
            "host": {"hostid": host["hostid"], "name": host["name"]},
            "item_count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/host/{hostid}/item/{itemid}/history")
def get_item_history(
    hostid: str,
    itemid: str,
    hours: int = Query(default=12, ge=1, le=168),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Return real Zabbix history using the Item's native value_type."""
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")

        item = next(
            (entry for entry in client.get_items(hostid)
             if str(entry.get("itemid")) == str(itemid)),
            None,
        )
        if not item:
            raise HTTPException(
                status_code=404,
                detail="Item does not belong to this Host or is not enabled.",
            )

        try:
            value_type = int(item["value_type"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Item value_type is missing or invalid.",
            )

        now = int(time.time())
        time_from = now - hours * 3600
        history = client.get_history(
            itemid=itemid,
            value_type=value_type,
            time_from=time_from,
            time_till=now,
            limit=limit,
        )

        return {
            "hostid": hostid,
            "hostname": host["name"],
            "item": {
                "itemid": item["itemid"],
                "name": item.get("name"),
                "key": item.get("key_"),
                "value_type": value_type,
                "units": item.get("units") or "",
                "lastvalue": item.get("lastvalue"),
                "lastclock": item.get("lastclock"),
                "delay": item.get("delay"),
            },
            "hours": hours,
            "time_from": time_from,
            "time_till": now,
            "sample_count": len(history),
            "history": history,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/host/{hostid}/triggers")
def debug_host_triggers(hostid: str):
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")
        triggers = client.get_triggers(hostid)
        return {
            "host": {"hostid": host["hostid"], "name": host["name"]},
            "trigger_count": len(triggers),
            "triggers": triggers,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/debug/host/{hostid}/macros")
def debug_host_macros(hostid: str):
    try:
        client = authenticated_client()
        host = client.get_host(hostid)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found.")
        macros = client.get_user_macros(hostid)
        return {
            "host": {"hostid": host["hostid"], "name": host["name"]},
            "macro_count": len(macros),
            "macros": macros,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/host/{hostid}/triggers")
def host_triggers(hostid: str):
    try:
        client = authenticated_client()
        triggers = client.get_triggers(hostid)
        return {"hostid": hostid, "count": len(triggers), "triggers": triggers}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
