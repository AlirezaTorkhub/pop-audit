from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import paramiko
from fastapi import FastAPI


app = FastAPI(
    title="POP Audit - Ericsson Service",
    version="2.1.0",
)


# ============================================================
# Configuration
# ============================================================

ENV_FILE = Path("/opt/pop-audit/config/.env")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        os.environ.setdefault(
            key,
            value,
        )


load_env_file(ENV_FILE)


MOSHELL_HOST = os.getenv(
    "MOSHELL_HOST",
    "",
)

MOSHELL_USER = os.getenv(
    "MOSHELL_USER",
    "",
)

MOSHELL_PASSWORD = os.getenv(
    "MOSHELL_PASSWORD",
    "",
)

MOSHELL_PATH = os.getenv(
    "MOSHELL_PATH",
    "/home/a.torkashvand/Moshell25F/moshell",
)

SSH_CONNECT_TIMEOUT = int(
    os.getenv(
        "SSH_CONNECT_TIMEOUT",
        "10",
    )
)

MOSHELL_SESSION_WAIT = 5
COMMAND_WAIT = 5


# ============================================================
# Status
# ============================================================

STATUS_PRIORITY = {
    "CRITICAL": 5,
    "WARNING": 4,
    "UNKNOWN": 3,
    "NOT_AVAILABLE": 2,
    "PASS": 1,
}


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


# ============================================================
# Channel helpers
# ============================================================

def read_channel(
    channel,
    quiet_window: float = 0.8,
) -> str:

    data = bytearray()

    while True:

        if channel.recv_ready():

            try:
                chunk = channel.recv(65535)
            except Exception:
                break

            if not chunk:
                break

            data.extend(chunk)

        else:

            time.sleep(
                quiet_window
            )

            if not channel.recv_ready():
                break

    return data.decode(
        errors="replace"
    )


def send_moshell_command(
    channel,
    command: str,
    wait_seconds: int = COMMAND_WAIT,
) -> str:

    channel.send(
        command + "\r"
    )

    time.sleep(
        wait_seconds
    )

    return read_channel(
        channel
    )


# ============================================================
# Parsers
# ============================================================

def parse_lt_all(
    output: str,
) -> dict[str, Any]:

    connected = bool(
        re.search(
            r"Connected to\s+[\d.]+\s+"
            r"\(ManagedElement=",
            output,
            re.IGNORECASE,
        )
    )

    loaded_match = re.search(
        r"Last MO:\s*(\d+)\.\s*"
        r"Loaded\s+(\d+)\s+MOs\.\s*"
        r"Total:\s*(\d+)\s+MOs",
        output,
        re.IGNORECASE,
    )

    if connected:
        status = "PASS"
    else:
        status = "CRITICAL"

    result = {
        "status": status,
        "connected": connected,
    }

    if loaded_match:
        result.update({
            "last_mo": int(
                loaded_match.group(1)
            ),
            "loaded_mos": int(
                loaded_match.group(2)
            ),
            "total_mos": int(
                loaded_match.group(3)
            ),
        })

    return result


def parse_cells(output: str) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+\(([^)]+)\)\s+(\d+)\s+\(([^)]+)\)\s+(.+?)\s*$"
    )
    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        proxy = int(match.group(1))
        adm_value = int(match.group(2))
        adm_state = match.group(3).strip()
        op_value = int(match.group(4))
        op_state = match.group(5).strip()
        mo = match.group(6).strip()
        cell_status = (
            "PASS"
            if adm_value == 1 and adm_state.upper() == "UNLOCKED"
            and op_value == 1 and op_state.upper() == "ENABLED"
            else "WARNING"
        )
        cells.append({
            "proxy": proxy,
            "admin_value": adm_value,
            "admin_state": adm_state,
            "oper_value": op_value,
            "oper_state": op_state,
            "mo": mo,
            "status": cell_status,
        })
    if not cells:
        return {
            "status": "UNKNOWN",
            "count": 0,
            "cells": [],
            "reason": "No parseable cell rows were returned by st cel.",
        }
    return {
        "status": aggregate_status([cell["status"] for cell in cells]),
        "count": len(cells),
        "cells": cells,
    }

def parse_alarms(output: str) -> dict[str, Any]:
    all_alarms: list[dict[str, Any]] = []
    alarm_pattern = re.compile(
        r"^\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+([A-Za-z])\s+(.+?)\s+(?:([A-Za-z0-9]+=.*))?$"
    )
    for line in output.splitlines():
        match = alarm_pattern.match(line.strip())
        if not match:
            continue
        timestamp, severity_code, remainder = (
            match.group(1), match.group(2), match.group(3).strip()
        )
        mo_match = re.search(r"\s{2,}([A-Za-z][A-Za-z0-9_]+=[^ ]+.*)$", remainder)
        if mo_match:
            problem = remainder[:mo_match.start()].strip()
            additional_text = mo_match.group(1).strip()
        else:
            problem = remainder
            additional_text = ""
        severity_map = {
            "C": "CRITICAL", "M": "MAJOR", "m": "MINOR", "w": "WARNING",
        }
        all_alarms.append({
            "timestamp": timestamp,
            "severity_code": severity_code,
            "severity": severity_map.get(severity_code, "UNKNOWN"),
            "problem": problem,
            "additional_text": additional_text,
            "raw": line.strip(),
        })

    summary = re.search(
        r">>>\s*Total:\s*(\d+)\s+Alarms\s*\((\d+)\s+Critical,\s*(\d+)\s+Major\)",
        output,
        re.IGNORECASE,
    )
    total_count = int(summary.group(1)) if summary else len(all_alarms)

    relevant_pattern = re.compile(
        r"\b(?:door|ac|power|cooling|fan|rectifier|battery|temperature|climate)\b",
        re.IGNORECASE,
    )
    relevant = [
        alarm for alarm in all_alarms
        if relevant_pattern.search(
            " ".join((alarm["problem"], alarm["additional_text"], alarm["raw"]))
        )
    ]
    relevant_critical = sum(alarm["severity"] == "CRITICAL" for alarm in relevant)
    relevant_major = sum(
        alarm["severity"] in ("MAJOR", "MINOR", "WARNING")
        for alarm in relevant
    )

    if relevant_critical:
        status = "CRITICAL"
    elif relevant_major:
        status = "WARNING"
    elif summary or all_alarms:
        status = "PASS"
    else:
        status = "UNKNOWN"

    return {
        "status": status,
        "total": total_count,
        "critical": relevant_critical,
        "major": relevant_major,
        "relevant_count": len(relevant),
        "ignored_count": len(all_alarms) - len(relevant),
        "alarms": all_alarms,
        "relevant_alarms": relevant,
        "scope": "Door and AC/power/cooling/fan/battery/temperature alarms affect health.",
    }

def parse_clock(
    output: str,
) -> dict[str, Any]:

    match = re.search(
        r"radioClockState\s+"
        r"(\d+)\s+\(([^)]+)\)",
        output,
        re.IGNORECASE,
    )

    if not match:
        return {
            "status": "NOT_AVAILABLE",
            "value": None,
            "state": None,
        }

    value = int(
        match.group(1)
    )

    state = match.group(2).strip()

    healthy = (
        value == 6
        and state.upper() == "RNT_TIME_LOCKED"
    )

    return {
        "status": (
            "PASS"
            if healthy
            else "WARNING"
        ),
        "value": value,
        "state": state,
        "required_value": 6,
        "required_state": "RNT_TIME_LOCKED",
    }


# ============================================================
# Moshell session
# ============================================================

def run_moshell_session(
    target_ip: str,
) -> dict[str, Any]:

    if not MOSHELL_HOST:
        raise RuntimeError(
            "MOSHELL_HOST is not configured."
        )

    if not MOSHELL_USER:
        raise RuntimeError(
            "MOSHELL_USER is not configured."
        )

    if not MOSHELL_PASSWORD:
        raise RuntimeError(
            "MOSHELL_PASSWORD is not configured."
        )

    if not target_ip:
        raise RuntimeError(
            "Ericsson target IP is missing."
        )

    ssh = paramiko.SSHClient()

    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    try:

        ssh.connect(
            hostname=MOSHELL_HOST,
            username=MOSHELL_USER,
            password=MOSHELL_PASSWORD,
            timeout=SSH_CONNECT_TIMEOUT,
            banner_timeout=SSH_CONNECT_TIMEOUT,
            auth_timeout=SSH_CONNECT_TIMEOUT,
        )

        channel = ssh.invoke_shell()

        channel.settimeout(1)

        time.sleep(1)

        startup = read_channel(
            channel
        )

        start_command = (
            f"cd $(dirname {MOSHELL_PATH}) && "
            f"./{Path(MOSHELL_PATH).name} "
            f"{target_ip}"
        )

        channel.send(
            start_command + "\r"
        )

        # Required 5-second session establishment delay.
        time.sleep(
            MOSHELL_SESSION_WAIT
        )

        session_output = read_channel(
            channel
        )

        outputs: dict[str, str] = {
            "startup": (
                startup
                + session_output
            )
        }

        # Required production sequence.
        outputs["lt all"] = send_moshell_command(
            channel,
            "lt all",
        )

        outputs["st cel"] = send_moshell_command(
            channel,
            "st cel",
        )

        outputs["alt"] = send_moshell_command(
            channel,
            "alt",
        )

        outputs["get . clock"] = send_moshell_command(
            channel,
            "get . clock",
        )

        channel.send(
            "q\r"
        )

        time.sleep(2)

        outputs["quit"] = read_channel(
            channel
        )

        combined = "\n".join(
            outputs.values()
        )

        if (
            "Wrong Password or Username"
            in combined
        ):
            return {
                "status": "CRITICAL",
                "message": (
                    "Moshell node authentication failed."
                ),
                "commands": [
                    "lt all",
                    "st cel",
                    "alt",
                    "get . clock",
                ],
                "outputs": outputs,
            }

        lt_result = parse_lt_all(
            outputs["lt all"]
        )

        cell_result = parse_cells(
            outputs["st cel"]
        )

        alarm_result = parse_alarms(
            outputs["alt"]
        )

        clock_result = parse_clock(
            outputs["get . clock"]
        )

        overall = aggregate_status([
            lt_result["status"],
            cell_result["status"],
            alarm_result["status"],
            clock_result["status"],
        ])

        return {
            "status": overall,
            "message": (
                "Ericsson Moshell audit completed."
            ),
            "checks": {
                "lt_all": lt_result,
                "cells": cell_result,
                "alarms": alarm_result,
                "clock": clock_result,
            },
            "commands": [
                "lt all",
                "st cel",
                "alt",
                "get . clock",
            ],
            "timing": {
                "session_wait_seconds": (
                    MOSHELL_SESSION_WAIT
                ),
                "command_wait_seconds": (
                    COMMAND_WAIT
                ),
            },
            "outputs": outputs,
        }

    finally:

        try:
            ssh.close()
        except Exception:
            pass


# ============================================================
# API
# ============================================================

@app.get("/health")
def health():
    return {
        "service": "ericsson",
        "status": "ok",
    }


@app.post("/check")
def check(payload: dict):

    basebands = payload.get(
        "basebands",
        [],
    )

    if not isinstance(
        basebands,
        list,
    ):
        return {
            "service": "ericsson",
            "site_code": payload.get(
                "site_code"
            ),
            "status": "UNKNOWN",
            "results": [],
            "error": (
                "basebands must be a list"
            ),
        }

    results = []

    for bb in basebands:

        hostname = bb.get(
            "hostname"
        )

        ip = bb.get(
            "ip"
        )

        hostid = bb.get(
            "zabbix_hostid"
        )

        try:

            analysis = run_moshell_session(
                ip
            )

            results.append({
                "hostname": hostname,
                "ip": ip,
                "zabbix_hostid": hostid,
                **analysis,
            })

        except Exception as exc:

            results.append({
                "hostname": hostname,
                "ip": ip,
                "zabbix_hostid": hostid,
                "status": "UNKNOWN",
                "message": (
                    "Ericsson/Moshell check failed."
                ),
                "error": str(exc),
            })

    overall = aggregate_status(
        [
            item.get(
                "status",
                "UNKNOWN",
            )
            for item in results
        ]
    )

    return {
        "service": "ericsson",
        "site_code": payload.get(
            "site_code"
        ),
        "status": overall,
        "results": results,
    }
