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


def related_site_codes(
    site_code: str,
) -> set[str]:

    site_code = normalize_site_code(
        site_code
    )

    return {
        site_code,
        f"7{site_code}",
        f"8{site_code}",
    }


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

    if "intracome" in value:
        return "Intracome"

    if "nrays" in value:
        return "NRays"

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

    def discover(
        self,
        site_code: str,
    ) -> DiscoveryResult:

        site_code = (
            normalize_site_code(
                site_code
            )
        )

        related_codes = (
            related_site_codes(
                site_code
            )
        )

        result = DiscoveryResult(
            site_code=site_code
        )

        self.client.login()

        # =====================================================
        # ENODEB / BASEBAND
        # =====================================================

        enodeb_group = (
            self.client.get_group_by_name(
                self.enodeb_group
            )
        )

        if not enodeb_group:

            result.errors.append(
                "Zabbix group not found: "
                f"{self.enodeb_group}"
            )

        else:

            hosts = (
                self.client.get_hosts_by_group(
                    enodeb_group[
                        "groupid"
                    ]
                )
            )

            seen = set()

            for host in hosts:

                text = " ".join([
                    host.get(
                        "host",
                        ""
                    ),
                    host.get(
                        "name",
                        ""
                    ),
                ])

                if not contains_site_code(
                    text,
                    related_codes,
                ):
                    continue

                host_id = host[
                    "hostid"
                ]

                if host_id in seen:
                    continue

                seen.add(
                    host_id
                )

                interface = (
                    get_primary_interface(
                        host
                    )
                )

                result.basebands.append(
                    Baseband(
                        hostname=host[
                            "name"
                        ],
                        ip=(
                            interface.ip
                            if interface
                            else None
                        ),
                        zabbix_hostid=host_id,
                        groups=
                            get_group_names(
                                host
                            ),
                        templates=
                            get_template_names(
                                host
                            ),
                    )
                )

        # =====================================================
        # SWITCH / NETWORK DEVICES
        # =====================================================

        switch_group = (
            self.client.get_group_by_name(
                self.switch_group
            )
        )

        if not switch_group:

            result.errors.append(
                "Zabbix group not found: "
                f"{self.switch_group}"
            )

        else:

            hosts = (
                self.client.get_hosts_by_group(
                    switch_group[
                        "groupid"
                    ]
                )
            )

            seen = set()

            for host in hosts:

                text = " ".join([
                    host.get(
                        "host",
                        ""
                    ),
                    host.get(
                        "name",
                        ""
                    ),
                ])

                # Only requested primary
                # site code for network devices.

                if not contains_site_code(
                    text,
                    {site_code},
                ):
                    continue

                host_id = host[
                    "hostid"
                ]

                if host_id in seen:
                    continue

                seen.add(
                    host_id
                )

                interface = (
                    get_primary_interface(
                        host
                    )
                )

                vendor, device_type = (
                    detect_device_type(
                        host
                    )
                )

                result.devices.append(
                    Device(
                        hostname=host[
                            "name"
                        ],
                        ip=(
                            interface.ip
                            if interface
                            else None
                        ),
                        vendor=vendor,
                        device_type=device_type,
                        role="network",
                        zabbix_hostid=host_id,
                        groups=
                            get_group_names(
                                host
                            ),
                        templates=
                            get_template_names(
                                host
                            ),
                        description=
                            host.get(
                                "description",
                                ""
                            ),
                    )
                )

        # =====================================================
        # RADIO
        # =====================================================

        radio_group = (
            self.client.get_group_by_name(
                self.radio_group
            )
        )

        if not radio_group:

            result.errors.append(
                "Zabbix group not found: "
                f"{self.radio_group}"
            )

        else:

            hosts = (
                self.client.get_hosts_by_group(
                    radio_group[
                        "groupid"
                    ]
                )
            )

            seen = set()

            for host in hosts:

                name = (
                    host.get(
                        "name"
                    )
                    or host.get(
                        "host"
                    )
                )

                (
                    source,
                    destination,
                    destination_name,
                ) = parse_direction(
                    name,
                    site_code,
                )

                # Only links originating from
                # requested site.

                if source != site_code:
                    continue

                host_id = host[
                    "hostid"
                ]

                if host_id in seen:
                    continue

                seen.add(
                    host_id
                )

                result.radio_links.append(
                    RadioLink(
                        name=name,
                        link_type=
                            infer_radio_type(
                                name
                            ),
                        source_site=source,
                        destination_site=
                            destination,
                        destination_name=
                            destination_name,
                        zabbix_hostid=
                            host_id,
                    )
                )

        return result



