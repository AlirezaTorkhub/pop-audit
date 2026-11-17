import os
import re

from dotenv import load_dotenv

from .client import ZabbixClient
from .models import (
    Baseband,
    Device,
    DiscoveryResult,
    Interface,
    RadioLink,
)


load_dotenv(
    "/opt/pop-audit/config/.env"
)


def normalize_site_code(
    site_code: str,
) -> str:

    value = str(
        site_code
    ).strip()

    if not value.isdigit():

        raise ValueError(
            "Site code must contain digits only."
        )

    return value


def is_host_enabled(host: dict) -> bool:
    """
    Zabbix host status 0 means enabled/monitored; 1 means disabled.
    Unknown status is excluded so an incomplete host record is never audited.
    """
    return str(host.get("status", "")) == "0"


def matches_baseband_site_code(
    text: str,
    site_code: str,
) -> bool:
    """
    Match the primary baseband by its exact Site Code.

    A secondary baseband is included only when its numeric token has the
    same width as the requested Site Code and shares its last three digits.
    Example: 2392 -> 7392.
    """
    site_code = normalize_site_code(site_code)
    tokens = extract_numeric_tokens(text)

    if site_code in tokens:
        return True

    if len(site_code) < 4:
        return False

    suffix = site_code[-3:]
    return any(
        len(token) == len(site_code)
        and token != site_code
        and token[-3:] == suffix
        for token in tokens
    )


def host_location_tokens(host: dict) -> set[str]:
    """
    Return non-generic location tokens from a Zabbix host's name,
    technical host name, description and inventory fields.
    """
    parts = [
        host.get("name", ""),
        host.get("host", ""),
        host.get("description", ""),
    ]

    inventory = host.get("inventory") or {}
    if isinstance(inventory, dict):
        for key in (
            "location",
            "location_name",
            "site_address_a",
            "site_address_b",
            "site_city",
            "site_state",
            "site_country",
            "notes",
        ):
            parts.append(inventory.get(key, ""))

    generic_tokens = {
        "th", "bh", "sw", "switch", "router", "rtr",
        "ncs", "agg", "aggregation", "cisco", "fdi",
        "ptp", "temperature", "template", "only", "olny",
        "lte", "backhaul", "network", "old", "ii",
        "site", "the", "and",
    }

    tokens = {
        token.lower()
        for part in parts
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", str(part or ""))
    }

    return tokens - generic_tokens


def is_ncs_host(host: dict) -> bool:
    vendor, device_type = detect_device_type(host)
    return vendor == "Cisco" and device_type == "ncs"


def extract_numeric_tokens(
    text: str,
) -> list[str]:

    return re.findall(
        r"(?<!\d)\d+(?!\d)",
        text or "",
    )


def contains_site_code(
    text: str,
    site_codes: set[str],
) -> bool:

    tokens = extract_numeric_tokens(
        text
    )

    return any(
        token in site_codes
        for token in tokens
    )


def get_primary_interface(
    host: dict,
) -> Interface | None:

    interfaces = host.get(
        "interfaces",
        [],
    )

    if not interfaces:
        return None

    main_interfaces = [
        item
        for item in interfaces
        if str(
            item.get("main")
        ) == "1"
    ]

    selected = (
        main_interfaces[0]
        if main_interfaces
        else interfaces[0]
    )

    return Interface(
        **selected
    )


def get_group_names(
    host: dict,
) -> list[str]:

    return [
        item["name"]
        for item in host.get(
            "groups",
            []
        )
        if item.get("name")
    ]


def get_template_names(
    host: dict,
) -> list[str]:

    return [
        item["name"]
        for item in host.get(
            "parentTemplates",
            []
        )
        if item.get("name")
    ]


def detect_device_type(
    host: dict,
) -> tuple[str, str]:

    hostname = (
        host.get(
            "name",
            ""
        )
        .lower()
    )

    templates = [
        value.lower()
        for value in get_template_names(
            host
        )
    ]

    groups = [
        value.lower()
        for value in get_group_names(
            host
        )
    ]

    # ---------------------------------------------------------
    # Strongest signal: explicit Cisco template
    # ---------------------------------------------------------

    if any(
        "cisco" in template
        for template in templates
    ):

        if any(
            x in hostname
            for x in [
                "ncs",
            ]
        ):

            return (
                "Cisco",
                "ncs",
            )

        if any(
            x in hostname
            for x in [
                "asr",
            ]
        ):

            return (
                "Cisco",
                "router",
            )

        return (
            "Cisco",
            "switch",
        )

    # ---------------------------------------------------------
    # Group based signal
    # ---------------------------------------------------------

    if any(
        "switch" in group
        for group in groups
    ):

        return (
            "Cisco",
            "switch",
        )

    # ---------------------------------------------------------
    # Hostname based fallback
    # ---------------------------------------------------------

    if "3750" in hostname:
        return (
            "Cisco",
            "switch",
        )

    if "asr" in hostname:
        return (
            "Cisco",
            "router",
        )

    if "ncs" in hostname:
        return (
            "Cisco",
            "ncs",
        )

    return (
        "Unknown",
        "network-device",
    )


def infer_radio_type(
    name: str,
) -> str:

    value = (
        name
        .lower()
    )

    if "eband" in value:
        return "EBand"

    if "rtn" in value:
        return "RTN"

    # Match canonical names and legacy/plural spelling variants.
    # Keep the returned values aligned with the public API contract:
    # NRay and Intracom.
    if "intracom" in value:
        return "Intracom"

    if "nray" in value:
        return "NRay"

    # Current real-world naming example:
    #
    # ...-980A-Huawei
    #
    # Treat Huawei radio naming as RTN
    # provisionally.
    #
    # This can be refined later using
    # Zabbix items/templates.

    if "huawei" in value:
        return "RTN"

    return "Unknown"


def split_link_name(
    name: str,
):

    value = (
        name
        .replace("→", "->")
    )

    separators = [
        "->",
        "-to-",
        " to ",
    ]

    lower = value.lower()

    for separator in separators:

        position = lower.find(
            separator
        )

        if position == -1:
            continue

        left = value[
            :position
        ].strip(
            " -"
        )

        right = value[
            position
            + len(separator):
        ].strip(
            " -"
        )

        return (
            left,
            right,
        )

    return (
        None,
        None,
    )


def parse_direction(
    name: str,
    site_code: str,
):

    left, right = split_link_name(
        name
    )

    if not left or not right:
        return (
            None,
            None,
            None,
        )

    site_codes = {
        site_code,
    }

    left_codes = extract_numeric_tokens(
        left
    )

    right_codes = extract_numeric_tokens(
        right
    )

    source = next(
        (
            code
            for code in left_codes
            if code in site_codes
        ),
        None,
    )

    destination = next(
        (
            code
            for code in right_codes
            if code != site_code
        ),
        None,
    )

    return (
        source,
        destination,
        right,
    )


class SiteDiscovery:

    def __init__(self):

        self.client = (
            ZabbixClient()
        )

        self.enodeb_group = os.environ[
            "ZABBIX_GROUP_ENODEB"
        ]

        self.switch_group = os.environ[
            "ZABBIX_GROUP_SWITCH"
        ]

        self.radio_group = os.environ[
            "ZABBIX_GROUP_RADIO"
        ]

        self.switch_aggregation_group = os.getenv(
            "ZABBIX_GROUP_SWITCH_AGGREGATION",
            "LTE-Backhaul-Switch-Aggregation",
        )

    def discover(
        self,
        site_code: str,
    ) -> DiscoveryResult:

        site_code = normalize_site_code(site_code)

        result = DiscoveryResult(
            site_code=site_code
        )

        self.client.login()

        # =====================================================
        # ENODEB / BASEBAND
        # =====================================================

        enodeb_group = self.client.get_group_by_name(
            self.enodeb_group
        )

        if not enodeb_group:
            result.errors.append(
                "Zabbix group not found: "
                f"{self.enodeb_group}"
            )
        else:
            hosts = self.client.get_hosts_by_group(
                enodeb_group["groupid"]
            )

            seen_basebands = set()

            for host in hosts:
                # Disabled or unknown-status hosts must never be audited.
                if not is_host_enabled(host):
                    continue

                host_text = " ".join([
                    host.get("host", ""),
                    host.get("name", ""),
                ])

                if not matches_baseband_site_code(
                    host_text,
                    site_code,
                ):
                    continue

                host_id = str(host["hostid"])
                if host_id in seen_basebands:
                    continue

                seen_basebands.add(host_id)

                interface = get_primary_interface(host)

                result.basebands.append(
                    Baseband(
                        hostname=host["name"],
                        ip=interface.ip if interface else None,
                        zabbix_hostid=host_id,
                        groups=get_group_names(host),
                        templates=get_template_names(host),
                    )
                )

        # =====================================================
        # PRIMARY SWITCHES / NETWORK DEVICES
        # =====================================================

        primary_switch_hosts = []
        seen_device_ids = set()

        switch_group = self.client.get_group_by_name(
            self.switch_group
        )

        if not switch_group:
            result.errors.append(
                "Zabbix group not found: "
                f"{self.switch_group}"
            )
        else:
            hosts = self.client.get_hosts_by_group(
                switch_group["groupid"]
            )

            for host in hosts:
                if not is_host_enabled(host):
                    continue

                host_text = " ".join([
                    host.get("host", ""),
                    host.get("name", ""),
                ])

                # The normal switch must be associated by the exact Site Code.
                if not contains_site_code(
                    host_text,
                    {site_code},
                ):
                    continue

                host_id = str(host["hostid"])
                if host_id in seen_device_ids:
                    continue

                seen_device_ids.add(host_id)
                primary_switch_hosts.append(host)

                interface = get_primary_interface(host)
                vendor, device_type = detect_device_type(host)

                result.devices.append(
                    Device(
                        hostname=host["name"],
                        ip=interface.ip if interface else None,
                        vendor=vendor,
                        device_type=device_type,
                        role="ncs" if device_type == "ncs" else "network",
                        zabbix_hostid=host_id,
                        groups=get_group_names(host),
                        templates=get_template_names(host),
                        description=host.get("description", ""),
                    )
                )

        # =====================================================
        # NCS SWITCHES (AGGREGATION GROUP)
        # =====================================================

        # NCS hostnames may not contain the numeric Site Code. Search their
        # dedicated aggregation group and associate only by unambiguous
        # shared location metadata with an active primary switch.
        site_location_tokens = set()
        for primary_host in primary_switch_hosts:
            if not is_ncs_host(primary_host):
                site_location_tokens.update(
                    host_location_tokens(primary_host)
                )

        aggregation_group = self.client.get_group_by_name(
            self.switch_aggregation_group
        )

        if aggregation_group and site_location_tokens:
            aggregation_hosts = self.client.get_hosts_by_group(
                aggregation_group["groupid"]
            )

            matched_ncs = []

            for host in aggregation_hosts:
                if not is_host_enabled(host):
                    continue

                if not is_ncs_host(host):
                    continue

                host_id = str(host["hostid"])
                if host_id in seen_device_ids:
                    continue

                shared_location = (
                    host_location_tokens(host)
                    & site_location_tokens
                )

                if shared_location:
                    matched_ncs.append(host)

            if len(matched_ncs) == 1:
                host = matched_ncs[0]
                host_id = str(host["hostid"])
                seen_device_ids.add(host_id)

                interface = get_primary_interface(host)
                vendor, device_type = detect_device_type(host)

                result.devices.append(
                    Device(
                        hostname=host["name"],
                        ip=interface.ip if interface else None,
                        vendor=vendor,
                        device_type=device_type,
                        role="ncs",
                        zabbix_hostid=host_id,
                        groups=get_group_names(host),
                        templates=get_template_names(host),
                        description=host.get("description", ""),
                    )
                )

            elif len(matched_ncs) > 1:
                result.warnings.append(
                    "Multiple active NCS candidates match the site's "
                    "location metadata; none were associated automatically."
                )

        # =====================================================
        # RADIO
        # =====================================================

        radio_group = self.client.get_group_by_name(
            self.radio_group
        )

        if not radio_group:
            result.errors.append(
                "Zabbix group not found: "
                f"{self.radio_group}"
            )
        else:
            hosts = self.client.get_hosts_by_group(
                radio_group["groupid"]
            )

            seen_radio_ids = set()

            for host in hosts:
                if not is_host_enabled(host):
                    continue

                name = host.get("name") or host.get("host") or ""

                (
                    source,
                    destination,
                    destination_name,
                ) = parse_direction(
                    name,
                    site_code,
                )

                # Only active links originating from the requested site.
                if source != site_code:
                    continue

                host_id = str(host["hostid"])
                if host_id in seen_radio_ids:
                    continue

                seen_radio_ids.add(host_id)

                result.radio_links.append(
                    RadioLink(
                        name=name,
                        link_type=infer_radio_type(name),
                        source_site=source,
                        destination_site=destination,
                        destination_name=destination_name,
                        zabbix_hostid=host_id,
                    )
                )

        return result
