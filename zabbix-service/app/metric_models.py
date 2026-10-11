from typing import List, Dict, Any

from pydantic import BaseModel


class MetricCandidate(BaseModel):

    itemid: str

    name: str

    key: str

    value_type: str

    units: str

    lastvalue: str

    lastclock: str

    metric_type: str


class HostMetricInventory(BaseModel):

    hostid: str

    hostname: str

    item_count: int

    metrics: Dict[str, List[MetricCandidate]]


