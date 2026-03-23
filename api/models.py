from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

JobType = Literal["mutual_connections", "company_people"]


class JobRequest(BaseModel):
    url: str
    job_type: JobType = "mutual_connections"
    force_refresh: bool = False
    max_steps: int = 40  # 40 for mutual_connections, 60-80 for company_people, 120 for large companies


class JobResponse(BaseModel):
    job_id: Optional[str]
    status: str
    message: str
    result: Optional[dict[str, Any]] = None


class JobStatus(BaseModel):
    job_id: str
    job_type: str
    url: str
    status: str
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
