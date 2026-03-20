"""
Slack alerting — silently no-ops if SLACK_BOT_TOKEN is not configured.
"""
from __future__ import annotations

import logging
import os
import urllib.request
import json

log = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL   = os.getenv("SLACK_CHANNEL", "test-zapier")


def send(message: str) -> None:
    """Post a message to Slack. Does nothing if token is not configured."""
    if not SLACK_BOT_TOKEN:
        return
    try:
        payload = json.dumps({
            "channel": SLACK_CHANNEL,
            "text": message,
        }).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log.warning(f"Slack alert failed (non-fatal): {e}")
