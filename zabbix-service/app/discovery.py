from __future__ import annotations

import os
import re
from typing import Any, Iterable

from dotenv import load_dotenv

from .client import ZabbixClient
from .models import Baseband, Device, DiscoveryResult, Interface, RadioLink

load_dotenv("/opt/pop-audit/config/.env", override=False)

_TOKEN_IGNORES = {
    "lte", "bh", "backhaul", "th", "tth", "alb", "sw", "switch",
    "ncs", "ncs540", "agg", "aggregation", "asr", "router", "rtr",
    "cisco", "mikrotik", "mikro", "enodeb", "nodeb", "baseband",
    "huawei", "rtn", "eband", "intracom", "intracome", "introcom",
    "nray", "nrays", "n", "to", "from", "radio", "link", "lte",
}


def normalize_site_code(site_code: str) -> str:
    value = str(site_code or "").strip()
    if not re.fullmatch(r"\d{4}", value):
        raise ValueError("Site code must contain exactly four digits.")
    return value


def extract_numeric_tokens(text: str) -> list[str]:
    return re.findall(r"(?<!\d)\d+(?!\d)", text or "")


def extract_baseband_ids(text: str) -> set[str]:
    return set(re.findall(r"(?<!\d)\d{4}(?!\d)", text or ""))


def contains_site_code(text: str, site_codes: set[str]) -> bool:
    return any(token in site_codes for token in extract_numeric_tokens(text))


def get_primary_interface(host: dict[str, Any]) -> Interface | None:
    interfaces = host.get("interfaces") or []
    if not interfaces:
        return None
    main = [item for item in interfaces if str(item.get("main")) == "1"]
    selected = main[0] if main else interfaces[0]
    return Interface(**selected)


def get_group_names(host: dict[str, Any]) -> list[str]:
    return [item["name"] for item in host.get("groups", []) if item.get("name")]


def get_template_names(host: dict[str, Any]) -> list[str]:
    return [
        item["name"]
        for item in host.get("parentTemplates", [])
        if item.get("name")
    ]


def _inventory_text(host: dict[str, Any]) -> str:
    inventory = host.get("inventory") or {}
    if not isinstance(inventory, dict):
        return ""
    return " ".join(str(value) for value in inventory.values() if value)


def detect_device_type(host: dict[str, Any]) -> tuple[str, str]:
    hostname = " ".join((host.get("host", ""), host.get("name", ""))).lower()
    templates = " ".join(get_template_names(host)).lower()
    groups = " ".join(get_group_names(host)).lower()
    inventory = _inventory_text(host).lower()
    evidence = " ".join((hostname, templates, groups, inventory))

    if "mikrotik" in evidence or "mikro tik" in evidence:
        return "MikroTik", "router"

    cisco_evidence = (
        "cisco" in templates
        or "cisco" in inventory
        or re.search(r"\b(?:cisco|asr|ncs(?:\s|-)?540|ncs\d{3})\b", hostname)
        or re.search(r"(?:^|[-_])(?:th|tth|alb)?[-_]?bh[-_](?:sw|rtr|ncs)(?:[-_]|$)", hostname)
    )
    if not cisco_evidence:
        return "Unknown", "network-device"

    if re.search(r"\bncs\s*540\b|\bncs540\b|(?:^|[-_])ncs(?:[-_]|$)", evidence):
        return "Cisco", "ncs540"
    if re.search(r"\basr(?:-\d+)?\b", evidence):
        return "Cisco", "router"
    return "Cisco", "switch"


def _words(text: str) -> set[str]:
    values = re.findall(r"[A-Za-z][A-Za-z0-9]+", text or "")
    return {
        value.lower()
        for value in values
        if len(value) > 2 and value.lower() not in _TOKEN_IGNORES
    }


def location_tokens(host: dict[str, Any]) -> set[str]:
    # A location identifier is a meaningful hostname/inventory token,
    # not a POP number or device-role prefix.
    text = " ".join((
        host.get("host", ""),
        host.get("name", ""),
        host.get("description", ""),
        _inventory_text(host),
    ))
    return _words(text)


def infer_radio_type(host: dict[str, Any]) -> str:
    name = " ".join((
        host.get("host", ""),
        host.get("name", ""),
        " ".join(get_group_names(host)),
        " ".join(get_template_names(host)),
        _inventory_text(host),
    )).lower()

    groups = {x.lower() for x in get_group_names(host)}
    templates = " ".join(get_template_names(host)).lower()

    # Explicit Zabbix group/template evidence is stronger than aliases.
    if any("radio-huawei" in group for group in groups):
        return "RTN"
    if "huawei rtn" in templates or "rtn huawei" in templates:
        return "RTN"

    if "eband" in name or "e-band" in name:
        return "EBAND"
    if re.search(r"\b(?:rtn|huawei)\b", name):
        return "RTN"
    compact = re.sub(r"[^a-z0-9]", "", name)
    if any(alias in compact for alias in ("intracom", "intracome", "introcom")):
        return "INTRACOM"
    if re.search(r"\bn[\s-]?rays?\b", name) or "nray" in compact:
        return "NRAY"

    return "UNKNOWN"


def split_link_name(name: str) -> tuple[str | None, str | None]:
    value = (name or "").replace("→", "->")
    separators = ("->", "-to-", " to ")
    lower = value.lower()
    for separator in separators:
        position = lower.find(separator)
        if position < 0:
            continue
        left = value[:position].strip(" -_")
        right = value[position + len(separator):].strip(" -_")
        if left and right:
            return left, right
    return None, None


def parse_direction(name: str, site_code: str) -> tuple[str | None, str | None, str | None]:
    left, right = split_link_name(name)
    if not left or not right:
        return None, None, None

    left_tokens = extract_numeric_tokens(left)
    source = next((token for token in left_tokens if token == site_code), None)
    if source is None:
        return None, None, None

    destination_tokens = extract_numeric_tokens(right)
    destination = next((token for token in destination_tokens if token != site_code), None)
    return source, destination, right


def _host_text(host: dict[str, Any]) -> str:
    return " ".join((host.get("host", ""), host.get("name", "")))


def _unique_hosts(hosts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for host in hosts:
        host_id = str(host.get("hostid") or "")
        if host_id:
            by_id.setdefault(host_id, host)
    return list(by_id.values())


def _device_from_host(host: dict[str, Any], device_type: str | None = None) -> Device:
    interface = get_primary_interface(host)
    vendor, detected_type = detect_device_type(host)
    return Device(
        hostname=host.get("name") or host.get("host") or "Unknown",
        ip=interface.ip if interface else None,
        vendor=vendor,
        device_type=device_type or detected_type,
        role="network",
        zabbix_hostid=str(host["hostid"]),
        groups=get_group_names(host),
        templates=get_template_names(host),
        description=host.get("description") or "",
    )


def _baseband_from_host(host: dict[str, Any], slot: str) -> Baseband:
    interface = get_primary_interface(host)
    return Baseband(
        name=slot,
        exists=True,
        status="UNKNOWN",
        hostname=host.get("name") or host.get("host") or "Unknown",
        ip=interface.ip if interface else None,
        zabbix_hostid=str(host["hostid"]),
        groups=get_group_names(host),
        templates=get_template_names(host),
    )


def _missing_baseband(slot: str, status: str = "NOT_EXISTS", reason: str | None = None) -> Baseband:
    return Baseband(
        name=slot,
        exists=False,
        status=status,
        hostname=None,
        ip=None,
        zabbix_hostid=None,
        groups=[],
        templates=[],
        reason=reason,
    )


class SiteDiscovery:
    def __init__(self, client: ZabbixClient | None = None):
        self.client = client or ZabbixClient()
        self.enodeb_group = os.getenv("ZABBIX_GROUP_ENODEB", "LTE-Backhaul-eNodeB")
        self.switch_group = os.getenv("ZABBIX_GROUP_SWITCH", "LTE-Backhaul-Switch")
        self.switch_aggregation_group = os.getenv(
            "ZABBIX_GROUP_SWITCH_AGGREGATION",
            "LTE-Backhaul-Switch-Aggregation",
        )
        self.radio_group = os.getenv("ZABBIX_GROUP_RADIO", "LTE-Backhaul-Radio")
        self.radio_huawei_group = os.getenv(
            "ZABBIX_GROUP_RADIO_HUAWEI",
            "LTE-Backhaul-Radio-Huawei",
        )

    def _hosts_for_group(self, group_name: str, errors: list[str]) -> list[dict[str, Any]]:
        group = self.client.get_group_by_name(group_name)
        if not group:
            errors.append(f"Zabbix group not found: {group_name}")
            return []
        return _unique_hosts(self.client.get_hosts_by_group(group["groupid"]))

    def _discover_basebands(self, site_code: str, errors: list[str], warnings: list[str]) -> tuple[list[Baseband], list[dict[str, Any]]]:
        hosts = self._hosts_for_group(self.enodeb_group, errors)
        group_missing = any(
            message == f"Zabbix group not found: {self.enodeb_group}"
            for message in errors
        )
        if group_missing:
            reason = f"Required Zabbix group {self.enodeb_group} is unavailable."
            return [
                _missing_baseband("BB1", "NOT_AVAILABLE", reason),
                _missing_baseband("BB2", "NOT_AVAILABLE", reason),
            ], []

        candidates: list[tuple[dict[str, Any], set[str]]] = []
        for host in hosts:
            ids = extract_baseband_ids(_host_text(host))
            if ids and any(value.endswith(site_code[-3:]) for value in ids):
                candidates.append((host, ids))

        exact = [(host, ids) for host, ids in candidates if site_code in ids]
        alternatives = [
            (host, ids) for host, ids in candidates
            if site_code not in ids
        ]

        if len(exact) > 1:
            warnings.append(
                "Multiple distinct Baseband hosts match the exact Site Code; BB1 is ambiguous."
            )
            return [
                _missing_baseband("BB1", "UNKNOWN", "Ambiguous exact Site Code Baseband candidates."),
                _missing_baseband("BB2", "NOT_EXISTS"),
            ], []

        if exact:
            bb1_host = exact[0][0]
            bb1 = _baseband_from_host(bb1_host, "BB1")
            alternatives = [
                (host, ids) for host, ids in alternatives
                if str(host.get("hostid")) != str(bb1_host.get("hostid"))
            ]
            if len(alternatives) == 1:
                bb2 = _baseband_from_host(alternatives[0][0], "BB2")
                selected = [bb1_host, alternatives[0][0]]
            elif len(alternatives) > 1:
                names = sorted(host.get("name") or host.get("host") or "" for host, _ in alternatives)
                warnings.append("Ambiguous BB2 candidates: " + ", ".join(names))
                bb2 = _missing_baseband("BB2", "UNKNOWN", "Multiple Baseband candidates share the final three digits.")
                selected = [bb1_host]
            else:
                bb2 = _missing_baseband("BB2")
                selected = [bb1_host]
            return [bb1, bb2], selected

        # BB1 is always the exact four-digit Site Code. A 7xxx/8xxx
        # variant can only populate BB2; it must never be promoted to BB1.
        bb1 = _missing_baseband("BB1")
        if len(alternatives) == 1:
            host = alternatives[0][0]
            warnings.append("Exact BB1 Site Code was not found; a matching final-three-digit Baseband was discovered as BB2.")
            return [bb1, _baseband_from_host(host, "BB2")], [host]
        if len(alternatives) > 1:
            names = sorted(host.get("name") or host.get("host") or "" for host, _ in alternatives)
            warnings.append("BB2 candidates are ambiguous: " + ", ".join(names))
            return [
                bb1,
                _missing_baseband("BB2", "UNKNOWN", "Multiple Baseband candidates share the final three digits."),
            ], []
        return [bb1, _missing_baseband("BB2")], []


    def discover(self, site_code: str) -> DiscoveryResult:
        site_code = normalize_site_code(site_code)
        result = DiscoveryResult(site_code=site_code)

        self.client.login()

        basebands, baseband_hosts = self._discover_basebands(
            site_code, result.errors, result.warnings
        )
        result.basebands = basebands

        switch_hosts = self._hosts_for_group(
            self.switch_group, result.errors
        )
        site_switch_hosts: list[dict[str, Any]] = []
        for host in switch_hosts:
            if not contains_site_code(_host_text(host), {site_code}):
                continue
            vendor, device_type = detect_device_type(host)
            if vendor != "Cisco" or device_type == "ncs540":
                continue
            site_switch_hosts.append(host)

        site_switch_hosts = _unique_hosts(site_switch_hosts)
        result.devices = [
            _device_from_host(host) for host in site_switch_hosts
        ]

        # The POP identity is inferred from location tokens shared by its
        # discovered Baseband and site-specific primary switch(es).
        site_tokens: set[str] = set()
        bb_tokens = set().union(*(location_tokens(host) for host in baseband_hosts)) if baseband_hosts else set()
        switch_tokens = set().union(*(location_tokens(host) for host in site_switch_hosts)) if site_switch_hosts else set()
        shared = bb_tokens & switch_tokens
        site_tokens.update(shared or bb_tokens or switch_tokens)
        if site_tokens:
            result.site_identity = sorted(site_tokens, key=lambda value: (len(value), value))[0]

        ncs_error_count = len(result.errors)
        ncs_hosts = self._hosts_for_group(
            self.switch_aggregation_group, result.errors
        )
        if len(result.errors) > ncs_error_count:
            result.ncs_status = "NOT_AVAILABLE"
            result.ncs_reason = f"Zabbix group {self.switch_aggregation_group} is unavailable."
        ncs_matches: list[dict[str, Any]] = []
        possible_ncs_hosts = []
        for host in ncs_hosts:
            vendor, device_type = detect_device_type(host)
            if device_type != "ncs540":
                # Aggregation group is not, by itself, proof of a Cisco NCS.
                continue
            possible_ncs_hosts.append(host)
            candidate_tokens = location_tokens(host)
            if site_tokens and candidate_tokens.intersection(site_tokens):
                ncs_matches.append(host)

        if possible_ncs_hosts and not site_tokens:
            result.ncs_status = "UNKNOWN"
            result.ncs_reason = "NCS 540 candidates exist, but Zabbix metadata did not provide enough POP location identity to associate one safely."
            result.warnings.append(result.ncs_reason)

        ncs_matches = _unique_hosts(ncs_matches)
        if len(ncs_matches) == 1:
            result.ncs_devices = [
                _device_from_host(ncs_matches[0], "ncs540")
            ]
            result.ncs_status = "UNKNOWN"  # Pending the live Cisco audit.
            result.ncs_reason = "A unique NCS 540 candidate was associated by POP location."
        elif len(ncs_matches) > 1:
            names = sorted(host.get("name") or host.get("host") or "" for host in ncs_matches)
            result.ncs_status = "UNKNOWN"
            result.ncs_reason = "Ambiguous NCS 540 association: " + ", ".join(names)
            result.warnings.append(
                "NCS 540 association is ambiguous for this POP: " + ", ".join(names)
            )
        # No matched NCS remains NOT_EXISTS unless the aggregation group is unavailable.

        radio_hosts = []
        radio_hosts.extend(self._hosts_for_group(self.radio_group, result.errors))
        radio_hosts.extend(self._hosts_for_group(self.radio_huawei_group, result.errors))
        radio_hosts = _unique_hosts(radio_hosts)

        for host in radio_hosts:
            canonical_name = host.get("name") or host.get("host") or ""
            # Examine both internal host and visible name because Zabbix
            # sometimes stores the direction in only one of the two fields.
            parsed = None
            for candidate_name in (canonical_name, host.get("host", "")):
                source, destination, destination_name = parse_direction(
                    candidate_name, site_code
                )
                if source == site_code:
                    parsed = (source, destination, destination_name)
                    if candidate_name == canonical_name:
                        break
            if parsed is None:
                continue

            source, destination, destination_name = parsed
            result.radio_links.append(
                RadioLink(
                    name=canonical_name,
                    link_type=infer_radio_type(host),
                    source_site=source,
                    destination_site=destination,
                    destination_name=destination_name,
                    zabbix_hostid=str(host["hostid"]),
                    groups=get_group_names(host),
                    templates=get_template_names(host),
                )
            )

        # Keep ordering stable for downstream reports and deterministic tests.
        result.radio_links.sort(
            key=lambda item: (item.link_type, item.name.lower(), item.zabbix_hostid)
        )
        return result
