from typing import Any, Dict
from pydantic import BaseModel, Field


class AuditJob(BaseModel):
    job_id: str
    site_code: str
    status: str
    results: Dict[str, Any] = Field(
        default_factory=dict
    )


