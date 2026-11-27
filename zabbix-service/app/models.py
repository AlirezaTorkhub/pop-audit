from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Interface(BaseModel):
    interfaceid: str
    ip: str = ""
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
    interfaces: List[Interface] = Field(default_factory=list)
    groups: List[dict] = Field(default_factory=list)
    templates: List[dict] = Field(default_factory=list)


class Device(BaseModel):
    hostname: str
    ip: Optional[str] = None
    vendor: Optional[str] = None
    device_type: Optional[str] = None
    role: Optional[str] = None
    zabbix_hostid: str
    groups: List[str] = Field(default_factory=list)
    templates: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class Baseband(BaseModel):
    name: str = "BB1"
    exists: bool = True
    status: str = "UNKNOWN"
    hostname: Optional[str] = None
    ip: Optional[str] = None
    zabbix_hostid: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    templates: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class RadioLink(BaseModel):
    name: str
    link_type: str
    source_site: Optional[str] = None
    destination_site: Optional[str] = None
    destination_name: Optional[str] = None
    zabbix_hostid: str
    groups: List[str] = Field(default_factory=list)
    templates: List[str] = Field(default_factory=list)


class DiscoveryResult(BaseModel):
    site_code: str
    site_identity: Optional[str] = None
    basebands: List[Baseband] = Field(default_factory=list)
    devices: List[Device] = Field(default_factory=list)
    ncs_devices: List[Device] = Field(default_factory=list)
    radio_links: List[RadioLink] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
