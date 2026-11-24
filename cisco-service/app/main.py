from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


app = FastAPI(
    title="POP Audit - Cisco Service",
    version="2.0.0",
)


# ============================================================
# Configuration
# ============================================================

ENV_FILE = Path("/opt/pop-audit/config/.env")


def load_env_file(path: Path) -> None:
    """
    Minimal .env loader.

    Does not overwrite variables that already exist in the
    process environment.
    """
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
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

        os.environ.setdefault(key, value)


load_env_file(ENV_FILE)


SSH_USERNAME = os.getenv("SSH_USERNAME", "")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")

SSH_CONNECT_TIMEOUT = int(
    os.getenv("SSH_CONNECT_TIMEOUT", "10")
)

SSH_COMMAND_TIMEOUT = int(
    os.getenv("SSH_COMMAND_TIMEOUT", "30")
)


# ============================================================
# Status model
# ============================================================

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

    return max(
        statuses,
        key=lambda value: STATUS_PRIORITY.get(value, 3),
    )


# ============================================================
# Helpers
# ============================================================

def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_text(value: Any) -> str:
    return str(value or "").strip()


def status_result(
    status: str,
    reason: str = "",
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "reason": reason,
    }

    result.update(extra)

    return result


# ============================================================
# SSH / Netmiko
# ============================================================

def connect_device(ip: str, device_type: str = "cisco_ios"):
    if not SSH_USERNAME or not SSH_PASSWORD:
        raise RuntimeError(
            "SSH_USERNAME or SSH_PASSWORD is not configured."
        )

    device = {
        "device_type": device_type,
        "host": ip,
        "username": SSH_USERNAME,
        "password": SSH_PASSWORD,
        "port": 22,
        "conn_timeout": SSH_CONNECT_TIMEOUT,
        "auth_timeout": SSH_CONNECT_TIMEOUT,
        "banner_timeout": SSH_CONNECT_TIMEOUT,
        "timeout": SSH_COMMAND_TIMEOUT,
        "fast_cli": False,
    }

    return ConnectHandler(**device)


def run_command(
    connection,
    command: str,
) -> dict[str, Any]:

    try:
        output = connection.send_command(
            command,
            read_timeout=SSH_COMMAND_TIMEOUT,
            strip_prompt=False,
            strip_command=False,
        )

        return {
            "status": "PASS",
            "command": command,
            "output": output,
        }

    except Exception as exc:
        return {
            "status": "NOT_AVAILABLE",
            "command": command,
            "output": "",
            "error": str(exc),
        }


# ============================================================
# Interface parsing
# ============================================================

def parse_interfaces_status(output: str) -> list[dict[str, Any]]:
    """
    Parse:
        show interfaces status

    Typical Cisco IOS format:

    Port      Name   Status       Vlan Duplex Speed Type
    Gi1/0/1          connected    10   a-full a-1000 ...
    """

    interfaces: list[dict[str, Any]] = []

    lines = output.splitlines()

    for line in lines:
        line = line.rstrip()

        match = re.match(
            r"^(\S+)\s+(.*?)\s{2,}"
            r"(connected|notconnect|disabled|err-disabled|"
            r"suspended|monitoring|inactive|down)\s+"
            r"(\S+)\s+(\S+)\s+(\S+)(?:\s+(.*))?$",
            line,
            re.IGNORECASE,
        )

        if not match:
            continue

        interface = match.group(1)
        name = match.group(2).strip()
        state = match.group(3)
        vlan = match.group(4)
        duplex = match.group(5)
        speed = match.group(6)
        media = (match.group(7) or "").strip()

        interfaces.append(
            {
                "interface": interface,
                "name": name,
                "status_raw": state,
                "vlan": vlan,
                "duplex": duplex,
                "speed": speed,
                "media": media,
            }
        )

    return interfaces


def parse_interface_description(
    output: str,
) -> dict[str, str]:

    descriptions: dict[str, str] = {}

    for line in output.splitlines():
        line = line.rstrip()

        if not line:
            continue

        if re.match(
            r"^\s*Interface\s+Status\s+Protocol\s+Description",
            line,
            re.IGNORECASE,
        ):
            continue

        match = re.match(
            r"^\s*(\S+)\s+"
            r"(\S+)\s+"
            r"(\S+)\s*"
            r"(.*)$",
            line,
        )

        if not match:
            continue

        interface = match.group(1)
        description = match.group(4).strip()

        descriptions[interface] = description

    return descriptions


def parse_interfaces_detail(
    output: str,
) -> list[dict[str, Any]]:

    blocks = re.split(
        r"(?=^\S+\s+is\s+)",
        output,
        flags=re.MULTILINE,
    )

    results: list[dict[str, Any]] = []

    for block in blocks:
        block = block.strip()

        if not block:
            continue

        first = re.match(
            r"^(\S+)\s+is\s+([^,]+)",
            block,
            re.IGNORECASE,
        )

        if not first:
            continue

        interface = first.group(1)
        line_state = first.group(2).strip()

        protocol_match = re.search(
            r"line protocol is\s+([^(\n]+)",
            block,
            re.IGNORECASE,
        )

        hardware_match = re.search(
            r"Hardware is\s+([^\n]+)",
            block,
            re.IGNORECASE,
        )

        description_match = re.search(
            r"Description:\s*(.*)",
            block,
            re.IGNORECASE,
        )

        mtu_match = re.search(
            r"MTU\s+(\d+)",
            block,
            re.IGNORECASE,
        )

        speed_match = re.search(
            r"BW\s+(\d+)\s+Kbit/sec",
            block,
            re.IGNORECASE,
        )

        duplex_match = re.search(
            r"(?:Full-duplex|Half-duplex|auto-duplex)",
            block,
            re.IGNORECASE,
        )

        input_errors_match = re.search(
            r"(\d+)\s+input errors",
            block,
            re.IGNORECASE,
        )

        crc_match = re.search(
            r"(\d+)\s+CRC",
            block,
            re.IGNORECASE,
        )

        output_errors_match = re.search(
            r"(\d+)\s+output errors",
            block,
            re.IGNORECASE,
        )

        output_discards_match = re.search(
            r"(\d+)\s+output drops",
            block,
            re.IGNORECASE,
        )

        input_discards_match = re.search(
            r"(\d+)\s+input queue drops",
            block,
            re.IGNORECASE,
        )

        carrier_transitions_match = re.search(
            r"(\d+)\s+carrier transitions",
            block,
            re.IGNORECASE,
        )

        results.append(
            {
                "interface": interface,
                "line_state": line_state,
                "protocol": (
                    protocol_match.group(1).strip()
                    if protocol_match
                    else None
                ),
                "hardware": (
                    hardware_match.group(1).strip()
                    if hardware_match
                    else None
                ),
                "description": (
                    description_match.group(1).strip()
                    if description_match
                    else ""
                ),
                "mtu": (
                    int(mtu_match.group(1))
                    if mtu_match
                    else None
                ),
                "bandwidth_kbps": (
                    int(speed_match.group(1))
                    if speed_match
                    else None
                ),
                "duplex": (
                    duplex_match.group(0)
                    if duplex_match
                    else None
                ),
                "input_errors": (
                    int(input_errors_match.group(1))
                    if input_errors_match
                    else 0
                ),
                # Missing CRC text is unknown, not a measured zero.
                "crc": (
                    int(crc_match.group(1))
                    if crc_match
                    else None
                ),
                "output_errors": (
                    int(output_errors_match.group(1))
                    if output_errors_match
                    else 0
                ),
                "output_drops": (
                    int(output_discards_match.group(1))
                    if output_discards_match
                    else 0
                ),
                "input_queue_drops": (
                    int(input_discards_match.group(1))
                    if input_discards_match
                    else 0
                ),
                "carrier_transitions": (
                    int(carrier_transitions_match.group(1))
                    if carrier_transitions_match
                    else 0
                ),
                "raw": block,
            }
        )

    return results


# ============================================================
# Interface health rules
# ============================================================

def is_expected_speed(
    interface: str,
    speed: str,
) -> bool | None:

    interface_upper = interface.upper()
    speed_upper = speed.upper()

    if (
        interface_upper.startswith("GI")
        or interface_upper.startswith("GIGABITETHERNET")
    ):
        if "1000" in speed_upper or "1G" in speed_upper:
            return True

        if speed_upper in {
            "AUTO",
            "A-1000",
        }:
            return True

        return False

    if (
        interface_upper.startswith("TE")
        or interface_upper.startswith("TENGIGABITETHERNET")
    ):
        if "10000" in speed_upper or "10G" in speed_upper:
            return True

        if speed_upper in {
            "AUTO",
            "A-10G",
            "A-10000",
        }:
            return True

        return False

    return None


def classify_interface(
    item: dict[str, Any],
) -> dict[str, Any]:

    interface = normalized_text(
        item.get("interface")
    )

    state = normalized_text(
        item.get("status_raw")
    ).lower()

    result = {
        **item,
        "health": "UNKNOWN",
        "health_reason": "",
    }

    if state in {
        "connected",
        "up",
    }:
        result["health"] = "PASS"
        result["health_reason"] = (
            "Interface is operational."
        )

    elif state in {
        "disabled",
        "err-disabled",
        "suspended",
        "inactive",
    }:
        result["health"] = "PASS"
        result["health_reason"] = (
            "Interface is administratively or intentionally inactive."
        )

    elif state in {
        "notconnect",
        "down",
    }:
        result["health"] = "WARNING"
        result["health_reason"] = (
            "Interface is not connected/up."
        )

    else:
        result["health"] = "UNKNOWN"
        result["health_reason"] = (
            f"Unrecognized interface state: {state}"
        )

    # Current negotiated speed is informational unless an
    # interface-specific expected-speed rule has been verified.
    expected_speed = None

    result["expected_speed"] = expected_speed

    return result


# ============================================================
# Version / Inventory
# ============================================================

def parse_version(output: str) -> dict[str, Any]:

    result: dict[str, Any] = {
        "hostname": None,
        "version": None,
        "model": None,
        "serial": None,
        "uptime": None,
    }

    match = re.search(
        r"Switch\s+uptime is\s+(.+)",
        output,
        re.IGNORECASE,
    )

    if match:
        result["uptime"] = match.group(1).strip()

    version_match = re.search(
        r"Cisco IOS Software.*?Version\s+([^,\n]+)",
        output,
        re.IGNORECASE,
    )

    if version_match:
        result["version"] = version_match.group(1).strip()

    hostname_match = re.search(
        r"^(\S+)\s+uptime is",
        output,
        re.MULTILINE | re.IGNORECASE,
    )

    if hostname_match:
        result["hostname"] = hostname_match.group(1)

    model_match = re.search(
        r"[Mm]odel [Nn]umber\s*[:]\s*(\S+)",
        output,
    )

    if model_match:
        result["model"] = model_match.group(1)

    serial_match = re.search(
        r"[Pp]rocessor board ID\s+(\S+)",
        output,
    )

    if serial_match:
        result["serial"] = serial_match.group(1)

    return result


def parse_inventory(output: str) -> list[dict[str, Any]]:

    inventory: list[dict[str, Any]] = []

    current: dict[str, Any] = {}

    for line in output.splitlines():

        line = line.rstrip()

        if not line:
            if current:
                inventory.append(current)
                current = {}
            continue

        name_match = re.match(
            r'^NAME:\s*"?(.*?)"?\s*,\s*DESCR:\s*"?(.*?)"?\s*$',
            line,
            re.IGNORECASE,
        )

        if name_match:
            if current:
                inventory.append(current)
                current = {}

            current["name"] = name_match.group(1).strip()
            current["description"] = name_match.group(2).strip()

            continue

        pid_match = re.search(
            r'PID:\s*([^,\s]+)',
            line,
            re.IGNORECASE,
        )

        if pid_match:
            current["pid"] = pid_match.group(1)

        vid_match = re.search(
            r'VID:\s*([^,\s]+)',
            line,
            re.IGNORECASE,
        )

        if vid_match:
            current["vid"] = vid_match.group(1)

        sn_match = re.search(
            r'SN:\s*([^,\s]+)',
            line,
            re.IGNORECASE,
        )

        if sn_match:
            current["serial"] = sn_match.group(1)

    if current:
        inventory.append(current)

    return inventory


# ============================================================
# Logging
# ============================================================

def parse_logging(output: str, limit: int = 10) -> dict[str, Any]:

    lines = [
        line.rstrip()
        for line in output.splitlines()
        if line.strip()
    ]

    recent = lines[-max(1, limit):]

    severity_counts = {
        "EMERGENCY": 0,
        "ALERT": 0,
        "CRITICAL": 0,
        "ERROR": 0,
        "WARNING": 0,
        "NOTICE": 0,
        "INFO": 0,
        "DEBUG": 0,
    }

    severity_patterns = {
        0: "EMERGENCY",
        1: "ALERT",
        2: "CRITICAL",
        3: "ERROR",
        4: "WARNING",
        5: "NOTICE",
        6: "INFO",
        7: "DEBUG",
    }

    for line in lines:

        match = re.search(
            r"%[A-Z0-9_-]+-(\d+)-",
            line,
        )

        if not match:
            continue

        level = int(match.group(1))

        severity = severity_patterns.get(level)

        if severity:
            severity_counts[severity] += 1

    critical_count = (
        severity_counts["EMERGENCY"]
        + severity_counts["ALERT"]
        + severity_counts["CRITICAL"]
        + severity_counts["ERROR"]
    )
    warning_count = severity_counts["WARNING"]

    if critical_count > 0:
        status = "CRITICAL"
    elif warning_count > 0:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "status": status,
        "severity_counts": severity_counts,
        "latest": recent,
        "recent": recent,
        "recent_10": recent,
        "event_count": len(recent),
    }


# ============================================================
# Environment
# ============================================================

def parse_environment(
    command_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:

    selected = None

    for key in (
        "show environment",
        "show env temperature status",
        "show environment status",
        "show environment summary",
    ):
        result = command_outputs.get(key)

        if result and result.get("output"):
            selected = result
            break

    if not selected:
        return {
            "status": "NOT_AVAILABLE",
            "message": (
                "No supported environment command returned data."
            ),
            "raw": {},
        }

    raw = selected.get("output", "")

    critical_terms = re.findall(
        r"\b(?:failed|fail|critical|shutdown|alarm)\b",
        raw,
        re.IGNORECASE,
    )

    warning_terms = re.findall(
        r"\b(?:warning|alert|overheat|high)\b",
        raw,
        re.IGNORECASE,
    )

    if critical_terms:
        status = "CRITICAL"
    elif warning_terms:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "status": status,
        "command": selected.get("command"),
        "critical_terms": critical_terms,
        "warning_terms": warning_terms,
        "raw": raw,
    }


# ============================================================
# Complete device audit
# ============================================================

COMMANDS = [
    "show version",
    "show inventory",
    "show interfaces status",
    "show interfaces description",
    "show interfaces",
    "show logging",
    "show environment",
    "show env temperature status",
    "show environment status",
    "show environment summary",
]


def audit_device(
    device: dict[str, Any],
) -> dict[str, Any]:

    hostname = device.get("hostname")
    ip = device.get("ip")
    zabbix_hostid = device.get("zabbix_hostid")

    base = {
        "hostname": hostname,
        "ip": ip,
        "zabbix_hostid": zabbix_hostid,
        "status": "UNKNOWN",
    }

    if not ip:
        return {
            **base,
            "status": "NOT_AVAILABLE",
            "message": "Cisco device has no IP address.",
        }

    device_type = str(device.get("device_type") or "switch").lower()
    if device_type in {"ncs", "ncs540", "ncs_540"}:
        return audit_ncs_device(device)

    command_outputs: dict[str, dict[str, Any]] = {}

    connection = None

    try:
        connection = connect_device(ip)

        # Disable paging.
        try:
            connection.send_command(
                "terminal length 0",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
        except Exception:
            pass

        # Disable terminal width limitations.
        try:
            connection.send_command(
                "terminal width 511",
                read_timeout=SSH_COMMAND_TIMEOUT,
            )
        except Exception:
            pass

        for command in COMMANDS:
            command_outputs[command] = run_command(
                connection,
                command,
            )

        version_output = command_outputs.get(
            "show version",
            {},
        ).get("output", "")

        inventory_output = command_outputs.get(
            "show inventory",
            {},
        ).get("output", "")

        interfaces_status_output = (
            command_outputs.get(
                "show interfaces status",
                {},
            ).get("output", "")
        )

        interfaces_description_output = (
            command_outputs.get(
                "show interfaces description",
                {},
            ).get("output", "")
        )

        interfaces_detail_output = (
            command_outputs.get(
                "show interfaces",
                {},
            ).get("output", "")
        )

        logging_output = (
            command_outputs.get(
                "show logging",
                {},
            ).get("output", "")
        )

        version = parse_version(
            version_output
        )

        inventory = parse_inventory(
            inventory_output
        )

        interface_status = parse_interfaces_status(
            interfaces_status_output
        )

        descriptions = parse_interface_description(
            interfaces_description_output
        )

        interface_details = parse_interfaces_detail(
            interfaces_detail_output
        )

        # Merge interface data.
        detail_by_name = {
            item["interface"]: item
            for item in interface_details
            if item.get("interface")
        }

        interfaces: list[dict[str, Any]] = []

        for item in interface_status:

            name = item["interface"]

            merged = {
                **item,
                "description": descriptions.get(
                    name,
                    item.get("name", ""),
                ),
            }

            detail = detail_by_name.get(name)

            if detail:
                merged.update(
                    {
                        "line_state": detail.get(
                            "line_state"
                        ),
                        "protocol": detail.get(
                            "protocol"
                        ),
                        "crc": detail.get(
                            "crc",
                            0,
                        ),
                        "input_errors": detail.get(
                            "input_errors",
                            0,
                        ),
                        "output_errors": detail.get(
                            "output_errors",
                            0,
                        ),
                        "output_drops": detail.get(
                            "output_drops",
                            0,
                        ),
                        "carrier_transitions": detail.get(
                            "carrier_transitions",
                            0,
                        ),
                        "bandwidth_kbps": detail.get(
                            "bandwidth_kbps"
                        ),
                    }
                )

            interfaces.append(
                classify_interface(merged)
            )

        # Any interface with CRC / serious errors becomes WARNING.
        for item in interfaces:
            crc = item.get("crc")
            input_errors = item.get("input_errors", 0) or 0
            output_errors = item.get("output_errors", 0) or 0

            if crc is not None and crc > 0:
                item["health"] = aggregate_status(
                    [
                        item.get(
                            "health",
                            "UNKNOWN",
                        ),
                        "WARNING",
                    ]
                )

                item["health_reason"] += (
                    f" CRC errors detected: {crc}."
                )

            if input_errors > 0 or output_errors > 0:
                item["health"] = aggregate_status(
                    [
                        item.get(
                            "health",
                            "UNKNOWN",
                        ),
                        "WARNING",
                    ]
                )

                item["health_reason"] += (
                    " Interface errors detected."
                )

        interface_statuses = [
            item.get("health", "UNKNOWN")
            for item in interfaces
        ]

        interface_health = aggregate_status(
            interface_statuses
        )

        logging_data = parse_logging(
            logging_output
        )

        environment = parse_environment(
            command_outputs
        )

        command_health = []

        for result in command_outputs.values():
            if result.get("status") == "NOT_AVAILABLE":
                command_health.append(
                    "NOT_AVAILABLE"
                )

        # A successfully connected device is fundamentally PASS
        # unless actual health data introduces a warning/critical.
        device_statuses = [
            interface_health,
            logging_data.get(
                "status",
                "UNKNOWN",
            ),
            environment.get(
                "status",
                "NOT_AVAILABLE",
            ),
        ]

        # Do not let unavailable optional environment data
        # make the entire Cisco device UNKNOWN.
        device_statuses = [
            status
            for status in device_statuses
            if status != "NOT_AVAILABLE"
        ]

        overall = aggregate_status(
            device_statuses or ["PASS"]
        )

        return {
            **base,
            "status": overall,
            "checks": {
                "connectivity": status_result(
                    "PASS",
                    "SSH connection established.",
                ),
                "version": {
                    "status": (
                        "PASS"
                        if version_output
                        else "NOT_AVAILABLE"
                    ),
                    "data": version,
                },
                "inventory": {
                    "status": (
                        "PASS"
                        if inventory
                        else "NOT_AVAILABLE"
                    ),
                    "components": inventory,
                },
                "interfaces": {
                    "status": interface_health,
                    "count": len(interfaces),
                    "data": interfaces,
                },
                "logging": logging_data,
                "environment": environment,
            },
            "raw_commands": command_outputs,
        }

    except NetmikoAuthenticationException as exc:

        return {
            **base,
            "status": "CRITICAL",
            "message": "SSH authentication failed.",
            "error": str(exc),
        }

    except NetmikoTimeoutException as exc:

        return {
            **base,
            "status": "CRITICAL",
            "message": "SSH connection timed out.",
            "error": str(exc),
        }

    except Exception as exc:

        return {
            **base,
            "status": "UNKNOWN",
            "message": "Cisco health check failed.",
            "error": str(exc),
        }

    finally:

        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


# ============================================================
# Cisco NCS 540 / IOS-XR profile
# ============================================================

NCS_COMMANDS = [
    "show version",
    "show inventory",
    "show interfaces description",
    "show interfaces",
    "show logging last 10",
]


def parse_ncs_interfaces_description(output: str) -> list[dict[str, Any]]:
    """Parse IOS-XR show interfaces description output."""
    results: list[dict[str, Any]] = []
    state_pattern = re.compile(
        r"^(up|down|admin[- ]down|shutdown|unknown|testing|dormant)$",
        re.IGNORECASE,
    )

    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if re.search(r"\bInterface\b.*\bStatus\b.*\bProtocol\b", line, re.IGNORECASE):
            continue

        parts = re.split(r"\s{2,}", line.strip(), maxsplit=3)
        if len(parts) < 3:
            continue

        interface = parts[0].strip()
        status = parts[1].strip()
        protocol = parts[2].strip()
        description = parts[3].strip() if len(parts) > 3 else ""

        if not state_pattern.match(status):
            continue
        if not state_pattern.match(protocol):
            protocol = None

        state = status.lower()
        protocol_state = str(protocol).lower()
        health = (
            "PASS" if state == "up" and protocol_state == "up"
            else "WARNING" if state in {"down", "admin down", "admin-down", "shutdown"}
            else "UNKNOWN"
        )

        results.append({
            "interface": interface,
            "status_raw": status,
            "protocol": protocol,
            "description": description,
            "health": health,
        })

    return results


def audit_ncs_device(device: dict[str, Any]) -> dict[str, Any]:
    hostname = device.get("hostname")
    ip = device.get("ip")
    zabbix_hostid = device.get("zabbix_hostid")
    base = {
        "hostname": hostname,
        "ip": ip,
        "zabbix_hostid": zabbix_hostid,
        "device_type": "ncs540",
        "role": device.get("role", "ncs_aggregation"),
        "site_identity": device.get("site_identity"),
        "status": "UNKNOWN",
    }

    if not ip:
        return {
            **base,
            "status": "NOT_AVAILABLE",
            "message": "NCS 540 has no IP address.",
        }

    connection = None
    command_outputs: dict[str, dict[str, Any]] = {}
    try:
        # NCS 540 runs IOS-XR; do not connect using the IOS driver.
        connection = connect_device(ip, device_type="cisco_xr")

        for setup_command in ("terminal length 0", "terminal width 511"):
            try:
                connection.send_command(
                    setup_command,
                    read_timeout=SSH_COMMAND_TIMEOUT,
                )
            except Exception:
                pass

        for command in NCS_COMMANDS:
            command_outputs[command] = run_command(connection, command)

        description_output = command_outputs.get(
            "show interfaces description", {}
        ).get("output", "")
        detail_output = command_outputs.get(
            "show interfaces", {}
        ).get("output", "")
        logging_output = command_outputs.get(
            "show logging last 10", {}
        ).get("output", "")

        interface_rows = parse_ncs_interfaces_description(description_output)
        details = parse_interfaces_detail(detail_output)
        detail_by_name = {
            str(row.get("interface", "")).lower(): row
            for row in details
            if row.get("interface")
        }

        interfaces: list[dict[str, Any]] = []
        for row in interface_rows:
            detail = detail_by_name.get(str(row["interface"]).lower())
            merged = {**row}
            if detail:
                merged.update({
                    "line_state": detail.get("line_state"),
                    "crc": detail.get("crc"),
                    "input_errors": detail.get("input_errors"),
                    "output_errors": detail.get("output_errors"),
                    "output_drops": detail.get("output_drops"),
                    "carrier_transitions": detail.get("carrier_transitions"),
                    "bandwidth_kbps": detail.get("bandwidth_kbps"),
                })
            else:
                merged.update({
                    "crc": None,
                    "input_errors": None,
                    "output_errors": None,
                    "output_drops": None,
                })

            crc = merged.get("crc")
            if crc is not None and crc > 0:
                merged["health"] = aggregate_status([
                    merged.get("health", "UNKNOWN"),
                    "WARNING",
                ])
                merged["health_reason"] = f"CRC errors detected: {crc}."
            interfaces.append(merged)

        crc_problems = [
            {
                "interface": row.get("interface"),
                "description": row.get("description"),
                "crc": row.get("crc"),
                "health": "WARNING",
            }
            for row in interfaces
            if row.get("crc") is not None and row.get("crc") > 0
        ]

        logging_data = parse_logging(logging_output, limit=10)
        if command_outputs.get("show logging last 10", {}).get("status") != "PASS":
            logging_data["status"] = "NOT_AVAILABLE"

        interface_status = aggregate_status([
            row.get("health", "UNKNOWN") for row in interfaces
        ]) if interfaces else "UNKNOWN"

        overall = aggregate_status([
            interface_status,
            logging_data.get("status", "UNKNOWN"),
        ])

        return {
            **base,
            "status": overall,
            "checks": {
                "connectivity": status_result(
                    "PASS",
                    "SSH connection established using Cisco IOS-XR profile.",
                ),
                "interfaces": {
                    "status": interface_status,
                    "count": len(interfaces),
                    "data": interfaces,
                    "problems": {
                        "crc_count": len(crc_problems),
                        "crc": crc_problems,
                    },
                },
                "logging": logging_data,
            },
            "raw_commands": command_outputs,
        }

    except NetmikoAuthenticationException as exc:
        return {
            **base,
            "status": "CRITICAL",
            "message": "NCS SSH authentication failed.",
            "error": str(exc),
        }
    except NetmikoTimeoutException as exc:
        return {
            **base,
            "status": "CRITICAL",
            "message": "NCS SSH connection timed out.",
            "error": str(exc),
        }
    except Exception as exc:
        return {
            **base,
            "status": "UNKNOWN",
            "message": "NCS 540 health check failed.",
            "error": str(exc),
        }
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


# ============================================================
# API
# ============================================================

@app.get("/health")
def health():
    return {
        "service": "cisco",
        "status": "ok",
    }


@app.post("/check")
def check(payload: dict):

    devices = payload.get(
        "devices",
        [],
    )

    if not isinstance(devices, list):
        return {
            "service": "cisco",
            "site_code": payload.get(
                "site_code"
            ),
            "status": "UNKNOWN",
            "results": [],
            "error": "devices must be a list",
        }

    results = []

    for device in devices:

        if not isinstance(device, dict):
            results.append({
                "status": "UNKNOWN",
                "message": "Invalid device payload.",
            })
            continue

        results.append(
            audit_device(device)
        )

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
        "service": "cisco",
        "site_code": payload.get(
            "site_code"
        ),
        "status": overall,
        "results": results,
    }
