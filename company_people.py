"""
LinkedIn Company People Scraper
Extracts 2nd-degree connections from a company's /people/ tab.

Run: python company_people.py --url "https://www.linkedin.com/company/acme/" --save out.json
     python company_people.py --url "..." --save out.json --max-steps 120
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

from mutual_connections import load_storage, find_free_port, _launch_browser

MODEL = "gemini-3-flash-preview"


def validate_company_url(url: str) -> None:
    if not re.match(r'https?://(www\.)?linkedin\.com/company/[^/?#]+', url):
        raise ValueError(
            f"Invalid LinkedIn company URL: {url!r}\n"
            "Expected format: https://www.linkedin.com/company/slug"
        )


def people_tab_url(company_url: str) -> str:
    return company_url.rstrip("/") + "/people/"


def build_task(company_url: str) -> str:
    tab_url = people_tab_url(company_url)
    return f"""
You are helping extract 2nd-degree connections from a LinkedIn company page.
The user is already logged into LinkedIn via session cookies.

Step-by-step task:

1. Navigate to: {tab_url}
2. Wait for the page to fully load. Note the company name shown on the page.
3. Scroll slowly and repeatedly through the entire employee list.
   Stop only when no new employee cards appear after two consecutive scrolls.
4. For EACH employee card, read the connection degree badge — it shows "1st", "2nd", or "3rd+".
   Include ONLY cards with "2nd" degree badge. Skip all others.
5. For each "2nd" degree employee extract:
   - Full name
   - LinkedIn profile URL (the /in/username part from the card href)
   - Job title / headline
   - Location (if visible on the card)
6. Count:
   - total_employees_visible: total cards seen (all degrees)
   - second_degree_count: how many were "2nd"
7. If the people tab is restricted or empty, return total_employees_visible: 0 and an empty people list.
8. Return ONLY a valid JSON object in this exact format, nothing else:

{{
  "company_url": "{company_url.rstrip('/')}",
  "company_name": "<name shown on the page>",
  "people_tab_url": "{tab_url}",
  "total_employees_visible": <integer>,
  "second_degree_count": <integer>,
  "people": [
    {{
      "name": "Full Name",
      "linkedin_url": "https://www.linkedin.com/in/username",
      "linkedin_id": "username",
      "title": "Their job title or headline",
      "location": "City, Country or null",
      "connection_degree": "2nd"
    }}
  ]
}}
"""


def parse_output(raw: str, company_url: str) -> dict:
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        raise RuntimeError(f"No JSON found in agent output.\nRaw output: {raw[:300]}")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse error: {e}\nRaw output: {raw[:300]}")

    seen = set()
    clean = []
    for p in data.get("people", []):
        # Filter: only 2nd degree (guard against agent mistakes)
        if "2nd" not in str(p.get("connection_degree", "2nd")):
            continue

        # Normalise linkedin_url and extract linkedin_id
        url = p.get("linkedin_url", "")
        m = re.search(r"/in/([^/?#]+)", url)
        if m:
            p["linkedin_id"] = m.group(1)
            p["linkedin_url"] = f"https://www.linkedin.com/in/{m.group(1)}"

        # Deduplicate by linkedin_id (fall back to name)
        uid = p.get("linkedin_id") or p.get("name")
        if not uid or uid in seen:
            continue
        seen.add(uid)

        # Enforce fields
        p["connection_degree"] = "2nd"
        p.setdefault("tags", [])
        p.setdefault("notes", "")
        p.setdefault("contacted", False)
        p.setdefault("contact_date", None)

        clean.append(p)

    meta = {
        "company_url": data.get("company_url", company_url.rstrip("/")),
        "company_name": data.get("company_name", ""),
        "people_tab_url": data.get("people_tab_url", people_tab_url(company_url)),
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "total_employees_visible": data.get("total_employees_visible", 0),
        "second_degree_count": len(clean),  # recomputed — don't trust agent's count
    }

    return {"meta": meta, "people": clean}


async def get_company_people(
    company_url: str,
    save_path: Optional[str] = None,
    max_steps: int = 80,
) -> dict:
    validate_company_url(company_url)
    print(f"\nTarget : {people_tab_url(company_url)}")

    storage = load_storage()
    pw, browser, page, port = await _launch_browser(storage)
    llm = ChatGoogle(model=MODEL, temperature=0)

    try:
        agent = Agent(
            task=build_task(company_url),
            llm=llm,
            browser=BrowserSession(cdp_url=f"http://localhost:{port}"),
            max_actions_per_step=15,
        )
        print(f"Agent starting (max_steps={max_steps})...\n")
        result = await agent.run(max_steps=max_steps)
        raw = result.final_result() if hasattr(result, "final_result") else str(result)
    finally:
        await browser.close()
        await pw.stop()

    data = parse_output(raw, company_url)

    meta = data["meta"]
    print(f"\nCompany              : {meta.get('company_name', '?')}")
    print(f"Total visible        : {meta.get('total_employees_visible', '?')}")
    print(f"2nd degree found     : {meta.get('second_degree_count', '?')}")

    for i, person in enumerate(data["people"], 1):
        print(f"  {i:3}. {person['name']:<35} {person.get('linkedin_url', '')}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to {save_path}")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Extract 2nd-degree connections from a LinkedIn company /people/ tab."
    )
    parser.add_argument("--url",       required=True,  help="LinkedIn company URL")
    parser.add_argument("--save",      default=None,   help="Save results to JSON file")
    parser.add_argument("--max-steps", default=80,     type=int,
                        help="Max agent steps (default 80; use 120+ for large companies)")
    args = parser.parse_args()
    asyncio.run(get_company_people(args.url, args.save, args.max_steps))


if __name__ == "__main__":
    main()
