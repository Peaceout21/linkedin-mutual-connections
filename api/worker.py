from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from . import store
from .config import settings


@dataclass
class WorkerJob:
    job_id: str
    job_type: str
    url: str
    enrich: bool
    max_steps: int
    ttl_days: int
    job_cache_key: str


# Module-level queue — safe to create outside an async context in Python 3.10+
job_queue: asyncio.Queue[WorkerJob] = asyncio.Queue()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def run_worker() -> None:
    # Lazy imports so main.py can patch mutual_connections.STORAGE_FILE first.
    from mutual_connections import get_mutual_connections
    from company_people import get_company_people
    from contact_info import get_contact_info

    while True:
        req = await job_queue.get()
        try:
            await store.update_job(req.job_id, status="running", started_at=_now())

            if req.job_type == "mutual_connections":
                result = await get_mutual_connections(req.url, enrich=req.enrich)
            elif req.job_type == "company_people":
                result = await get_company_people(req.url, max_steps=req.max_steps)
            else:  # contact_info
                result = await get_contact_info(req.url, max_steps=req.max_steps)

            # Write cache BEFORE updating job status — if the status write fails
            # transiently, the next POST /jobs for the same URL returns a cache
            # hit instead of launching a duplicate scrape.
            await store.write_cache(
                req.job_cache_key, req.url, req.job_type, result, req.ttl_days
            )
            await store.update_job(
                req.job_id,
                status="completed",
                finished_at=_now(),
                result=result,
            )
        except Exception as exc:
            await store.update_job(
                req.job_id,
                status="failed",
                finished_at=_now(),
                error=str(exc),
            )
        finally:
            job_queue.task_done()
