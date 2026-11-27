from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


app = FastAPI(
    title="POP Audit Report Service",
    version="2.0.0",
)


REPORT_DIR = Path(
    os.getenv(
        "REPORT_DIR",
        "/opt/pop-audit/reports",
    )
)

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


STATUS_PRIORITY = {
    "CRITICAL": 5,
    "WARNING": 4,
    "UNKNOWN": 3,
    "NOT_AVAILABLE": 2,
    "PASS": 1,
    "NOT_EXISTS": 0,
}


STATUS_FILL = {
    "PASS": "C6EFCE",
    "WARNING": "FFEB9C",
    "CRITICAL": "FFC7CE",
    "UNKNOWN": "D9E1F2",
    "NOT_AVAILABLE": "E7E6E6",
    "NOT_EXISTS": "F2F2F2",
}


HEADER_FILL = "1F4E78"
HEADER_FONT = "FFFFFF"
TITLE_FILL = "17365D"


thin_gray = Side(
    style="thin",
    color="D9E1F2",
)

BORDER = Border(
    left=thin_gray,
    right=thin_gray,
    top=thin_gray,
    bottom=thin_gray,
)


# ============================================================
# Status helpers
# ============================================================

def aggregate_status(
    statuses: list[str],
) -> str:

    if not statuses:
        return "UNKNOWN"

    return max(
        statuses,
        key=lambda value: STATUS_PRIORITY.get(
            value,
            3,
        ),
    )


def service_status(result: Any) -> str:
    if not isinstance(result, dict):
        return "UNKNOWN"
    status = result.get("status")
    if status in STATUS_PRIORITY:
        return status
    if status == "COMPLETED":
        data = result.get("data")
        if isinstance(data, dict) and data.get("status") in STATUS_PRIORITY:
            return data["status"]
        return "UNKNOWN"
    return "UNKNOWN"

def find_data(
    result: dict[str, Any],
) -> dict[str, Any]:

    data = result.get(
        "data"
    )

    if isinstance(data, dict):
        return data

    return result


# ============================================================
# Excel helpers
# ============================================================

def style_header(
    ws,
    row: int,
) -> None:

    for cell in ws[row]:

        if cell.value is None:
            continue

        cell.fill = PatternFill(
            "solid",
            fgColor=HEADER_FILL,
        )

        cell.font = Font(
            bold=True,
            color=HEADER_FONT,
        )

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
        )

        cell.border = BORDER


def style_title(
    ws,
    cell_range: str,
) -> None:

    for row in ws[cell_range]:

        for cell in row:

            cell.fill = PatternFill(
                "solid",
                fgColor=TITLE_FILL,
            )

            cell.font = Font(
                bold=True,
                color="FFFFFF",
                size=14,
            )

            cell.alignment = Alignment(
                horizontal="left",
                vertical="center",
            )


def style_body(
    ws,
    min_row: int,
    max_row: int,
    max_col: int,
) -> None:

    for row in ws.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=1,
        max_col=max_col,
    ):

        for cell in row:

            cell.border = BORDER

            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )


def style_status_cell(
    cell,
) -> None:

    status = str(
        cell.value or ""
    ).upper()

    color = STATUS_FILL.get(
        status
    )

    if not color:
        return

    cell.fill = PatternFill(
        "solid",
        fgColor=color,
    )

    cell.font = Font(
        bold=True,
    )

    cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
    )


def auto_width(
    ws,
    max_width: int = 38,
) -> None:

    for column_cells in ws.columns:

        length = 0

        for cell in column_cells:

            value = (
                ""
                if cell.value is None
                else str(cell.value)
            )

            if "\n" in value:
                value = max(
                    value.split("\n"),
                    key=len,
                )

            length = max(
                length,
                len(value),
            )

        width = min(
            max(length + 2, 10),
            max_width,
        )

        ws.column_dimensions[
            get_column_letter(
                column_cells[0].column
            )
        ].width = width


def add_kpi(
    ws,
    row: int,
    label: str,
    value: Any,
) -> None:

    ws.cell(
        row=row,
        column=1,
        value=label,
    )

    ws.cell(
        row=row,
        column=2,
        value=value,
    )

    ws.cell(
        row=row,
        column=1,
    ).font = Font(
        bold=True,
    )

    ws.cell(
        row=row,
        column=1,
    ).fill = PatternFill(
        "solid",
        fgColor="D9EAF7",
    )

    ws.cell(
        row=row,
        column=1,
    ).border = BORDER

    ws.cell(
        row=row,
        column=2,
    ).border = BORDER


# ============================================================
# Summary
# ============================================================

def build_summary(
    wb: Workbook,
    site_code: str,
    results: dict[str, Any],
    summary: dict[str, Any] | None = None,
    audit_status: str | None = None,
) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.merge_cells("A1:F1")
    ws["A1"] = f"POP AUDIT REPORT - SITE {site_code}"
    style_title(ws, "A1:F1")
    audit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    categories = (summary or {}).get("categories") or {}
    ordered = ("Cisco Switch", "BB1", "BB2", "NCS 540", "EBand", "Huawei RTN", "Intracom", "NRay")
    applicable = [categories.get(name, "UNKNOWN") for name in ordered if categories.get(name, "NOT_EXISTS") != "NOT_EXISTS"]
    overall = audit_status or aggregate_status(applicable)
    add_kpi(ws, 3, "Site Code", site_code)
    add_kpi(ws, 4, "Audit Time", audit_time)
    add_kpi(ws, 5, "Overall Status", overall)
    style_status_cell(ws["B5"])
    ws["A7"] = "POP COMPONENT"
    ws["B7"] = "STATUS"
    style_header(ws, 7)
    row = 8
    for name in ordered:
        ws.cell(row=row, column=1, value=name)
        ws.cell(row=row, column=2, value=categories.get(name, "UNKNOWN"))
        style_status_cell(ws.cell(row=row, column=2))
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="SERVICE")
    ws.cell(row=row, column=2, value="STATUS")
    style_header(ws, row)
    row += 1
    for name in ("cisco", "ericsson", "radio"):
        ws.cell(row=row, column=1, value=name.upper())
        ws.cell(row=row, column=2, value=service_status(results.get(name)))
        style_status_cell(ws.cell(row=row, column=2))
        row += 1
    ws.freeze_panes = "A8"
    auto_width(ws)

def build_devices(wb: Workbook, results: dict[str, Any]) -> None:
    ws = wb.create_sheet("Devices")
    ws.append(["Service / Device Type","Hostname","IP","Zabbix Host ID","Status"])
    style_header(ws, 1)
    for service_name, result in results.items():
        data = find_data(result)
        if service_name == "cisco":
            devices = data.get("results") or []
            for device in devices:
                device_type = str(device.get("device_type") or "switch").upper()
                label = "NCS 540" if device_type == "NCS540" else f"Cisco {device_type}"
                ws.append([
                    label, device.get("hostname"), device.get("ip"),
                    device.get("zabbix_hostid"), device.get("status"),
                ])
        elif service_name == "ericsson":
            for device in data.get("results", []):
                ws.append([
                    "Ericsson Baseband", device.get("hostname"), device.get("ip"),
                    device.get("zabbix_hostid"), device.get("status"),
                ])
        elif service_name == "radio":
            for link in data.get("links", []):
                ws.append([
                    link.get("link_type"), link.get("name"), None,
                    link.get("zabbix_hostid"), link.get("status"),
                ])
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=5):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws)



def build_cisco(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("Cisco Switches")
    ws.append(["Hostname","IP","Zabbix Host ID","Interface","Description","Status","Admin/Oper","Speed","Duplex","CRC","Input Errors","Output Errors","Output Drops","Health Reason"])
    style_header(ws, 1)
    data = find_data(result)
    devices = data.get("switches")
    if not isinstance(devices, list):
        devices = [d for d in data.get("results", []) if str(d.get("device_type", "")).lower() != "ncs540"]
    for device in devices:
        interfaces = device.get("checks", {}).get("interfaces", {}).get("data", [])
        if not interfaces:
            ws.append([device.get("hostname"),device.get("ip"),device.get("zabbix_hostid"),None,None,device.get("status"),None,None,None,None,None,None,None,device.get("message") or device.get("error")])
            continue
        for item in interfaces:
            ws.append([device.get("hostname"),device.get("ip"),device.get("zabbix_hostid"),item.get("interface"),item.get("description"),item.get("health"),f'{item.get("status_raw") or ""} / {item.get("protocol") or ""}',item.get("speed"),item.get("duplex"),item.get("crc"),item.get("input_errors"),item.get("output_errors"),item.get("output_drops"),item.get("health_reason")])
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=6, max_col=6):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws)

def build_ericsson(
    wb: Workbook,
    result: dict[str, Any],
) -> None:

    ws = wb.create_sheet(
        "Ericsson"
    )

    ws.append([
        "Hostname",
        "IP",
        "Overall Status",
        "LT All",
        "Cell Status",
        "Cell Count",
        "Alarm Status",
        "Alarm Count",
        "Critical",
        "Major",
        "Clock Status",
        "Clock State",
        "Clock Value",
    ])

    style_header(
        ws,
        1,
    )

    data = find_data(
        result
    )

    for device in data.get(
        "results",
        [],
    ):

        checks = device.get(
            "checks",
            {}
        )

        cells = checks.get(
            "cells",
            {}
        )

        alarms = checks.get(
            "alarms",
            {}
        )

        clock = checks.get(
            "clock",
            {}
        )

        ws.append([
            device.get("hostname"),
            device.get("ip"),
            device.get("status"),
            checks.get(
                "lt_all",
                {}
            ).get("status"),
            cells.get("status"),
            cells.get("count"),
            alarms.get("status"),
            alarms.get("total"),
            alarms.get("critical"),
            alarms.get("major"),
            clock.get("status"),
            clock.get("state"),
            clock.get("value"),
        ])

    style_body(
        ws,
        2,
        ws.max_row,
        ws.max_column,
    )

    for row in ws.iter_rows(
        min_row=2,
        max_row=ws.max_row,
    ):

        for index in (
            3,
            4,
            5,
            7,
            11,
        ):

            style_status_cell(
                row[index - 1]
            )

    ws.freeze_panes = "A2"

    auto_width(
        ws
    )

    # Alarm details
    detail = wb.create_sheet(
        "Ericsson Alarms"
    )

    detail.append([
        "Hostname",
        "Severity",
        "Timestamp",
        "Problem",
        "Additional Text",
        "Raw",
    ])

    style_header(
        detail,
        1,
    )

    for device in data.get(
        "results",
        [],
    ):

        alarms = (
            device.get(
                "checks",
                {}
            )
            .get(
                "alarms",
                {}
            )
            .get(
                "alarms",
                []
            )
        )

        for alarm in alarms:

            detail.append([
                device.get("hostname"),
                alarm.get("severity"),
                alarm.get("timestamp"),
                alarm.get("problem"),
                alarm.get("additional_text"),
                alarm.get("raw"),
            ])

    style_body(
        detail,
        2,
        detail.max_row,
        detail.max_column,
    )

    for row in detail.iter_rows(
        min_row=2,
        min_col=2,
        max_col=2,
    ):
        style_status_cell(
            row[0]
        )

    detail.freeze_panes = "A2"

    auto_width(
        detail,
        50,
    )


# ============================================================
# RTN
# ============================================================

def build_rtn(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("RTN")
    ws.append([
        "Radio Host", "Link / Destination", "Overall Status",
        "Modulation Status", "Difference Status", "Traffic Status",
        "Modulation Current", "Modulation Maximum", "History Samples",
        "Current Timestamp", "Maximum Timestamp", "Packet Loss", "Packet Loss Status",
    ])
    style_header(ws, 1)
    data = find_data(result)

    for link in data.get("links", []):
        if str(link.get("link_type", "")).upper() != "RTN":
            continue
        analysis = link.get("analysis", {})
        for item in analysis.get("links", []):
            modulation = item.get("modulation") or []
            differences = item.get("difference") or []
            traffic = item.get("traffic") or {}
            modulation_statuses = [
                str(value.get("status", "UNKNOWN")).upper()
                for value in modulation if isinstance(value, dict)
            ]
            difference_statuses = [
                str(value.get("status", "UNKNOWN")).upper()
                for value in differences if isinstance(value, dict)
            ]
            traffic_statuses = []
            for direction in ("RX", "TX"):
                values = traffic.get(direction, []) if isinstance(traffic, dict) else []
                traffic_statuses.extend(
                    str(value.get("status", "UNKNOWN")).upper()
                    for value in values if isinstance(value, dict)
                )
            current_values = [
                value for value in modulation
                if isinstance(value, dict) and value.get("value") is not None
            ]
            latest = current_values[-1] if current_values else {}
            history = latest.get("history", {}) if isinstance(latest.get("history"), dict) else {}
            packet_loss = analysis.get("packet_loss") or {}
            ws.append([
                link.get("name"),
                item.get("destination"),
                item.get("status"),
                aggregate_status(modulation_statuses),
                aggregate_status(difference_statuses),
                aggregate_status(traffic_statuses),
                latest.get("value"),
                history.get("max"),
                history.get("history_count"),
                history.get("current_timestamp"),
                history.get("max_timestamp"),
                packet_loss.get("value"),
                packet_loss.get("status"),
            ])

    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=6):
        for cell in row:
            style_status_cell(cell)
    ws.freeze_panes = "A2"
    auto_width(ws)



def build_eband(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("EBand")
    ws.append(["Radio Host","Zabbix Host ID","Slot","RX","RX Units","TX","TX Units","RX Calloff","TX Calloff","Calculated Difference","Difference Status","RX Status","RX Modulation","Modulation Status","Capacity Profile Input","Capacity Units","Interface Status","Overall Status"])
    style_header(ws, 1)
    data = find_data(result)
    for link in data.get("links", []):
        if str(link.get("link_type", "")).upper() != "EBAND":
            continue
        analysis = link.get("analysis", {})
        checks = analysis.get("checks", {})
        for slot in checks.get("difference", {}).get("slots", []):
            rx, tx = slot.get("rx", {}), slot.get("tx", {})
            modulation = slot.get("rx_modulation", {})
            diff = slot.get("difference", {})
            ws.append([link.get("name"),link.get("zabbix_hostid"),slot.get("slot"),rx.get("value"),rx.get("units"),tx.get("value"),tx.get("units"),slot.get("rx_calloff", {}).get("value"),slot.get("tx_calloff", {}).get("value"),diff.get("value"),diff.get("status"),slot.get("rx_health", {}).get("status"),modulation.get("metric", {}).get("value"),modulation.get("health", {}).get("status"),slot.get("capacity_profile_input", {}).get("value"),slot.get("capacity_profile_input", {}).get("units"),checks.get("interfaces", {}).get("status"),analysis.get("status")])
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2):
        for index in (11,12,14,17,18):
            style_status_cell(row[index-1])
    ws.freeze_panes = "A2"
    auto_width(ws)

def create_workbook(
    site_code: str,
    results: dict[str, Any],
    discovery: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    audit_status: str | None = None,
) -> tuple[Path, str]:
    wb = Workbook()
    build_summary(wb, site_code, results, summary, audit_status)
    build_devices(wb, results)
    if discovery:
        build_basebands(wb, discovery, results.get("ericsson", {}))
    if "cisco" in results:
        build_cisco(wb, results["cisco"])
        build_ncs(wb, results["cisco"])
        build_crc_problems(wb, results["cisco"])
        build_device_logs(wb, results["cisco"])
    if "ericsson" in results:
        build_ericsson(wb, results["ericsson"])
    if "radio" in results:
        build_rtn(wb, results["radio"])
        build_eband(wb, results["radio"])
        build_links(wb, results["radio"])

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_site = re.sub(r"[^A-Za-z0-9_-]", "_", site_code)
    filename = f"POP-Audit-{safe_site}-{timestamp}.xlsx"
    output = REPORT_DIR / filename
    wb.save(output)

    categories = (summary or {}).get("categories") or {}
    applicable = [value for value in categories.values() if value != "NOT_EXISTS"]
    overall = audit_status or (
        aggregate_status(applicable) if categories
        else aggregate_status([service_status(result) for result in results.values()])
    )
    return output, overall
@app.get("/health")
def health():
    return {
        "service": "report",
        "status": "ok",
    }


@app.post("/generate")
def generate_report(
    payload: dict,
):

    site_code = str(
        payload.get(
            "site_code",
            "",
        )
    ).strip()

    if not site_code:
        raise HTTPException(
            status_code=400,
            detail="site_code is required",
        )

    results = payload.get(
        "results",
        {},
    )

    if not isinstance(
        results,
        dict,
    ):
        raise HTTPException(
            status_code=400,
            detail="results must be an object",
        )

    try:

        output, overall = create_workbook(
            site_code,
            results,
            payload.get("discovery") or {},
            payload.get("summary") or {},
            payload.get("audit_status"),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Report generation failed: {exc}"
            ),
        )

    return {
        "service": "report",
        "site_code": site_code,
        "status": overall,
        "filename": output.name,
        "path": str(output),
        "download_url": (
            f"/download/{output.name}"
        ),
    }


@app.get("/download/{filename}")
def download_report(
    filename: str,
):

    safe_name = Path(
        filename
    ).name

    path = REPORT_DIR / safe_name

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Report not found",
        )

    return FileResponse(
        path,
        filename=safe_name,
        media_type=(
            "application/"
            "vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )

def build_basebands(wb: Workbook, discovery: dict[str, Any], ericsson_result: dict[str, Any]) -> None:
    ws = wb.create_sheet("Basebands")
    ws.append(["Slot","Exists","Hostname","IP","Zabbix Host ID","Status","LT All","Cell Status","Cell Count","Alarm Status","Relevant Alarms","Clock Status","Clock State","Clock Value","Reason"])
    style_header(ws, 1)
    data = find_data(ericsson_result)
    checks_by_host = {str(d.get("zabbix_hostid")): d for d in data.get("results", []) if d.get("zabbix_hostid")}
    for bb in discovery.get("basebands", []):
        device = checks_by_host.get(str(bb.get("zabbix_hostid") or ""), {})
        checks = device.get("checks", {})
        cells, alarms, clock = checks.get("cells", {}), checks.get("alarms", {}), checks.get("clock", {})
        ws.append([bb.get("name"),bb.get("exists"),bb.get("hostname"),bb.get("ip"),bb.get("zabbix_hostid"),device.get("status") or bb.get("status") or "UNKNOWN",checks.get("lt_all", {}).get("status"),cells.get("status"),cells.get("count"),alarms.get("status"),alarms.get("relevant_count"),clock.get("status"),clock.get("state"),clock.get("value"),bb.get("reason") or device.get("error") or device.get("message")])
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2):
        for index in (6,7,8,10,12):
            style_status_cell(row[index-1])
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_ncs(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("NCS 540")
    ws.append(["Hostname","IP","Zabbix Host ID","Interface","Description","Health","Line State","Protocol","CRC","Input Errors","Output Errors","Health Reason"])
    style_header(ws, 1)
    data = find_data(result)
    devices = data.get("ncs_devices")
    if not isinstance(devices, list):
        devices = [d for d in data.get("results", []) if str(d.get("device_type", "")).lower() == "ncs540"]
    for device in devices:
        interfaces = device.get("checks", {}).get("interfaces", {}).get("data", [])
        if not interfaces:
            ws.append([device.get("hostname"),device.get("ip"),device.get("zabbix_hostid"),None,None,device.get("status"),None,None,None,None,None,device.get("message") or device.get("error")])
            continue
        for item in interfaces:
            ws.append([device.get("hostname"),device.get("ip"),device.get("zabbix_hostid"),item.get("interface"),item.get("description"),item.get("health"),item.get("line_state"),item.get("protocol"),item.get("crc"),item.get("input_errors"),item.get("output_errors"),item.get("health_reason")])
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=6, max_col=6):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_crc_problems(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("CRC Problems")
    ws.append(["Device Type","Hostname","IP","Interface","CRC","Description"])
    style_header(ws, 1)
    data = find_data(result)
    for device in data.get("results", []):
        for item in device.get("checks", {}).get("interfaces", {}).get("data", []):
            crc = item.get("crc")
            if isinstance(crc, (int, float)) and crc > 0:
                ws.append([str(device.get("device_type") or "Cisco").upper(),device.get("hostname"),device.get("ip"),item.get("interface"),crc,item.get("description")])
    style_body(ws, 2, ws.max_row, ws.max_column)
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_links(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("Links")
    ws.append(["Radio Type","Link","Source Site","Destination","Zabbix Host ID","Link Status","Metric","Item Key","Value","Units","Timestamp","Metric Status","History Count","History Maximum","Maximum Timestamp","Trigger Status","Trigger Details","Reason"])
    style_header(ws, 1)
    data = find_data(result)
    for link in data.get("links", []):
        radio_type = str(link.get("link_type") or link.get("type") or "UNKNOWN").upper()
        analysis = link.get("analysis", {})
        base = [radio_type,link.get("name"),link.get("source_site"),link.get("destination_name") or link.get("destination_site"),link.get("zabbix_hostid"),link.get("status")]
        rows = []
        def add_metric(label, metric, status=None, reason=None):
            metric = metric if isinstance(metric, dict) else {}
            history = metric.get("history", {}) if isinstance(metric.get("history"), dict) else {}
            trigger = metric.get("trigger_health", {}) if isinstance(metric.get("trigger_health"), dict) else {}
            rows.append(base + [label,metric.get("key"),metric.get("value",metric.get("raw_value")),metric.get("units",""),metric.get("clock"),status or metric.get("status"),history.get("history_count"),history.get("max"),history.get("max_timestamp"),trigger.get("status"),json.dumps(trigger.get("triggers",[]),ensure_ascii=False),reason or metric.get("reason") or history.get("reason")])
        if radio_type == "EBAND":
            checks=analysis.get("checks",{})
            for slot in checks.get("difference",{}).get("slots",[]):
                ix=slot.get("slot")
                for field in ("rx","tx","rx_calloff","tx_calloff","zabbix_difference","capacity_profile_input"):
                    add_metric(f"Slot {ix} {field.upper()}",slot.get(field,{}))
                diff=slot.get("difference",{})
                add_metric(f"Slot {ix} Difference",{"value":diff.get("value"),"units":"dB","status":diff.get("status"),"reason":diff.get("reason")})
                add_metric(f"Slot {ix} RX Health",{"value":slot.get("rx",{}).get("value"),"units":slot.get("rx",{}).get("units"),"status":slot.get("rx_health",{}).get("status"),"reason":slot.get("rx_health",{}).get("reason")})
                mod=slot.get("rx_modulation",{})
                add_metric(f"Slot {ix} RX Modulation",mod.get("metric",{}),mod.get("health",{}).get("status"),mod.get("health",{}).get("reason"))
        elif radio_type == "RTN":
            for field,label in (("modulation","Huawei Modulation"),("difference","RX/TX Difference"),("traffic","Traffic")):
                for metric in analysis.get(field,[]) if isinstance(analysis.get(field),list) else []:
                    add_metric(label,metric)
            packet_loss = analysis.get("packet_loss")
            if isinstance(packet_loss, dict):
                add_metric("Packet Loss", packet_loss)
        else:
            for metric in analysis.get("metrics",[]):
                add_metric(radio_type+" Metric",metric)
        if not rows:
            rows.append(base+["No metric returned",None,None,None,None,None,None,None,None,None,None,analysis.get("reason")])
        for row in rows:
            ws.append(row)
    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=6, max_col=6):
        style_status_cell(row[0])
    for row in ws.iter_rows(min_row=2, min_col=12, max_col=12):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws, 48)



def build_device_logs(wb: Workbook, result: dict[str, Any]) -> None:
    ws = wb.create_sheet("Device Logs")
    ws.append(["Device Type","Hostname","Severity","Recent Event","Severity Counts"])
    style_header(ws, 1)
    data = find_data(result)
    devices = data.get("results", [])
    for device in devices:
        checks = device.get("checks", {})
        logging_data = checks.get("logging", {})
        events = logging_data.get("recent_10") or logging_data.get("recent_20") or []
        counts = logging_data.get("severity_counts", {})
        device_type = str(device.get("device_type") or "Cisco Switch").upper()
        if not events:
            ws.append([device_type,device.get("hostname"),logging_data.get("status") or "UNKNOWN",None,json.dumps(counts,ensure_ascii=False)])
            continue
        for event in events[-10:]:
            match = re.search(r"%[A-Z0-9_-]+-(\d+)-", str(event))
            severity_map = {0:"EMERGENCY",1:"ALERT",2:"CRITICAL",3:"ERROR",4:"WARNING",5:"NOTICE",6:"INFO",7:"DEBUG"}
            severity = severity_map.get(int(match.group(1))) if match else None
            ws.append([device_type,device.get("hostname"),severity,str(event),json.dumps(counts,ensure_ascii=False)])
    style_body(ws, 2, ws.max_row, ws.max_column)
    ws.freeze_panes = "A2"
    auto_width(ws, 55)

