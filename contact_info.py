"""
LinkedIn Contact Info Scraper
Extracts the contact info overlay for a profile.

Run: python contact_info.py --url "https://www.linkedin.com/in/username/"
     python contact_info.py --url "..." --save out.json
"""

import asyncio
import json
import argparse
import re
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm.google.chat import ChatGoogle

from mutual_connections import load_storage, _launch_browser, validate_linkedin_url

MODEL = "gemini-3-flash-preview"


def contact_overlay_url(profile_url: str) -> str:
    return profile_url.strip().rstrip("/") + "/overlay/contact-info/"


def build_task(profile_url: str) -> str:
    overlay = contact_overlay_url(profile_url)
    return f"""
You are extracting contact information from a LinkedIn profile contact info overlay.
The user is already logged into LinkedIn via session cookies.

Step-by-step task:

1. Navigate directly to: {overlay}
2. Wait for the page to fully load. The contact info appears in a modal/overlay on
   top of the profile. If the page redirects away from this URL, note where it went.
3. Check for any restriction message such as "You must be connected",
   "Connect to see contact info", or similar. If found, set "access_restricted": true
   and return null/empty for all contact fields — do NOT try to extract further.
4. Otherwise extract ALL visible contact fields. Common ones include:
   - Email address
   - Phone number(s) — there may be more than one (e.g. Work, Mobile). Capture each
     with its label.
   - LinkedIn profile URL (the canonical /in/username shown on the overlay)
   - Website URL(s) — there may be several (e.g. Portfolio, Blog, Company). Capture
     each with its label.
   - Twitter / X handle
   - Connected date (e.g. "Connected since January 2023")
   - Birthday (e.g. "March 15")
   - Address / location
   - Instant messenger handle
5. Any field not visible or not shared should be null (phones/websites use empty list).
6. Return ONLY a valid JSON object in this exact format, nothing else:

{{
  "profile_url": "{profile_url.rstrip('/')}",
  "contact_info_url": "{overlay}",
  "access_restricted": false,
  "extracted_at": "<ISO timestamp>",
  "email": "user@example.com or null",
  "phones": [
    {{"number": "+1 555 000 0000", "label": "Work"}}
  ],
  "linkedin_url": "https://www.linkedin.com/in/username or null",
  "websites": [
    {{"url": "https://example.com", "label": "Portfolio"}}
  ],
  "twitter": "@handle or null",
  "connected_since": "January 2023 or null",
  "birthday": "March 15 or null",
  "address": "City, Country or null",
  "other": {{}}
}}

Put any extra fields not listed above into "other" as key-value string pairs.
"""


def parse_output(raw: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise RuntimeError(f"No JSON found in agent output.\nRaw: {raw[:300]}")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse error: {e}\nRaw: {raw[:300]}")

    # Always stamp extraction time ourselves
    data["extracted_at"] = datetime.utcnow().isoformat() + "Z"

    # Normalise linkedin_url
    li = data.get("linkedin_url")
    if li:
        m = re.search(r"/in/([^/?#]+)", li)
        if m:
            data["linkedin_url"] = f"https://www.linkedin.com/in/{m.group(1)}"

    # Guarantee phones is a list of dicts
    phones = data.get("phones")
    if phones is None:
        data["phones"] = []
    elif isinstance(phones, str):
        data["phones"] = [{"number": phones, "label": None}]
    elif isinstance(phones, dict):
        data["phones"] = [phones]
    else:
        # Filter to only dict entries; drop malformed
        data["phones"] = [p for p in phones if isinstance(p, dict)]

    # Guarantee websites is a list of dicts
    websites = data.get("websites")
    if websites is None:
        data["websites"] = []
    elif isinstance(websites, str):
        data["websites"] = [{"url": websites, "label": None}]
    elif isinstance(websites, dict):
        data["websites"] = [websites]
    else:
        data["websites"] = [w for w in websites if isinstance(w, dict)]

    # Guarantee other is a dict
    if not isinstance(data.get("other"), dict):
        data["other"] = {}

    # Guarantee access_restricted is a bool
    data["access_restricted"] = bool(data.get("access_restricted", False))

    return data


async def get_contact_info(
    profile_url: str,
    save_path: Optional[str] = None,
    max_steps: int = 20,
) -> dict:
    validate_linkedin_url(profile_url)
    print(f"\nTarget : {contact_overlay_url(profile_url)}")

    storage = load_storage()
    pw, browser, page, port = await _launch_browser(storage)
    llm = ChatGoogle(model=MODEL, temperature=0)

    try:
        agent = Agent(
            task=build_task(profile_url),
            llm=llm,
            browser=BrowserSession(cdp_url=f"http://localhost:{port}"),
            max_actions_per_step=10,
        )
        print(f"Agent starting (max_steps={max_steps})...\n")
        result = await agent.run(max_steps=max_steps)
        raw = result.final_result() if hasattr(result, "final_result") else str(result)
    finally:
        await browser.close()
        await pw.stop()

    data = parse_output(raw)

    if data.get("access_restricted"):
        print("Access restricted — must be connected to see contact info.")
    else:
        print(f"Email          : {data.get('email')}")
        print(f"Phones         : {data.get('phones')}")
        print(f"LinkedIn URL   : {data.get('linkedin_url')}")
        print(f"Websites       : {data.get('websites')}")
        print(f"Twitter        : {data.get('twitter')}")
        print(f"Connected since: {data.get('connected_since')}")
        print(f"Birthday       : {data.get('birthday')}")
        print(f"Address        : {data.get('address')}")
        if data.get("other"):
            print(f"Other fields   : {list(data['other'].keys())}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to {save_path}")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Extract contact info from a LinkedIn profile contact info overlay."
    )
    parser.add_argument("--url", required=True, help="LinkedIn profile URL")
    parser.add_argument("--save", default=None, help="Save results to JSON file")
    parser.add_argument(
        "--max-steps", default=20, type=int, help="Max agent steps (default 20)"
    )
    args = parser.parse_args()
    asyncio.run(get_contact_info(args.url, args.save, args.max_steps))


if __name__ == "__main__":
    main()
