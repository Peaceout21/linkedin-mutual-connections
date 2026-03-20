#!/usr/bin/env python3
"""
LinkedIn Scraper — Local Worker

Pulls jobs from Pub/Sub one at a time and runs the scrape on this machine.
Auto-started by launchd on login. Safe to start/stop at any time.

Usage:
    python worker.py
"""

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone

WORKER_HOST = socket.gethostname()

from google.cloud import firestore, pubsub_v1
from google.api_core.exceptions import DeadlineExceeded

from api.config import settings

# Heavy scraper deps (browser_use, playwright, Gemini) are NOT imported here.
# They are lazy-loaded the first time a job actually arrives, so the worker
# sits at ~20MB RAM while idle instead of ~150MB.
_scrapers: dict = {}

def _load_scraper(job_type: str):
    if job_type not in _scrapers:
        log.info(f"Loading scraper for job_type={job_type} (first job) ...")
        if job_type == "company_people":
            from company_people import get_company_people
            _scrapers[job_type] = get_company_people
        else:
            from mutual_connections import get_mutual_connections
            _scrapers[job_type] = get_mutual_connections
        log.info("Scraper loaded")
    return _scrapers[job_type]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SCRAPE_MAX_STEPS   = 60
ACK_EXTEND_EVERY   = 60   # seconds between ack deadline extensions
ACK_EXTEND_TO      = 300  # extend deadline to this many seconds each time
PULL_TIMEOUT       = 30   # seconds to wait for a message before looping


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reset_stuck_jobs(db: firestore.Client) -> None:
    """
    On startup, reset any jobs stuck in 'running' (laptop was closed mid-scrape).
    Their Pub/Sub messages will be redelivered automatically once the ack deadline
    expires, so we only need to fix the Firestore status.
    """
    stuck = list(db.collection(settings.jobs_collection).where("status", "==", "running").stream())
    for doc in stuck:
        doc.reference.update({"status": "pending", "started_at": None})
        log.warning(f"Reset stuck job {doc.id} → pending")
    if stuck:
        log.warning(f"Reset {len(stuck)} stuck job(s). They will be redelivered by Pub/Sub.")


def _extend_ack_loop(
    subscriber: pubsub_v1.SubscriberClient,
    subscription_path: str,
    ack_id: str,
    stop_event: threading.Event,
) -> None:
    """Background thread: keeps extending the ack deadline while scraping."""
    while not stop_event.wait(timeout=ACK_EXTEND_EVERY):
        try:
            subscriber.modify_ack_deadline(request={
                "subscription": subscription_path,
                "ack_ids": [ack_id],
                "ack_deadline_seconds": ACK_EXTEND_TO,
            })
            log.debug("Extended ack deadline")
        except Exception as e:
            log.warning(f"Failed to extend ack deadline: {e}")


# ── Job processor ─────────────────────────────────────────────────────────────

async def _process(job_id: str, url: str, job_type: str, db: firestore.Client) -> None:
    job_ref = db.collection(settings.jobs_collection).document(job_id)

    # Guard: skip if already completed (duplicate delivery)
    snap = job_ref.get()
    if snap.exists and snap.to_dict().get("status") == "completed":
        log.info(f"Job {job_id} already completed — skipping duplicate delivery")
        return

    log.info(f"Starting job {job_id}  type={job_type}  url={url}")
    job_ref.update({"status": "running", "started_at": _now(), "worker_host": WORKER_HOST})

    scraper = _load_scraper(job_type)
    # company_people scraper needs more steps (more employees to scroll through)
    max_steps = SCRAPE_MAX_STEPS if job_type == "mutual_connections" else max(SCRAPE_MAX_STEPS, 80)
    result = await scraper(url, max_steps=max_steps)

    # Write cache (90-day TTL)
    from datetime import timedelta
    cache_key = snap.to_dict().get("cache_key") if snap.exists else None
    if cache_key:
        db.collection(settings.cache_collection).document(cache_key).set({
            "cache_key": cache_key,
            "url": url,
            "job_type": job_type,
            "result": result,
            "created_at": _now(),
            "expires_at": _now() + timedelta(days=settings.cache_ttl_days),
        })

    job_ref.update({
        "status": "completed",
        "finished_at": _now(),
        "result": result,
    })
    log.info(
        f"Job {job_id} completed — "
        f"{result.get('actual_extracted', '?')} connections extracted"
    )


# ── Main worker loop ──────────────────────────────────────────────────────────

def run() -> None:
    db = firestore.Client(project=settings.gcp_project_id, database=settings.database_id)
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(
        settings.gcp_project_id, settings.pubsub_subscription
    )

    log.info("=" * 60)
    log.info("LinkedIn Worker starting")
    log.info(f"  Host         : {WORKER_HOST}")
    log.info(f"  Project      : {settings.gcp_project_id}")
    log.info(f"  Subscription : {subscription_path}")
    log.info(f"  Max steps    : {SCRAPE_MAX_STEPS}")
    log.info("=" * 60)

    _reset_stuck_jobs(db)

    while True:
        try:
            # Pull one message at a time — serial processing
            response = subscriber.pull(
                request={"subscription": subscription_path, "max_messages": 1},
                timeout=PULL_TIMEOUT,
            )
        except DeadlineExceeded:
            # No messages within timeout — loop and try again
            continue
        except Exception as e:
            log.error(f"Pull error: {e} — retrying in 10s")
            time.sleep(10)
            continue

        if not response.received_messages:
            continue

        msg = response.received_messages[0]
        ack_id = msg.ack_id

        try:
            data = json.loads(msg.message.data.decode())
        except Exception as e:
            log.error(f"Malformed message, acking to discard: {e}")
            subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": [ack_id]})
            continue

        job_id = data.get("job_id", "unknown")
        url = data.get("url", "")
        job_type = data.get("job_type", "mutual_connections")
        log.info(f"Received job {job_id}  type={job_type}")

        # Start background thread to keep ack alive during scraping
        stop_event = threading.Event()
        extender = threading.Thread(
            target=_extend_ack_loop,
            args=(subscriber, subscription_path, ack_id, stop_event),
            daemon=True,
        )
        extender.start()

        success = False
        try:
            asyncio.run(_process(job_id, url, job_type, db))
            success = True
        except Exception as e:
            log.error(f"Job {job_id} failed: {e}")
            # Update Firestore with failure
            try:
                db.collection(settings.jobs_collection).document(job_id).update({
                    "status": "failed",
                    "finished_at": _now(),
                    "error": str(e),
                })
            except Exception:
                pass
        finally:
            stop_event.set()

        if success:
            # Ack: job done, remove from queue
            subscriber.acknowledge(
                request={"subscription": subscription_path, "ack_ids": [ack_id]}
            )
            log.info(f"Job {job_id} acked")
        else:
            # Nack: requeue for retry (Pub/Sub will redeliver after backoff)
            subscriber.modify_ack_deadline(request={
                "subscription": subscription_path,
                "ack_ids": [ack_id],
                "ack_deadline_seconds": 60,  # retry after 60s
            })
            log.info(f"Job {job_id} nacked — will retry in ~60s")


if __name__ == "__main__":
    run()
