"""
LinkedIn Mutual Connections Agent
Run: python mutual_connections.py --url "https://www.linkedin.com/in/someprofile/"
"""

import asyncio
import json
import argparse
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import socket
from playwright.async_api import async_playwright

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm.google.chat import ChatGoogle


STORAGE_FILE = "linkedin_storage.json"
MODEL        = "gemini-3-flash-preview"
HEADLESS     = False


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def load_storage() -> dict:
    path = Path(STORAGE_FILE).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"No session at '{STORAGE_FILE}'. Run 'python save_cookies.py' first."
        )
    with open(path) as f:
        storage = json.load(f)
    cookie_count = len(storage.get("cookies", []))
    print(f"Loaded {cookie_count} session cookies")
    return storage


def build_task(profile_url: str) -> str:
    return f"""
You are helping extract mutual connections from a LinkedIn profile.
The user is already logged into LinkedIn via session cookies.

Step-by-step task:

1. Navigate to: {profile_url}
2. Wait for the page to fully load.
3. Find text near the profile photo that says something like "X mutual connections"
   or "Name, Name, and X other mutual connections". Note the total count.
4. Click on that mutual connections link.
5. You will see a list of people (modal or new page). Scroll slowly and repeatedly
   until no new people appear — you have reached the end of the list.
6. For every person in the list extract:
   - Full name
   - LinkedIn profile URL (the /in/username part)
   - Current job title / headline
   - Location (if visible)
7. Return ONLY a valid JSON object in this exact format, nothing else:

{{
  "target_profile": "{profile_url}",
  "mutual_count": <number from step 3>,
  "extracted_at": "<ISO timestamp>",
  "mutual_connections": [
    {{
      "name": "Full Name",
      "linkedin_url": "https://www.linkedin.com/in/username",
      "linkedin_id": "username",
      "title": "Their current role",
      "location": "City, Country or null"
    }}
  ]
}}
"""


def parse_output(raw: str, profile_url: str) -> dict:
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {"error": "No JSON found", "raw": raw}
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw": raw}

    seen = set()
    clean = []
    for p in data.get("mutual_connections", []):
        url = p.get("linkedin_url", "")
        m = re.search(r"/in/([^/?#]+)", url)
        if m:
            p["linkedin_id"] = m.group(1)
            p["linkedin_url"] = f"https://www.linkedin.com/in/{m.group(1)}"
        uid = p.get("linkedin_id") or p.get("name")
        if uid and uid not in seen:
            seen.add(uid)
            clean.append(p)

    data["mutual_connections"] = clean
    data["actual_extracted"] = len(clean)
    data["extracted_at"] = datetime.utcnow().isoformat() + "Z"
    return data


async def get_mutual_connections(profile_url: str, save_path: Optional[str] = None) -> dict:
    print(f"\nTarget : {profile_url}")
    storage = load_storage()

    port = find_free_port()
    print(f"Launching browser on port {port}...")

    # We use Playwright to launch the browser so cookies are applied to the DEFAULT
    # context natively and synchronously — before the agent touches anything.
    # Playwright stays alive throughout so there's no CDP disconnect event that
    # would clear browser-use's SessionManager.
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=[
            f"--remote-debugging-port={port}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    # Use browser.new_page() → this creates a page in the DEFAULT browser context.
    # Cookies set on page.context apply to ALL future tabs in that same default context,
    # including new tabs created by browser-use via CDP.
    page = await browser.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})
    await page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
    })

    # Inject cookies into the default context (synchronous — no race condition).
    # Strip partitionKey if it's a dict — Playwright expects string or absent.
    clean_cookies = [
        {k: v for k, v in c.items() if k != "partitionKey" or isinstance(v, str)}
        for c in storage["cookies"]
    ]
    await page.context.add_cookies(clean_cookies)
    print(f"Injected {len(storage['cookies'])} cookies")

    # Verify the session is alive before handing off to the agent
    print("Verifying LinkedIn session...")
    await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
    await asyncio.sleep(1)
    current_url = page.url

    if "login" in current_url or "authwall" in current_url or "checkpoint" in current_url:
        await browser.close()
        await pw.stop()
        raise RuntimeError(
            f"LinkedIn session check failed (at {current_url}).\n"
            "Re-run: python save_cookies.py"
        )
    print(f"Session verified — at {current_url[:70]}")

    # Connect browser-use to the SAME running browser via CDP.
    # Playwright stays open alongside it — no disconnect events, no state clearing.
    browser_session = BrowserSession(cdp_url=f"http://localhost:{port}")

    llm = ChatGoogle(model=MODEL, temperature=0)

    agent = Agent(
        task=build_task(profile_url),
        llm=llm,
        browser=browser_session,
        max_actions_per_step=15,
    )

    print("Agent starting...\n")
    try:
        result = await agent.run(max_steps=40)
        raw = result.final_result() if hasattr(result, 'final_result') else str(result)
    finally:
        await browser.close()
        await pw.stop()

    data = parse_output(raw, profile_url)

    print(f"\nMutual count (LinkedIn) : {data.get('mutual_count', '?')}")
    print(f"Extracted               : {data.get('actual_extracted', '?')}")

    for i, person in enumerate(data.get("mutual_connections", []), 1):
        print(f"  {i:2}. {person['name']:<35} {person.get('linkedin_url', '')}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to {save_path}")

    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="LinkedIn profile URL")
    parser.add_argument("--save", default=None, help="Save results to this JSON file")
    args = parser.parse_args()
    asyncio.run(get_mutual_connections(args.url, args.save))


if __name__ == "__main__":
    main()
