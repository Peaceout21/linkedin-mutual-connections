from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class JobRequest(BaseModel):
    url: str
    force_refresh: bool = False


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
