from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .client import ZabbixClient
from .discovery import SiteDiscovery
from .metric_models import (
    HostMetricInventory,
    MetricCandidate,
)

from .radio_metrics import classify_item


app = FastAPI(
    title="POP Audit - Zabbix Service",
    version="1.0.0",
)


class DiscoveryRequest(BaseModel):
    site_code: str


@app.get("/health")
def health():
    return {
        "service": "zabbix-service",
        "status": "ok",
    }


@app.post("/discover")
def discover(request: DiscoveryRequest):

    try:
        service = SiteDiscovery()

        result = service.discover(
            request.site_code
        )

        return result.model_dump()

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/debug/groups")
def debug_groups():

    try:

        client = ZabbixClient()
        client.login()

        groups = [
            "LTE-Backhaul-eNodeB",
            "LTE-Backhaul-Switch",
            "LTE-Backhaul-Radio",
        ]

        output = {}

        for group_name in groups:

            group = client.get_group_by_name(
                group_name
            )

            if not group:

                output[group_name] = {
                    "found": False,
                    "hosts": [],
                }

                continue

            hosts = client.get_hosts_by_group(
                group["groupid"]
            )

            output[group_name] = {
                "found": True,
                "groupid": group["groupid"],
                "host_count": len(hosts),
                "hosts": hosts,
            }

        return output

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/debug/all-groups")
def debug_all_groups():

    try:

        client = ZabbixClient()
        client.login()

        groups = client.call(
            "hostgroup.get",
            {
                "output": [
                    "groupid",
                    "name",
                ],
            },
        )

        return {
            "count": len(groups),
            "groups": groups,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/debug/host/{hostid}/items")
def debug_host_items(hostid: str):

    try:

        client = ZabbixClient()
        client.login()

        host = client.get_host(
            hostid
        )

        if not host:
            raise HTTPException(
                status_code=404,
                detail="Host not found.",
            )

        items = client.get_items(
            hostid
        )

        return {
            "host": {
                "hostid": host["hostid"],
                "name": host["name"],
            },
            "item_count": len(items),
            "items": items,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
@app.get("/debug/host/{hostid}/metrics")
def debug_host_metrics(hostid: str):

    try:

        client = ZabbixClient()
        client.login()

        host = client.get_host(hostid)

        if not host:

            raise HTTPException(
                status_code=404,
                detail="Host not found.",
            )

        items = client.get_items(hostid)

        categories = {}

        for item in items:

            metric_type = classify_item(
                item
            )

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

            categories.setdefault(
                metric_type,
                []
            ).append(
                metric
            )

        return HostMetricInventory(
            hostid=hostid,
            hostname=host["name"],
            item_count=len(items),
            metrics=categories,
        ).model_dump()

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/host/{hostid}/items")
def get_host_items(hostid: str):

    try:

        client = ZabbixClient()
        client.login()

        host = client.get_host(hostid)

        if not host:
            raise HTTPException(
                status_code=404,
                detail="Host not found.",
            )

        items = client.get_items(hostid)

        return {
            "host": {
                "hostid": host["hostid"],
                "name": host["name"],
            },
            "item_count": len(items),
            "items": items,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

@app.get("/debug/host/{hostid}/triggers")
def debug_host_triggers(hostid: str):

    try:

        client = ZabbixClient()
        client.login()

        host = client.get_host(
            hostid
        )

        if not host:

            raise HTTPException(
                status_code=404,
                detail="Host not found.",
            )

        triggers = client.get_triggers(
            hostid
        )

        return {
            "host": {
                "hostid": host["hostid"],
                "name": host["name"],
            },
            "trigger_count": len(triggers),
            "triggers": triggers,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/debug/host/{hostid}/macros")
def debug_host_macros(hostid: str):

    try:

        client = ZabbixClient()
        client.login()

        host = client.get_host(
            hostid
        )

        if not host:

            raise HTTPException(
                status_code=404,
                detail="Host not found.",
            )

        macros = client.get_user_macros(
            hostid
        )

        return {
            "host": {
                "hostid": host["hostid"],
                "name": host["name"],
            },
            "macro_count": len(macros),
            "macros": macros,
        }

    except HTTPException:
        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
@app.get("/host/{hostid}/triggers")
def host_triggers(hostid: str):
    try:
        client = ZabbixClient()

        client.login()

        triggers = client.get_triggers(hostid)

        return {
            "hostid": hostid,
            "count": len(triggers),
            "triggers": triggers,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


