from typing import List, Optional

from pydantic import BaseModel


class Interface(BaseModel):
    interfaceid: str
    ip: str
    dns: str = ""
    type: str = ""
    main: str = "0"
    port: str = ""


class Host(BaseModel):
    hostid: str
    host: str
    name: str
    status: str
    description: str = ""

    interfaces: List[Interface] = []

    groups: List[dict] = []
    templates: List[dict] = []


class Device(BaseModel):
    hostname: str
    ip: Optional[str] = None

    vendor: Optional[str] = None
    device_type: Optional[str] = None
    role: Optional[str] = None

    zabbix_hostid: str

    groups: List[str] = []
    templates: List[str] = []

    description: Optional[str] = None


class Baseband(BaseModel):
    hostname: str
    ip: Optional[str] = None
    zabbix_hostid: str

    groups: List[str] = []
    templates: List[str] = []


class RadioLink(BaseModel):
    name: str

    link_type: str

    source_site: Optional[str] = None
    destination_site: Optional[str] = None

    destination_name: Optional[str] = None

    zabbix_hostid: str


class DiscoveryResult(BaseModel):
    site_code: str

    basebands: List[Baseband] = []
    devices: List[Device] = []
    radio_links: List[RadioLink] = []

    warnings: List[str] = []
    errors: List[str] = []



