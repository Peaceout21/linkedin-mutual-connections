# LinkedIn Mutual Connections Agent — Claude Code Setup Instructions

## What You Are Building

A local Python agent that:
1. Opens a real browser window (Playwright Chromium)
2. Logs into LinkedIn using saved session cookies
3. Navigates to any LinkedIn profile
4. Clicks the "mutual connections" link
5. Scrolls through and extracts every mutual connection (name + `/in/` URL + title)
6. Returns structured JSON

The agent is LLM-driven via **browser-use** — meaning Claude (via langchain-anthropic) controls the browser in natural language, not brittle CSS selectors.

---

## Tech Stack

- **browser-use** — LLM-driven browser agent (Claude navigates the UI)
- **Playwright** — browser automation underneath browser-use
- **langchain-anthropic** — connects browser-use to Claude Sonnet
- **Python 3.11+**

---

## Step 1 — Check Prerequisites

```bash
python3 --version        # needs 3.11+
pip --version
```

If Python < 3.11, install it first before proceeding.

---

## Step 2 — Create Project + Virtual Environment

linkedin_mutual already created 
```bash

python3 -m venv venv
source venv/bin/activate
```

Confirm venv is active — terminal prompt should show `(venv)`.

---

## Step 3 — Install Dependencies

```bash
pip install browser-use playwright langchain-anthropic python-dotenv
playwright install chromium
```

If `playwright install chromium` fails with missing system deps on Linux:
```bash
playwright install-deps chromium
playwright install chromium
```

---

## Step 4 — Set Anthropic API Key

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
```

Or export it:
```bash
export ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
```

---

## Step 5 — Create save_cookies.py

Create this file exactly:

```python
"""
Run this once to save your LinkedIn session cookies.
A browser window opens. You log in manually. Cookies saved to linkedin_cookies.json.
"""

import asyncio
import json
from playwright.async_api import async_playwright


async def save_linkedin_session():
    print("Opening browser... Log into LinkedIn, then press Enter here.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )
        )

        page = await context.new_page()
        await page.goto("https://www.linkedin.com/login")

        input(">>> Log into LinkedIn in the browser window, then press Enter: ")

        cookies = await context.cookies()
        with open("linkedin_cookies.json", "w") as f:
            json.dump(cookies, f, indent=2)

        print(f"Saved {len(cookies)} cookies to linkedin_cookies.json")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(save_linkedin_session())
```

---

## Step 6 — Create mutual_connections.py

Create this file exactly:

```python
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

from playwright.async_api import async_playwright
from browser_use import Agent, Browser, BrowserConfig
from langchain_anthropic import ChatAnthropic


COOKIES_FILE = "linkedin_cookies.json"
MODEL        = "claude-sonnet-4-6"
HEADLESS     = False


def load_cookies() -> list[dict]:
    path = Path(COOKIES_FILE)
    if not path.exists():
        raise FileNotFoundError(
            f"No cookies at '{COOKIES_FILE}'. Run 'python save_cookies.py' first."
        )
    with open(path) as f:
        cookies = json.load(f)
    print(f"Loaded {len(cookies)} session cookies")
    return cookies


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
    cookies = load_cookies()

    async with async_playwright() as p:
        browser_instance = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = await browser_instance.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )
        )
        await context.add_cookies(cookies)
        print("Session cookies injected")

        browser_config = BrowserConfig(
            headless=HEADLESS,
            playwright_browser=browser_instance,
            playwright_context=context,
        )

        llm = ChatAnthropic(model=MODEL, temperature=0, max_tokens=4096)

        agent = Agent(
            task=build_task(profile_url),
            llm=llm,
            browser=Browser(config=browser_config),
            max_actions_per_step=15,
        )

        print("Agent starting...\n")
        result = await agent.run(max_steps=40)
        raw = result.final_result() if hasattr(result, 'final_result') else str(result)

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
```

---

## Step 7 — Run Cookie Saver

```bash
python save_cookies.py
```

- A Chromium browser window opens
- Log into LinkedIn manually in that window
- Come back to terminal and press Enter
- `linkedin_cookies.json` is created

---

## Step 8 — Test Run

```bash
python mutual_connections.py \
  --url "https://www.linkedin.com/in/gregg-hill-parkway/" \
  --save results.json
```

You should see:
- Browser window opens (non-headless)
- Claude navigates to the profile
- Clicks mutual connections
- Scrolls through the list
- Prints names + LinkedIn URLs in terminal
- Saves `results.json`

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'browser_use'`
```bash
pip install browser-use
```

### `BrowserConfig` does not accept `playwright_browser` / `playwright_context`
browser-use API changes frequently. Check current API:
```bash
python -c "import browser_use; help(browser_use.BrowserConfig)"
```
Adjust the `BrowserConfig` and `Browser` initialization in `mutual_connections.py` to match current API. The core logic (cookies injection, task prompt, output parsing) stays the same.

### Browser opens but LinkedIn shows "Sign in" page
Session cookie expired. Re-run `save_cookies.py`.

### Agent stops scrolling before extracting all mutuals
Increase `max_steps=40` to `max_steps=60` in the agent init.
Also make the scroll instruction in `build_task()` more explicit.

### `playwright install chromium` fails on Mac with permissions error
```bash
sudo playwright install chromium
# or
playwright install chromium --with-deps
```

---

## File Structure When Done

```
linkedin_mutual/
├── venv/
├── .env                      ← ANTHROPIC_API_KEY
├── linkedin_cookies.json     ← your LI session (git ignore this)
├── save_cookies.py
├── mutual_connections.py
├── results.json              ← output from last run
└── CLAUDE.md                 ← this file
```

---

## Important Notes for Claude Code

- **Do not hardcode the Anthropic API key** anywhere. Always read from `.env` or environment.
- **Do not commit `linkedin_cookies.json`** — add it to `.gitignore`.
- **`HEADLESS = False`** during development so you can see what the agent is doing.
- The `browser-use` library updates frequently. If initialization fails, check `pip show browser-use` for the version and adjust the `BrowserConfig` init accordingly.
- The task prompt in `build_task()` is the most important tuning lever. If extraction is incomplete, make the scroll instructions more explicit there.