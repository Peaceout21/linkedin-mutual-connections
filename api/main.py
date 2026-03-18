from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()  # must run before any other imports so env vars are available

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi import status as http_status
from fastapi.security import APIKeyHeader

from .config import settings
from . import store
from .pubsub import publish_job
from .models import JobRequest, JobResponse, JobStatus


# ── Authentication ─────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: Optional[str] = Security(_api_key_header)) -> str:
    if key != settings.api_key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header",
        )
    return key


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db(settings.gcp_project_id)
    yield


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="LinkedIn Scraper API", lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/jobs", response_model=JobResponse, status_code=202)
async def create_job(req: JobRequest, _: str = Depends(require_api_key)):
    ck = store.cache_key(req.url)

    # Return cached result if within TTL
    if not req.force_refresh:
        cached = await store.get_cached(ck)
        if cached:
            return JobResponse(
                job_id=None,
                status="cached",
                message="Returning cached result.",
                result=cached["result"],
            )

    job_id = str(uuid.uuid4())
    await store.create_job(job_id=job_id, url=req.url, job_cache_key=ck)
    publish_job(settings.gcp_project_id, settings.pubsub_topic, job_id, req.url)

    return JobResponse(job_id=job_id, status="pending", message="Job queued.")


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, _: str = Depends(require_api_key)):
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**job)


@app.get("/jobs", response_model=list[JobStatus])
async def list_jobs(
    status: Optional[str] = None,
    _: str = Depends(require_api_key),
):
    jobs = await store.list_jobs(status=status)
    return [JobStatus(**j) for j in jobs]


@app.delete("/cache")
async def evict_cache(url: str, _: str = Depends(require_api_key)):
    ck = store.cache_key(url)
    deleted = await store.evict_cache(ck)
    if not deleted:
        raise HTTPException(status_code=404, detail="No cache entry for this URL")
    return {"deleted": True, "cache_key": ck}
