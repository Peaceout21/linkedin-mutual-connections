from __future__ import annotations

import json
import logging

from google.cloud import pubsub_v1

log = logging.getLogger(__name__)

_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def publish_job(project_id: str, topic_id: str, job_id: str, url: str) -> str:
    """Publish a job to Pub/Sub. Returns the message ID."""
    publisher = _get_publisher()
    topic_path = publisher.topic_path(project_id, topic_id)
    data = json.dumps({
        "job_id": job_id,
        "url": url,
        "job_type": "mutual_connections",
    }).encode()
    future = publisher.publish(topic_path, data)
    message_id = future.result()
    log.info(f"Published job {job_id} to {topic_path} (msg_id={message_id})")
    return message_id
