from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from google.cloud import firestore

from .config import settings

_db: Optional[firestore.AsyncClient] = None


def init_db(project_id: str) -> None:
    global _db
    _db = firestore.AsyncClient(project=project_id, database=settings.database_id)


def _get_db() -> firestore.AsyncClient:
    if _db is None:
        raise RuntimeError("Firestore not initialised. Call init_db() first.")
    return _db


def get_sync_db() -> firestore.Client:
    """Synchronous Firestore client for the local worker."""
    return firestore.Client(project=settings.gcp_project_id, database=settings.database_id)


def cache_key(url: str) -> str:
    """Normalise a LinkedIn URL to a safe Firestore document ID."""
    path = urlparse(url.strip().rstrip("/").lower()).path.strip("/")
    return re.sub(r"[^\w]", "_", path.replace("/", "__"))


async def get_cached(key: str) -> Optional[dict[str, Any]]:
    db = _get_db()
    doc = await db.collection(settings.cache_collection).document(key).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    expires_at = data.get("expires_at")
    if expires_at and datetime.now(timezone.utc) > expires_at:
        return None
    return data


async def write_cache(key: str, url: str, result: dict[str, Any], ttl_days: int, job_type: str = "mutual_connections") -> None:
    db = _get_db()
    now = datetime.now(timezone.utc)
    await db.collection(settings.cache_collection).document(key).set({
        "cache_key": key,
        "url": url,
        "job_type": job_type,
        "result": result,
        "created_at": now,
        "expires_at": now + timedelta(days=ttl_days),
    })


async def create_job(job_id: str, url: str, job_cache_key: str, job_type: str = "mutual_connections", max_steps: int = 60) -> None:
    db = _get_db()
    now = datetime.now(timezone.utc)
    await db.collection(settings.jobs_collection).document(job_id).set({
        "job_id": job_id,
        "job_type": job_type,
        "url": url,
        "status": "pending",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "cache_key": job_cache_key,
        "max_steps": max_steps,
    })


async def update_job(job_id: str, **kwargs: Any) -> None:
    db = _get_db()
    await db.collection(settings.jobs_collection).document(job_id).update(kwargs)


async def get_job(job_id: str) -> Optional[dict[str, Any]]:
    db = _get_db()
    doc = await db.collection(settings.jobs_collection).document(job_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


async def list_jobs(status: Optional[str] = None) -> list[dict[str, Any]]:
    db = _get_db()
    col = db.collection(settings.jobs_collection)
    if status:
        query = col.where("status", "==", status).order_by("created_at")
    else:
        query = col.order_by("created_at", direction="DESCENDING")
    results = []
    async for doc in query.stream():
        results.append(doc.to_dict())
    return results


async def evict_cache(key: str) -> bool:
    db = _get_db()
    doc_ref = db.collection(settings.cache_collection).document(key)
    doc = await doc_ref.get()
    if not doc.exists:
        return False
    await doc_ref.delete()
    return True
