from __future__ import annotations

import os
import re
from collections import Counter
from typing import Iterable

from dotenv import load_dotenv

from .client import ZabbixClient
from .models import Baseband, Device, DiscoveryResult, Interface, RadioLink


load_dotenv("/opt/pop-audit/config/.env")


# Words that describe device roles/vendors rather than a POP identity.
_GENERIC_LOCATION_WORDS = {
    "TH", "BH", "SW", "RTR", "ROUTER", "SWITCH", "NCS", "AGG",
    "AGGREGATION", "ENODEB", "ENB", "LTE", "BACKHAUL", "RADIO",
    "EBAND", "RTN", "HUAWEI", "ERICSSON", "INTRACOM", "INTRACOME",
    "INTROCOM", "NRAY", "NRAYS", "TO", "FROM", "OLD", "II",
    "CISCO", "540", "IP", "POP", "SITE",
}


def normalize_site_code(site_code: str) -> str:
    value = str(site_code or "").strip()
    if not value.isdigit():
        raise ValueError("Site code must contain digits only.")
    if len(value) != 4:
        raise ValueError("Site code must be exactly four digits.")
    return value


def related_site_codes(site_code: str) -> set[str]:
    """Return all four-digit BB identifiers sharing the site's final 3 digits."""
    site_code = normalize_site_code(site_code)
    suffix = site_code[-3:]
    return {f"{digit}{suffix}" for digit in "0123456789"}


def extract_numeric_tokens(text: str) -> list[str]:
    return re.findall(r"(?<!\d)\d+(?!\d)", text or "")


def extract_four_digit_codes(text: str) -> list[str]:
    return re.findall(r"(?<!\d)\d{4}(?!\d)", text or "")


def contains_site_code(text: str, site_codes: set[str]) -> bool:
    return any(token in site_codes for token in extract_numeric_tokens(text))


def get_primary_interface(host: dict) -> Interface | None:
    interfaces = host.get("interfaces") or []
    if not interfaces:
        return None
    selected = next((item for item in interfaces if str(item.get("main")) == "1"), interfaces[0])
    try:
        return Interface(**selected)
    except Exception:
        return None


def get_group_names(host: dict) -> list[str]:
    return [str(item["name"]) for item in host.get("groups") or [] if item.get("name")]


def get_template_names(host: dict) -> list[str]:
    templates = host.get("parentTemplates") or host.get("templates") or []
    return [str(item["name"]) for item in templates if item.get("name")]


def host_text(host: dict) -> str:
    return " ".join(str(host.get(key) or "") for key in ("host", "name", "description"))


def location_tokens(host_or_text: dict | str, site_code: str | None = None) -> set[str]:
    raw = host_text(host_or_text) if isinstance(host_or_text, dict) else str(host_or_text or "")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", raw.upper())
    result = set()
    for token in tokens:
        if token in _GENERIC_LOCATION_WORDS or token.isdigit():
            continue
        if token.isdigit() or len(token) < 3:
            continue
        if site_code and token == site_code:
            continue
        result.add(token)
    return result


def detect_device_type(host: dict) -> tuple[str, str]:
    hostname = str(host.get("name") or host.get("host") or "").lower()
    groups = [name.lower() for name in get_group_names(host)]
    templates = [name.lower() for name in get_template_names(host)]
    combined = " ".join([hostname, *groups, *templates])

    # NCS identity has precedence over generic switch classification.
    if "ncs" in hostname or any("switch-aggregation" in group for group in groups):
        return "Cisco", "ncs540"

    if any("cisco" in template or "ios" in template or "ios-xr" in template for template in templates):
        if "asr" in hostname:
            return "Cisco", "router"
        return "Cisco", "switch"

    # The normal switch group is authoritative only when the host does not
    # explicitly identify another vendor such as MikroTik.
    if any("switch" in group for group in groups):
        if any(term in combined for term in ("mikrotik", "routeros", "router os")):
            return "MikroTik", "router"
        if "ncs" in hostname:
            return "Cisco", "ncs540"
        return "Cisco", "switch"

    if "ncs" in hostname or "cisco" in combined:
        return "Cisco", "ncs540" if "ncs" in hostname else "switch"
    if "asr" in hostname:
        return "Cisco", "router"
    if "mikrotik" in combined or "routeros" in combined:
        return "MikroTik", "router"
    return "Unknown", "network-device"


def infer_radio_type(name: str, groups: Iterable[str] = (), templates: Iterable[str] = ()) -> str:
    value = " ".join([str(name or ""), *map(str, groups), *map(str, templates)]).lower()
    compact = re.sub(r"[^a-z0-9]", "", value)

    # Explicit technology/vendor signals precede generic "radio" group membership.
    if "eband" in compact or "eband" in value:
        return "EBand"
    if any(term in compact for term in ("intracom", "intracome", "introcom")):
        return "Intracom"
    if "nray" in compact or "nrays" in compact or "nray" in value:
        return "NRay"
    if "rtn" in compact or "huawei" in compact or "radio-huawei" in value:
        return "RTN"
    return "Unknown"


def split_link_name(name: str) -> tuple[str | None, str | None]:
    value = str(name or "").replace("→", "->")
    for separator in ("->", "-to-", " to "):
        position = value.lower().find(separator)
        if position < 0:
            continue
        left = value[:position].strip(" -")
        right = value[position + len(separator):].strip(" -")
        if left and right:
            return left, right
    return None, None


def parse_direction(name: str, site_code: str) -> tuple[str | None, str | None, str | None]:
    left, right = split_link_name(name)
    if not left or not right:
        return None, None, None

    # Source must be the exact requested POP code on the left side.
    source = next((code for code in extract_numeric_tokens(left) if code == site_code), None)
    destination = next((code for code in extract_numeric_tokens(right) if code != site_code), None)
    return source, destination, right


def _unique_hosts(host_lists: Iterable[list[dict]]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for hosts in host_lists:
        for host in hosts or []:
            host_id = str(host.get("hostid") or "")
            if host_id and host_id not in by_id:
                by_id[host_id] = host
    return sorted(by_id.values(), key=lambda item: str(item.get("name") or item.get("host") or "").lower())


class SiteDiscovery:
    def __init__(self):
        self.client = ZabbixClient()
        self.enodeb_group = os.getenv("ZABBIX_GROUP_ENODEB", "LTE-Backhaul-eNodeB")
        self.switch_group = os.getenv("ZABBIX_GROUP_SWITCH", "LTE-Backhaul-Switch")
        self.aggregation_group = os.getenv(
            "ZABBIX_GROUP_SWITCH_AGGREGATION",
            "LTE-Backhaul-Switch-Aggregation",
        )
        self.radio_groups = [
            os.getenv("ZABBIX_GROUP_RADIO", "LTE-Backhaul-Radio"),
            os.getenv("ZABBIX_GROUP_RADIO_HUAWEI", "LTE-Backhaul-Radio-Huawei"),
        ]

    def _hosts_for_group(self, group_name: str, *, required: bool = False) -> list[dict]:
        group = self.client.get_group_by_name(group_name)
        if not group:
            if required:
                return []
            return []
        return self.client.get_hosts_by_group(group["groupid"])

    def discover(self, site_code: str) -> DiscoveryResult:
        site_code = normalize_site_code(site_code)
        result = DiscoveryResult(site_code=site_code)
        self.client.login()

        # -------------------------- Basebands --------------------------
        enodeb_group = self.client.get_group_by_name(self.enodeb_group)
        baseband_hosts: list[dict] = []
        if not enodeb_group:
            result.errors.append(f"Required Zabbix group not found: {self.enodeb_group}")
        else:
            candidates = self.client.get_hosts_by_group(enodeb_group["groupid"])
            for host in candidates:
                codes = set(extract_four_digit_codes(host_text(host)))
                if site_code in codes or (codes & (related_site_codes(site_code) - {site_code})):
                    baseband_hosts.append(host)

            exact = [host for host in baseband_hosts if site_code in set(extract_four_digit_codes(host_text(host)))]
            alternates = [
                host for host in baseband_hosts
                if site_code not in set(extract_four_digit_codes(host_text(host)))
                and bool(set(extract_four_digit_codes(host_text(host))) & (related_site_codes(site_code) - {site_code}))
            ]

            exact = _unique_hosts([exact])
            alternates = _unique_hosts([alternates])

            if exact:
                primary = exact[0]
                iface = get_primary_interface(primary)
                result.basebands.append(Baseband(
                    hostname=primary.get("name") or primary.get("host") or "",
                    ip=iface.ip if iface else None,
                    zabbix_hostid=str(primary["hostid"]),
                    role="BB1",
                    site_code=site_code,
                    groups=get_group_names(primary),
                    templates=get_template_names(primary),
                ))
                if len(exact) > 1:
                    result.warnings.append(
                        f"Multiple exact Site Code Basebands found for {site_code}; selected {exact[0].get('name')} and retained the others as discovery warnings."
                    )
            else:
                result.warnings.append(f"Baseband 1 was not found for Site Code {site_code}.")

            # There should be at most one alternate BB code. Never select
            # arbitrarily when more than one first digit is configured.
            alternate_codes: dict[str, list[dict]] = {}
            for host in alternates:
                host_codes = set(extract_four_digit_codes(host_text(host)))
                for code in host_codes:
                    if code in related_site_codes(site_code) - {site_code}:
                        alternate_codes.setdefault(code, []).append(host)

            if len(alternate_codes) == 1:
                bb_code, matches = next(iter(alternate_codes.items()))
                matches = _unique_hosts([matches])
                if len(matches) == 1:
                    host = matches[0]
                    iface = get_primary_interface(host)
                    result.basebands.append(Baseband(
                        hostname=host.get("name") or host.get("host") or "",
                        ip=iface.ip if iface else None,
                        zabbix_hostid=str(host["hostid"]),
                        role="BB2",
                        site_code=bb_code,
                        groups=get_group_names(host),
                        templates=get_template_names(host),
                    ))
                elif len(matches) > 1:
                    result.warnings.append(
                        f"Multiple Baseband hosts advertise BB code {bb_code}; BB2 association is ambiguous."
                    )
            elif len(alternate_codes) > 1:
                result.warnings.append(
                    "Multiple alternate Baseband codes share the final three digits of the Site Code; BB2 was not selected: "
                    + ", ".join(sorted(alternate_codes))
                )

        # ------------------------ Primary Cisco ------------------------
        switch_group = self.client.get_group_by_name(self.switch_group)
        primary_switch_hosts: list[dict] = []
        if not switch_group:
            result.errors.append(f"Required Zabbix group not found: {self.switch_group}")
        else:
            candidates = self.client.get_hosts_by_group(switch_group["groupid"])
            for host in candidates:
                if not contains_site_code(host_text(host), {site_code}):
                    continue
                vendor, device_type = detect_device_type(host)
                if vendor != "Cisco" or device_type == "ncs540":
                    # Do not accidentally audit MikroTik or other vendors as Cisco IOS.
                    continue
                primary_switch_hosts.append(host)

            for host in _unique_hosts([primary_switch_hosts]):
                iface = get_primary_interface(host)
                result.devices.append(Device(
                    hostname=host.get("name") or host.get("host") or "",
                    ip=iface.ip if iface else None,
                    vendor="Cisco",
                    device_type="switch",
                    role="primary_switch",
                    zabbix_hostid=str(host["hostid"]),
                    groups=get_group_names(host),
                    templates=get_template_names(host),
                    description=host.get("description") or "",
                ))

        # Infer POP identity from the overlap between site-specific BB and
        # switch names. Do not use unrelated radio destination names.
        identity_candidates: Counter = Counter()
        site_hosts = _unique_hosts([baseband_hosts, primary_switch_hosts])
        for host in site_hosts:
            tokens = location_tokens(host, site_code)
            for token in tokens:
                identity_candidates[token] += 1
        # A POP identity is stronger when shared by at least one BB and one
        # site-specific Cisco switch.
        bb_tokens = set().union(*(location_tokens(h, site_code) for h in baseband_hosts)) if baseband_hosts else set()
        switch_tokens = set().union(*(location_tokens(h, site_code) for h in primary_switch_hosts)) if primary_switch_hosts else set()
        shared_identity = bb_tokens & switch_tokens
        if len(shared_identity) == 1:
            result.site_identity = next(iter(shared_identity))
        elif len(shared_identity) > 1:
            # Prefer the common token with highest appearance count only if unique.
            scored = sorted(((identity_candidates[token], token) for token in shared_identity), reverse=True)
            if len(scored) == 1 or scored[0][0] > scored[1][0]:
                result.site_identity = scored[0][1]
            else:
                result.warnings.append(
                    "Could not determine a unique POP identity from Baseband and primary-switch hostnames: "
                    + ", ".join(sorted(shared_identity))
                )
        elif bb_tokens or switch_tokens:
            result.warnings.append(
                "POP identity could not be cross-validated between Baseband and primary Cisco Switch hostnames; NCS association will be skipped."
            )

        # ----------------------------- NCS -----------------------------
        aggregation_group = self.client.get_group_by_name(self.aggregation_group)
        if not aggregation_group:
            result.warnings.append(f"NCS aggregation group not found: {self.aggregation_group}")
        else:
            ncs_hosts = self.client.get_hosts_by_group(aggregation_group["groupid"])
            anchor_tokens = {result.site_identity} if result.site_identity else set()
            matches: list[tuple[int, dict]] = []
            if anchor_tokens:
                for host in ncs_hosts:
                    vendor, device_type = detect_device_type(host)
                    if device_type != "ncs540":
                        continue
                    overlap = anchor_tokens & location_tokens(host, site_code)
                    if overlap:
                        matches.append((len(overlap), host))

            if matches:
                highest = max(score for score, _ in matches)
                best = _unique_hosts([[host for score, host in matches if score == highest]])
                if len(best) == 1:
                    host = best[0]
                    iface = get_primary_interface(host)
                    result.devices.append(Device(
                        hostname=host.get("name") or host.get("host") or "",
                        ip=iface.ip if iface else None,
                        vendor="Cisco",
                        device_type="ncs540",
                        role="ncs_aggregation",
                        zabbix_hostid=str(host["hostid"]),
                        groups=get_group_names(host),
                        templates=get_template_names(host),
                        description=host.get("description") or "",
                        site_identity=result.site_identity,
                    ))
                else:
                    result.warnings.append(
                        f"Multiple NCS 540 hosts match POP identity {result.site_identity}; no NCS device was associated."
                    )
            elif result.site_identity:
                result.warnings.append(
                    f"No NCS 540 host matching POP identity {result.site_identity} was found."
                )

        # ----------------------------- Radios --------------------------
        radio_host_lists: list[list[dict]] = []
        for group_name in self.radio_groups:
            group = self.client.get_group_by_name(group_name)
            if not group:
                result.warnings.append(f"Optional radio group not found: {group_name}")
                continue
            radio_host_lists.append(self.client.get_hosts_by_group(group["groupid"]))

        for host in _unique_hosts(radio_host_lists):
            canonical_name = host.get("name") or host.get("host") or ""
            source, destination, destination_name = parse_direction(canonical_name, site_code)
            # Strictly outgoing links only. Never include a radio whose left/source
            # endpoint is another POP even if the requested Site Code is on the right.
            if source != site_code:
                continue

            link_type = infer_radio_type(
                canonical_name,
                get_group_names(host),
                get_template_names(host),
            )
            if link_type == "Unknown":
                result.warnings.append(
                    f"Radio {canonical_name} originates from Site {site_code}, but its technology could not be classified."
                )

            result.radio_links.append(RadioLink(
                name=canonical_name,
                link_type=link_type,
                source_site=source,
                destination_site=destination,
                destination_name=destination_name,
                zabbix_hostid=str(host["hostid"]),
                source_hostname=host.get("host") or canonical_name,
            ))

        result.basebands.sort(key=lambda item: 0 if item.role == "BB1" else 1)
        result.radio_links.sort(key=lambda item: (item.link_type, item.name.lower()))
        result.devices.sort(key=lambda item: (0 if item.role == "primary_switch" else 1, item.hostname.lower()))
        return result
