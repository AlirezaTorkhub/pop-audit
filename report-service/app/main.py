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
    "NOT_EXISTS": 0,
    "PASS": 1,
}


STATUS_FILL = {
    "PASS": "C6EFCE",
    "WARNING": "FFEB9C",
    "CRITICAL": "FFC7CE",
    "UNKNOWN": "D9E1F2",
    "NOT_AVAILABLE": "E7E6E6",
    "NOT_EXISTS": "E7E6E6",
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


def service_status(
    result: Any,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return "UNKNOWN"

    status = result.get("status")

    if status in STATUS_PRIORITY:
        return status

    if status == "COMPLETED":

        data = result.get(
            "data"
        )

        if isinstance(data, dict):

            data_status = data.get(
                "status"
            )

            if data_status in STATUS_PRIORITY:
                return data_status

        return "PASS"

    if status == "FAILED":
        return "CRITICAL"

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
) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.merge_cells("A1:F1")
    ws["A1"] = f"POP AUDIT REPORT - SITE {site_code}"
    style_title(ws, "A1:F1")

    audit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    statuses = {
        name: service_status(result)
        for name, result in results.items()
    }

    cisco_data = find_data(results.get("cisco", {}))
    ericsson_data = find_data(results.get("ericsson", {}))
    radio_data = find_data(results.get("radio", {}))

    cisco_devices = cisco_data.get("results", []) or []
    ncs_devices = [
        device for device in cisco_devices
        if str(device.get("device_type") or "").lower() in {"ncs", "ncs540", "ncs_540"}
        or str(device.get("role") or "").lower() == "ncs_aggregation"
    ]
    primary_switches = [device for device in cisco_devices if device not in ncs_devices]

    basebands = ericsson_data.get("results", []) or []
    bb1 = [device for device in basebands if str(device.get("role") or "").upper() == "BB1"]
    bb2 = [device for device in basebands if str(device.get("role") or "").upper() == "BB2"]
    if basebands and not bb1:
        bb1 = basebands[:1]

    radio_links = radio_data.get("links", []) or []
    def links_of(kind: str) -> list[dict]:
        return [
            link for link in radio_links
            if str(link.get("link_type") or "").upper().replace("_", "") == kind
        ]

    def collection_status(rows: list[dict]) -> str:
        if not rows:
            return "NOT_EXISTS"
        return aggregate_status([
            str(row.get("status") or "UNKNOWN").upper()
            for row in rows
        ])

    category_statuses = {
        "Cisco Switch": collection_status(primary_switches),
        "Baseband 1": collection_status(bb1),
        "Baseband 2": collection_status(bb2),
        "NCS 540": collection_status(ncs_devices),
        "EBand Radios": collection_status(links_of("EBAND")),
        "RTN Radios": collection_status(links_of("RTN")),
        "Intracom Radios": collection_status(links_of("INTRACOM")),
        "NRay Radios": collection_status(links_of("NRAY")),
    }

    overall = aggregate_status(
        [status for status in category_statuses.values() if status != "NOT_EXISTS"]
    )

    add_kpi(ws, 3, "Site Code", site_code)
    add_kpi(ws, 4, "Audit Time", audit_time)
    add_kpi(ws, 5, "Overall Status", overall)
    style_status_cell(ws["B5"])

    row = 7
    for service in ("cisco", "ericsson", "radio"):
        add_kpi(ws, row, service.upper(), statuses.get(service, "NOT_AVAILABLE"))
        style_status_cell(ws.cell(row=row, column=2))
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="POP COMPONENT STATUS")
    ws.cell(row=row, column=1).font = Font(bold=True, color="17365D")
    row += 1
    for label, status in category_statuses.items():
        add_kpi(ws, row, label, status)
        style_status_cell(ws.cell(row=row, column=2))
        row += 1

    ws.freeze_panes = "A3"
    auto_width(ws)


def build_devices(
    wb: Workbook,
    results: dict[str, Any],
) -> None:

    ws = wb.create_sheet(
        "Devices"
    )

    headers = [
        "Service",
        "Hostname",
        "IP",
        "Zabbix Host ID",
        "Status",
    ]

    ws.append(
        headers
    )

    style_header(
        ws,
        1,
    )

    for service_name, result in results.items():

        data = find_data(
            result
        )

        if service_name == "cisco":

            for device in data.get(
                "results",
                [],
            ):

                ws.append([
                    "Cisco",
                    device.get("hostname"),
                    device.get("ip"),
                    device.get("zabbix_hostid"),
                    device.get("status"),
                ])

        elif service_name == "ericsson":

            for device in data.get(
                "results",
                [],
            ):

                ws.append([
                    "Ericsson",
                    device.get("hostname"),
                    device.get("ip"),
                    device.get("zabbix_hostid"),
                    device.get("status"),
                ])

        elif service_name == "radio":

            for link in data.get(
                "links",
                [],
            ):

                ws.append([
                    link.get("link_type"),
                    link.get("name"),
                    None,
                    link.get(
                        "zabbix_hostid"
                    ),
                    link.get("status"),
                ])

    style_body(
        ws,
        2,
        ws.max_row,
        ws.max_column,
    )

    for row in ws.iter_rows(
        min_row=2,
        min_col=5,
        max_col=5,
    ):
        style_status_cell(
            row[0]
        )

    ws.freeze_panes = "A2"

    auto_width(
        ws
    )


# ============================================================
# Cisco
# ============================================================

def build_cisco(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Cisco Switch")
    ws.append([
        "Hostname", "IP", "Interface", "Description", "Health",
        "Admin/Oper", "Speed", "Duplex", "CRC", "Input Errors",
        "Output Errors", "Output Drops", "Health Reason",
    ])
    style_header(ws, 1)

    data = find_data(result)
    devices = [
        device for device in data.get("results", [])
        if str(device.get("device_type") or "").lower() not in {"ncs", "ncs540", "ncs_540"}
        and str(device.get("role") or "").lower() != "ncs_aggregation"
    ]

    for device in devices:
        interfaces = (device.get("checks") or {}).get("interfaces", {}).get("data", []) or []
        if not interfaces:
            ws.append([
                device.get("hostname"), device.get("ip"), None, None,
                device.get("status"), None, None, None, None, None, None, None,
                device.get("message") or device.get("error"),
            ])
            continue

        for item in interfaces:
            ws.append([
                device.get("hostname"),
                device.get("ip"),
                item.get("interface"),
                item.get("description"),
                item.get("health"),
                f'{item.get("status_raw") or ""} / {item.get("protocol") or ""}',
                item.get("speed"),
                item.get("duplex"),
                item.get("crc"),
                item.get("input_errors"),
                item.get("output_errors"),
                item.get("output_drops"),
                item.get("health_reason"),
            ])

    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=5):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_ericsson(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Basebands")
    ws.append([
        "Role", "Hostname", "IP", "Overall Status", "LT All",
        "Cell Status", "Cell Count", "Clock Status", "Clock State",
        "Clock Value", "Door Alarm Status", "Door Alarm Count",
        "AC Alarm Status", "AC Alarm Count", "Total Alarms", "Critical", "Major",
    ])
    style_header(ws, 1)

    data = find_data(result)
    devices = data.get("results", []) or []
    for device in devices:
        checks = device.get("checks", {}) or {}
        cells = checks.get("cells", {}) or {}
        alarms = checks.get("alarms", {}) or {}
        clock = checks.get("clock", {}) or {}
        door = checks.get("door_alarm", {}) or {}
        ac = checks.get("ac_alarm", {}) or {}

        ws.append([
            device.get("role"),
            device.get("hostname"),
            device.get("ip"),
            device.get("status"),
            checks.get("lt_all", {}).get("status"),
            cells.get("status"),
            cells.get("count"),
            clock.get("status"),
            clock.get("state"),
            clock.get("value"),
            door.get("status"),
            door.get("count"),
            ac.get("status"),
            ac.get("count"),
            alarms.get("total"),
            alarms.get("critical"),
            alarms.get("major"),
        ])

    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2):
        for index in (4, 5, 6, 8, 11, 13):
            style_status_cell(row[index - 1])
    ws.freeze_panes = "A2"
    auto_width(ws)

    # Detailed active Ericsson alarms, retaining the originating Baseband role.
    detail = wb.create_sheet("Ericsson Alarms")
    detail.append(["Baseband", "Hostname", "Severity", "Timestamp", "Problem", "Additional Text", "Raw"])
    style_header(detail, 1)
    for device in devices:
        checks = device.get("checks", {}) or {}
        alarms = (checks.get("alarms", {}) or {}).get("alarms", []) or []
        for alarm in alarms:
            detail.append([
                device.get("role"),
                device.get("hostname"),
                alarm.get("severity"),
                alarm.get("timestamp"),
                alarm.get("problem"),
                alarm.get("additional_text"),
                alarm.get("raw"),
            ])
    style_body(detail, 2, detail.max_row, detail.max_column)
    detail.freeze_panes = "A2"
    auto_width(detail, 50)


def build_rtn(
    wb: Workbook,
    result: dict[str, Any],
) -> None:

    ws = wb.create_sheet(
        "RTN"
    )

    ws.append([
        "Radio Host",
        "Destination",
        "Overall Status",
        "Modulation Status",
        "Difference Status",
        "Traffic Status",
        "Packet Loss",
    ])

    style_header(
        ws,
        1,
    )

    data = find_data(
        result
    )

    for link in data.get(
        "links",
        [],
    ):

        if not isinstance(link, dict):
            continue

        if str(
            link.get(
                "link_type",
                ""
            )
        ).upper() != "RTN":

            continue

        analysis = link.get(
            "analysis",
            {}
        )

        if not isinstance(analysis, dict):
            continue

        analysis_links = analysis.get(
            "links",
            []
        )

        if not isinstance(analysis_links, list):
            continue

        for item in analysis_links:

            if not isinstance(item, dict):
                continue

            destination = item.get(
                "destination"
            )

            modulation = item.get(
                "modulation",
                []
            )

            difference = item.get(
                "difference",
                {}
            )

            traffic = item.get(
                "traffic",
                []
            )

            # ------------------------------------------------
            # Normalise modulation statuses.
            # Real Radio output may contain either:
            #   [{"status": "PASS"}, ...]
            # or:
            #   ["PASS", "WARNING", ...]
            # ------------------------------------------------
            modulation_statuses = []

            if isinstance(modulation, list):

                for value in modulation:

                    if isinstance(value, dict):

                        status = value.get(
                            "status"
                        )

                        if status:
                            modulation_statuses.append(
                                str(status).upper()
                            )

                    elif isinstance(value, str):

                        modulation_statuses.append(
                            value.upper()
                        )

            elif isinstance(modulation, dict):

                status = modulation.get(
                    "status"
                )

                if status:
                    modulation_statuses.append(
                        str(status).upper()
                    )

            elif isinstance(modulation, str):

                modulation_statuses.append(
                    modulation.upper()
                )

            # ------------------------------------------------
            # Normalise traffic statuses.
            # ------------------------------------------------
            traffic_statuses = []

            if isinstance(traffic, list):

                for value in traffic:

                    if isinstance(value, dict):

                        status = value.get(
                            "status"
                        )

                        if status:
                            traffic_statuses.append(
                                str(status).upper()
                            )

                    elif isinstance(value, str):

                        traffic_statuses.append(
                            value.upper()
                        )

            elif isinstance(traffic, dict):

                status = traffic.get(
                    "status"
                )

                if status:
                    traffic_statuses.append(
                        str(status).upper()
                    )

            elif isinstance(traffic, str):

                traffic_statuses.append(
                    traffic.upper()
                )

            # ------------------------------------------------
            # Difference may be dict or direct status/string.
            # ------------------------------------------------
            difference_status = None

            if isinstance(difference, dict):

                difference_status = difference.get(
                    "status"
                )

            elif isinstance(difference, str):

                difference_status = difference

            if difference_status:
                difference_status = str(
                    difference_status
                ).upper()

            # ------------------------------------------------
            # Packet-loss extraction.
            # ------------------------------------------------
            packet_loss = None

            packet_loss_data = item.get(
                "packet_loss"
            )

            if isinstance(packet_loss_data, dict):

                packet_loss = (
                    packet_loss_data.get("value")
                    if "value" in packet_loss_data
                    else packet_loss_data.get("status")
                )

            elif packet_loss_data is not None:

                packet_loss = packet_loss_data

            ws.append([
                link.get("name"),
                destination,
                item.get("status"),
                aggregate_status(
                    modulation_statuses
                ),
                difference_status,
                aggregate_status(
                    traffic_statuses
                ),
                packet_loss,
            ])

    style_body(
        ws,
        2,
        ws.max_row,
        ws.max_column,
    )

    for row in ws.iter_rows(
        min_row=2,
    ):

        for index in (
            3,
            4,
            5,
            6,
        ):

            style_status_cell(
                row[index - 1]
            )

    ws.freeze_panes = "A2"

    auto_width(
        ws
    )


def _all_cisco_devices(result: dict[str, Any]) -> list[dict]:
    return find_data(result).get("results", []) or []


def _is_ncs_device(device: dict) -> bool:
    return (
        str(device.get("device_type") or "").lower() in {"ncs", "ncs540", "ncs_540"}
        or str(device.get("role") or "").lower() == "ncs_aggregation"
    )


def build_ncs(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("NCS 540")
    ws.append([
        "Hostname", "IP", "Interface", "Description", "Health",
        "Admin/Oper", "CRC", "Input Errors", "Output Errors", "Output Drops",
    ])
    style_header(ws, 1)

    devices = [device for device in _all_cisco_devices(result) if _is_ncs_device(device)]
    for device in devices:
        interfaces = (device.get("checks") or {}).get("interfaces", {}).get("data", []) or []
        if not interfaces:
            ws.append([
                device.get("hostname"), device.get("ip"), None, None,
                device.get("status"), None, None, None, None, None,
            ])
            continue
        for item in interfaces:
            ws.append([
                device.get("hostname"),
                device.get("ip"),
                item.get("interface"),
                item.get("description"),
                item.get("health"),
                f'{item.get("status_raw") or ""} / {item.get("protocol") or ""}',
                item.get("crc"),
                item.get("input_errors"),
                item.get("output_errors"),
                item.get("output_drops"),
            ])

    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=5):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_switch_problems(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Switch Problems")
    ws.append(["Device Type", "Hostname", "IP", "Interface", "Description", "CRC"])
    style_header(ws, 1)

    for device in _all_cisco_devices(result):
        device_type = "NCS 540" if _is_ncs_device(device) else "Cisco Switch"
        interfaces = (device.get("checks") or {}).get("interfaces", {}).get("data", []) or []
        for item in interfaces:
            crc = item.get("crc")
            if crc is None or crc <= 0:
                continue
            ws.append([
                device_type,
                device.get("hostname"),
                device.get("ip"),
                item.get("interface"),
                item.get("description"),
                crc,
            ])

    if ws.max_row == 1:
        ws.append(["No CRC problems detected.", None, None, None, None, None])

    style_body(ws, 2, ws.max_row, ws.max_column)
    ws.freeze_panes = "A2"
    auto_width(ws)


def build_switch_logs(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Switch Logs")
    ws.append(["Device Type", "Hostname", "IP", "Timestamp", "Severity", "Log Entry"])
    style_header(ws, 1)

    for device in _all_cisco_devices(result):
        device_type = "NCS 540" if _is_ncs_device(device) else "Cisco Switch"
        logging_data = (device.get("checks") or {}).get("logging", {}) or {}
        logs = logging_data.get("latest") or logging_data.get("recent_10") or logging_data.get("recent") or []
        for log in logs:
            if isinstance(log, str):
                ws.append([device_type, device.get("hostname"), device.get("ip"), None, None, log])
            elif isinstance(log, dict):
                ws.append([
                    device_type,
                    device.get("hostname"),
                    device.get("ip"),
                    log.get("timestamp"),
                    log.get("severity"),
                    log.get("message") or log.get("raw"),
                ])

    if ws.max_row == 1:
        ws.append(["No switch log records were returned.", None, None, None, None, None])

    style_body(ws, 2, ws.max_row, ws.max_column)
    ws.freeze_panes = "A2"
    auto_width(ws, 60)


def build_links(
    wb: Workbook,
    result: dict[str, Any],
) -> None:
    ws = wb.create_sheet("Links")
    ws.append([
        "Radio Type", "Radio Host", "Destination / Leg", "Metric",
        "Slot / Direction", "RX", "TX", "RX/TX Difference",
        "Current Modulation", "Maximum Modulation · 12h",
        "Units", "Sample Timestamp", "Health", "Details",
    ])
    style_header(ws, 1)

    data = find_data(result)
    for link in data.get("links", []) or []:
        if not isinstance(link, dict):
            continue

        radio_type = str(link.get("link_type") or "UNKNOWN").upper()
        hostname = link.get("name")
        destination = link.get("destination_name") or link.get("destination_site")
        analysis = link.get("analysis", {}) or {}
        link_status = link.get("status") or analysis.get("status") or "UNKNOWN"

        if radio_type == "EBAND":
            checks = analysis.get("checks", {}) or {}
            slots = (checks.get("difference", {}) or {}).get("slots", []) or []
            for slot in slots:
                diff = slot.get("difference", {}) or {}
                zabbix_diff = slot.get("zabbix_difference", {}) or {}
                rx = slot.get("rx", {}) or {}
                tx = slot.get("tx", {}) or {}
                difference_value = diff.get("value")
                if difference_value is None:
                    difference_value = zabbix_diff.get("value")
                diff_status = diff.get("status") or zabbix_diff.get("status") or "UNKNOWN"
                ws.append([
                    "EBand",
                    hostname,
                    destination,
                    "RX/TX Difference",
                    slot.get("slot"),
                    rx.get("value"),
                    tx.get("value"),
                    difference_value,
                    None,
                    None,
                    "dB",
                    rx.get("clock") or tx.get("clock") or None,
                    diff_status,
                    None,
                ])
            if not slots:
                ws.append(["EBand", hostname, destination, "Audit", None, None, None, None, None, None, None, None, link_status, "No slot data returned."])

        elif radio_type == "RTN":
            for leg in analysis.get("links", []) or []:
                leg_destination = leg.get("destination") or destination
                modulation_items = leg.get("modulation", []) or []
                if not modulation_items:
                    ws.append(["RTN", hostname, leg_destination, "Modulation", None, None, None, None, None, None, None, None, leg.get("status") or link_status, "No modulation Item was associated with this leg."])
                for modulation in modulation_items:
                    history = modulation.get("history_comparison", {}) or {}
                    ws.append([
                        "RTN",
                        hostname,
                        leg_destination or modulation.get("link"),
                        "Modulation",
                        None,
                        None,
                        None,
                        None,
                        modulation.get("value"),
                        history.get("maximum"),
                        None,
                        modulation.get("clock") or history.get("current_timestamp"),
                        modulation.get("status") or history.get("status") or "UNKNOWN",
                        history.get("reason"),
                    ])
                diff = leg.get("difference")
                if isinstance(diff, dict):
                    ws.append([
                        "RTN", hostname, leg_destination, "RX/TX Difference",
                        None, None, None, diff.get("value"), None, None, "dB",
                        diff.get("clock"), diff.get("status") or "UNKNOWN", diff.get("description"),
                    ])

        elif radio_type in {"INTRACOM", "NRAY"}:
            for direction in ("rx", "tx"):
                for metric in analysis.get(direction, []) or []:
                    ws.append([
                        "Intracom" if radio_type == "INTRACOM" else "NRay",
                        hostname,
                        destination,
                        "Traffic",
                        metric.get("direction") or direction.upper(),
                        metric.get("value") if direction == "rx" else None,
                        metric.get("value") if direction == "tx" else None,
                        None,
                        None,
                        None,
                        metric.get("units"),
                        metric.get("timestamp"),
                        analysis.get("status") or metric.get("status") or link_status,
                        metric.get("name") or metric.get("key"),
                    ])

        else:
            ws.append([
                radio_type, hostname, destination, "Audit", None, None, None,
                None, None, None, None, None, link_status,
                analysis.get("reason") or "Unclassified radio type",
            ])

    style_body(ws, 2, ws.max_row, ws.max_column)
    for row in ws.iter_rows(min_row=2, min_col=13, max_col=13):
        style_status_cell(row[0])
    ws.freeze_panes = "A2"
    auto_width(ws, 46)


# ============================================================
# EBand
# ============================================================

def build_eband(
    wb: Workbook,
    result: dict[str, Any],
) -> None:

    ws = wb.create_sheet(
        "EBand"
    )

    ws.append([
        "Radio Host",
        "Slot",
        "RX",
        "TX",
        "RX Calloff",
        "TX Calloff",
        "Calculated Difference",
        "Zabbix Difference",
        "Capacity",
        "RX Modulation",
        "RX Health",
        "Capacity Health",
        "Modulation Health",
        "Interface Status",
        "Overall Status",
    ])

    style_header(
        ws,
        1,
    )

    data = find_data(
        result
    )

    for link in data.get(
        "links",
        [],
    ):

        if str(
            link.get(
                "link_type",
                ""
            )
        ).upper() != "EBAND":

            continue

        analysis = link.get(
            "analysis",
            {}
        )

        checks = analysis.get(
            "checks",
            {}
        )

        difference = checks.get(
            "difference",
            {}
        )

        slots = difference.get(
            "slots",
            []
        )

        for slot_data in slots:

            rx = slot_data.get(
                "rx",
                {}
            )

            tx = slot_data.get(
                "tx",
                {}
            )

            rx_calloff = slot_data.get(
                "rx_calloff",
                {}
            )

            tx_calloff = slot_data.get(
                "tx_calloff",
                {}
            )

            diff = slot_data.get(
                "difference",
                {}
            )

            zabbix_diff = slot_data.get(
                "zabbix_difference",
                {}
            )

            capacity = slot_data.get(
                "capacity",
                {}
            )

            modulation = slot_data.get(
                "rx_modulation",
                {}
            )

            interfaces = checks.get(
                "interfaces",
                {}
            )

            ws.append([
                link.get("name"),
                slot_data.get("slot"),
                rx.get("value"),
                tx.get("value"),
                rx_calloff.get("value"),
                tx_calloff.get("value"),
                diff.get("value"),
                zabbix_diff.get("value"),
                capacity.get(
                    "metric",
                    {}
                ).get("value"),
                modulation.get(
                    "metric",
                    {}
                ).get("value"),
                slot_data.get(
                    "rx_health",
                    {}
                ).get("status"),
                capacity.get(
                    "health",
                    {}
                ).get("status"),
                modulation.get(
                    "health",
                    {}
                ).get("status"),
                interfaces.get(
                    "status"
                ),
                analysis.get(
                    "status"
                ),
            ])

    style_body(
        ws,
        2,
        ws.max_row,
        ws.max_column,
    )

    for row in ws.iter_rows(
        min_row=2,
    ):

        for index in (
            11,
            12,
            13,
            14,
            15,
        ):

            style_status_cell(
                row[index - 1]
            )

    ws.freeze_panes = "A2"

    auto_width(
        ws
    )


# ============================================================
# Workbook generation
# ============================================================

def create_workbook(
    site_code: str,
    results: dict[str, Any],
) -> tuple[Path, str]:
    wb = Workbook()

    build_summary(wb, site_code, results)
    build_devices(wb, results)

    if "cisco" in results:
        build_cisco(wb, results["cisco"])
        build_ncs(wb, results["cisco"])
        build_switch_problems(wb, results["cisco"])
        build_switch_logs(wb, results["cisco"])

    if "ericsson" in results:
        build_ericsson(wb, results["ericsson"])

    if "radio" in results:
        build_links(wb, results["radio"])

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_site = re.sub(r"[^A-Za-z0-9_-]", "_", site_code)
    filename = f"POP-Audit-{safe_site}-{timestamp}.xlsx"
    output = REPORT_DIR / filename
    wb.save(output)

    overall = aggregate_status([
        service_status(result)
        for result in results.values()
    ])
    return output, overall


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
