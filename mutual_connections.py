"""
LinkedIn Mutual Connections Agent
Run: python mutual_connections.py --url "https://www.linkedin.com/in/someprofile/"
Add --enrich to also fetch the latest experience entry from each profile.
  Warning: --enrich visits every mutual profile individually — slow for large lists.
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
# Set HEADLESS=false in .env to see the browser locally; VMs always run headless
HEADLESS     = os.getenv("HEADLESS", "false").lower() != "false"


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
   - Headline (the short bio text they set, e.g. "Partner @ Acme | Investor")
   - Current company — look for a dedicated company line or badge on the card,
     separate from the headline. If the headline itself contains "at CompanyName"
     or "@ CompanyName", extract just the company name from it. If no company is
     visible anywhere, use null.
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
      "title": "Their headline / bio text",
      "company": "Current company name or null",
      "location": "City, Country or null"
    }}
  ]
}}
"""


def build_enrich_task(profiles: list[dict]) -> str:
    url_list = "\n".join(f'- {p["linkedin_url"]}  (id: {p["linkedin_id"]})' for p in profiles)
    ids = [p["linkedin_id"] for p in profiles]
    return f"""
You are enriching LinkedIn profiles with their latest work experience.
The user is already logged in via session cookies.

Visit each LinkedIn profile URL below ONE BY ONE. For each profile:
1. Navigate to the URL and wait for it to load.
2. Scroll down until you find the "Experience" section.
3. Read the TOPMOST (most recent) entry only. Extract:
   - job_title   : exact job title shown
   - company     : company name
   - start_date  : start date as shown (e.g. "Jan 2023", "2021")
   - end_date    : end date as shown, or "Present" if current
   - location    : city/country if shown, else null
4. Move to the next URL.

Profiles to visit:
{url_list}

After visiting ALL profiles return ONLY this JSON, nothing else:
{{
{chr(10).join(f'  "{lid}": {{"job_title": "...", "company": "...", "start_date": "...", "end_date": "...", "location": "..."}},' for lid in ids)}
}}

Use null for any field not visible on the page.
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


def parse_enrich_output(raw: str) -> dict:
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


async def _launch_browser(storage: dict):
    """Launch Playwright browser with LinkedIn session. Returns (pw, browser, page, port)."""
    port = find_free_port()
    print(f"Launching browser on port {port}...")

    headless_args = [
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-setuid-sandbox",
        "--single-process",
    ] if HEADLESS else []

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=[
            f"--remote-debugging-port={port}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            *headless_args,
        ],
    )

    page = await browser.new_page()
    await page.set_viewport_size({"width": 1280, "height": 800})

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
        if HEADLESS else
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
    await page.set_extra_http_headers({"User-Agent": user_agent})

    clean_cookies = [
        {k: v for k, v in c.items() if k != "partitionKey" or isinstance(v, str)}
        for c in storage["cookies"]
    ]
    await page.context.add_cookies(clean_cookies)
    print(f"Injected {len(storage['cookies'])} cookies")

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
    return pw, browser, page, port


def validate_linkedin_url(url: str) -> None:
    """Raise ValueError if url doesn't look like a LinkedIn profile URL."""
    if not re.match(r'https?://(www\.)?linkedin\.com/in/[^/?#]+', url):
        raise ValueError(
            f"Invalid LinkedIn profile URL: {url!r}\n"
            "Expected format: https://www.linkedin.com/in/username"
        )


async def get_mutual_connections(profile_url: str, save_path: Optional[str] = None,
                                  enrich: bool = False) -> dict:
    validate_linkedin_url(profile_url)
    print(f"\nTarget : {profile_url}")
    storage = load_storage()

    # ── Phase 1: extract mutual connections list ──────────────────────────────
    pw, browser, page, port = await _launch_browser(storage)
    llm = ChatGoogle(model=MODEL, temperature=0)

    try:
        agent = Agent(
            task=build_task(profile_url),
            llm=llm,
            browser=BrowserSession(cdp_url=f"http://localhost:{port}"),
            max_actions_per_step=15,
        )
        print("Phase 1 — extracting mutual connections list...\n")
        result = await agent.run(max_steps=40)
        raw = result.final_result() if hasattr(result, 'final_result') else str(result)
    finally:
        await browser.close()
        await pw.stop()

    data = parse_output(raw, profile_url)
    if "error" in data:
        raise RuntimeError(
            f"Agent returned unparseable output: {data['error']}\n"
            f"Raw output: {str(data.get('raw', ''))[:300]}"
        )
    print(f"\nMutual count : {data.get('mutual_count', '?')}")
    print(f"Extracted    : {data.get('actual_extracted', '?')}")

    # ── Phase 2 (optional): visit each profile for top experience entry ───────
    if enrich and data.get("mutual_connections"):
        profiles = data["mutual_connections"]
        print(f"\n⚠️  --enrich: will visit {len(profiles)} profiles one by one — this is slow.")
        print(f"Phase 2 — enriching {len(profiles)} profiles with latest experience...")

        pw2, browser2, page2, port2 = await _launch_browser(storage)
        try:
            # Each profile needs ~3 steps (navigate, scroll, read) → budget generously
            max_steps = max(60, len(profiles) * 4)
            agent2 = Agent(
                task=build_enrich_task(profiles),
                llm=llm,
                browser=BrowserSession(cdp_url=f"http://localhost:{port2}"),
                max_actions_per_step=15,
            )
            result2 = await agent2.run(max_steps=max_steps)
            raw2 = result2.final_result() if hasattr(result2, 'final_result') else str(result2)
        finally:
            await browser2.close()
            await pw2.stop()

        experience_map = parse_enrich_output(raw2)
        enriched = 0
        for person in data["mutual_connections"]:
            lid = person.get("linkedin_id", "")
            exp = experience_map.get(lid)
            if exp and isinstance(exp, dict):
                person["latest_experience"] = exp
                enriched += 1
            else:
                person["latest_experience"] = None
        print(f"Enriched {enriched}/{len(profiles)} profiles with experience data")

    # ── Print summary ─────────────────────────────────────────────────────────
    for i, person in enumerate(data.get("mutual_connections", []), 1):
        exp = person.get("latest_experience")
        exp_str = f'  [{exp["job_title"]} @ {exp["company"]}]' if exp else ""
        print(f"  {i:2}. {person['name']:<35}{exp_str}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to {save_path}")

    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",    required=True, help="LinkedIn profile URL")
    parser.add_argument("--save",   default=None,  help="Save results to JSON file")
    parser.add_argument("--enrich", action="store_true",
                        help="Also fetch latest experience entry from each profile")
    args = parser.parse_args()
    asyncio.run(get_mutual_connections(args.url, args.save, enrich=args.enrich))


if __name__ == "__main__":
    main()
